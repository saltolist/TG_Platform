"""Real channel connect (Telethon), Phase 3 / Step 2.

Verifies that the channel exists and the authenticated account has rights
to post in it, then stores ``channel`` / ``channelTitle`` / ``channelId`` /
``channelStatus=connected`` on the profile. Does **not** import post
history — that is Step 3, a separate piece of work.

Supported input (after MTProto auth):
  - public ``@username`` / ``t.me/username``;
  - private invite links ``t.me/+…`` / ``t.me/joinchat/…`` (account must
    already be a member — Telethon resolves the link via ``get_entity``);
  - numeric peer id ``-100…`` — looked up in the authenticated account's
    dialogs (``iter_dialogs``), because a fresh ``StringSession`` client has
    no entity cache and cannot resolve a bare id alone.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from telethon import errors, utils
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator

from app.core.config import Settings, get_settings
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    TelegramAuthError,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)

_NUMERIC_RE = re.compile(r"^-?\d+$")
_INVITE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me/|telegram\.me/)(?:\+|joinchat/)([\w-]+)/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ParsedChannelInput:
    kind: Literal["username", "invite", "numeric"]
    resolve_key: str
    display: str


def _parse_channel_input(raw: str) -> _ParsedChannelInput | None:
    value = raw.strip()
    if not value:
        return None

    invite_match = _INVITE_RE.match(value)
    if invite_match:
        token = invite_match.group(1)
        if "joinchat/" in value.lower():
            link = f"https://t.me/joinchat/{token}"
        else:
            link = f"https://t.me/+{token}"
        return _ParsedChannelInput("invite", link, link)

    if _NUMERIC_RE.match(value):
        peer_id = int(value)
        display = str(peer_id)
        return _ParsedChannelInput("numeric", display, display)

    handle = value
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if handle.lower().startswith(prefix):
            handle = handle[len(prefix) :]
            break
    handle = handle.strip().rstrip("/")
    if not handle or handle.startswith("+") or "joinchat" in handle.lower():
        return None
    return _ParsedChannelInput("username", handle, f"@{handle}")


def _normalize_peer_id(value: int) -> int:
    """Normalize user input to Telethon peer id (``-100…`` for channels)."""
    if value < 0:
        return value
    return int(f"-100{value}")


def _peer_ids_match(entity: Any, target_peer_id: int) -> bool:
    try:
        if utils.get_peer_id(entity) == target_peer_id:
            return True
    except (TypeError, ValueError):
        pass
    bare = abs(target_peer_id)
    bare_str = str(bare)
    if bare_str.startswith("100"):
        bare = int(bare_str[3:])
    return getattr(entity, "id", None) == bare


async def _resolve_from_dialogs(client: Any, target_peer_id: int, settings: Settings) -> Any:
    target_peer_id = _normalize_peer_id(target_peer_id)

    async def _search() -> Any:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not hasattr(entity, "broadcast") and not hasattr(entity, "megagroup"):
                continue
            if _peer_ids_match(entity, target_peer_id):
                return entity
        raise TelegramAuthError(
            "Канал не найден среди ваших диалогов — проверьте id или вступите в канал в Telegram",
            404,
        )

    return await with_timeout(_search(), settings)


async def _resolve_entity(client: Any, parsed: _ParsedChannelInput, settings: Settings) -> Any:
    if parsed.kind == "numeric":
        target = int(parsed.resolve_key)
        normalized = _normalize_peer_id(target) if target > 0 else target
        try:
            return await with_timeout(client.get_entity(normalized), settings)
        except errors.FloodWaitError:
            raise
        except Exception:
            return await _resolve_from_dialogs(client, target, settings)

    try:
        return await with_timeout(client.get_entity(parsed.resolve_key), settings)
    except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
        raise TelegramAuthError("Канал не найден", 404) from None
    except errors.InviteHashExpiredError:
        raise TelegramAuthError("Ссылка-приглашение истекла", 400) from None
    except errors.InviteHashInvalidError:
        raise TelegramAuthError("Неверная ссылка-приглашение", 400) from None
    except errors.ChannelPrivateError:
        raise TelegramAuthError(
            "Канал приватный — вступите в него в Telegram или используйте invite-ссылку",
            403,
        ) from None
    except errors.UserNotParticipantError:
        raise TelegramAuthError(
            "Вы не состоите в этом канале — сначала вступите по invite-ссылке в Telegram",
            403,
        ) from None
    except errors.FloodWaitError as exc:
        raise TelegramAuthError(_flood_wait_message(exc), 429) from exc
    except errors.RPCError as exc:
        raise TelegramAuthError(str(exc), 400) from exc


def _flood_wait_message(exc: Any) -> str:
    seconds = int(getattr(exc, "seconds", 0) or 0)
    if seconds <= 0:
        import re

        match = re.search(r"(\d+)\s*seconds?", str(exc), flags=re.IGNORECASE)
        if match:
            seconds = int(match.group(1))
    if seconds >= 120:
        minutes = max(1, round(seconds / 60))
        return (
            f"Telegram временно ограничил запросы — подождите около {minutes} мин "
            "и повторите"
        )
    if seconds > 0:
        return f"Telegram временно ограничил запросы — подождите {seconds} с и повторите"
    return "Telegram временно ограничил запросы — попробуйте позже"


async def resolve_channel_entity_for_profile(
    client: Any,
    telegram: dict[str, Any],
    settings: Settings,
) -> Any:
    """Resolve the connected channel without re-checking invite links when possible.

    Short-lived RPC clients (comment push/pull, edit, delete) must not call
    ``CheckChatInviteRequest`` on every request — prefer ``@username`` or stored
    ``channelId`` over invite links saved in ``channel``.
    """
    channel = str(telegram.get("channel") or "").strip()
    parsed_channel = _parse_channel_input(channel)

    if parsed_channel is not None and parsed_channel.kind != "invite":
        return await _resolve_entity(client, parsed_channel, settings)

    channel_id = str(telegram.get("channelId") or "").strip()
    if channel_id and _NUMERIC_RE.match(channel_id):
        parsed = _ParsedChannelInput("numeric", channel_id, channel_id)
        return await _resolve_entity(client, parsed, settings)

    if parsed_channel is not None:
        return await _resolve_entity(client, parsed_channel, settings)

    raise TelegramAuthError("Не удалось определить канал", 400)


async def _user_can_post(client: Any, entity: Any, settings: Settings) -> bool:
    """Check whether the authenticated account can publish in *entity*."""
    if bool(getattr(entity, "creator", False)):
        return True
    admin_rights = getattr(entity, "admin_rights", None)
    if admin_rights is not None:
        return bool(getattr(admin_rights, "post_messages", False))

    try:
        result = await with_timeout(client(GetParticipantRequest(entity, "me")), settings)
    except errors.UserNotParticipantError:
        return False
    except errors.RPCError:
        return False

    participant = result.participant
    if isinstance(participant, ChannelParticipantCreator):
        return True
    if isinstance(participant, ChannelParticipantAdmin):
        rights = participant.admin_rights
        return bool(rights and rights.post_messages)
    return False


def _format_channel_id(entity: Any) -> str:
    try:
        return str(utils.get_peer_id(entity))
    except (TypeError, ValueError):
        pass
    bare_id = getattr(entity, "id", None)
    if bare_id is None:
        return ""
    if hasattr(entity, "broadcast") or hasattr(entity, "megagroup"):
        return str(_normalize_peer_id(int(bare_id)))
    return str(bare_id)


def channel_peer_id(entity: Any) -> int:
    """Return Telethon peer id for a channel entity (real TL objects and test stubs)."""
    try:
        return utils.get_peer_id(entity)
    except (TypeError, ValueError):
        bare_id = getattr(entity, "id", None)
        if bare_id is None:
            raise ValueError("Cannot resolve channel peer id") from None
        if hasattr(entity, "broadcast") or hasattr(entity, "megagroup"):
            return _normalize_peer_id(int(bare_id))
        return int(bare_id)


def _non_empty_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


async def _resolve_channel_title(client: Any, entity: Any, settings: Settings) -> str:
    """Return the human-readable channel name — never an invite link or numeric id."""
    title = _non_empty_title(getattr(entity, "title", None))
    if title:
        return title

    try:
        full = await with_timeout(client(GetFullChannelRequest(entity)), settings)
        for chat in getattr(full, "chats", []) or []:
            chat_title = _non_empty_title(getattr(chat, "title", None))
            if chat_title:
                return chat_title
    except errors.RPCError:
        pass

    username = _non_empty_title(getattr(entity, "username", None))
    if username:
        return f"@{username.lstrip('@')}"

    return "Telegram канал"


parse_channel_input = _parse_channel_input
resolve_channel_entity = _resolve_entity


def extract_subscriber_count(full: Any) -> int | None:
    """Read ``participants_count`` from a ``GetFullChannelRequest`` response."""
    raw = getattr(getattr(full, "full_chat", None), "participants_count", None)
    if raw is None:
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


async def fetch_channel_subscriber_count(
    client: Any, entity: Any, settings: Settings
) -> int | None:
    """Return the channel subscriber count, or None when Telegram hides it."""
    try:
        full = await with_timeout(client(GetFullChannelRequest(entity)), settings)
    except (errors.RPCError, TelegramAuthError, TypeError, ValueError):
        return None
    return extract_subscriber_count(full)


async def connect_channel(
    profile: dict[str, Any], channel_input: str, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    parsed = _parse_channel_input(channel_input)
    if parsed is None:
        raise TelegramAuthError("Укажите канал", 400)

    if profile.get("authStatus") not in ("authorized", "connected") or not profile.get(
        "sessionString"
    ):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    api_id, api_hash = require_api_credentials(profile, settings)
    session_string = decrypt_field(str(profile.get("sessionString") or ""), settings)
    if not session_string:
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

    client = build_client(api_id, api_hash, session_string)
    try:
        await connect_telegram_client(client, settings)
        entity = await _resolve_entity(client, parsed, settings)

        if not hasattr(entity, "broadcast") and not hasattr(entity, "megagroup"):
            raise TelegramAuthError("Это не похоже на канал", 400)

        if not await _user_can_post(client, entity, settings):
            raise TelegramAuthError("У вас нет прав администратора в этом канале", 403)

        discussion_chat_id: int | None = None
        subscriber_count: int | None = None
        try:
            full = await with_timeout(client(GetFullChannelRequest(entity)), settings)
            subscriber_count = extract_subscriber_count(full)
            linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
            if linked is not None:
                discussion_chat_id = int(linked)
        except (TypeError, ValueError, errors.RPCError):
            discussion_chat_id = None

        result = copy.deepcopy(profile)
        result["channel"] = parsed.display
        result["channelTitle"] = await _resolve_channel_title(client, entity, settings)
        result["channelId"] = _format_channel_id(entity)
        result["channelStatus"] = "connected"
        result["authStatus"] = "connected"
        result["authStep"] = "connected"
        result["discussionChatId"] = str(discussion_chat_id) if discussion_chat_id else ""
        result["commentsEnabled"] = bool(discussion_chat_id)
        if subscriber_count is not None:
            result["subscriberCount"] = subscriber_count
            result["subscriberCountAt"] = datetime.now(timezone.utc).isoformat()
        result["lastSync"] = datetime.now(timezone.utc).isoformat()
        sync_mode = str(profile.get("syncMode") or "history-and-live")
        if sync_mode == "publish-only":
            result["importStatus"] = "idle"
            result["importError"] = ""
        else:
            result["importStatus"] = "importing"
            result["importError"] = ""
        return result
    finally:
        await disconnect_safely(client)
