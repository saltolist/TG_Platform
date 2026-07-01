"""Tests for propagating a platform text edit to Telegram (Phase 3 / Step 4c).

Covers the ``PATCH /posts/:id/`` -> ``edit_flow.sync_edit_to_telegram`` path,
plus the content-based loop-guard in ``update_telegram_post`` that stops the
live-sync echo of that same edit from re-touching the post/profile.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Post, Profile
from app.services.telegram import mtproto_client
from app.services.telegram.post_sync import update_telegram_post
from tests.conftest import TestSessionLocal, sample_post

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"
TELEGRAM_MESSAGE_ID = "777"


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class EditScenario:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None


SCENARIO = EditScenario()


class EditFakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        return SimpleNamespace(id=555, title="Edit Channel", broadcast=True)

    async def edit_message(self, entity: Any, message_id: int, text: str) -> Any:
        if SCENARIO.fail_with is not None:
            raise SCENARIO.fail_with
        SCENARIO.edits.append({"entity": entity, "message_id": message_id, "text": text})
        return SimpleNamespace(id=message_id)


@pytest.fixture(autouse=True)
def _patch_edit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    SCENARIO.edits = []
    SCENARIO.fail_with = None
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", EditFakeTelegramClient)
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
    client: AsyncClient, headers: dict[str, str], *, text: str = "Original text"
) -> dict[str, Any]:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text=text)
    payload["status"] = "published"
    payload["telegramMessageId"] = TELEGRAM_MESSAGE_ID
    payload["source"] = "telegram"
    resp = await client.post("/api/v1/posts/", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_patch_text_change_syncs_edit_to_telegram(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)

    resp = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={"text": "Edited from platform"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Edited from platform"
    assert "telegramSyncError" not in body

    assert len(SCENARIO.edits) == 1
    assert SCENARIO.edits[0]["message_id"] == int(TELEGRAM_MESSAGE_ID)
    assert SCENARIO.edits[0]["text"] == "Edited from platform"


@pytest.mark.asyncio
async def test_patch_without_text_change_does_not_call_telegram(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)

    resp = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={"rubric": "News"},
    )
    assert resp.status_code == 200
    assert SCENARIO.edits == []


@pytest.mark.asyncio
async def test_patch_edit_failure_keeps_db_write_and_surfaces_error(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)
    SCENARIO.fail_with = RuntimeError("Telegram is unreachable")

    resp = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={"text": "Edited while Telegram is down"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Edited while Telegram is down"
    assert body["telegramSyncError"]

    listed = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    posts = listed.json()
    assert any(p["text"] == "Edited while Telegram is down" for p in posts)


@pytest.mark.asyncio
async def test_patch_draft_post_does_not_call_telegram(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Draft text")
    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    resp = await client.patch(
        f"/api/v1/posts/{post_id}/",
        headers=writer_auth_headers,
        json={"text": "Still a draft"},
    )
    assert resp.status_code == 200
    assert SCENARIO.edits == []


@pytest.mark.asyncio
async def test_live_sync_skips_stale_channel_edit_after_platform_save(writer_user) -> None:
    """A delayed MessageEdited from before a platform PATCH must not roll back the DB text."""
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(Profile(user_id=user_id, telegram={"syncRevision": 0, "importedPosts": 1}))
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "tg-post",
                    "status": "published",
                    "text": "From platform",
                    "telegramMessageId": TELEGRAM_MESSAGE_ID,
                    "source": "telegram",
                    "_platformTextEditAt": "2026-07-01T12:00:00+00:00",
                },
            )
        )
        await session.commit()

    async with TestSessionLocal() as session:
        await update_telegram_post(
            session,
            user_id,
            {
                "telegramMessageId": TELEGRAM_MESSAGE_ID,
                "text": "Stale from channel",
                "_telegramEditDate": "2026-07-01T11:00:00+00:00",
            },
        )
        await session.commit()

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        assert int(profile.telegram.get("syncRevision") or 0) == 0

        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == TELEGRAM_MESSAGE_ID,
            )
        )
        post = result.scalar_one()
        assert post.data["text"] == "From platform"


@pytest.mark.asyncio
async def test_upsert_skips_channel_text_without_edit_date_after_platform_save(writer_user) -> None:
    """Catch-up upsert must not overwrite a platform save when edit_date is missing."""
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(Profile(user_id=user_id, telegram={"syncRevision": 0, "importedPosts": 1}))
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "tg-post",
                    "status": "published",
                    "text": "From platform",
                    "telegramMessageId": TELEGRAM_MESSAGE_ID,
                    "source": "telegram",
                    "_platformTextEditAt": "2026-07-01T12:00:00+00:00",
                },
            )
        )
        await session.commit()

    from app.services.telegram.post_sync import upsert_telegram_post

    async with TestSessionLocal() as session:
        await upsert_telegram_post(
            session,
            user_id,
            {
                "telegramMessageId": TELEGRAM_MESSAGE_ID,
                "text": "Stale from channel catch-up",
                "status": "published",
            },
        )
        await session.commit()

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == TELEGRAM_MESSAGE_ID,
            )
        )
        post = result.scalar_one()
        assert post.data["text"] == "From platform"


@pytest.mark.asyncio
async def test_live_sync_loop_guard_skips_unchanged_content(writer_user) -> None:
    """A live-sync echo of a platform-triggered edit must not bump syncRevision again."""
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(Profile(user_id=user_id, telegram={"syncRevision": 0, "importedPosts": 1}))
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "tg-post",
                    "status": "published",
                    "text": "Same text",
                    "telegramMessageId": TELEGRAM_MESSAGE_ID,
                    "source": "telegram",
                },
            )
        )
        await session.commit()

    async with TestSessionLocal() as session:
        await update_telegram_post(
            session,
            user_id,
            {"telegramMessageId": TELEGRAM_MESSAGE_ID, "text": "Same text"},
        )
        await session.commit()

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        assert int(profile.telegram.get("syncRevision") or 0) == 0

        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == TELEGRAM_MESSAGE_ID,
            )
        )
        post = result.scalar_one()
        assert post.data["text"] == "Same text"
