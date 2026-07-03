"""Tests for window channel reconcile (Phase 3 / Step 3.5b)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Post, Profile, User
from app.db import session as db_session_module
from app.services.telegram import mtproto_client
from app.services.telegram.reconcile_flow import (
    reconcile_channel_window,
    reset_reconcile_throttle_storage,
    try_acquire_reconcile_slot,
)
from tests.conftest import TestSessionLocal, writer_auth_headers

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"
MSG_ID = 501


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


def _fake_message(msg_id: int, *, text: str = "Channel text") -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        message=text,
        date=datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc),
        views=42,
        grouped_id=None,
        media=None,
        action=None,
        edit_date=None,
    )


class ReconcileFakeClient:
    known_messages: dict[int, Any] = {}
    scan_messages: list[Any] = []

    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        return SimpleNamespace(id=555, title="Reconcile Channel", broadcast=True)

    async def get_messages(self, entity: Any, ids: Any = None, **kwargs: Any) -> list[Any]:
        if ids is None:
            return []
        id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        return [ReconcileFakeClient.known_messages.get(mid) for mid in id_list]

    async def iter_messages(self, entity: Any, min_id: int = 0, limit: int | None = None) -> Any:
        count = 0
        for message in sorted(ReconcileFakeClient.scan_messages, key=lambda m: m.id, reverse=True):
            if min_id and message.id <= min_id:
                continue
            yield message
            count += 1
            if limit is not None and count >= limit:
                break

    async def download_media(self, message: Any, file: str | None = None) -> str | None:
        return file


@pytest.fixture(autouse=True)
async def _patch_reconcile_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    await reset_reconcile_throttle_storage()
    ReconcileFakeClient.known_messages = {}
    ReconcileFakeClient.scan_messages = []
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", ReconcileFakeClient)
    monkeypatch.setattr(db_session_module, "async_session_factory", TestSessionLocal)
    yield
    await reset_reconcile_throttle_storage()


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
        "lastTelegramMessageId": str(MSG_ID),
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


async def _seed_profile(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.put(
        "/api/v1/profile/telegram/",
        headers=headers,
        json=_connected_telegram_payload(),
    )
    assert resp.status_code == 200


async def _insert_published_post(
    user_id: uuid.UUID,
    *,
    msg_id: int = MSG_ID,
    text: str = "Platform text",
    status: str = "published",
) -> Post:
    async with TestSessionLocal() as session:
        post = Post(
            id=uuid.uuid4(),
            user_id=user_id,
            position=0,
            data={
                "id": str(uuid.uuid4()),
                "status": status,
                "text": text,
                "telegramMessageId": str(msg_id),
                "source": "telegram",
                "date": "2026-01-01T00:00:00+00:00",
            },
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)
        return post


@pytest.mark.asyncio
async def test_reconcile_marks_missing_telegram_message_deleted(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_profile(client, writer_auth_headers)
    post = await _insert_published_post(writer_user.id)
    settings = get_settings()
    entity = SimpleNamespace(id=555)
    stats = await reconcile_channel_window(
        ReconcileFakeClient(None, 1, "hash"),
        entity,
        writer_user.id,
        settings,
        TestSessionLocal,
        force=True,
        include_new_scan=False,
    )
    assert stats.deleted == 1
    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post.id)
        assert refreshed is not None
        assert refreshed.data["status"] == "deleted"


@pytest.mark.asyncio
async def test_reconcile_updates_changed_text(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_profile(client, writer_auth_headers)
    post = await _insert_published_post(writer_user.id, text="Old text")
    ReconcileFakeClient.known_messages[MSG_ID] = _fake_message(MSG_ID, text="New from TG")
    stats = await reconcile_channel_window(
        ReconcileFakeClient(None, 1, "hash"),
        SimpleNamespace(id=555),
        writer_user.id,
        get_settings(),
        TestSessionLocal,
        force=True,
        include_new_scan=False,
    )
    assert stats.updated == 1
    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post.id)
        assert refreshed is not None
        assert refreshed.data["text"] == "New from TG"


@pytest.mark.asyncio
async def test_reconcile_does_not_resurrect_soft_deleted(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_profile(client, writer_auth_headers)
    await _insert_published_post(writer_user.id, status="deleted")
    new_msg = _fake_message(999, text="Only in channel")
    ReconcileFakeClient.scan_messages = [new_msg]
    stats = await reconcile_channel_window(
        ReconcileFakeClient(None, 1, "hash"),
        SimpleNamespace(id=555),
        writer_user.id,
        get_settings(),
        TestSessionLocal,
        force=True,
        include_new_scan=True,
    )
    assert stats.imported == 1
    async with TestSessionLocal() as session:
        deleted = await session.execute(
            select(Post).where(
                Post.user_id == writer_user.id,
                Post.data["telegramMessageId"].astext == str(MSG_ID),
            )
        )
        assert deleted.scalar_one().data["status"] == "deleted"


@pytest.mark.asyncio
async def test_reconcile_throttle_skips_second_call(writer_user: User) -> None:
    await reset_reconcile_throttle_storage()
    settings = get_settings()
    entity = SimpleNamespace(id=555)
    fake = ReconcileFakeClient(None, 1, "hash")
    first = await reconcile_channel_window(
        fake, entity, writer_user.id, settings, TestSessionLocal, force=False, include_new_scan=False
    )
    second = await reconcile_channel_window(
        fake, entity, writer_user.id, settings, TestSessionLocal, force=False, include_new_scan=False
    )
    assert first.skipped_throttle is False
    assert second.skipped_throttle is True


@pytest.mark.asyncio
async def test_reconcile_force_bypasses_throttle(writer_user: User) -> None:
    await reset_reconcile_throttle_storage()
    settings = get_settings()
    assert await try_acquire_reconcile_slot(writer_user.id, settings, force=False)
    stats = await reconcile_channel_window(
        ReconcileFakeClient(None, 1, "hash"),
        SimpleNamespace(id=555),
        writer_user.id,
        settings,
        TestSessionLocal,
        force=True,
        include_new_scan=False,
    )
    assert stats.skipped_throttle is False


@pytest.mark.asyncio
async def test_reconcile_noop_does_not_bump_sync_revision(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_profile(client, writer_auth_headers)
    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile is not None
        base_revision = int(profile.telegram.get("syncRevision") or 0)
    stats = await reconcile_channel_window(
        ReconcileFakeClient(None, 1, "hash"),
        SimpleNamespace(id=555),
        writer_user.id,
        get_settings(),
        TestSessionLocal,
        force=True,
        include_new_scan=False,
    )
    assert stats.checked == 0
    assert stats.updated == 0
    assert stats.deleted == 0
    assert stats.imported == 0
    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile is not None
        assert int(profile.telegram.get("syncRevision") or 0) == base_revision


@pytest.mark.asyncio
async def test_reconcile_api_endpoint(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_profile(client, writer_auth_headers)
    await _insert_published_post(writer_user.id)
    ReconcileFakeClient.known_messages[MSG_ID] = _fake_message(MSG_ID, text="Synced")
    resp = await client.post(
        "/api/v1/telegram/channel/reconcile/",
        headers=writer_auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reconciled"] is True
    assert "stats" in body
    assert body["stats"]["checked"] >= 1
