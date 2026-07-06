"""Cross-process Telegram listener control (dedicated sync worker mode)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_ACTIVE_TTL_SECONDS = 60
_PAUSE_POLL_INTERVAL = 0.25

_redis_client: Any | None = None
_redis_unavailable = False


def uses_remote_listener(settings: Settings | None = None) -> bool:
    """True when this process does not run the in-process live-sync worker."""
    settings = settings or get_settings()
    return not settings.telegram_live_sync_enabled


def _active_key(user_id: UUID) -> str:
    return f"tg:listener:active:{user_id}"


def _pause_channel(user_id: UUID) -> str:
    return f"tg:listener:pause:{user_id}"


def _resume_channel(user_id: UUID) -> str:
    return f"tg:listener:resume:{user_id}"


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
        logger.warning("Redis unavailable for listener control")
        _redis_unavailable = True
        return None


async def touch_listener_active(user_id: UUID) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    await redis.set(_active_key(user_id), "1", ex=_ACTIVE_TTL_SECONDS)


async def clear_listener_active(user_id: UUID) -> None:
    redis = await _get_redis()
    if redis is None:
        return
    await redis.delete(_active_key(user_id))


async def is_listener_active_remote(user_id: UUID) -> bool:
    redis = await _get_redis()
    if redis is None:
        return False
    return bool(await redis.exists(_active_key(user_id)))


async def request_listener_pause(
    user_id: UUID, *, timeout: float | None = None
) -> None:
    """Stop the live-sync listener before exclusive reader MTProto use."""
    from app.services.telegram.live_sync_worker import listener_registry

    settings = get_settings()
    wait_seconds = (
        timeout if timeout is not None else settings.telegram_listener_stop_timeout_seconds
    )
    if settings.telegram_live_sync_enabled:
        await listener_registry.await_stop_user_listener(user_id, timeout=wait_seconds)
        return

    redis = await _get_redis()
    if redis is None:
        logger.warning(
            "Cannot pause remote listener for user %s — Redis unavailable", user_id
        )
        return

    await redis.publish(_pause_channel(user_id), "1")
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        if not await redis.exists(_active_key(user_id)):
            return
        await asyncio.sleep(_PAUSE_POLL_INTERVAL)

    logger.warning("Remote listener pause timed out for user %s", user_id)


async def signal_listener_resume(user_id: UUID, telegram: dict[str, Any]) -> None:
    """Ask the sync worker to restart the listener after exclusive reader use."""
    from app.services.telegram.live_sync_worker import (
        ensure_user_listener,
        should_listen,
    )

    settings = get_settings()
    if settings.telegram_live_sync_enabled:
        if should_listen(telegram):
            ensure_user_listener(user_id, telegram)
        return

    if not should_listen(telegram):
        return

    redis = await _get_redis()
    if redis is None:
        return
    await redis.publish(_resume_channel(user_id), "1")


async def ensure_user_listener_async(user_id: UUID, telegram: dict[str, Any]) -> None:
    """Start listener in-process, or no-op when a remote sync worker owns listeners."""
    if uses_remote_listener():
        return
    from app.services.telegram.live_sync_worker import ensure_user_listener

    ensure_user_listener(user_id, telegram)


async def apply_effective_sync_fields_async(
    telegram: dict[str, Any], user_id: UUID
) -> dict[str, Any]:
    from app.services.telegram.live_sync_worker import should_listen

    result = dict(telegram)
    sync_status, sync_error = await effective_sync_status_async(telegram, user_id)
    result["syncStatus"] = sync_status
    result["syncError"] = sync_error
    if not should_listen(telegram) and sync_status == "listening":
        result["syncStatus"] = str(telegram.get("syncStatus") or "idle")
    return result


async def effective_sync_status_async(
    telegram: dict[str, Any], user_id: UUID
) -> tuple[str, str]:
    from app.services.telegram.live_sync_worker import listener_registry, should_listen

    if not should_listen(telegram):
        return str(telegram.get("syncStatus") or "idle"), str(telegram.get("syncError") or "")
    if uses_remote_listener():
        if await is_listener_active_remote(user_id):
            return "listening", ""
    elif listener_registry.is_running(user_id):
        return "listening", ""
    stored_status = str(telegram.get("syncStatus") or "idle")
    stored_error = str(telegram.get("syncError") or "")
    if stored_status == "listening":
        return "idle", stored_error
    return stored_status, stored_error


async def run_listener_control_subscriber(stop_event: asyncio.Event) -> None:
    """Sync-worker side: react to pause/resume pub/sub signals."""
    from app.db.session import async_session_factory
    from app.services.telegram.live_sync_worker import (
        ensure_user_listener,
        listener_registry,
    )

    redis = await _get_redis()
    if redis is None:
        return

    pubsub = redis.pubsub()
    await pubsub.psubscribe("tg:listener:pause:*", "tg:listener:resume:*")
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
            if channel.startswith("tg:listener:pause:"):
                user_id_raw = channel.rsplit(":", 1)[-1]
                try:
                    user_id = UUID(user_id_raw)
                except ValueError:
                    continue
                await listener_registry.await_stop_user_listener(user_id)
                await clear_listener_active(user_id)
            elif channel.startswith("tg:listener:resume:"):
                user_id_raw = channel.rsplit(":", 1)[-1]
                try:
                    user_id = UUID(user_id_raw)
                except ValueError:
                    continue
                async with async_session_factory() as session:
                    from app.db.models import Profile

                    profile = await session.get(Profile, user_id)
                    if profile is not None:
                        ensure_user_listener(user_id, profile.telegram or {})
    finally:
        await pubsub.punsubscribe("tg:listener:pause:*", "tg:listener:resume:*")
        await pubsub.aclose()


async def reset_listener_control_storage() -> None:
    """Test helper."""
    global _redis_client, _redis_unavailable
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _redis_unavailable = False


__all__ = [
    "apply_effective_sync_fields_async",
    "clear_listener_active",
    "effective_sync_status_async",
    "ensure_user_listener_async",
    "is_listener_active_remote",
    "request_listener_pause",
    "reset_listener_control_storage",
    "run_listener_control_subscriber",
    "signal_listener_resume",
    "touch_listener_active",
    "uses_remote_listener",
]
