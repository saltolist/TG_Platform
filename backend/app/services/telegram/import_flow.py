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

from app.core.config import Settings, get_settings
from app.db.models import Post, Profile
from app.db.seed_ids import user_scoped_entity_uuid
from app.db.session import async_session_factory
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.message_mapping import collect_posts_from_iter
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.session_guard import telegram_session_lock

logger = logging.getLogger(__name__)


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

        max_message_id = 0
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
            try:
                max_message_id = max(max_message_id, int(post_data["telegramMessageId"]))
            except (TypeError, ValueError, KeyError):
                pass

        offset = len(posts_data)
        for index, post in enumerate(remaining):
            post.position = offset + index

        telegram = dict(profile.telegram or {})
        telegram["importedPosts"] = len(posts_data)
        telegram["lastSync"] = datetime.now(timezone.utc).isoformat()
        telegram["syncRevision"] = int(telegram.get("syncRevision") or 0) + 1
        telegram["importStatus"] = import_status
        telegram["importError"] = import_error
        if max_message_id > 0:
            telegram["lastTelegramMessageId"] = str(max_message_id)
        profile.telegram = telegram

        await session.commit()

    if import_status == "done":
        from app.services.telegram.live_sync_worker import listener_registry

        listener_registry.start_user_listener(user_id)


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
        await connect_telegram_client(client, settings)
        entity = await resolve_channel_entity(client, parsed, settings)
        posts_data = await collect_posts_from_iter(
            client,
            entity,
            user_id,
            settings,
            limit=settings.telegram_import_post_limit,
        )
        await _persist_import_result(user_id, posts_data, import_status="done")
    finally:
        await disconnect_safely(client)


async def run_channel_import(user_id: UUID, settings: Settings | None = None) -> None:
    """Background entry point — wraps the import with a global timeout and error handling."""
    from app.services.telegram.live_sync_worker import listener_registry

    settings = settings or get_settings()
    await listener_registry.await_stop_user_listener(user_id)
    try:
        async with telegram_session_lock(user_id):
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
