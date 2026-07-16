"""Normalize post JSON blobs before API responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.services.telegram.comments_flow import normalize_post_comments

_TELEGRAM_IMPORTED_WEBP = re.compile(r"^/media/[^/]+/\d+\.webp$", re.IGNORECASE)
_TELEGRAM_IMPORTED_JSON = re.compile(r"^/media/[^/]+/\d+\.json$", re.IGNORECASE)
_TGS_MIMES = frozenset({"application/x-tgsticker", "application/x-tgs"})


def normalize_post_media_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure ``kind`` is set for Telegram sticker media saved before kind was persisted."""
    result = dict(item)
    kind = result.get("kind")
    if kind in {
        "image",
        "video",
        "video_note",
        "sticker",
        "animated_sticker",
        "video_sticker",
        "voice",
        "document",
    }:
        return result

    mime = (result.get("type") or "").lower()
    url = (result.get("url") or "").lower()
    if mime in _TGS_MIMES or _TELEGRAM_IMPORTED_JSON.match(url):
        result["kind"] = "animated_sticker"
    elif mime == "image/webp" and _TELEGRAM_IMPORTED_WEBP.match(url):
        result["kind"] = "sticker"
    return result


def _normalize_media_list(media: Any) -> list[dict[str, Any]]:
    if not isinstance(media, list):
        return []
    return [
        normalize_post_media_item(item) for item in media if isinstance(item, Mapping)
    ]


def normalize_post_for_api(
    data: Mapping[str, Any],
    *,
    db_id: str | None = None,
) -> dict[str, Any]:
    """Ensure required Post fields exist so clients can parse the payload reliably.

    ``id`` always reflects the UUID PK (``db_id``), never the JSONB
    ``data['id']`` — that legacy field stays the RAG partition key /
    telegramMessageId alias internally and must never reach clients (or come
    back on a write), or it drifts from the PK on Telegram re-sync and the
    frontend starts addressing a post that resolvers can no longer find
    (chat d395d1ef: post_id "3" sent by the client matched neither the PK nor
    any post's legacy data['id']).
    """
    result = dict(data)
    if db_id:
        result["id"] = db_id
    elif not result.get("id"):
        result["id"] = None
    if result.get("notes") is None:
        result["notes"] = []
    if result.get("chats") is None:
        result["chats"] = []
    if result.get("text") is None:
        result["text"] = ""
    if "rubric" not in result:
        result["rubric"] = None
    if isinstance(result.get("media"), list):
        result["media"] = _normalize_media_list(result["media"])
    if isinstance(result.get("comments"), list):
        comments = normalize_post_comments(result["comments"])
        for comment in comments:
            if isinstance(comment.get("media"), list):
                comment["media"] = _normalize_media_list(comment["media"])
        result["comments"] = comments
    return result


__all__ = ["normalize_post_for_api", "normalize_post_media_item"]
