"""Convert Telethon message entities to HTML for platform display."""

from __future__ import annotations

import html as html_module
import logging
from typing import Any, Mapping

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
    if "\n" in parsed:
        parsed = parsed.replace("\n", "<br>")
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


def _html_for_telethon_parse(text_html: str) -> str:
    return (
        text_html.replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
    )


def normalize_platform_text_html(
    text: str, text_html: str | None
) -> tuple[str, str | None, list[Any] | None]:
    """Validate platform-authored HTML and return normalized storage + entities."""
    plain = str(text or "").strip()
    raw_html = str(text_html or "").strip()
    if not raw_html:
        return plain, None, None

    try:
        from telethon.extensions import html as tg_html

        _ensure_telegram_html_formatters()
        parsed_text, entities = tg_html.parse(_html_for_telethon_parse(raw_html))
    except Exception:
        logger.debug("Failed to parse platform textHtml", exc_info=True)
        return plain, None, None

    parsed_text = str(parsed_text or "")
    if parsed_text.strip() != plain:
        return plain, None, None

    if not entities:
        return plain, None, None

    try:
        normalized_html = tg_html.unparse(parsed_text, entities).strip()
    except Exception:
        logger.debug("Failed to unparse platform entities", exc_info=True)
        return plain, None, None

    if not normalized_html:
        return plain, None, None
    if "\n" in normalized_html:
        normalized_html = normalized_html.replace("\n", "<br>")
    if normalized_html == html_module.escape(plain):
        return plain, None, None

    return plain, normalized_html, list(entities)


def apply_platform_text_fields(payload: dict[str, Any]) -> None:
    """Normalize ``text`` / ``textHtml`` authored on the platform."""
    text = str(payload.get("text") or "")
    text_html = payload.get("textHtml")
    if text_html is None:
        payload.pop("textHtml", None)
        return
    if not isinstance(text_html, str):
        payload.pop("textHtml", None)
        return

    normalized_text, normalized_html, _entities = normalize_platform_text_html(
        text, text_html
    )
    payload["text"] = normalized_text
    if normalized_html:
        payload["textHtml"] = normalized_html
    else:
        payload.pop("textHtml", None)


def post_formatting_entities_from_payload(payload: Mapping[str, Any]) -> list[Any] | None:
    """Return Telethon entities for outbound publish/edit when formatting is present."""
    text = str(payload.get("text") or "")
    text_html = payload.get("textHtml")
    if not isinstance(text_html, str):
        return None
    _normalized_text, _normalized_html, entities = normalize_platform_text_html(
        text, text_html
    )
    return entities or None


__all__ = [
    "apply_message_text_fields",
    "apply_platform_text_fields",
    "extract_plain_text",
    "message_entities",
    "message_to_text_html",
    "normalize_platform_text_html",
    "post_formatting_entities_from_payload",
]
