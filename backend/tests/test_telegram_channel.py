"""Tests for the real channel-connect endpoint (/telegram/channel/connect/).

Telethon's network layer is replaced by a scripted fake client (monkeypatched
onto app.services.telegram.mtproto_client), so these tests exercise the full
HTTP -> channel_flow -> profile-persistence round trip without touching real
Telegram servers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from telethon import errors
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.types import ChannelParticipant, ChannelParticipantAdmin, ChannelParticipantCreator, ChatAdminRights

from app.services.telegram import mtproto_client
from tests.conftest import guest_auth_headers

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"


class FakeStringSession:
    """Stand-in for telethon.sessions.StringSession — just holds an opaque string."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class Scenario:
    """Mutable script consulted by FakeTelegramClient; reset per test."""

    def __init__(self) -> None:
        # "ok" | "not_found" | "private" | "not_a_channel" | "no_rights"
        self.outcome = "ok"
        self.entity_id = 555
        self.entity_title = "My Real Channel"
        self.is_creator = False
        self.can_post_as_admin = False
        self.dialog_channel: SimpleNamespace | None = None


SCENARIO = Scenario()


@pytest.fixture(autouse=True)
def _reset_scenario_and_patch_telethon(monkeypatch: pytest.MonkeyPatch):
    global SCENARIO
    SCENARIO = Scenario()
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", FakeTelegramClient)
    yield


def _build_channel_entity(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": SCENARIO.entity_id,
        "title": SCENARIO.entity_title,
        "broadcast": True,
        "creator": SCENARIO.is_creator,
        "admin_rights": (
            SimpleNamespace(post_messages=SCENARIO.can_post_as_admin)
            if SCENARIO.can_post_as_admin
            else None
        ),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        if SCENARIO.outcome == "not_found":
            raise errors.UsernameNotOccupiedError(None)
        if SCENARIO.outcome == "private":
            raise errors.ChannelPrivateError(None)
        if SCENARIO.outcome == "not_a_channel":
            return SimpleNamespace(id=SCENARIO.entity_id, title=None)
        if SCENARIO.outcome == "no_rights":
            return SimpleNamespace(
                id=SCENARIO.entity_id,
                title=SCENARIO.entity_title,
                broadcast=True,
                creator=False,
                admin_rights=None,
            )
        return _build_channel_entity()

    async def iter_dialogs(self):
        if SCENARIO.dialog_channel is not None:
            yield SimpleNamespace(entity=SCENARIO.dialog_channel)

    async def __call__(self, request: Any) -> Any:
        if isinstance(request, GetFullChannelRequest):
            return SimpleNamespace(chats=[_build_channel_entity()])
        if isinstance(request, GetParticipantRequest):
            if SCENARIO.is_creator:
                return SimpleNamespace(
                    participant=ChannelParticipantCreator(
                        user_id=1,
                        admin_rights=ChatAdminRights(post_messages=True),
                    )
                )
            if SCENARIO.can_post_as_admin:
                return SimpleNamespace(
                    participant=ChannelParticipantAdmin(
                        user_id=1,
                        promoted_by=1,
                        date=datetime.now(timezone.utc),
                        admin_rights=ChatAdminRights(post_messages=True),
                    )
                )
            return SimpleNamespace(
                participant=ChannelParticipant(user_id=1, date=datetime.now(timezone.utc))
            )
        raise TypeError(type(request))


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
        "channelId": "",
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


async def _put_authorized_credentials(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.put(
        "/api/v1/profile/telegram/",
        headers=headers,
        json=_telegram_payload(
            authStatus="authorized",
            authStep="channel",
            sessionString=SESSION_VALUE,
        ),
    )
    assert resp.status_code == 200
    return resp.json()


async def _connect(client: AsyncClient, headers: dict[str, str], channel: str = "@mychannel"):
    return await client.post(
        "/api/v1/telegram/channel/connect/", headers=headers, json={"channel": channel}
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_requires_authorization(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    resp = await _connect(client, writer_auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_connect_success_as_creator(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True

    resp = await _connect(client, writer_auth_headers, channel="@mychannel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channelStatus"] == "connected"
    assert body["authStatus"] == "connected"
    assert body["channel"] == "@mychannel"
    assert body["channelTitle"] == SCENARIO.entity_title
    assert body["channelId"] == "-100555"
    assert body["lastSync"] != "—"


@pytest.mark.asyncio
async def test_connect_success_as_admin_with_post_rights(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.can_post_as_admin = True

    resp = await _connect(client, writer_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["channelStatus"] == "connected"


@pytest.mark.asyncio
async def test_connect_accepts_t_me_link_and_normalizes_handle(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True

    resp = await _connect(client, writer_auth_headers, channel="https://t.me/mychannel")
    assert resp.status_code == 200
    assert resp.json()["channel"] == "@mychannel"


@pytest.mark.asyncio
async def test_connect_success_via_invite_link(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True
    invite = "https://t.me/+AbCdEfGhIjKlMnOp"

    resp = await _connect(client, writer_auth_headers, channel=invite)
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == invite
    assert body["channelStatus"] == "connected"


@pytest.mark.asyncio
async def test_connect_success_via_joinchat_link(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True
    invite = "https://t.me/joinchat/AbCdEfGhIjKlMnOp"

    resp = await _connect(client, writer_auth_headers, channel=invite)
    assert resp.status_code == 200
    assert resp.json()["channel"] == invite


@pytest.mark.asyncio
async def test_connect_success_via_numeric_id_from_dialogs(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True
    SCENARIO.entity_id = 1234567890
    SCENARIO.dialog_channel = _build_channel_entity(id=1234567890, creator=True, admin_rights=None)

    resp = await _connect(client, writer_auth_headers, channel="-1001234567890")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == "-1001234567890"
    assert body["channelId"] == "-1001234567890"


@pytest.mark.asyncio
async def test_connect_numeric_id_not_in_dialogs(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.dialog_channel = None

    resp = await _connect(client, writer_auth_headers, channel="-1009999999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_connect_invite_link_uses_channel_title_not_link(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.is_creator = True
    SCENARIO.entity_title = "Мой приватный канал"
    invite = "https://t.me/+AbCdEfGhIjKlMnOp"

    resp = await _connect(client, writer_auth_headers, channel=invite)
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == invite
    assert body["channelTitle"] == "Мой приватный канал"


@pytest.mark.asyncio
async def test_connect_channel_not_found(client: AsyncClient, writer_auth_headers: dict) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.outcome = "not_found"

    resp = await _connect(client, writer_auth_headers, channel="@doesnotexist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_connect_channel_private(client: AsyncClient, writer_auth_headers: dict) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.outcome = "private"

    resp = await _connect(client, writer_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_connect_not_a_channel(client: AsyncClient, writer_auth_headers: dict) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.outcome = "not_a_channel"

    resp = await _connect(client, writer_auth_headers, channel="@someuser")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_connect_no_admin_rights(client: AsyncClient, writer_auth_headers: dict) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)
    SCENARIO.outcome = "no_rights"

    resp = await _connect(client, writer_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_connect_rejects_empty_channel(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _put_authorized_credentials(client, writer_auth_headers)

    resp = await _connect(client, writer_auth_headers, channel="   ")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_seed_account_cannot_connect_channel(
    client: AsyncClient, presentation_user
) -> None:
    headers = guest_auth_headers()
    resp = await _connect(client, headers)
    assert resp.status_code == 403
