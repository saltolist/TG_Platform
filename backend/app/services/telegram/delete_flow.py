"""Delete a published Telegram message when its platform post is deleted
(Phase 3 / Step 4c — delete).

Unlike edit-sync (best-effort), delete-sync is strict: the platform is treated
as a mirror of the channel, so if the Telegram delete fails the caller must
abort and keep the platform post. This function therefore *raises*
``TelegramAuthError`` on failure instead of swallowing it.
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


async def delete_message_in_telegram(
    profile: Profile,
    telegram_message_id: str,
    user_id: UUID,
    settings: Settings | None = None,
) -> None:
    """Delete *telegram_message_id* in the connected channel.

    Raises :class:`TelegramAuthError` if the channel is not reachable or the
    delete fails, so the caller can keep the platform post (platform mirrors
    the channel).
    """
    settings = settings or get_settings()
    telegram = profile.telegram or {}

    if telegram.get("channelStatus") != "connected":
        raise TelegramAuthError("Сначала подключите канал", 400)
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    api_id, api_hash = require_api_credentials(telegram, settings)
    session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
    parsed = parse_channel_input(str(telegram.get("channel") or ""))
    if not parsed or not session_string:
        raise TelegramAuthError("Не удалось подготовить удаление в Telegram", 400)

    try:
        msg_id = int(telegram_message_id)
    except ValueError as exc:
        raise TelegramAuthError("Некорректный идентификатор сообщения", 400) from exc

    async with exclusive_telegram_access(user_id):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)
            await with_timeout(client.delete_messages(entity, [msg_id]), settings)
        except TelegramAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as a strict delete failure
            raise TelegramAuthError(
                str(exc) or "Не удалось удалить сообщение в Telegram", 502
            ) from exc
        finally:
            await disconnect_safely(client)


__all__ = ["delete_message_in_telegram"]
