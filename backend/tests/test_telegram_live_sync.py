"""Tests for Telegram live-sync (Phase 3 / Step 3.5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from telethon import events
from telethon.tl.types import MessageMediaPhoto

from app.core.config import get_settings
from app.db.models import Post, Profile
from app.services.telegram import import_flow as import_flow_module
from app.services.telegram import live_sync_worker as live_sync_module
from app.services.telegram import message_mapping as mapping_module
from app.services.telegram import mtproto_client
from app.services.telegram import post_sync as post_sync_module
from app.services.telegram.live_sync_worker import (
    listener_registry,
    should_listen,
    telegram_live_sync_worker,
)
from app.services.telegram.message_mapping import map_group_to_post
from app.services.telegram.post_sync import (
    delete_telegram_post,
    update_telegram_post,
    upsert_telegram_post,
)
from tests.conftest import TestSessionLocal, writer_auth_headers
from app.db.models import User

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


def _photo_media() -> MessageMediaPhoto:
    return MessageMediaPhoto(spoiler=False, photo=SimpleNamespace(id=1, access_hash=1, file_reference=b""))


def _fake_message(
    msg_id: int,
    *,
    text: str = "",
    grouped_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        message=text,
        date=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        views=50,
        grouped_id=grouped_id,
        media=_photo_media() if not text else None,
        action=None,
        file=SimpleNamespace(mime_type="image/jpeg", name="photo.jpg", size=512),
    )


class LiveSyncFakeClient:
    _latest: LiveSyncFakeClient | None = None
    catchup_messages: list[Any] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.handlers: list[tuple[Any, Any]] = []
        self._disconnect = asyncio.Event()
        self.known_messages: dict[int, Any] = {}
        self.catchup_messages = list(LiveSyncFakeClient.catchup_messages)
        LiveSyncFakeClient._latest = self

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        self._disconnect.set()

    async def __call__(self, *args: Any, **kwargs: Any) -> "LiveSyncFakeClient":
        return self

    def add_event_handler(self, callback: Any, event: Any) -> None:
        self.handlers.append((callback, event))

    def on(self, event: Any) -> Any:
        def decorator(callback: Any) -> Any:
            self.add_event_handler(callback, event)
            return callback

        return decorator

    async def run_until_disconnected(self) -> None:
        await self._disconnect.wait()

    async def iter_messages(self, entity: Any, min_id: int = 0, limit: int | None = None) -> Any:
        for message in sorted(self.catchup_messages, key=lambda m: m.id):
            if message.id > min_id:
                yield message

    async def download_media(self, message: Any, file: str | None = None) -> str | None:
        if file:
            with open(file, "wb") as handle:
                handle.write(b"fake-image")
        return file

    async def get_messages(
        self,
        entity: Any,
        grouped_id: int | None = None,
        ids: Any = None,
    ) -> list[Any]:
        if ids is not None:
            id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
            return [self.known_messages[mid] for mid in id_list if mid in self.known_messages]
        if grouped_id is not None:
            return [m for m in self.catchup_messages if getattr(m, "grouped_id", None) == grouped_id]
        return []

    async def emit_new(self, message: Any) -> None:
        self.known_messages[getattr(message, "id", 0)] = message
        for callback, event in self.handlers:
            if isinstance(event, events.NewMessage):
                await callback(SimpleNamespace(message=message))

    async def emit_edited(self, message: Any) -> None:
        self.known_messages[getattr(message, "id", 0)] = message
        for callback, event in self.handlers:
            if isinstance(event, events.MessageEdited):
                await callback(SimpleNamespace(message=message))

    async def emit_deleted(self, deleted_ids: list[int]) -> None:
        for callback, event in self.handlers:
            if isinstance(event, events.MessageDeleted):
                await callback(SimpleNamespace(deleted_ids=deleted_ids))


@pytest.fixture(autouse=True)
def _patch_live_sync_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    LiveSyncFakeClient._latest = None
    LiveSyncFakeClient.catchup_messages = []
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", LiveSyncFakeClient)
    monkeypatch.setattr(import_flow_module, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(live_sync_module, "_get_session_factory", lambda: TestSessionLocal)

    settings = get_settings().model_copy(
        update={
            "media_storage_root": str(tmp_path / "media"),
            "media_public_base_url": "http://localhost:8000",
            "telegram_live_sync_enabled": True,
            "telegram_live_sync_registry_refresh_seconds": 0.05,
            "telegram_live_sync_reconnect_seconds": 0.01,
            "telegram_album_debounce_seconds": 0.05,
            "telegram_import_post_limit": 200,
        }
    )
    monkeypatch.setattr(live_sync_module, "get_settings", lambda: settings)
    monkeypatch.setattr(import_flow_module, "get_settings", lambda: settings)

    async def _fake_resolve(_client: Any, _parsed: Any, _settings: Any) -> SimpleNamespace:
        return SimpleNamespace(id=123, broadcast=True)

    monkeypatch.setattr(live_sync_module, "resolve_channel_entity", _fake_resolve)

    for user_id in list(listener_registry._tasks.keys()):
        listener_registry.stop_user_listener(user_id)
    yield
    for user_id in list(listener_registry._tasks.keys()):
        listener_registry.stop_user_listener(user_id)


async def _seed_connected_profile(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    sync_mode: str = "history-and-live",
    import_status: str = "done",
    last_message_id: str = "10",
) -> None:
    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "+7 999 000-00-00",
        "sessionName": "",
        "sessionString": SESSION_VALUE,
        "channel": "@testchannel",
        "channelTitle": "Test Channel",
        "channelId": "-100123",
        "channelStatus": "connected",
        "syncMode": sync_mode,
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 1,
        "importStatus": import_status,
        "importError": "",
        "lastTelegramMessageId": last_message_id,
        "syncStatus": "idle",
        "syncError": "",
        "syncRevision": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    await client.put("/api/v1/profile/telegram/", json=payload, headers=headers)


async def _get_writer_user_id(client: AsyncClient, headers: dict[str, str], writer_user: User) -> Any:
    await _seed_connected_profile(client, headers)
    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile is not None
        telegram = dict(profile.telegram or {})
        telegram["lastTelegramMessageId"] = "10"
        profile.telegram = telegram
        await session.commit()
    return writer_user.id


@pytest.mark.asyncio
async def test_should_listen_skips_publish_only_and_importing() -> None:
    assert should_listen({"channelStatus": "connected", "sessionString": "x", "syncMode": "history-and-live", "importStatus": "done"})
    assert not should_listen({"channelStatus": "connected", "sessionString": "x", "syncMode": "publish-only", "importStatus": "done"})
    assert not should_listen({"channelStatus": "connected", "sessionString": "x", "syncMode": "history-and-live", "importStatus": "importing"})


@pytest.mark.asyncio
async def test_upsert_new_message_at_position_zero(
    client: AsyncClient, writer_auth_headers, writer_user, tmp_path
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    fake_client = LiveSyncFakeClient()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path / "media")})
    post_data = await map_group_to_post(
        fake_client,
        [_fake_message(20, text="Live post")],
        user_id,
        settings,
    )
    assert post_data is not None

    async with TestSessionLocal() as session:
        await upsert_telegram_post(session, user_id, post_data)
        await session.commit()

    async with TestSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.user_id == user_id).order_by(Post.position))
        posts = list(result.scalars())
        assert len(posts) == 1
        assert posts[0].position == 0
        assert posts[0].data["text"] == "Live post"
        profile = await session.get(Profile, user_id)
        assert profile.telegram["importedPosts"] == 2
        assert profile.telegram["syncStatus"] == "listening"
        assert int(profile.telegram.get("syncRevision") or 0) >= 1


@pytest.mark.asyncio
async def test_update_and_delete_telegram_post(
    client: AsyncClient, writer_auth_headers, writer_user, tmp_path
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    fake_client = LiveSyncFakeClient()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path / "media")})
    original = await map_group_to_post(fake_client, [_fake_message(30, text="Before")], user_id, settings)
    updated = await map_group_to_post(fake_client, [_fake_message(30, text="After")], user_id, settings)
    updated_again = await map_group_to_post(
        fake_client, [_fake_message(30, text="After again")], user_id, settings
    )
    assert original and updated and updated_again

    async with TestSessionLocal() as session:
        await upsert_telegram_post(session, user_id, original)
        await session.commit()
    async with TestSessionLocal() as session:
        await update_telegram_post(session, user_id, updated)
        await session.commit()
    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        rev_after_first = int(profile.telegram.get("syncRevision") or 0)

    # Re-applying the exact same content (e.g. a duplicated Telethon event) is a
    # no-op — the content-based loop-guard (Step 4c) must not bump syncRevision again.
    async with TestSessionLocal() as session:
        await update_telegram_post(session, user_id, updated)
        await session.commit()
    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        assert int(profile.telegram.get("syncRevision") or 0) == rev_after_first

    async with TestSessionLocal() as session:
        await update_telegram_post(session, user_id, updated_again)
        await session.commit()
    async with TestSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.user_id == user_id))
        post = result.scalar_one()
        assert post.data["text"] == "After again"
        profile = await session.get(Profile, user_id)
        assert int(profile.telegram.get("syncRevision") or 0) == rev_after_first + 1
    async with TestSessionLocal() as session:
        await delete_telegram_post(session, user_id, "30")
        await session.commit()
    async with TestSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.user_id == user_id))
        post = result.scalar_one()
        assert post.data["status"] == "deleted"
        assert post.data.get("deletedAt")
        profile = await session.get(Profile, user_id)
        assert int(profile.telegram.get("syncRevision") or 0) > rev_after_first


@pytest.mark.asyncio
async def test_live_sync_message_edited_via_handler(
    client: AsyncClient, writer_auth_headers, writer_user, tmp_path
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    fake_client = LiveSyncFakeClient()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path / "media")})
    original = await map_group_to_post(fake_client, [_fake_message(35, text="Before edit")], user_id, settings)
    assert original is not None
    async with TestSessionLocal() as session:
        await upsert_telegram_post(session, user_id, original)
        await session.commit()

    listener_registry.start_user_listener(user_id)
    await asyncio.sleep(0.1)
    fake = LiveSyncFakeClient._latest
    assert fake is not None
    await fake.emit_edited(_fake_message(35, text="After edit"))
    await asyncio.sleep(0.15)
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == "35",
            )
        )
        post = result.scalar_one()
        assert post.data["text"] == "After edit"
    listener_registry.stop_user_listener(user_id)


@pytest.mark.asyncio
async def test_update_preserves_media_when_edit_payload_omits_it(
    client: AsyncClient, writer_auth_headers, writer_user, tmp_path
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    fake_client = LiveSyncFakeClient()
    settings = get_settings().model_copy(update={"media_storage_root": str(tmp_path / "media")})
    with_media = await map_group_to_post(fake_client, [_fake_message(36)], user_id, settings)
    text_only = dict(with_media or {})
    text_only["text"] = "Photo edited"
    text_only.pop("media", None)
    assert with_media and with_media.get("media")

    async with TestSessionLocal() as session:
        await upsert_telegram_post(session, user_id, with_media)
        await session.commit()
    async with TestSessionLocal() as session:
        await update_telegram_post(session, user_id, text_only)
        await session.commit()
    async with TestSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.user_id == user_id))
        post = result.scalar_one()
        assert post.data["text"] == "Photo edited"
        assert post.data.get("media") == with_media.get("media")


@pytest.mark.asyncio
async def test_live_sync_new_message_via_handler(
    client: AsyncClient, writer_auth_headers, writer_user
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    listener_registry.start_user_listener(user_id)
    await asyncio.sleep(0.1)
    fake = LiveSyncFakeClient._latest
    assert fake is not None
    await fake.emit_new(_fake_message(40, text="From event"))
    await asyncio.sleep(0.15)
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == "40",
            )
        )
        post = result.scalar_one_or_none()
        assert post is not None
        assert post.data["text"] == "From event"
    listener_registry.stop_user_listener(user_id)


@pytest.mark.asyncio
async def test_album_buffer_groups_messages() -> None:
    flushed: list[list[Any]] = []

    async def capture(messages: list[Any]) -> None:
        flushed.append(list(messages))

    buffer = live_sync_module.AlbumBuffer(0.05, capture)
    await buffer.add(SimpleNamespace(grouped_id=900, id=51))
    await buffer.add(SimpleNamespace(grouped_id=900, id=52))
    await asyncio.sleep(0.15)
    assert len(flushed) == 1
    assert len(flushed[0]) == 2


@pytest.mark.asyncio
async def test_live_sync_album_debounce(
    client: AsyncClient, writer_auth_headers, writer_user
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    listener_registry.start_user_listener(user_id)
    await asyncio.sleep(0.1)
    fake = LiveSyncFakeClient._latest
    assert fake is not None
    await fake.emit_new(_fake_message(51, grouped_id=900))
    await fake.emit_new(_fake_message(52, text="Album", grouped_id=900))
    await asyncio.sleep(0.35)
    async with TestSessionLocal() as session:
        result = await session.execute(select(Post).where(Post.user_id == user_id))
        posts = list(result.scalars())
    album_posts = [p for p in posts if p.data.get("telegramMessageId") in {"51", "52"}]
    assert any(p.data.get("text") == "Album" for p in album_posts)
    assert len(album_posts) >= 1
    listener_registry.stop_user_listener(user_id)


@pytest.mark.asyncio
async def test_live_sync_catch_up_on_start(
    client: AsyncClient, writer_auth_headers, writer_user
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    LiveSyncFakeClient.catchup_messages = [_fake_message(60, text="Missed while offline")]
    listener_registry.start_user_listener(user_id)
    await asyncio.sleep(0.2)
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["telegramMessageId"].astext == "60",
            )
        )
        assert result.scalar_one_or_none() is not None
    listener_registry.stop_user_listener(user_id)


@pytest.mark.asyncio
async def test_reconcile_skips_publish_only(
    client: AsyncClient, writer_auth_headers, writer_user
) -> None:
    await _seed_connected_profile(
        client, writer_auth_headers, sync_mode="publish-only", import_status="idle"
    )
    await listener_registry.reconcile_from_db(TestSessionLocal)
    user_id = writer_user.id
    assert not listener_registry.is_running(user_id)


@pytest.mark.asyncio
async def test_reset_stops_listener(
    client: AsyncClient, writer_auth_headers, writer_user
) -> None:
    user_id = await _get_writer_user_id(client, writer_auth_headers, writer_user)
    listener_registry.start_user_listener(user_id)
    await asyncio.sleep(0.05)
    assert listener_registry.is_running(user_id)
    listener_registry.stop_user_listener(user_id)
    await asyncio.sleep(0.05)
    assert not listener_registry.is_running(user_id)


@pytest.mark.asyncio
async def test_worker_exits_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"telegram_live_sync_enabled": False})
    monkeypatch.setattr(live_sync_module, "get_settings", lambda: settings)
    stop = asyncio.Event()
    stop.set()
    await telegram_live_sync_worker(TestSessionLocal, stop)
