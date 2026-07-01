"""Track in-flight platform→Telegram operations in Redis (survives page reload).

While publish / edit-sync / delete-sync runs, the post id is stored under a short
TTL so ``GET /posts/`` can expose ``telegramSyncPending: true`` until the RPC
finishes or the TTL expires.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 180
_redis_client: Any | None = None
_redis_unavailable = False
# Fallback when Redis is down (tests / local without redis).
_memory_store: dict[str, dict[str, float]] = {}


def _user_key(user_id: UUID) -> str:
    return str(user_id)


def _post_key(user_id: UUID, post_id: str) -> str:
    return f"tg:sync:{user_id}:{post_id}"


def _set_key(user_id: UUID) -> str:
    return f"tg:sync-pending:{user_id}"


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
        logger.warning("Redis unavailable for telegram sync-pending — using in-memory fallback")
        _redis_unavailable = True
        return None


def _memory_mark(user_id: UUID, post_id: str, ttl: int) -> None:
    bucket = _memory_store.setdefault(_user_key(user_id), {})
    bucket[post_id] = time.monotonic() + ttl


def _memory_clear(user_id: UUID, post_id: str) -> None:
    bucket = _memory_store.get(_user_key(user_id))
    if bucket is not None:
        bucket.pop(post_id, None)


def _memory_pending(user_id: UUID) -> set[str]:
    bucket = _memory_store.get(_user_key(user_id), {})
    now = time.monotonic()
    alive = {pid for pid, expires in bucket.items() if expires > now}
    for pid in list(bucket):
        if pid not in alive:
            bucket.pop(pid, None)
    return alive


async def mark_post_sync_pending(user_id: UUID, post_id: str) -> None:
    pid = str(post_id)
    redis = await _get_redis()
    if redis is None:
        _memory_mark(user_id, pid, _TTL_SECONDS)
        return
    pipe = redis.pipeline()
    pipe.set(_post_key(user_id, pid), "1", ex=_TTL_SECONDS)
    pipe.sadd(_set_key(user_id), pid)
    await pipe.execute()


async def clear_post_sync_pending(user_id: UUID, post_id: str) -> None:
    pid = str(post_id)
    redis = await _get_redis()
    if redis is None:
        _memory_clear(user_id, pid)
        return
    pipe = redis.pipeline()
    pipe.delete(_post_key(user_id, pid))
    pipe.srem(_set_key(user_id), pid)
    await pipe.execute()


async def get_pending_post_ids(user_id: UUID) -> set[str]:
    redis = await _get_redis()
    if redis is None:
        return _memory_pending(user_id)
    members = await redis.smembers(_set_key(user_id))
    if not members:
        return set()
    alive: set[str] = set()
    for pid in members:
        if await redis.exists(_post_key(user_id, pid)):
            alive.add(pid)
        else:
            await redis.srem(_set_key(user_id), pid)
    return alive


def enrich_post_data(data: dict[str, Any], pending_ids: set[str]) -> dict[str, Any]:
    result = dict(data)
    post_id = str(result.get("id") or "")
    if post_id and post_id in pending_ids:
        result["telegramSyncPending"] = True
    else:
        result.pop("telegramSyncPending", None)
    return result


async def enrich_posts_for_user(
    user_id: UUID, posts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    pending = await get_pending_post_ids(user_id)
    return [enrich_post_data(post, pending) for post in posts]


@asynccontextmanager
async def telegram_sync_pending(
    user_id: UUID, post_id: str | UUID
) -> AsyncIterator[None]:
    pid = str(post_id)
    await mark_post_sync_pending(user_id, pid)
    try:
        yield
    finally:
        await clear_post_sync_pending(user_id, pid)


async def reset_sync_pending_storage() -> None:
    """Test helper — drop in-memory state and redis connection."""
    global _redis_client, _redis_unavailable
    _memory_store.clear()
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _redis_unavailable = False


__all__ = [
    "clear_post_sync_pending",
    "enrich_post_data",
    "enrich_posts_for_user",
    "get_pending_post_ids",
    "mark_post_sync_pending",
    "reset_sync_pending_storage",
    "telegram_sync_pending",
]
