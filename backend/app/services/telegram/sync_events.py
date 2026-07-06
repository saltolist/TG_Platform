"""In-process SSE pub/sub for Telegram sync revision updates."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import UUID

from app.services.ai.sse import format_sse_comment, format_sse_meta

logger = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 25.0

_SYNC_EVENT_FIELDS = (
    "syncRevision",
    "commentsRevision",
    "metricsRevision",
    "lastSync",
    "syncStatus",
    "syncError",
    "channelStatus",
    "syncMode",
    "importStatus",
)

_subscribers: dict[UUID, list[asyncio.Queue[dict[str, Any]]]] = {}
_registry_lock = asyncio.Lock()


def telegram_sync_event_payload(telegram: Mapping[str, Any]) -> dict[str, Any]:
    """Extract client-facing sync fields from a profile.telegram dict."""
    return {
        "syncRevision": int(telegram.get("syncRevision") or 0),
        "commentsRevision": int(telegram.get("commentsRevision") or 0),
        "metricsRevision": int(telegram.get("metricsRevision") or 0),
        "lastSync": str(telegram.get("lastSync") or "—"),
        "syncStatus": str(telegram.get("syncStatus") or "idle"),
        "syncError": str(telegram.get("syncError") or ""),
        "channelStatus": str(telegram.get("channelStatus") or "idle"),
        "syncMode": str(telegram.get("syncMode") or "history-and-live"),
        "importStatus": str(telegram.get("importStatus") or "idle"),
    }


async def subscribe_telegram_sync_events(user_id: UUID) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    async with _registry_lock:
        _subscribers.setdefault(user_id, []).append(queue)
    return queue


async def unsubscribe_telegram_sync_events(
    user_id: UUID, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    async with _registry_lock:
        subscribers = _subscribers.get(user_id)
        if subscribers is None:
            return
        try:
            subscribers.remove(queue)
        except ValueError:
            return
        if not subscribers:
            _subscribers.pop(user_id, None)


def publish_telegram_sync_event(user_id: UUID, telegram: Mapping[str, Any]) -> None:
    """Notify all SSE subscribers for *user_id* (best-effort, never raises)."""
    payload = telegram_sync_event_payload(telegram)
    subscribers = list(_subscribers.get(user_id, ()))
    for queue in subscribers:
        try:
            queue.put_nowait(payload)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to enqueue telegram sync event for user %s", user_id, exc_info=True)


async def stream_telegram_sync_events(
    user_id: UUID,
    initial: Mapping[str, Any],
    *,
    is_disconnected: Any | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames: initial snapshot, revision pushes, and heartbeats."""
    queue = await subscribe_telegram_sync_events(user_id)
    try:
        yield format_sse_meta(telegram_sync_event_payload(initial))
        while True:
            if is_disconnected is not None and await is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield format_sse_comment("ping")
                continue
            yield format_sse_meta(payload)
    finally:
        await unsubscribe_telegram_sync_events(user_id, queue)


__all__ = [
    "publish_telegram_sync_event",
    "stream_telegram_sync_events",
    "subscribe_telegram_sync_events",
    "telegram_sync_event_payload",
    "unsubscribe_telegram_sync_events",
]
