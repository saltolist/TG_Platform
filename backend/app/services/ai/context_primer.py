"""Shared primer/dialog helpers for context assembly (no circular imports)."""

from __future__ import annotations

from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW
from app.services.ai.context_turns import annotate_user_turns

DEFAULT_SYSTEM_PROMPT = (
    "Ты AI-ассистент TG Platform. Помогай автору Telegram-канала с текстами, "
    "идеями и анализом. Отвечай на языке пользователя, кратко и по делу."
)

PRIMER_USER_TAG = "SUMMARY_BUNDLE"
CONTEXT_SUMMARY_TAG = "CONTEXT_SUMMARY"


def build_primer_user_content(bundle_text: str, rolling_summary: str = "") -> str:
    parts = [f"{PRIMER_USER_TAG}:", bundle_text.strip()]
    summary = rolling_summary.strip()
    if summary:
        parts.extend(["", f"{CONTEXT_SUMMARY_TAG}:", summary])
    return "\n".join(parts)


def attach_floating_bundle_to_user_message(bundle_text: str, user_text: str) -> str:
    bundle_block = f"{PRIMER_USER_TAG}:\n{bundle_text.strip()}"
    text = user_text.strip()
    if not text:
        return bundle_block
    return f"{bundle_block}\n\n{text}"


def take_prompt_window(
    pairs: list[tuple[str, str]],
    *,
    window_size: int = PROMPT_WINDOW,
) -> list[tuple[str, str]]:
    if window_size <= 0:
        return []
    return pairs[-window_size:]


def build_dialog_messages(
    window_pairs: list[tuple[str, str]],
    *,
    valid_pairs: list[tuple[str, str]],
    floating_bundles: dict[int, str],
) -> list[dict[str, str]]:
    annotated = annotate_user_turns(valid_pairs)
    window_len = len(window_pairs)
    window_annotated = annotated[-window_len:] if window_len else []

    messages: list[dict[str, str]] = []
    for user_turn, role, content in window_annotated:
        if role == "user" and user_turn is not None and user_turn in floating_bundles:
            content = attach_floating_bundle_to_user_message(floating_bundles[user_turn], content)
        messages.append({"role": role, "content": content})
    return messages
