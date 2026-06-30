"""Telegram channel history import (Telethon), Phase 3 / Step 3.

Runs as a background task after ``POST /telegram/channel/connect/``.
Imports up to ``telegram_import_post_limit`` posts (text + photo/document media)
into ``posts`` with ``data.source = "telegram"`` for idempotent re-import.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from app.core.config import Settings, get_settings
from app.db.models import Post, Profile
from app.db.seed_ids import user_scoped_entity_uuid
from app.db.session import async_session_factory
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.media_storage import save_message_media
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)

logger = logging.getLogger(__name__)

# Safety cap on raw messages fetched from Telegram (albums count as one post).
_RAW_MESSAGE_SCAN_FACTOR = 10


def _message_is_importable(message: Any) -> bool:
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


def _format_views(views: Any) -> str:
    if views is None:
        return "0"
    return str(views)


async def _map_group_to_post(
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
    iso_date = date.astimezone(timezone.utc).isoformat() if date else datetime.now(timezone.utc).isoformat()

    views = getattr(primary, "views", None)
    post: dict[str, Any] = {
        "id": str(getattr(primary, "id", "")),
        "status": "published",
        "date": iso_date,
        "rubric": None,
        "text": text,
        "metrics": {
            "views": _format_views(views),
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


async def _collect_posts(
    client: Any, entity: Any, user_id: UUID, settings: Settings
) -> list[dict[str, Any]]:
    limit = settings.telegram_import_post_limit
    raw_limit = max(limit * _RAW_MESSAGE_SCAN_FACTOR, limit)
    posts: list[dict[str, Any]] = []
    group: list[Any] = []
    group_id: int | None = None

    async def flush_group() -> None:
        nonlocal group, group_id
        if not group:
            return
        mapped = await _map_group_to_post(client, group, user_id, settings)
        if mapped is not None:
            posts.append(mapped)
        group = []
        group_id = None

    async for message in client.iter_messages(entity, limit=raw_limit):
        if not _message_is_importable(message):
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
            mapped = await _map_group_to_post(client, [message], user_id, settings)
            if mapped is not None:
                posts.append(mapped)
            if len(posts) >= limit:
                break

    if len(posts) < limit and group:
        await flush_group()

    return posts[:limit]


async def _persist_import_result(
    user_id: UUID,
    posts_data: list[dict[str, Any]],
    *,
    import_status: str,
    import_error: str = "",
) -> None:
    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return

        await session.execute(
            delete(Post).where(
                Post.user_id == user_id,
                Post.data["source"].astext == "telegram",
            )
        )

        result = await session.execute(
            select(Post).where(Post.user_id == user_id).order_by(Post.position)
        )
        remaining = list(result.scalars())

        for index, post_data in enumerate(posts_data):
            seed_id = f"tg-{post_data['telegramMessageId']}"
            session.add(
                Post(
                    id=user_scoped_entity_uuid(user_id, "post", seed_id),
                    user_id=user_id,
                    position=index,
                    data=post_data,
                )
            )

        offset = len(posts_data)
        for index, post in enumerate(remaining):
            post.position = offset + index

        telegram = dict(profile.telegram or {})
        telegram["importedPosts"] = len(posts_data)
        telegram["lastSync"] = datetime.now(timezone.utc).isoformat()
        telegram["importStatus"] = import_status
        telegram["importError"] = import_error
        profile.telegram = telegram

        await session.commit()


async def _set_import_error(user_id: UUID, error: str) -> None:
    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return
        telegram = dict(profile.telegram or {})
        telegram["importStatus"] = "error"
        telegram["importError"] = error[:500]
        profile.telegram = telegram
        await session.commit()


async def _import_channel_history(user_id: UUID, settings: Settings) -> None:
    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return
        telegram = profile.telegram or {}
        if telegram.get("channelStatus") != "connected":
            return
        if telegram.get("syncMode") == "publish-only":
            return

        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        channel_input = str(telegram.get("channel") or "")
        parsed = parse_channel_input(channel_input)
        if not parsed or not session_string:
            await _set_import_error(user_id, "Не удалось подготовить импорт канала")
            return

    client = build_client(api_id, api_hash, session_string)
    try:
        await with_timeout(client.connect(), settings)
        entity = await resolve_channel_entity(client, parsed, settings)
        posts_data = await _collect_posts(client, entity, user_id, settings)
        await _persist_import_result(user_id, posts_data, import_status="done")
    finally:
        await disconnect_safely(client)


async def run_channel_import(user_id: UUID, settings: Settings | None = None) -> None:
    """Background entry point — wraps the import with a global timeout and error handling."""
    settings = settings or get_settings()
    try:
        await asyncio.wait_for(
            _import_channel_history(user_id, settings),
            timeout=settings.telegram_import_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning("Telegram import timed out for user %s", user_id)
        await _set_import_error(user_id, "Импорт занял слишком много времени, попробуйте позже")
    except Exception as exc:  # noqa: BLE001 — background task must not crash the worker
        logger.exception("Telegram import failed for user %s", user_id)
        await _set_import_error(user_id, str(exc) or "Не удалось импортировать историю канала")
