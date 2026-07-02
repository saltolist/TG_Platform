"""Propagate a platform text edit to an already-published Telegram message
(Phase 3 / Step 4c).

Called synchronously from ``PATCH /posts/:id/`` right after the DB write, so
the platform stays the source of truth even when this call fails: the caller
persists the DB change unconditionally and only surfaces this function's
error (if any) as ``telegramSyncError`` on the response, never rolls back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.db.models import Profile
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    TelegramAuthError,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.message_mapping import (
    is_message_gone_error,
    telethon_fetch_has_messages,
)
from app.services.telegram.post_sync import delete_telegram_post
from app.services.telegram.reconcile_flow import maybe_reconcile_after_rpc
from app.services.telegram.session_guard import exclusive_telegram_access


@dataclass
class EditSyncResult:
    error: str | None = None
    deleted_in_telegram: bool = False


async def _mark_deleted_in_platform(user_id: UUID, telegram_message_id: str) -> None:
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        await delete_telegram_post(session, user_id, telegram_message_id)
        await session.commit()


async def sync_edit_to_telegram(
    profile: Profile,
    telegram_message_id: str,
    new_text: str,
    user_id: UUID,
    settings: Settings | None = None,
) -> EditSyncResult:
    """Edit *telegram_message_id* in the connected channel."""
    settings = settings or get_settings()
    telegram = profile.telegram or {}

    if telegram.get("channelStatus") != "connected":
        return EditSyncResult()
    if telegram.get("authStatus") not in ("authorized", "connected"):
        return EditSyncResult()

    try:
        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        parsed = parse_channel_input(str(telegram.get("channel") or ""))
        if not parsed or not session_string:
            return EditSyncResult(error="Не удалось подготовить синхронизацию с Telegram")

        msg_id = int(telegram_message_id)
    except (TelegramAuthError, ValueError) as exc:
        return EditSyncResult(error=str(getattr(exc, "detail", exc)))

    async with exclusive_telegram_access(
        user_id, listener_stop_timeout=settings.telegram_short_rpc_listener_stop_seconds
    ):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)

            try:
                fetched = await with_timeout(
                    client.get_messages(entity, ids=msg_id), settings
                )
            except Exception:
                fetched = None
            if not telethon_fetch_has_messages(fetched):
                await _mark_deleted_in_platform(user_id, telegram_message_id)
                return EditSyncResult(deleted_in_telegram=True)

            await with_timeout(client.edit_message(entity, msg_id, new_text), settings)
            await maybe_reconcile_after_rpc(
                client, entity, user_id, settings, force=False
            )
        except TelegramAuthError as exc:
            if is_message_gone_error(exc):
                await _mark_deleted_in_platform(user_id, telegram_message_id)
                return EditSyncResult(deleted_in_telegram=True)
            return EditSyncResult(error=exc.detail)
        except Exception as exc:  # noqa: BLE001 — best-effort sync, never raises to the caller
            if is_message_gone_error(exc):
                await _mark_deleted_in_platform(user_id, telegram_message_id)
                return EditSyncResult(deleted_in_telegram=True)
            return EditSyncResult(
                error=str(exc) or "Не удалось синхронизировать правку с Telegram"
            )
        finally:
            await disconnect_safely(client)

    return EditSyncResult()


__all__ = ["EditSyncResult", "sync_edit_to_telegram"]
