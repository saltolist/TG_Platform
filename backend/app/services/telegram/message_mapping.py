"""Map Telethon channel messages to platform post payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from app.core.config import Settings
from app.services.telegram.media_storage import resolve_group_media, save_message_media
from app.services.telegram.text_formatting import apply_message_text_fields, extract_plain_text

# Safety cap on raw messages fetched from Telegram (albums count as one post).
RAW_MESSAGE_SCAN_FACTOR = 10
_NON_FETCHABLE_MESSAGE_TYPES = frozenset({"MessageEmpty", "MessageService"})
MESSAGE_GONE_MARKERS = (
    "message id is invalid",
    "message_id_invalid",
    "can't do that operation on such message",
    "message to edit not found",
    "message to delete not found",
    "message not found",
)


def is_message_gone_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in MESSAGE_GONE_MARKERS)


def telethon_message_fetchable(message: Any) -> bool:
    """True when ``get_messages`` returned a real post, not a tombstone."""
    if message is None:
        return False
    if type(message).__name__ in _NON_FETCHABLE_MESSAGE_TYPES:
        return False
    return bool(getattr(message, "id", None))


def telethon_fetch_has_messages(fetched: Any) -> bool:
    if fetched is None:
        return False
    if isinstance(fetched, (list, tuple)):
        return any(telethon_message_fetchable(message) for message in fetched)
    return telethon_message_fetchable(fetched)


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


def _reaction_to_emoji(reaction: Any) -> str | None:
    emoticon = getattr(reaction, "emoticon", None)
    if emoticon:
        return str(emoticon)
    return None


def extract_metrics_from_message(message: Any) -> dict[str, Any]:
    """Map Telethon message counters to platform ``PostMetrics``."""
    views = format_views(getattr(message, "views", None))
    forwards = getattr(message, "forwards", None)
    reposts = int(forwards) if forwards else 0

    reactions: list[dict[str, Any]] = []
    msg_reactions = getattr(message, "reactions", None)
    if msg_reactions is not None:
        for item in getattr(msg_reactions, "results", None) or []:
            count = int(getattr(item, "count", 0) or 0)
            if count <= 0:
                continue
            emoji = _reaction_to_emoji(getattr(item, "reaction", None))
            if emoji:
                reactions.append({"emoji": emoji, "count": count})

    return {"views": views, "reposts": reposts, "reactions": reactions}


def _telegram_edit_timestamp_iso(message: Any) -> str | None:
    """ISO timestamp of the last Telegram-side edit, if the message was edited."""
    edit_date = getattr(message, "edit_date", None)
    if edit_date is None:
        return None
    if edit_date.tzinfo is None:
        edit_date = edit_date.replace(tzinfo=timezone.utc)
    return edit_date.astimezone(timezone.utc).isoformat()


async def map_group_to_post(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    *,
    fetch_media: bool = True,
    existing_media: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    primary = messages[0]
    text = ""
    text_html: str | None = None
    for msg in messages:
        candidate = extract_plain_text(msg)
        if candidate:
            text = candidate
            payload: dict[str, Any] = {}
            apply_message_text_fields(payload, msg)
            text_html = payload.get("textHtml")
            break

    media_items: list[dict[str, Any]] = []
    if fetch_media:
        if existing_media is not None:
            media_items = await resolve_group_media(
                client, messages, user_id, settings, existing_media
            )
        else:
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
        "metrics": extract_metrics_from_message(primary),
        "notes": [],
        "chats": [],
        "comments": [],
        "source": "telegram",
        "telegramMessageId": str(getattr(primary, "id", "")),
    }
    if media_items:
        post["media"] = media_items
    if text_html:
        post["textHtml"] = text_html
    telegram_edit = _telegram_edit_timestamp_iso(primary)
    if telegram_edit:
        post["_telegramEditDate"] = telegram_edit
    if not text and not media_items:
        return None
    return post


def map_message_for_reconcile(message: Any) -> dict[str, Any] | None:
    """Lightweight TG message → post payload for window reconcile (no media download)."""
    text = extract_plain_text(message)
    if not text and getattr(message, "media", None) is None:
        return None

    date = getattr(message, "date", None)
    if date and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    iso_date = (
        date.astimezone(timezone.utc).isoformat()
        if date
        else datetime.now(timezone.utc).isoformat()
    )

    post: dict[str, Any] = {
        "status": "published",
        "date": iso_date,
        "text": text,
        "metrics": extract_metrics_from_message(message),
        "source": "telegram",
        "telegramMessageId": str(getattr(message, "id", "")),
    }
    apply_message_text_fields(post, message)
    telegram_edit = _telegram_edit_timestamp_iso(message)
    if telegram_edit:
        post["_telegramEditDate"] = telegram_edit
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
