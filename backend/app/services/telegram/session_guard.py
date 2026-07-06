"""Per-user MTProto session locks — reader (listener) and writer (outbound RPC)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.config import get_settings
from app.services.telegram.net import TelegramAuthError

_reader_locks: dict[UUID, asyncio.Lock] = {}
_writer_locks: dict[UUID, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


async def _acquire_user_lock(
    locks: dict[UUID, asyncio.Lock],
    user_id: UUID,
    *,
    acquire_timeout: float | None,
    busy_message: str,
) -> asyncio.Lock:
    async with _registry_lock:
        lock = locks.setdefault(user_id, asyncio.Lock())
    if acquire_timeout is not None:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=acquire_timeout)
        except asyncio.TimeoutError as exc:
            raise TelegramAuthError(busy_message, 503) from exc
    else:
        await lock.acquire()
    return lock


@asynccontextmanager
async def reader_session_lock(
    user_id: UUID, *, acquire_timeout: float | None = None
) -> AsyncIterator[None]:
    """Serialize the long-lived reader Telethon connection (live-sync listener)."""
    lock = await _acquire_user_lock(
        _reader_locks,
        user_id,
        acquire_timeout=acquire_timeout,
        busy_message="Telegram занят синхронизацией канала — попробуйте ещё раз",
    )
    try:
        yield
    finally:
        lock.release()


@asynccontextmanager
async def writer_session_lock(
    user_id: UUID, *, acquire_timeout: float | None = None
) -> AsyncIterator[None]:
    """Serialize short writer Telethon RPCs (publish/edit/delete/reconcile)."""
    lock = await _acquire_user_lock(
        _writer_locks,
        user_id,
        acquire_timeout=acquire_timeout,
        busy_message="Telegram занят исходящей операцией — попробуйте ещё раз",
    )
    try:
        yield
    finally:
        lock.release()


# Backward-compatible alias — reader lock for legacy call sites.
telegram_session_lock = reader_session_lock


@asynccontextmanager
async def telegram_writer_access(
    user_id: UUID, *, acquire_timeout: float | None = None
) -> AsyncIterator[None]:
    """Hold the writer lock for a short outbound RPC without stopping the listener."""
    settings = get_settings()
    timeout = (
        acquire_timeout
        if acquire_timeout is not None
        else settings.telegram_lock_acquire_timeout_seconds
    )
    async with writer_session_lock(user_id, acquire_timeout=timeout):
        yield


@asynccontextmanager
async def exclusive_telegram_access(
    user_id: UUID, *, listener_stop_timeout: float | None = None
) -> AsyncIterator[None]:
    """Pause live-sync, hold the reader MTProto lock, then restart the listener.

    Use only when the reader session must be used without a concurrent listener:
    channel connect, history import (when no writer yet), auth reset paths.
    """
    from app.db.models import Profile
    from app.db.session import async_session_factory
    from app.services.telegram.listener_control import (
        is_listener_active_remote,
        request_listener_pause,
        signal_listener_resume,
        uses_remote_listener,
    )
    from app.services.telegram.live_sync_worker import listener_registry

    settings = get_settings()
    remote = uses_remote_listener(settings)
    was_listening = (
        await is_listener_active_remote(user_id)
        if remote
        else listener_registry.is_running(user_id)
    )
    if was_listening:
        await request_listener_pause(user_id, timeout=listener_stop_timeout)
    try:
        async with reader_session_lock(
            user_id, acquire_timeout=settings.telegram_lock_acquire_timeout_seconds
        ):
            yield
    finally:
        if was_listening:
            async with async_session_factory() as session:
                profile = await session.get(Profile, user_id)
                if profile is not None:
                    await signal_listener_resume(user_id, profile.telegram or {})
