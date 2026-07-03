"""Download Telethon message media to local disk (Phase 3 / Step 3)."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.services.telegram.media_fingerprint import (
    index_existing_media,
    media_fingerprint,
    media_item_unchanged,
)
from app.services.telegram.media_kinds import (
    classify_telegram_media,
    normalize_tgs_to_lottie_json,
)


def _guess_extension(mime_type: str, fallback_name: str = "") -> str:
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) if mime_type else ""
    if ext:
        return ext
    if fallback_name and "." in fallback_name:
        return Path(fallback_name).suffix
    return ".bin"


async def save_message_media(
    client: Any, message: Any, user_id: UUID, settings: Settings
) -> dict[str, str] | None:
    """Download *message* media to ``media_storage_root/<user_id>/`` and return PostMedia dict."""
    media = getattr(message, "media", None)
    if media is None:
        return None

    file_obj = getattr(message, "file", None)
    if file_obj is None:
        return None

    max_bytes = int(settings.telegram_import_max_media_mb * 1024 * 1024)
    size = getattr(file_obj, "size", None)
    if size is not None and size > max_bytes:
        return None

    kind = classify_telegram_media(message)
    if kind is None:
        return None

    mime_type = getattr(file_obj, "mime_type", None) or "application/octet-stream"
    original_name = getattr(file_obj, "name", None) or ""
    ext = _guess_extension(mime_type, original_name)
    filename = f"{message.id}{ext}"

    user_dir = Path(settings.media_storage_root) / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / filename

    downloaded = await client.download_media(message, file=str(dest))
    if not downloaded and not dest.is_file():
        return None

    stored_type = mime_type
    stored_name = original_name or filename
    stored_filename = filename

    if kind == "animated_sticker":
        try:
            lottie_bytes = normalize_tgs_to_lottie_json(dest.read_bytes())
        except ValueError:
            return None
        stored_filename = f"{message.id}.json"
        stored_dest = user_dir / stored_filename
        stored_dest.write_bytes(lottie_bytes)
        if stored_dest != dest and dest.is_file():
            dest.unlink(missing_ok=True)
        stored_type = "application/json"
        if not stored_name.lower().endswith(".json"):
            stored_name = f"{Path(stored_name).stem or message.id}.json"

    display_name = stored_name
    url = f"/media/{user_id}/{stored_filename}"
    item: dict[str, str] = {"name": display_name, "url": url, "type": stored_type, "kind": kind}
    msg_id = getattr(message, "id", None)
    if msg_id is not None:
        item["telegramMessageId"] = str(msg_id)
    fp = media_fingerprint(message)
    if fp:
        item["mediaKey"] = fp
    return item


async def resolve_group_media(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    existing_media: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Download only media whose Telegram file id changed (or is new)."""
    existing_by_msg = index_existing_media(existing_media)
    result: list[dict[str, Any]] = []

    for message in messages:
        fp = media_fingerprint(message)
        if fp is None:
            continue
        msg_id = str(getattr(message, "id", "") or "")
        if not msg_id:
            continue

        existing = existing_by_msg.get(msg_id)
        if existing and media_item_unchanged(existing, fp, user_id, settings):
            enriched = dict(existing)
            enriched["telegramMessageId"] = msg_id
            enriched["mediaKey"] = fp
            result.append(enriched)
            continue

        item = await save_message_media(client, message, user_id, settings)
        if item:
            result.append(item)

    return result
