"""Rolling dialog summary (LLM + template fallback)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.ai.context_config import ROLLING_SUMMARY_SENTENCE_LIMIT

if TYPE_CHECKING:
    from app.services.ai.providers import ProviderSpec

ROLLING_SUMMARY_SYSTEM = (
    "Ты сжимаешь историю диалога для контекста LLM. "
    f"Пиши кратко от первого лица пользователя, не более {ROLLING_SUMMARY_SENTENCE_LIMIT} "
    "предложений. Сохраняй числа, имена и термины. Не добавляй вводных фраз."
)


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

    messages = build_rolling_summary_messages(existing_summary, exchanges)
    text = await complete_chat_completion(
        spec=spec,
        model=model,
        api_key=api_key,
        messages=messages,
    )
    limited = _limit_sentences(text.strip())
    return limited or update_rolling_summary_template(existing_summary, exchanges)
