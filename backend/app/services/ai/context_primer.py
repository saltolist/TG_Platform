"""Shared primer/dialog helpers for context assembly (no circular imports)."""

from __future__ import annotations

from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW
from app.services.ai.context_turns import annotate_user_turns

DEFAULT_SYSTEM_PROMPT = """\
Ты AI-ассистент TG Platform. Помогай автору Telegram-канала с текстами, идеями и анализом. Отвечай на языке пользователя, кратко и по делу.

Если в запросе пользователя есть блок «Контекст из заметок» — используй его содержимое при ответе. \
Пиши ответ обычным связным текстом: не вставляй названия заметок внутрь предложений и не заменяй ими слова. \
Если утверждение основано на заметке, в конце предложения добавь сноску-ссылку: \
[название заметки](/note/global/ID/) — это источник, не часть фразы. \
Для заметок поста: [название](/note/post/POST_ID/NOTE_ID/). \
Путь (cite-path) и название (cite-title) бери из блока контекста. \
Пример: «Нужно подготовить отчёт.[Работа](/note/global/ID/)», а не «В заметке [Работа](...) указано». \
Отвечай в markdown: **жирный**, списки, заголовки — где уместно.\
"""

POST_SCOPE_SYSTEM_ADDENDUM = (
    "Сейчас ассистент работает в контексте конкретного поста канала. "
    "Учитывай текст поста и сводки в запросе пользователя."
)

LABEL_CHANNEL_HEAD = "Профиль канала"
LABEL_CHANNEL_UPDATED = "Обновлённый профиль канала"
LABEL_POST_HEAD = "Пост"
LABEL_POST_UPDATED = "Обновлённый пост"
LABEL_USER_REQUEST = "Мой текущий запрос"
LABEL_DIALOG_SUMMARY = "Сводка по диалогу"

# Legacy tags — kept for tests/docs that reference the old primer format.
PRIMER_USER_TAG = "SUMMARY_BUNDLE"
CONTEXT_SUMMARY_TAG = "CONTEXT_SUMMARY"


def build_system_prompt(user_system_prompt: str, *, scope: str = "global") -> str:
    """Combine the platform base prompt with the user's custom system prompt.

    The base prompt is always present and contains core instructions (language,
    tone, note-citation rules).  The user's prompt is appended after a blank
    line so it can extend or override style/persona without losing the base rules.
    """
    base = DEFAULT_SYSTEM_PROMPT
    if scope == "post":
        base = f"{base}\n\n{POST_SCOPE_SYSTEM_ADDENDUM}"
    user_part = user_system_prompt.strip()
    if not user_part:
        return base
    return f"{base}\n\n{user_part}"


def format_labeled_section(label: str, body: str) -> str:
    text = body.strip()
    if not text:
        return ""
    return f"{label}:\n{text}"


def format_channel_summary(text: str, *, updated: bool = False) -> str:
    label = LABEL_CHANNEL_UPDATED if updated else LABEL_CHANNEL_HEAD
    return format_labeled_section(label, text)


def format_post_summary(text: str, *, updated: bool = False) -> str:
    label = LABEL_POST_UPDATED if updated else LABEL_POST_HEAD
    return format_labeled_section(label, text)


def format_bundle_sections(
    *,
    channel_text: str = "",
    post_text: str = "",
    channel_updated: bool = False,
    post_updated: bool = False,
    dialog_summary: str = "",
) -> str:
    parts: list[str] = []
    if channel_text.strip():
        parts.append(format_channel_summary(channel_text, updated=channel_updated))
    if post_text.strip():
        parts.append(format_post_summary(post_text, updated=post_updated))
    if dialog_summary.strip():
        parts.append(format_labeled_section(LABEL_DIALOG_SUMMARY, dialog_summary))
    return "\n\n".join(parts)


def wrap_user_request(user_text: str) -> str:
    text = user_text.strip()
    if not text:
        return f"{LABEL_USER_REQUEST}:"
    return f"{LABEL_USER_REQUEST}:\n{text}"


def build_primer_user_content(bundle_text: str, rolling_summary: str = "") -> str:
    parts = [bundle_text.strip()]
    summary = rolling_summary.strip()
    if summary:
        parts.append(format_labeled_section(LABEL_DIALOG_SUMMARY, summary))
    return "\n\n".join(part for part in parts if part)


def attach_floating_bundle_to_user_message(bundle_text: str, user_text: str) -> str:
    bundle_block = bundle_text.strip()
    request = wrap_user_request(user_text)
    if not bundle_block:
        return request
    return f"{bundle_block}\n\n{request}"


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
        if role == "user":
            if user_turn is not None and user_turn in floating_bundles:
                content = attach_floating_bundle_to_user_message(floating_bundles[user_turn], content)
            else:
                content = wrap_user_request(content)
        messages.append({"role": role, "content": content})
    return messages
