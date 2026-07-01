"""Per-user MTProto session lock — only one Telethon connection per account at a time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.config import get_settings
from app.services.telegram.net import TelegramAuthError

_locks: dict[UUID, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


@asynccontextmanager
async def telegram_session_lock(
    user_id: UUID, *, acquire_timeout: float | None = None
) -> AsyncIterator[None]:
    """Serialize Telethon connect/import/live-sync for a single user session."""
    async with _registry_lock:
        lock = _locks.setdefault(user_id, asyncio.Lock())
    if acquire_timeout is not None:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=acquire_timeout)
        except asyncio.TimeoutError as exc:
            raise TelegramAuthError(
                "Telegram занят синхронизацией канала — попробуйте ещё раз",
                503,
            ) from exc
    else:
        await lock.acquire()
    try:
        yield
    finally:
        lock.release()


@asynccontextmanager
async def exclusive_telegram_access(user_id: UUID) -> AsyncIterator[None]:
    """Pause live-sync, hold the MTProto lock for a short RPC, then restart the listener.

    The live-sync worker keeps a long-lived Telethon connection and holds
    ``telegram_session_lock`` for its whole lifetime. Platform publish/edit/delete
    (Step 4a/4c) must stop that listener first — same pattern as channel
    connect and history import.
    """
    from app.db.models import Profile
    from app.db.session import async_session_factory
    from app.services.telegram.live_sync_worker import (
        ensure_user_listener,
        listener_registry,
    )

    settings = get_settings()
    was_listening = listener_registry.is_running(user_id)
    if was_listening:
        await listener_registry.await_stop_user_listener(user_id)
    try:
        async with telegram_session_lock(
            user_id, acquire_timeout=settings.telegram_lock_acquire_timeout_seconds
        ):
            yield
    finally:
        if was_listening:
            async with async_session_factory() as session:
                profile = await session.get(Profile, user_id)
                if profile is not None:
                    ensure_user_listener(user_id, profile.telegram or {})
