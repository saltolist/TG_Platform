"""Rolling dialog summary (LLM + template fallback)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from app.services.ai.context_config import PROMPT_WINDOW, ROLLING_SUMMARY_SENTENCE_LIMIT

if TYPE_CHECKING:
    from app.services.ai.providers import ProviderSpec

ROLLING_SUMMARY_SYSTEM = (
    "Ты сжимаешь историю диалога для контекста LLM. "
    f"Пиши кратко от первого лица пользователя, не более {ROLLING_SUMMARY_SENTENCE_LIMIT} "
    "предложений. Сохраняй числа, имена и термины. Не добавляй вводных фраз."
)

_META_SUMMARY_MARKERS = (
    "текущее саммари",
    "нет реплик",
    "новые реплики для включения",
    "(пусто)",
)


def _is_invalid_rolling_summary_response(text: str) -> bool:
    """Reject LLM meta-replies that echo the summarizer prompt instead of dialog."""
    lowered = text.strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _META_SUMMARY_MARKERS)


def is_meta_rolling_summary_response(text: str) -> bool:
    """True when text looks like an LLM meta-reply, not a real dialog summary."""
    return _is_invalid_rolling_summary_response(text)


def exchanges_from_messages(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    exchanges: list[tuple[str, str]] = []
    index = 0
    while index < len(messages):
        role, content = messages[index]
        if role != "user":
            index += 1
            continue
        assistant_text = ""
        if index + 1 < len(messages) and messages[index + 1][0] == "assistant":
            assistant_text = messages[index + 1][1]
            index += 2
        else:
            index += 1
        exchanges.append((content, assistant_text))
    return exchanges


def prefix_pairs_outside_window(
    pairs: list[tuple[str, str]],
    *,
    window_size: int = PROMPT_WINDOW,
) -> list[tuple[str, str]]:
    if window_size <= 0 or len(pairs) <= window_size:
        return []
    return pairs[:-window_size]


def reconcile_rolling_summary_fields(
    state: Mapping[str, Any],
    valid_pairs: list[tuple[str, str]],
) -> dict[str, Any]:
    """Clear stale dialog summary when history was shortened (e.g. turn deleted).

    Only touches ``rolling_summary`` / ``rolling_summary_idx``; bundle labels are unchanged.
    """
    prefix = prefix_pairs_outside_window(valid_pairs)
    try:
        summary_idx = int(state.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    summary_idx = max(0, summary_idx)

    rolling_summary = str(state.get("rolling_summary") or "").strip()
    if not prefix or summary_idx > len(prefix):
        if rolling_summary or summary_idx:
            return {**dict(state), "rolling_summary": "", "rolling_summary_idx": 0}
    return dict(state)


def rolling_summary_for_assembly(
    state: Mapping[str, Any],
    valid_pairs: list[tuple[str, str]],
) -> str:
    """Effective CONTEXT_SUMMARY for the current request.

    Bootstraps unstored prefix pairs with the template fallback so new fork
    threads and pre-reply turns still get dialog summary in the primer.
    Does not mutate stored thread state or touch bundle labels.
    """
    reconciled = reconcile_rolling_summary_fields(state, valid_pairs)
    prefix = prefix_pairs_outside_window(valid_pairs)
    try:
        summary_idx = int(reconciled.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    summary_idx = max(0, summary_idx)

    rolling_summary = str(reconciled.get("rolling_summary") or "").strip()
    if _is_invalid_rolling_summary_response(rolling_summary):
        rolling_summary = ""
        summary_idx = 0

    if len(prefix) > summary_idx:
        new_segment = prefix[summary_idx:]
        exchanges = exchanges_from_messages(new_segment)
        if exchanges:
            rolling_summary = update_rolling_summary_template(rolling_summary, exchanges)

    return rolling_summary.strip()


def _limit_sentences(text: str, limit: int = ROLLING_SUMMARY_SENTENCE_LIMIT) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", cleaned)
    if len(parts) <= limit:
        return cleaned
    return " ".join(parts[:limit]).strip()


def build_rolling_summary_messages(
    existing_summary: str,
    exchanges: list[tuple[str, str]],
) -> list[dict[str, str]]:
    lines = [f"Текущее саммари:\n{existing_summary.strip() or '(пусто)'}"]
    if exchanges:
        lines.append("\nНовые реплики для включения:")
        for user_text, assistant_text in exchanges:
            lines.append(f"Пользователь: {user_text}")
            if assistant_text.strip():
                lines.append(f"Ассистент: {assistant_text}")
            lines.append("")
    lines.append("Обнови саммари одним блоком текста.")
    return [
        {"role": "system", "content": ROLLING_SUMMARY_SYSTEM},
        {"role": "user", "content": "\n".join(lines).strip()},
    ]


def update_rolling_summary_template(
    existing_summary: str,
    exchanges: list[tuple[str, str]],
) -> str:
    """Offline fallback when LLM is unavailable (stub / presentation)."""
    parts: list[str] = []
    if existing_summary.strip():
        parts.append(existing_summary.strip())
    for user_text, assistant_text in exchanges:
        user_short = user_text.strip()
        if not user_short:
            continue
        if assistant_text.strip():
            parts.append(f"Я спрашивал: {user_short}. Ответ: {assistant_text.strip()}")
        else:
            parts.append(f"Я спрашивал: {user_short}.")
    return _limit_sentences(" ".join(parts))


async def update_rolling_summary_llm(
    existing_summary: str,
    exchanges: list[tuple[str, str]],
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> str:
    from app.services.ai.llm import complete_chat_completion

    if not exchanges:
        return existing_summary.strip()

    messages = build_rolling_summary_messages(existing_summary, exchanges)
    text = await complete_chat_completion(
        spec=spec,
        model=model,
        api_key=api_key,
        messages=messages,
    )
    limited = _limit_sentences(text.strip())
    if _is_invalid_rolling_summary_response(limited):
        return update_rolling_summary_template(existing_summary, exchanges)
    return limited or update_rolling_summary_template(existing_summary, exchanges)
