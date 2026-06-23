"""Shared primer/dialog helpers for context assembly (no circular imports)."""

from __future__ import annotations

from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW
from app.services.ai.context_turns import annotate_user_turns

DEFAULT_SYSTEM_PROMPT = """\
Ты AI-ассистент TG Platform. Помогай автору Telegram-канала с текстами, идеями и анализом. Отвечай на языке пользователя, кратко и по делу.

Если в запросе пользователя есть блок «Контекст из заметок» — используй его содержимое при ответе. \
Когда опираешься на конкретную заметку, вставь inline-цитату markdown-ссылкой: \
[название заметки](/note/global/ID/) — видимый текст должен быть точным названием заметки из контекста. \
Для заметок поста: [название](/note/post/POST_ID/NOTE_ID/). \
Путь (cite-path) и название (cite-title) бери из блока контекста. \
Цитаты ставь только на те заметки, которые реально повлияли на ответ. \
Отвечай в markdown: **жирный**, списки, заголовки — где уместно.\
"""


def build_system_prompt(user_system_prompt: str) -> str:
    """Combine the platform base prompt with the user's custom system prompt.

    The base prompt is always present and contains core instructions (language,
    tone, note-citation rules).  The user's prompt is appended after a blank
    line so it can extend or override style/persona without losing the base rules.
    """
    user_part = user_system_prompt.strip()
    if not user_part:
        return DEFAULT_SYSTEM_PROMPT
    return f"{DEFAULT_SYSTEM_PROMPT}\n\n{user_part}"

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
