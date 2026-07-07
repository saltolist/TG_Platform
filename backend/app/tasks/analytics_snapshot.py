"""Celery Beat task: periodic per-post and channel metric snapshots."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.models import Profile
from app.db.session import async_session_factory
from app.services.analytics.analytics_snapshot import capture_metrics_snapshot
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
)
from app.tasks.publish import _run_async

logger = logging.getLogger(__name__)


async def _capture_for_user(user_id: UUID, settings: Any) -> None:
    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return
        telegram = dict(profile.telegram or {})
        if telegram.get("channelStatus") != "connected":
            return

    client = None
    entity = None
    try:
        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        parsed = parse_channel_input(str(telegram.get("channel") or ""))
        if parsed and session_string:
            client = build_client(api_id, api_hash, session_string)
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Telethon unavailable for analytics snapshot user %s — DB-only capture",
            user_id,
            exc_info=True,
        )
        client = None
        entity = None

    try:
        await capture_metrics_snapshot(
            async_session_factory,
            user_id,
            client,
            entity,
            settings,
        )
    finally:
        if client is not None:
            await disconnect_safely(client)


async def _capture_all_channel_snapshots() -> None:
    settings = get_settings()
    if settings.telegram_analytics_snapshot_seconds <= 0:
        return

    async with async_session_factory() as session:
        result = await session.execute(select(Profile))
        profiles = list(result.scalars().all())

    for profile in profiles:
        telegram = profile.telegram or {}
        if telegram.get("channelStatus") != "connected":
            continue
        try:
            await _capture_for_user(profile.user_id, settings)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Analytics snapshot failed for user %s",
                profile.user_id,
            )


@celery_app.task(name="app.tasks.analytics_snapshot.capture_all_channel_snapshots")
def capture_all_channel_snapshots() -> None:
    """Capture metric snapshots for every connected channel."""
    _run_async(_capture_all_channel_snapshots())
