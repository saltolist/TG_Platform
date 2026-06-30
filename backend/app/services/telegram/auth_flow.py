"""MTProto authentication state machine (Telethon), Phase 3 / Step 1.

State lives entirely in ``profiles.telegram`` (JSON):
  authStatus: idle -> code-sent -> authorized -> connected (connected is set
              later by the channel-connect step, out of scope here)
  authStep:   credentials -> code -> [password] -> channel

Every HTTP request gets a fresh, short-lived Telethon client reconnected
from a ``StringSession`` string — see mtproto_client.py for why. The
``phone_code_hash`` returned by ``send_code_request`` and the intermediate
``StringSession`` must survive between the send-code and verify requests;
they are stored as encrypted *internal* fields (never exposed to the
client — see ``byok_telegram.strip_internal_fields``).
"""

from __future__ import annotations

import copy
from typing import Any

from telethon import errors

from app.core.config import Settings, get_settings
from app.core.crypto import encrypt_byok
from app.services.telegram.mtproto_client import build_client, save_session
from app.services.telegram.net import (
    TelegramAuthError,
    decrypt_field as _decrypt_field,
    disconnect_safely as _disconnect_safely,
    require_api_credentials as _require_api_credentials,
    with_timeout as _with_timeout,
)

__all__ = ["TelegramAuthError", "send_code", "verify_code", "verify_password", "reset_auth"]

_PENDING_SESSION = "_pendingSessionString"
_PENDING_CODE_HASH = "_pendingPhoneCodeHash"
_PENDING_PHONE = "_pendingPhone"


def _load_pending(profile: dict[str, Any], settings: Settings) -> tuple[str, str, str]:
    session_string = _decrypt_field(str(profile.get(_PENDING_SESSION) or ""), settings)
    phone_code_hash = _decrypt_field(str(profile.get(_PENDING_CODE_HASH) or ""), settings)
    phone = _decrypt_field(str(profile.get(_PENDING_PHONE) or ""), settings)
    if not session_string or not phone_code_hash or not phone:
        raise TelegramAuthError("Сначала запросите код подтверждения", 400)
    return session_string, phone_code_hash, phone


def _clear_pending(profile: dict[str, Any]) -> None:
    for field in (_PENDING_SESSION, _PENDING_CODE_HASH, _PENDING_PHONE):
        profile.pop(field, None)


async def send_code(
    profile: dict[str, Any], phone: str, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    phone = phone.strip()
    if not phone:
        raise TelegramAuthError("Укажите номер телефона", 400)

    api_id, api_hash = _require_api_credentials(profile, settings)

    client = build_client(api_id, api_hash)
    try:
        await _with_timeout(client.connect(), settings)
        try:
            sent = await _with_timeout(client.send_code_request(phone), settings)
        except errors.PhoneNumberInvalidError:
            raise TelegramAuthError("Неверный номер телефона", 400) from None
        except errors.FloodWaitError as exc:
            raise TelegramAuthError(
                f"Слишком много попыток, подождите {exc.seconds} с", 429
            ) from None
        except errors.RPCError as exc:
            raise TelegramAuthError(str(exc), 400) from exc
        session_string = save_session(client)
    finally:
        await _disconnect_safely(client)

    result = copy.deepcopy(profile)
    result["authStatus"] = "code-sent"
    result["authStep"] = "code"
    result["phone"] = phone
    result[_PENDING_SESSION] = encrypt_byok(session_string, settings)
    result[_PENDING_CODE_HASH] = encrypt_byok(sent.phone_code_hash, settings)
    result[_PENDING_PHONE] = encrypt_byok(phone, settings)
    return result


async def verify_code(
    profile: dict[str, Any], code: str, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    code = code.strip()
    if not code:
        raise TelegramAuthError("Укажите код из Telegram", 400)

    api_id, api_hash = _require_api_credentials(profile, settings)
    session_string, phone_code_hash, phone = _load_pending(profile, settings)

    result = copy.deepcopy(profile)

    client = build_client(api_id, api_hash, session_string)
    try:
        await _with_timeout(client.connect(), settings)
        try:
            await _with_timeout(
                client.sign_in(phone, code, phone_code_hash=phone_code_hash), settings
            )
        except errors.SessionPasswordNeededError:
            # Expected branch, not an error: the same intermediate session
            # context remains valid for the password step.
            result[_PENDING_SESSION] = encrypt_byok(save_session(client), settings)
            result["authStep"] = "password"
            return result
        except errors.PhoneCodeInvalidError:
            raise TelegramAuthError("Неверный код", 400) from None
        except errors.PhoneCodeExpiredError:
            _clear_pending(result)
            result["authStatus"] = "idle"
            result["authStep"] = "credentials"
            raise TelegramAuthError(
                "Код истёк, запросите новый", 400, profile_patch=result
            ) from None
        except errors.RPCError as exc:
            raise TelegramAuthError(str(exc), 400) from exc

        final_session = save_session(client)
    finally:
        await _disconnect_safely(client)

    result["sessionString"] = encrypt_byok(final_session, settings)
    result["authStatus"] = "authorized"
    result["authStep"] = "channel"
    _clear_pending(result)
    return result


async def verify_password(
    profile: dict[str, Any], password: str, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    password = password.strip()
    if not password:
        raise TelegramAuthError("Укажите пароль", 400)
    if profile.get("authStep") != "password":
        raise TelegramAuthError("Сначала подтвердите код из Telegram", 400)

    api_id, api_hash = _require_api_credentials(profile, settings)
    session_string, _phone_code_hash, _phone = _load_pending(profile, settings)

    result = copy.deepcopy(profile)

    client = build_client(api_id, api_hash, session_string)
    try:
        await _with_timeout(client.connect(), settings)
        try:
            await _with_timeout(client.sign_in(password=password), settings)
        except errors.PasswordHashInvalidError:
            raise TelegramAuthError("Неверный пароль", 400) from None
        except errors.RPCError as exc:
            raise TelegramAuthError(str(exc), 400) from exc
        final_session = save_session(client)
    finally:
        await _disconnect_safely(client)

    result["sessionString"] = encrypt_byok(final_session, settings)
    result["authStatus"] = "authorized"
    result["authStep"] = "channel"
    _clear_pending(result)
    return result


async def reset_auth(
    profile: dict[str, Any], settings: Settings | None = None
) -> dict[str, Any]:
    """Best-effort remote log-out (revokes the Telegram-side session) + local reset."""
    settings = settings or get_settings()
    result = copy.deepcopy(profile)

    session_value = str(profile.get("sessionString") or "")
    api_id_raw = str(profile.get("apiId") or "").strip()
    api_hash_raw = str(profile.get("apiHash") or "")
    if session_value and api_id_raw and api_hash_raw:
        try:
            session_string = _decrypt_field(session_value, settings)
            api_id = int(api_id_raw)
            api_hash = _decrypt_field(api_hash_raw, settings)
            if session_string and api_hash:
                client = build_client(api_id, api_hash, session_string)
                try:
                    await _with_timeout(client.connect(), settings)
                    await _with_timeout(client.log_out(), settings)
                finally:
                    await _disconnect_safely(client)
        except Exception:  # noqa: BLE001 — remote logout is best-effort only
            pass

    result["authStatus"] = "idle"
    result["authStep"] = "credentials"
    result["sessionString"] = ""
    _clear_pending(result)
    return result
