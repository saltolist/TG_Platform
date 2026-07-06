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

_pending_deferred: dict[UUID, tuple[str, Callable[[], Awaitable[object]]]] = {}
_drain_tasks: dict[UUID, asyncio.Task[None]] = {}


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


def _schedule_deferred_drain(user_id: UUID) -> None:
    if user_id not in _pending_deferred:
        return
    existing = _drain_tasks.get(user_id)
    if existing is not None and not existing.done():
        return

    async def _drain() -> None:
        try:
            while user_id in _pending_deferred:
                lock = await ingest_lock_for(user_id)
                async with lock:
                    deferred = _pending_deferred.pop(user_id, None)
                    if deferred is None:
                        return
                    label, operation = deferred
                    try:
                        await operation()
                    except Exception:
                        logger.exception(
                            "Deferred channel ingest failed for user %s (%s)",
                            user_id,
                            label,
                        )
        finally:
            current = _drain_tasks.get(user_id)
            if current is asyncio.current_task():
                _drain_tasks.pop(user_id, None)

    task = asyncio.create_task(_drain())
    _drain_tasks[user_id] = task


async def run_channel_ingest(user_id: UUID, operation: Callable[[], Awaitable[_T]]) -> _T:
    """Run a background ingest pass — waits if another pass is in flight."""
    lock = await ingest_lock_for(user_id)
    async with lock:
        result = await operation()
    _schedule_deferred_drain(user_id)
    return result


async def run_channel_ingest_or_defer(
    user_id: UUID,
    operation: Callable[[], Awaitable[_T]],
    *,
    label: str = "ingest",
) -> _T | None:
    """Run when idle; otherwise coalesce into a single deferred retry after the lock frees."""
    lock = await ingest_lock_for(user_id)
    if lock.locked():
        _pending_deferred[user_id] = (label, operation)  # type: ignore[assignment]
        logger.debug("Deferred %s for user %s — channel ingest busy", label, user_id)
        _schedule_deferred_drain(user_id)
        return None
    async with lock:
        result = await operation()
    _schedule_deferred_drain(user_id)
    return result


async def run_channel_ingest_if_idle(
    user_id: UUID,
    operation: Callable[[], Awaitable[_T]],
    *,
    label: str = "ingest",
) -> _T | None:
    """Backward-compatible alias for :func:`run_channel_ingest_or_defer`."""
    return await run_channel_ingest_or_defer(user_id, operation, label=label)


async def drain_deferred_ingest_for_tests(user_id: UUID, *, timeout: float = 5.0) -> None:
    """Wait for a deferred ingest drain (tests only)."""
    _schedule_deferred_drain(user_id)
    task = _drain_tasks.get(user_id)
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        task.cancel()
        raise
