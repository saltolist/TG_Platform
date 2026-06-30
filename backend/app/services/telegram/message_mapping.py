"""Map Telethon channel messages to platform post payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from app.core.config import Settings
from app.services.telegram.media_storage import save_message_media

# Safety cap on raw messages fetched from Telegram (albums count as one post).
RAW_MESSAGE_SCAN_FACTOR = 10


def message_is_importable(message: Any) -> bool:
    if getattr(message, "action", None) is not None:
        return False
    text = getattr(message, "message", None) or ""
    if str(text).strip():
        return True
    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaPhoto):
        return True
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is None:
            return False
        mime = getattr(doc, "mime_type", "") or ""
        return (
            mime.startswith("image/")
            or mime.startswith("video/")
            or mime.startswith("application/")
        )
    return False


def format_views(views: Any) -> str:
    if views is None:
        return "0"
    return str(views)


async def map_group_to_post(
    client: Any, messages: list[Any], user_id: UUID, settings: Settings
) -> dict[str, Any] | None:
    primary = messages[0]
    text = ""
    for msg in messages:
        candidate = str(getattr(msg, "message", None) or "").strip()
        if candidate:
            text = candidate
            break

    media_items: list[dict[str, str]] = []
    for msg in messages:
        item = await save_message_media(client, msg, user_id, settings)
        if item:
            media_items.append(item)

    date = getattr(primary, "date", None)
    if date and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    iso_date = (
        date.astimezone(timezone.utc).isoformat()
        if date
        else datetime.now(timezone.utc).isoformat()
    )

    views = getattr(primary, "views", None)
    post: dict[str, Any] = {
        "id": str(getattr(primary, "id", "")),
        "status": "published",
        "date": iso_date,
        "rubric": None,
        "text": text,
        "metrics": {
            "views": format_views(views),
            "reposts": 0,
            "reactions": [],
        },
        "notes": [],
        "chats": [],
        "comments": [],
        "source": "telegram",
        "telegramMessageId": str(getattr(primary, "id", "")),
    }
    if media_items:
        post["media"] = media_items
    if not text and not media_items:
        return None
    return post


async def _flush_message_group(
    client: Any,
    group: list[Any],
    user_id: UUID,
    settings: Settings,
    posts: list[dict[str, Any]],
    *,
    limit: int | None,
) -> bool:
    """Flush an album group. Returns True when *limit* posts reached."""
    if not group:
        return False
    mapped = await map_group_to_post(client, group, user_id, settings)
    if mapped is not None:
        posts.append(mapped)
    if limit is not None and len(posts) >= limit:
        return True
    return False


async def collect_posts_from_messages(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Group *messages* (ascending id) into posts — used for catch-up batches."""
    posts: list[dict[str, Any]] = []
    group: list[Any] = []
    group_id: int | None = None

    for message in messages:
        if not message_is_importable(message):
            continue

        gid = getattr(message, "grouped_id", None) or None
        if gid:
            if group_id is not None and gid != group_id:
                if await _flush_message_group(client, group, user_id, settings, posts, limit=limit):
                    return posts[:limit] if limit else posts
                group = []
                group_id = None
            group_id = gid
            group.append(message)
        else:
            if await _flush_message_group(client, group, user_id, settings, posts, limit=limit):
                return posts[:limit] if limit else posts
            group = []
            group_id = None
            if limit is not None and len(posts) >= limit:
                return posts[:limit]
            mapped = await map_group_to_post(client, [message], user_id, settings)
            if mapped is not None:
                posts.append(mapped)
            if limit is not None and len(posts) >= limit:
                return posts[:limit]

    if group and (limit is None or len(posts) < limit):
        await _flush_message_group(client, group, user_id, settings, posts, limit=limit)

    return posts[:limit] if limit else posts


async def collect_posts_from_iter(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    *,
    limit: int,
    min_id: int = 0,
) -> list[dict[str, Any]]:
    """Fetch posts from Telethon ``iter_messages`` with optional *min_id* filter."""
    if min_id:
        collected: list[Any] = []
        async for message in client.iter_messages(entity, min_id=min_id):
            if message_is_importable(message):
                collected.append(message)
        collected.sort(key=lambda m: getattr(m, "id", 0))
        return await collect_posts_from_messages(
            client, collected, user_id, settings, limit=limit
        )

    raw_limit = max(limit * RAW_MESSAGE_SCAN_FACTOR, limit)
    posts: list[dict[str, Any]] = []
    group: list[Any] = []
    group_id: int | None = None

    async def flush_group() -> None:
        nonlocal group, group_id
        if await _flush_message_group(client, group, user_id, settings, posts, limit=limit):
            group = []
            group_id = None
            return
        group = []
        group_id = None

    async for message in client.iter_messages(entity, limit=raw_limit):
        if not message_is_importable(message):
            continue

        gid = getattr(message, "grouped_id", None) or None
        if gid:
            if group_id is not None and gid != group_id:
                await flush_group()
                if len(posts) >= limit:
                    break
            group_id = gid
            group.append(message)
        else:
            await flush_group()
            if len(posts) >= limit:
                break
            mapped = await map_group_to_post(client, [message], user_id, settings)
            if mapped is not None:
                posts.append(mapped)
            if len(posts) >= limit:
                break

    if len(posts) < limit and group:
        await flush_group()

    return posts[:limit]
