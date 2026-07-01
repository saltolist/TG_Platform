"""Propagate a platform text edit to an already-published Telegram message
(Phase 3 / Step 4c).

Called synchronously from ``PATCH /posts/:id/`` right after the DB write, so
the platform stays the source of truth even when this call fails: the caller
persists the DB change unconditionally and only surfaces this function's
error (if any) as ``telegramSyncError`` on the response, never rolls back.
"""

from __future__ import annotations

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
from app.services.telegram.session_guard import exclusive_telegram_access


async def sync_edit_to_telegram(
    profile: Profile,
    telegram_message_id: str,
    new_text: str,
    user_id: UUID,
    settings: Settings | None = None,
) -> str | None:
    """Edit *telegram_message_id* in the connected channel. Returns an error string, or ``None`` on success."""
    settings = settings or get_settings()
    telegram = profile.telegram or {}

    if telegram.get("channelStatus") != "connected":
        return None  # nothing to sync to — not an error worth surfacing
    if telegram.get("authStatus") not in ("authorized", "connected"):
        return None

    try:
        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        parsed = parse_channel_input(str(telegram.get("channel") or ""))
        if not parsed or not session_string:
            return "Не удалось подготовить синхронизацию с Telegram"

        msg_id = int(telegram_message_id)
    except (TelegramAuthError, ValueError) as exc:
        return str(getattr(exc, "detail", exc))

    async with exclusive_telegram_access(user_id):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)
            await with_timeout(client.edit_message(entity, msg_id, new_text), settings)
        except TelegramAuthError as exc:
            return exc.detail
        except Exception as exc:  # noqa: BLE001 — best-effort sync, never raises to the caller
            return str(exc) or "Не удалось синхронизировать правку с Telegram"
        finally:
            await disconnect_safely(client)

    return None


__all__ = ["sync_edit_to_telegram"]
