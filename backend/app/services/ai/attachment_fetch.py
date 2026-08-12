"""Resolve attachment bytes from data URLs or local /media/ paths."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from app.core.config import Settings
from app.services.ai.attachment_text import decode_data_url


def _local_media_path(url: str, user_id: uuid.UUID, settings: Settings) -> Path | None:
    raw = (url or "").strip()
    prefix = f"/media/{user_id}/"
    if not raw.startswith(prefix):
        return None
    filename = raw.rsplit("/", 1)[-1]
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return None
    path = Path(settings.media_storage_root) / str(user_id) / filename
    try:
        resolved = path.resolve()
        root = (Path(settings.media_storage_root) / str(user_id)).resolve()
        if not str(resolved).startswith(str(root)):
            return None
    except OSError:
        return None
    return resolved if resolved.is_file() else None


async def resolve_attachment_bytes(
    url: str,
    user_id: uuid.UUID,
    settings: Settings,
) -> tuple[bytes, str] | None:
    """Return raw bytes and mime type for a data: URL or local /media/ URL."""
    decoded = decode_data_url(url)
    if decoded is not None:
        return decoded

    local_path = _local_media_path(url, user_id, settings)
    if local_path is None:
        return None

    try:
        data = local_path.read_bytes()
    except OSError:
        return None

    filename = local_path.name
    guessed, _ = mimetypes.guess_type(filename)
    mime_type = (guessed or "application/octet-stream").lower()
    return data, mime_type
