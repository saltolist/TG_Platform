"""Per-user serialization for background channel ingest (catch-up, reconcile, metrics poll)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_ingest_locks: dict[UUID, asyncio.Lock] = {}
_ingest_locks_guard = asyncio.Lock()


async def ingest_lock_for(user_id: UUID) -> asyncio.Lock:
    async with _ingest_locks_guard:
        lock = _ingest_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _ingest_locks[user_id] = lock
        return lock


def ingest_lock_busy(user_id: UUID) -> bool:
    lock = _ingest_locks.get(user_id)
    return lock is not None and lock.locked()


async def run_channel_ingest(user_id: UUID, operation: Callable[[], Awaitable[_T]]) -> _T:
    """Run a background ingest pass — waits if another pass is in flight."""
    lock = await ingest_lock_for(user_id)
    async with lock:
        return await operation()


async def run_channel_ingest_if_idle(
    user_id: UUID,
    operation: Callable[[], Awaitable[_T]],
    *,
    label: str = "ingest",
) -> _T | None:
    """Run only when no other ingest holds the lock; otherwise skip (no queue)."""
    lock = await ingest_lock_for(user_id)
    if lock.locked():
        logger.debug("Skipped %s for user %s — channel ingest busy", label, user_id)
        return None
    async with lock:
        return await operation()
