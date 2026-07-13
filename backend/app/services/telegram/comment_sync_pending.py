"""Track in-flight platform→Telegram comment push/delete in Redis (survives reload).

While background comment push or discussion delete runs, the post id is stored so
``GET /posts/`` can expose ``commentsSyncPending: true`` until the RPC finishes.
"""

from __future__ import annotations

import logging
import asyncio
import time
from typing import Any
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 180
_redis_clients: dict[asyncio.AbstractEventLoop, Any] = {}
_redis_unavailable: set[asyncio.AbstractEventLoop] = set()
_memory_store: dict[str, dict[str, float]] = {}


def _user_key(user_id: UUID) -> str:
    return str(user_id)


def _post_key(user_id: UUID, post_id: str) -> str:
    return f"tg:comment-sync:{user_id}:{post_id}"


def _set_key(user_id: UUID) -> str:
    return f"tg:comment-sync-pending:{user_id}"


async def _get_redis() -> Any | None:
    loop_key = asyncio.get_running_loop()
    if loop_key in _redis_unavailable:
        return None
    if loop_key in _redis_clients:
        return _redis_clients[loop_key]
    try:
        from redis.asyncio import Redis

        settings = get_settings()
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis_clients[loop_key] = client
        return client
    except Exception:  # noqa: BLE001
        logger.warning(
            "Redis unavailable for comment sync-pending — using in-memory fallback"
        )
        _redis_unavailable.add(loop_key)
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


async def mark_comments_sync_pending(user_id: UUID, post_id: str) -> None:
    pid = str(post_id)
    redis = await _get_redis()
    if redis is None:
        _memory_mark(user_id, pid, _TTL_SECONDS)
        return
    pipe = redis.pipeline()
    pipe.set(_post_key(user_id, pid), "1", ex=_TTL_SECONDS)
    pipe.sadd(_set_key(user_id), pid)
    await pipe.execute()


async def clear_comments_sync_pending(user_id: UUID, post_id: str) -> None:
    pid = str(post_id)
    redis = await _get_redis()
    if redis is None:
        _memory_clear(user_id, pid)
        return
    pipe = redis.pipeline()
    pipe.delete(_post_key(user_id, pid))
    pipe.srem(_set_key(user_id), pid)
    await pipe.execute()


async def get_pending_comment_post_ids(user_id: UUID) -> set[str]:
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
        result["commentsSyncPending"] = True
    else:
        result.pop("commentsSyncPending", None)
    return result


async def enrich_posts_for_user(
    user_id: UUID, posts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    pending = await get_pending_comment_post_ids(user_id)
    return [enrich_post_data(post, pending) for post in posts]


async def reset_comment_sync_pending_storage() -> None:
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
    "clear_comments_sync_pending",
    "enrich_post_data",
    "enrich_posts_for_user",
    "get_pending_comment_post_ids",
    "mark_comments_sync_pending",
    "reset_comment_sync_pending_storage",
]
