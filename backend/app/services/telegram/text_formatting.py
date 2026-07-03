"""Convert Telethon message entities to HTML for platform display."""

from __future__ import annotations

import html as html_module
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SPOILER_HTML = ('<span class="tg-spoiler">', '</span>')
_spoiler_formatter_registered = False


def _ensure_telegram_html_formatters() -> None:
    """Register HTML formatters that Telethon does not ship by default."""
    global _spoiler_formatter_registered
    if _spoiler_formatter_registered:
        return
    try:
        from telethon.extensions import html as tg_html
        from telethon.tl.types import MessageEntitySpoiler
    except ImportError:
        return
    if MessageEntitySpoiler not in tg_html.ENTITY_TO_FORMATTER:
        tg_html.ENTITY_TO_FORMATTER[MessageEntitySpoiler] = _SPOILER_HTML
    _spoiler_formatter_registered = True


def extract_plain_text(message: Any) -> str:
    return str(getattr(message, "message", None) or "").strip()


def message_entities(message: Any) -> list[Any]:
    raw = getattr(message, "entities", None)
    return list(raw) if raw else []


def message_to_text_html(message: Any) -> str | None:
    """Return HTML with Telegram formatting, or None when plain text suffices."""
    text = getattr(message, "message", None)
    if text is None:
        return None
    text = str(text)
    if not text.strip():
        return None
    entities = message_entities(message)
    if not entities:
        return None
    try:
        from telethon.extensions import html as tg_html

        _ensure_telegram_html_formatters()
        parsed = tg_html.unparse(text, entities).strip()
    except Exception:
        logger.debug("Failed to unparse Telegram entities", exc_info=True)
        return None
    if not parsed:
        return None
    if parsed == html_module.escape(text):
        return None
    return parsed


def apply_message_text_fields(payload: dict[str, Any], message: Any) -> None:
    """Write ``text`` / ``textHtml`` on a post or comment payload from a Telethon message."""
    payload["text"] = extract_plain_text(message)
    text_html = message_to_text_html(message)
    if text_html:
        payload["textHtml"] = text_html
    else:
        payload.pop("textHtml", None)


__all__ = [
    "apply_message_text_fields",
    "extract_plain_text",
    "message_entities",
    "message_to_text_html",
]
