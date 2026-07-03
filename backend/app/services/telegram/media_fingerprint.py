"""Fingerprint Telegram message media without downloading files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

_MEDIA_URL_MESSAGE_ID = re.compile(r"/(\d+)\.[^/]+$")


def media_message_id_from_item(item: dict[str, Any]) -> str | None:
    stored = item.get("telegramMessageId")
    if stored:
        return str(stored)
    url = str(item.get("url") or "")
    match = _MEDIA_URL_MESSAGE_ID.search(url)
    return match.group(1) if match else None


def media_fingerprint(message: Any) -> str | None:
    """Stable key for the attached file — changes when Telegram replaces the media."""
    media = getattr(message, "media", None)
    if media is None:
        return None

    if isinstance(media, MessageMediaPhoto):
        photo = getattr(media, "photo", None)
        photo_id = getattr(photo, "id", None) if photo is not None else None
        if photo_id is not None:
            return f"photo:{photo_id}"
        return f"msg:{getattr(message, 'id', 0)}:photo"

    if isinstance(media, MessageMediaDocument):
        document = getattr(media, "document", None)
        if document is None:
            return None
        doc_id = getattr(document, "id", None)
        if doc_id is None:
            return f"msg:{getattr(message, 'id', 0)}:document"
        size = int(getattr(document, "size", 0) or 0)
        mime = str(getattr(document, "mime_type", "") or "")
        return f"doc:{doc_id}:{size}:{mime}"

    return f"msg:{getattr(message, 'id', 0)}:media"


def media_file_exists(item: dict[str, Any], user_id: Any, settings: Any) -> bool:
    url = str(item.get("url") or "")
    if not url.startswith("/media/"):
        return False
    filename = url.rsplit("/", 1)[-1]
    if not filename:
        return False
    path = Path(settings.media_storage_root) / str(user_id) / filename
    return path.is_file()


def index_existing_media(existing_media: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in existing_media or []:
        if not isinstance(item, dict):
            continue
        msg_id = media_message_id_from_item(item)
        if msg_id:
            indexed[msg_id] = item
    return indexed


def media_item_unchanged(existing: dict[str, Any], fingerprint: str, user_id: Any, settings: Any) -> bool:
    stored_key = existing.get("mediaKey")
    if not stored_key:
        # Legacy rows without mediaKey — re-download once to verify content and backfill the key.
        return False
    if stored_key != fingerprint:
        return False
    return media_file_exists(existing, user_id, settings)
