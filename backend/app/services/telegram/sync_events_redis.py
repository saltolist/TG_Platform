"""Redis pub/sub bridge for Telegram sync SSE across API replicas."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SYNC_EVENTS_PREFIX = "tg:sync-events:"

_redis_client: Any | None = None
_redis_unavailable = False
_bridge_task: asyncio.Task[None] | None = None


async def _get_redis() -> Any | None:
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        from redis.asyncio import Redis

        settings = get_settings()
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:  # noqa: BLE001
        logger.warning("Redis unavailable for sync-events bridge — local SSE only")
        _redis_unavailable = True
        return None


def _channel_for_user(user_id: UUID) -> str:
    return f"{_SYNC_EVENTS_PREFIX}{user_id}"


async def publish_sync_event_to_redis(user_id: UUID, payload: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_sync_events_redis_enabled:
        return
    redis = await _get_redis()
    if redis is None:
        return
    try:
        await redis.publish(_channel_for_user(user_id), json.dumps(payload))
    except Exception:  # noqa: BLE001
        logger.debug("Failed to publish sync event to Redis for user %s", user_id, exc_info=True)


async def start_redis_sync_events_bridge(stop_event: asyncio.Event) -> None:
    """Subscribe to Redis sync-events and fan out into in-process SSE queues."""
    from app.services.telegram.sync_events import fan_out_local_sync_event

    settings = get_settings()
    if not settings.telegram_sync_events_redis_enabled:
        while not stop_event.is_set():
            await asyncio.sleep(1.0)
        return

    redis = await _get_redis()
    if redis is None:
        while not stop_event.is_set():
            await asyncio.sleep(1.0)
        return

    pubsub = redis.pubsub()
    await pubsub.psubscribe(f"{_SYNC_EVENTS_PREFIX}*")
    try:
        while not stop_event.is_set():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                continue
            if message.get("type") not in {"message", "pmessage"}:
                continue
            channel = str(message.get("channel") or "")
            if not channel.startswith(_SYNC_EVENTS_PREFIX):
                continue
            user_id_raw = channel[len(_SYNC_EVENTS_PREFIX) :]
            try:
                user_id = UUID(user_id_raw)
            except ValueError:
                continue
            raw_data = message.get("data")
            if not raw_data:
                continue
            try:
                payload = json.loads(raw_data)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                fan_out_local_sync_event(user_id, payload)
    finally:
        await pubsub.punsubscribe(f"{_SYNC_EVENTS_PREFIX}*")
        await pubsub.aclose()


def ensure_redis_sync_events_bridge(stop_event: asyncio.Event) -> asyncio.Task[None]:
    global _bridge_task
    if _bridge_task is not None and not _bridge_task.done():
        return _bridge_task
    _bridge_task = asyncio.create_task(
        start_redis_sync_events_bridge(stop_event),
        name="redis-sync-events-bridge",
    )
    return _bridge_task


async def reset_sync_events_redis_storage() -> None:
    """Test helper."""
    global _redis_client, _redis_unavailable, _bridge_task
    if _bridge_task is not None and not _bridge_task.done():
        _bridge_task.cancel()
        try:
            await _bridge_task
        except asyncio.CancelledError:
            pass
    _bridge_task = None
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _redis_unavailable = False


__all__ = [
    "ensure_redis_sync_events_bridge",
    "publish_sync_event_to_redis",
    "reset_sync_events_redis_storage",
    "start_redis_sync_events_bridge",
]
