"""Tests for publishing a draft post to Telegram (Phase 3 / Step 4a).

Telethon's network layer is replaced by a scripted fake client (same pattern
as test_telegram_channel.py), so these tests exercise the full HTTP ->
publish_flow -> profile/post persistence round trip without touching real
Telegram servers.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services.telegram import mtproto_client
from app.services.telegram import publish_flow as publish_flow_module
from tests.conftest import TestSessionLocal, sample_post

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class FakeMessage:
    def __init__(self, msg_id: int, *, text: str = "", views: int = 128) -> None:
        from datetime import datetime, timezone

        self.id = msg_id
        self.message = text
        self.views = views
        self.date = datetime.now(timezone.utc)
        self.media = None
        self.edit_date = None
        self.action = None


class PublishScenario:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.messages: dict[int, FakeMessage] = {}
        self.next_message_id = 1000


SCENARIO = PublishScenario()


class PublishFakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        return SimpleNamespace(id=555, title="Publish Channel", broadcast=True)

    async def send_message(self, entity: Any, text: str) -> FakeMessage:
        SCENARIO.next_message_id += 1
        SCENARIO.sent.append({"kind": "message", "entity": entity, "text": text})
        message = FakeMessage(SCENARIO.next_message_id, text=text)
        SCENARIO.messages[message.id] = message
        return message

    async def send_file(self, entity: Any, file: Any, caption: str = "") -> Any:
        SCENARIO.next_message_id += 1
        SCENARIO.sent.append({"kind": "file", "entity": entity, "file": file, "caption": caption})
        message = FakeMessage(SCENARIO.next_message_id, text=caption)
        SCENARIO.messages[message.id] = message
        if isinstance(file, list):
            return [message for _ in file]
        return message

    async def get_messages(self, entity: Any, ids: Any = None, **kwargs: Any) -> list[FakeMessage]:
        if ids is None:
            return []
        msg_id = int(ids[0] if isinstance(ids, (list, tuple)) else ids)
        message = SCENARIO.messages.get(msg_id)
        return [message] if message is not None else []


@pytest.fixture(autouse=True)
def _patch_publish_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    SCENARIO.sent = []
    SCENARIO.messages = {}
    SCENARIO.next_message_id = 1000
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", PublishFakeTelegramClient)
    monkeypatch.setattr(publish_flow_module, "async_session_factory", TestSessionLocal)

    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path / "media")})
    monkeypatch.setattr(publish_flow_module, "get_settings", lambda: settings)
    yield


def _connected_telegram_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "",
        "sessionName": "",
        "sessionString": SESSION_VALUE,
        "channel": "@mychannel",
        "channelTitle": "My Channel",
        "channelId": "-100555",
        "channelStatus": "connected",
        "syncMode": "publish-only",
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 0,
        "importStatus": "idle",
        "importError": "",
        "lastTelegramMessageId": "",
        "syncStatus": "idle",
        "syncError": "",
        "syncRevision": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    payload.update(overrides)
    return payload


async def _seed_connected_profile(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> None:
    resp = await client.put(
        "/api/v1/profile/telegram/",
        headers=headers,
        json=_connected_telegram_payload(**overrides),
    )
    assert resp.status_code == 200


async def _create_draft(
    client: AsyncClient, headers: dict[str, str], *, text: str = "Hello Telegram", **overrides: Any
) -> dict[str, Any]:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text=text)
    payload.update(overrides)
    resp = await client.post("/api/v1/posts/", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_publish_sends_text_message_and_marks_published(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers, text="Hello Telegram")

    resp = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "published"
    assert body["telegramMessageId"]
    assert body["source"] == "telegram"
    assert body["metrics"]["views"] == "128"
    assert body["comments"] == []
    assert len(SCENARIO.sent) == 1
    assert SCENARIO.sent[0]["kind"] == "message"
    assert SCENARIO.sent[0]["text"] == "Hello Telegram"
    assert "created" not in body


@pytest.mark.asyncio
async def test_publish_uses_telegram_date_not_draft_created(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(
        client,
        writer_auth_headers,
        text="Timed publish",
        created="2020-01-01T08:00:00.000Z",
    )

    resp = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] != "2020-01-01T08:00:00.000Z"
    assert "created" not in body


@pytest.mark.asyncio
async def test_publish_is_idempotent_for_already_published_post(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers)

    first = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert first.status_code == 200
    first_message_id = first.json()["telegramMessageId"]

    second = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert second.status_code == 200
    assert second.json()["telegramMessageId"] == first_message_id
    assert len(SCENARIO.sent) == 1


@pytest.mark.asyncio
async def test_publish_requires_connected_channel(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post = await _create_draft(client, writer_auth_headers)
    resp = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert resp.status_code == 400
    assert SCENARIO.sent == []


@pytest.mark.asyncio
async def test_publish_rejects_already_published_status(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers, status="published")

    resp = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_publish_with_media_uses_send_file(
    client: AsyncClient, writer_auth_headers: dict, tmp_path, writer_user
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    media_dir = tmp_path / "media" / str(writer_user.id)
    media_dir.mkdir(parents=True)
    (media_dir / "photo.jpg").write_bytes(b"fake-image-bytes")

    post = await _create_draft(
        client,
        writer_auth_headers,
        text="With photo",
        media=[
            {
                "name": "photo.jpg",
                "url": f"/media/{writer_user.id}/photo.jpg",
                "type": "image/jpeg",
            }
        ],
    )

    resp = await client.post(f"/api/v1/posts/{post['id']}/publish/", headers=writer_auth_headers)
    assert resp.status_code == 200
    assert SCENARIO.sent[0]["kind"] == "file"
    assert SCENARIO.sent[0]["caption"] == "With photo"


@pytest.mark.asyncio
async def test_publish_not_found_for_foreign_post(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    resp = await client.post(
        f"/api/v1/posts/{uuid.uuid4()}/publish/", headers=writer_auth_headers
    )
    assert resp.status_code == 404
