"""Per-user MTProto session lock — only one Telethon connection per account at a time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

_locks: dict[UUID, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


@asynccontextmanager
async def telegram_session_lock(user_id: UUID) -> AsyncIterator[None]:
    """Serialize Telethon connect/import/live-sync for a single user session."""
    async with _registry_lock:
        lock = _locks.setdefault(user_id, asyncio.Lock())
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
