"""Tests for the real MTProto auth endpoints (/telegram/auth/*).

Telethon's network layer is replaced by a scripted fake client (monkeypatched
onto app.services.telegram.mtproto_client), so these tests exercise the full
HTTP -> auth_flow -> encryption round trip without touching real Telegram
servers.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from telethon import errors

from app.core.crypto import ENC_PREFIX
from app.db.models import Profile, User
from app.services.telegram import mtproto_client
from tests.conftest import TestSessionLocal, guest_auth_headers

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
PHONE = "+79001234567"

_INTERNAL_FIELDS = ("_pendingSessionString", "_pendingPhoneCodeHash", "_pendingPhone")

_session_counter = itertools.count(1)


def _next_session_value(label: str) -> str:
    return f"{label}-{next(_session_counter)}"


class FakeStringSession:
    """Stand-in for telethon.sessions.StringSession — just holds an opaque string."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class Scenario:
    """Mutable script consulted by FakeTelegramClient; reset per test."""

    def __init__(self) -> None:
        self.send_code_exception: Exception | None = None
        self.phone_code_hash = "phone-code-hash-1"
        # "ok" | "invalid_code" | "expired_code" | "needs_password"
        self.sign_in_code_result = "ok"
        # "ok" | "invalid_password"
        self.sign_in_password_result = "ok"
        self.log_out_exception: Exception | None = None


SCENARIO = Scenario()


@pytest.fixture(autouse=True)
def _reset_scenario_and_patch_telethon(monkeypatch: pytest.MonkeyPatch):
    global SCENARIO
    SCENARIO = Scenario()
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", FakeTelegramClient)
    yield


class FakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def send_code_request(self, phone: str) -> SimpleNamespace:
        if SCENARIO.send_code_exception is not None:
            raise SCENARIO.send_code_exception
        self.session.value = _next_session_value("session-after-send-code")
        return SimpleNamespace(phone_code_hash=SCENARIO.phone_code_hash)

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ) -> SimpleNamespace:
        if password is not None:
            if SCENARIO.sign_in_password_result == "invalid_password":
                raise errors.PasswordHashInvalidError(None)
            self.session.value = _next_session_value("session-final")
            return SimpleNamespace()

        if SCENARIO.sign_in_code_result == "invalid_code":
            raise errors.PhoneCodeInvalidError(None)
        if SCENARIO.sign_in_code_result == "expired_code":
            raise errors.PhoneCodeExpiredError(None)
        if SCENARIO.sign_in_code_result == "needs_password":
            self.session.value = _next_session_value("session-pending-password")
            raise errors.SessionPasswordNeededError(None)

        self.session.value = _next_session_value("session-final")
        return SimpleNamespace()

    async def log_out(self) -> bool:
        if SCENARIO.log_out_exception is not None:
            raise SCENARIO.log_out_exception
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _telegram_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "authStatus": "idle",
        "authStep": "credentials",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "",
        "sessionName": "",
        "sessionString": "",
        "channel": "",
        "channelTitle": "",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    payload.update(overrides)
    return payload


async def _put_credentials(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict:
    resp = await client.put(
        "/api/v1/profile/telegram/", headers=headers, json=_telegram_payload(**overrides)
    )
    assert resp.status_code == 200
    return resp.json()


async def _send_code(client: AsyncClient, headers: dict[str, str], phone: str = PHONE):
    return await client.post(
        "/api/v1/telegram/auth/send-code/", headers=headers, json={"phone": phone}
    )


async def _verify(client: AsyncClient, headers: dict[str, str], code: str = "11111"):
    return await client.post(
        "/api/v1/telegram/auth/verify/", headers=headers, json={"code": code}
    )


async def _verify_2fa(client: AsyncClient, headers: dict[str, str], password: str = "secret-pw"):
    return await client.post(
        "/api/v1/telegram/auth/verify-2fa/", headers=headers, json={"password": password}
    )


async def _reset(client: AsyncClient, headers: dict[str, str]):
    return await client.post("/api/v1/telegram/auth/reset/", headers=headers)


async def _load_db_telegram(user_id) -> dict[str, Any]:
    async with TestSessionLocal() as session:
        result = await session.execute(select(Profile).where(Profile.user_id == user_id))
        profile = result.scalar_one()
        return profile.telegram or {}


def _assert_no_internal_fields(body: dict[str, Any]) -> None:
    for field in _INTERNAL_FIELDS:
        assert field not in body


# ---------------------------------------------------------------------------
# send-code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_code_requires_api_credentials(client: AsyncClient, writer_auth_headers: dict) -> None:
    resp = await _send_code(client, writer_auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_send_code_success(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)

    resp = await _send_code(client, writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["authStatus"] == "code-sent"
    assert body["authStep"] == "code"
    assert body["phone"] == PHONE
    _assert_no_internal_fields(body)

    stored = await _load_db_telegram(writer_user.id)
    assert stored["_pendingSessionString"].startswith(ENC_PREFIX)
    assert stored["_pendingPhoneCodeHash"].startswith(ENC_PREFIX)
    assert stored["_pendingPhone"].startswith(ENC_PREFIX)


# ---------------------------------------------------------------------------
# verify (code)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_success(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)

    resp = await _verify(client, writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["authStatus"] == "authorized"
    assert body["authStep"] == "channel"
    _assert_no_internal_fields(body)

    stored = await _load_db_telegram(writer_user.id)
    assert stored["sessionString"].startswith(ENC_PREFIX)
    for field in _INTERNAL_FIELDS:
        assert field not in stored


@pytest.mark.asyncio
async def test_verify_invalid_code(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)

    SCENARIO.sign_in_code_result = "invalid_code"
    resp = await _verify(client, writer_auth_headers, code="00000")
    assert resp.status_code == 400

    stored = await _load_db_telegram(writer_user.id)
    assert stored["authStatus"] == "code-sent"
    assert stored["_pendingSessionString"].startswith(ENC_PREFIX)


@pytest.mark.asyncio
async def test_verify_expired_code_resets_state(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)

    SCENARIO.sign_in_code_result = "expired_code"
    resp = await _verify(client, writer_auth_headers, code="00000")
    assert resp.status_code == 400

    stored = await _load_db_telegram(writer_user.id)
    assert stored["authStatus"] == "idle"
    assert stored["authStep"] == "credentials"
    for field in _INTERNAL_FIELDS:
        assert field not in stored


@pytest.mark.asyncio
async def test_verify_needs_password(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)

    SCENARIO.sign_in_code_result = "needs_password"
    resp = await _verify(client, writer_auth_headers, code="11111")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authStep"] == "password"
    assert body["authStatus"] == "code-sent"
    _assert_no_internal_fields(body)

    stored = await _load_db_telegram(writer_user.id)
    assert stored["_pendingSessionString"].startswith(ENC_PREFIX)


# ---------------------------------------------------------------------------
# verify-2fa
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_2fa_success(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)
    SCENARIO.sign_in_code_result = "needs_password"
    await _verify(client, writer_auth_headers)

    resp = await _verify_2fa(client, writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["authStatus"] == "authorized"
    assert body["authStep"] == "channel"
    _assert_no_internal_fields(body)

    stored = await _load_db_telegram(writer_user.id)
    assert stored["sessionString"].startswith(ENC_PREFIX)
    for field in _INTERNAL_FIELDS:
        assert field not in stored


@pytest.mark.asyncio
async def test_verify_2fa_wrong_password(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)
    SCENARIO.sign_in_code_result = "needs_password"
    await _verify(client, writer_auth_headers)

    SCENARIO.sign_in_password_result = "invalid_password"
    resp = await _verify_2fa(client, writer_auth_headers, password="wrong")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_verify_2fa_without_password_step_fails(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)
    # authStep is "code", not "password" yet.
    resp = await _verify_2fa(client, writer_auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_clears_session(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)
    await _verify(client, writer_auth_headers)

    resp = await _reset(client, writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["authStatus"] == "idle"
    assert body["authStep"] == "credentials"
    assert body["sessionString"] == ""
    _assert_no_internal_fields(body)

    stored = await _load_db_telegram(writer_user.id)
    assert stored["sessionString"] == ""
    for field in _INTERNAL_FIELDS:
        assert field not in stored


@pytest.mark.asyncio
async def test_reset_survives_log_out_failure(
    client: AsyncClient, writer_auth_headers: dict, writer_user: User
) -> None:
    await _put_credentials(client, writer_auth_headers)
    await _send_code(client, writer_auth_headers)
    await _verify(client, writer_auth_headers)

    SCENARIO.log_out_exception = RuntimeError("network down")
    resp = await _reset(client, writer_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["authStatus"] == "idle"


# ---------------------------------------------------------------------------
# Seed/demo accounts are read-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_account_cannot_use_auth_endpoints(
    client: AsyncClient, presentation_user: User
) -> None:
    headers = guest_auth_headers()

    assert (await _send_code(client, headers)).status_code == 403
    assert (await _verify(client, headers)).status_code == 403
    assert (await _verify_2fa(client, headers)).status_code == 403
    assert (await _reset(client, headers)).status_code == 403
