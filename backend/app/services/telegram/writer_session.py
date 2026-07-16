"""Lazy writer MTProto session — separate auth key for short outbound RPCs.

The live-sync listener holds a long-lived *reader* session (``sessionString``).
Outbound publish/edit/delete uses ``writerSessionString``, bootstrapped on first
use via ``auth.ExportAuthorization`` / ``auth.ImportAuthorization`` from the reader.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings, get_settings
from app.core.crypto import encrypt_byok
from app.db.models import Profile
from app.db.session import async_session_factory
from app.services.telegram.mtproto_client import build_client, save_session
from app.services.telegram.net import (
    TelegramAuthError,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)

logger = logging.getLogger(__name__)


def decrypt_writer_session(profile: dict[str, Any], settings: Settings | None = None) -> str | None:
    """Return decrypted ``writerSessionString``, or None when unset."""
    settings = settings or get_settings()
    raw = str(profile.get("writerSessionString") or "")
    if not raw:
        return None
    value = decrypt_field(raw, settings)
    return value or None


async def persist_writer_session_string(
    user_id: UUID, writer_session: str, settings: Settings | None = None
) -> None:
    settings = settings or get_settings()
    encrypted = encrypt_byok(writer_session, settings)
    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return
        telegram = dict(profile.telegram or {})
        telegram["writerSessionString"] = encrypted
        profile.telegram = telegram
        flag_modified(profile, "telegram")
        await session.commit()


async def _resolve_writer_export_dc(
    reader_client: Any, settings: Settings
) -> tuple[int, str, int]:
    """Pick a non-CDN DC different from the reader for auth export/import."""
    from telethon.tl.functions.help import GetConfigRequest

    reader_dc = int(getattr(reader_client.session, "dc_id", 0) or 0)
    if reader_dc <= 0:
        raise TelegramAuthError("Не удалось определить DC для writer-сессии", 502)

    config = await with_timeout(reader_client(GetConfigRequest()), settings)
    for option in config.dc_options:
        if option.id != reader_dc and not getattr(option, "cdn", False):
            return option.id, option.ip_address, option.port

    raise TelegramAuthError("Не удалось выбрать DC для writer-сессии", 502)


async def export_writer_session(
    reader_client: Any,
    api_id: int,
    api_hash: str,
    settings: Settings,
) -> str:
    """Clone reader authorization into a fresh StringSession (new auth key)."""
    from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest

    target_dc_id, target_ip, target_port = await _resolve_writer_export_dc(
        reader_client, settings
    )

    writer_client = build_client(api_id, api_hash, "")
    writer_client.session.set_dc(target_dc_id, target_ip, target_port)
    try:
        await connect_telegram_client(writer_client, settings)
        exported = await with_timeout(
            reader_client(ExportAuthorizationRequest(target_dc_id)),
            settings,
        )
        await with_timeout(
            writer_client(
                ImportAuthorizationRequest(id=exported.id, bytes=exported.bytes)
            ),
            settings,
        )
        await with_timeout(writer_client.get_me(), settings)
        return save_session(writer_client)
    finally:
        await disconnect_safely(writer_client)


async def _writer_session_is_valid(
    api_id: int, api_hash: str, session_string: str, settings: Settings
) -> bool:
    """Probe a cached writer session's auth key against Telegram.

    Telegram can revoke a session out-of-band (password change, "terminate all
    sessions", new login) without this backend ever hearing about it — the
    reader session is a separate auth key and keeps working, so nothing else
    surfaces the revocation. A stale writer session was then returned
    unconditionally on every publish/edit/delete, permanently failing outbound
    RPCs with AuthKeyUnregisteredError while incoming sync via the reader
    session kept working fine (chat b0d11b7c).
    """
    client = build_client(api_id, api_hash, session_string)
    try:
        await connect_telegram_client(client, settings)
        return bool(await with_timeout(client.is_user_authorized(), settings))
    except Exception:
        return False
    finally:
        await disconnect_safely(client)


async def ensure_writer_session_string(
    profile: Profile,
    user_id: UUID,
    settings: Settings | None = None,
) -> str:
    """Return a writer session string, creating and persisting one when missing
    or when the cached one was revoked by Telegram."""
    settings = settings or get_settings()
    telegram = profile.telegram or {}
    existing = decrypt_writer_session(telegram, settings)
    if existing:
        api_id, api_hash = require_api_credentials(telegram, settings)
        if await _writer_session_is_valid(api_id, api_hash, existing, settings):
            return existing
        logger.warning(
            "Cached writer session for user %s failed auth check — re-exporting",
            user_id,
        )
    else:
        api_id, api_hash = require_api_credentials(telegram, settings)
    reader_session = decrypt_field(str(telegram.get("sessionString") or ""), settings)
    if not reader_session:
        raise TelegramAuthError("Не удалось подготовить writer-сессию Telegram", 400)

    from app.services.telegram.live_sync_worker import listener_registry
    from app.services.telegram.session_guard import reader_session_lock

    reader_client = listener_registry.get_active_reader_client(user_id)
    if reader_client is not None:
        writer_session = await export_writer_session(
            reader_client, api_id, api_hash, settings
        )
    else:
        from app.services.telegram.listener_control import (
            is_listener_active_remote,
            request_listener_pause,
            signal_listener_resume,
            uses_remote_listener,
        )

        remote_active = uses_remote_listener(settings) and await is_listener_active_remote(user_id)
        if remote_active:
            await request_listener_pause(
                user_id, timeout=settings.telegram_listener_stop_timeout_seconds
            )
        try:
            async with reader_session_lock(
                user_id, acquire_timeout=settings.telegram_lock_acquire_timeout_seconds
            ):
                client = build_client(api_id, api_hash, reader_session)
                try:
                    await connect_telegram_client(client, settings)
                    writer_session = await export_writer_session(
                        client, api_id, api_hash, settings
                    )
                finally:
                    await disconnect_safely(client)
        finally:
            if remote_active:
                await signal_listener_resume(user_id, telegram)

    # Some accounts have Export/ImportAuthorizationRequest revoked server-side
    # (Telegram invalidates the freshly imported auth key on the very next
    # request) — export_writer_session then "succeeds" with a session string
    # that is already dead. Persisting and returning it would repeat the same
    # AuthKeyUnregisteredError forever. Raise instead so the caller
    # (open_outbound_telegram_client) falls back to the reader session, which
    # is the already-designed degraded path for this case (chat b0d11b7c).
    if not await _writer_session_is_valid(api_id, api_hash, writer_session, settings):
        raise TelegramAuthError(
            "Не удалось создать writer-сессию Telegram (ключ отозван сразу после создания)",
            400,
        )

    await persist_writer_session_string(user_id, writer_session, settings)
    return writer_session


@asynccontextmanager
async def open_outbound_telegram_client(
    profile: Profile,
    user_id: UUID,
    settings: Settings | None = None,
) -> AsyncIterator[tuple[Any, dict[str, Any]]]:
    """Connect for a short outbound RPC using the writer session when possible.

    Falls back to the reader session with listener stop when writer bootstrap fails
    (migration edge cases only).
    """
    from app.services.telegram.session_guard import (
        exclusive_telegram_access,
        telegram_writer_access,
    )

    settings = settings or get_settings()
    telegram = dict(profile.telegram or {})
    api_id, api_hash = require_api_credentials(telegram, settings)

    use_writer = True
    session_string = ""
    try:
        session_string = await ensure_writer_session_string(profile, user_id, settings)
    except Exception:
        logger.warning(
            "Writer session bootstrap failed for user %s — falling back to reader",
            user_id,
            exc_info=True,
        )
        use_writer = False
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        if not session_string:
            raise TelegramAuthError("Не удалось подготовить сессию Telegram", 400)

    access = (
        telegram_writer_access(user_id)
        if use_writer
        else exclusive_telegram_access(
            user_id, listener_stop_timeout=settings.telegram_short_rpc_listener_stop_seconds
        )
    )

    async with access:
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            yield client, telegram
        finally:
            await disconnect_safely(client)


__all__ = [
    "decrypt_writer_session",
    "ensure_writer_session_string",
    "export_writer_session",
    "open_outbound_telegram_client",
    "persist_writer_session_string",
]
