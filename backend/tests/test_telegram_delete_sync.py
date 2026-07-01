"""Tests for deleting a Telegram message when its platform post is deleted
(Phase 3 / Step 4c — delete).

Covers the ``DELETE /posts/:id/`` -> ``delete_flow.delete_message_in_telegram``
path. The platform mirrors the channel: if the Telegram delete fails the post
must stay on the platform and the endpoint returns an error.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Post
from app.services.telegram import mtproto_client
from tests.conftest import sample_post

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"
TELEGRAM_MESSAGE_ID = "777"


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class DeleteScenario:
    def __init__(self) -> None:
        self.deleted: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None


SCENARIO = DeleteScenario()


class DeleteFakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        return SimpleNamespace(id=555, title="Delete Channel", broadcast=True)

    async def delete_messages(self, entity: Any, message_ids: list[int]) -> Any:
        if SCENARIO.fail_with is not None:
            raise SCENARIO.fail_with
        SCENARIO.deleted.append({"entity": entity, "message_ids": message_ids})
        return SimpleNamespace()


@pytest.fixture(autouse=True)
def _patch_delete_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    SCENARIO.deleted = []
    SCENARIO.fail_with = None
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", DeleteFakeTelegramClient)
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
        "syncMode": "history-and-live",
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 1,
        "importStatus": "done",
        "importError": "",
        "lastTelegramMessageId": TELEGRAM_MESSAGE_ID,
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


async def _create_published_post(
    client: AsyncClient, headers: dict[str, str]
) -> dict[str, Any]:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Published text")
    payload["status"] = "published"
    payload["telegramMessageId"] = TELEGRAM_MESSAGE_ID
    payload["source"] = "telegram"
    resp = await client.post("/api/v1/posts/", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_delete_published_post_removes_channel_message(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)

    resp = await client.delete(f"/api/v1/posts/{post['id']}/", headers=writer_auth_headers)
    assert resp.status_code == 204

    assert len(SCENARIO.deleted) == 1
    assert SCENARIO.deleted[0]["message_ids"] == [int(TELEGRAM_MESSAGE_ID)]

    listed = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    deleted_post = next(p for p in listed.json() if p["id"] == post["id"])
    assert deleted_post["status"] == "deleted"
    assert deleted_post.get("deletedAt")


@pytest.mark.asyncio
async def test_delete_draft_post_does_not_call_telegram(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Draft text")
    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    resp = await client.delete(f"/api/v1/posts/{post_id}/", headers=writer_auth_headers)
    assert resp.status_code == 204
    assert SCENARIO.deleted == []

    listed = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    draft = next(p for p in listed.json() if p["id"] == post_id)
    assert draft["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_aborts_and_keeps_post_when_telegram_fails(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)
    SCENARIO.fail_with = RuntimeError("Telegram is unreachable")

    resp = await client.delete(f"/api/v1/posts/{post['id']}/", headers=writer_auth_headers)
    assert resp.status_code == 502
    assert resp.json()["error"]

    listed = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert any(p["id"] == post["id"] and p["status"] != "deleted" for p in listed.json())
