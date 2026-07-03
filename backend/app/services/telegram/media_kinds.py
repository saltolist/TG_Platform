"""Classify Telegram message media into platform ``PostMedia.kind`` values."""

from __future__ import annotations

import json
from typing import Any, Literal

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

PostMediaKind = Literal[
    "image",
    "video",
    "video_note",
    "sticker",
    "animated_sticker",
    "video_sticker",
    "document",
]

TGS_MIME_TYPES = frozenset(
    {
        "application/x-tgsticker",
        "application/x-tgs",
    }
)


def _attribute_type_name(attribute: Any) -> str:
    return type(attribute).__name__


def _document_attributes(document: Any) -> list[Any]:
    return list(getattr(document, "attributes", None) or [])


def _has_sticker_attribute(document: Any) -> bool:
    return any(_attribute_type_name(attr) == "DocumentAttributeSticker" for attr in _document_attributes(document))


def _is_round_video(document: Any) -> bool:
    for attr in _document_attributes(document):
        if _attribute_type_name(attr) == "DocumentAttributeVideo":
            if bool(getattr(attr, "round_message", False)):
                return True
    return False


def classify_telegram_media(message: Any) -> PostMediaKind | None:
    """Map a Telethon message to a platform media kind, or ``None`` when no media."""
    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaPhoto):
        return "image"
    if not isinstance(media, MessageMediaDocument):
        return None

    document = getattr(media, "document", None)
    if document is None:
        return None

    mime = (getattr(document, "mime_type", None) or "").lower()
    if _is_round_video(document):
        return "video_note"
    if _has_sticker_attribute(document):
        if mime in TGS_MIME_TYPES:
            return "animated_sticker"
        if mime.startswith("video/"):
            return "video_sticker"
        return "sticker"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    return "document"


def normalize_tgs_to_lottie_json(raw: bytes) -> bytes:
    """Decompress a Telegram ``.tgs`` sticker into Lottie JSON bytes."""
    import gzip

    try:
        payload = gzip.decompress(raw)
    except OSError as exc:
        raise ValueError("Invalid TGS gzip payload") from exc
    try:
        json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid TGS Lottie JSON") from exc
    return payload
