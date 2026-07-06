"""Delete a published Telegram message when its platform post is deleted
(Phase 3 / Step 4c — delete).

The platform mirrors the channel: if the message is already gone in Telegram,
delete-sync treats that as success and lets the caller soft-delete the platform
post. Other Telegram failures still abort so the platform post is kept.
"""

from __future__ import annotations

from uuid import UUID

from app.core.config import Settings, get_settings
from app.db.models import Profile
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity_for_profile
from app.services.telegram.message_mapping import is_message_gone_error, telethon_fetch_has_messages
from app.services.telegram.net import (
    TelegramAuthError,
    decrypt_field,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.reconcile_flow import maybe_reconcile_after_rpc
from app.services.telegram.writer_session import open_outbound_telegram_client


async def delete_message_in_telegram(
    profile: Profile,
    telegram_message_id: str,
    user_id: UUID,
    settings: Settings | None = None,
) -> None:
    """Delete *telegram_message_id* in the connected channel.

    Raises :class:`TelegramAuthError` if the channel is not reachable or the
    delete fails for a reason other than the message already being gone.
    """
    settings = settings or get_settings()
    telegram = profile.telegram or {}

    if telegram.get("channelStatus") != "connected":
        raise TelegramAuthError("Сначала подключите канал", 400)
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    require_api_credentials(telegram, settings)
    if not decrypt_field(str(telegram.get("sessionString") or ""), settings):
        raise TelegramAuthError("Не удалось подготовить удаление в Telegram", 400)
    if not str(telegram.get("channelId") or "").strip() and not parse_channel_input(
        str(telegram.get("channel") or "")
    ):
        raise TelegramAuthError("Не удалось подготовить удаление в Telegram", 400)

    try:
        msg_id = int(telegram_message_id)
    except ValueError as exc:
        raise TelegramAuthError("Некорректный идентификатор сообщения", 400) from exc

    try:
        async with open_outbound_telegram_client(profile, user_id, settings) as (
            client,
            telegram,
        ):
            entity = await resolve_channel_entity_for_profile(client, telegram, settings)

            try:
                fetched = await with_timeout(
                    client.get_messages(entity, ids=msg_id), settings
                )
            except Exception:
                fetched = None
            if not telethon_fetch_has_messages(fetched):
                return

            try:
                await with_timeout(client.delete_messages(entity, [msg_id]), settings)
            except TelegramAuthError as exc:
                if is_message_gone_error(exc):
                    return
                raise
            except Exception as exc:
                if is_message_gone_error(exc):
                    return
                raise TelegramAuthError(
                    str(exc) or "Не удалось удалить сообщение в Telegram", 502
                ) from exc
            await maybe_reconcile_after_rpc(
                client,
                entity,
                user_id,
                settings,
                force=True,
                include_new_scan=False,
            )
    except TelegramAuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        if is_message_gone_error(exc):
            return
        raise TelegramAuthError(
            str(exc) or "Не удалось удалить сообщение в Telegram", 502
        ) from exc


__all__ = ["delete_message_in_telegram"]
