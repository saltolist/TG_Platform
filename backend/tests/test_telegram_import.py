"""Tests for Telegram channel history import (Phase 3 / Step 3)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from telethon import errors
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.types import (
    ChannelParticipant,
    ChannelParticipantAdmin,
    ChannelParticipantCreator,
    ChatAdminRights,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.core.config import get_settings
from app.db.models import Post, Profile
from app.services.telegram import import_flow as import_flow_module
from app.services.telegram import mtproto_client
from app.services.telegram.import_flow import run_channel_import
from tests.conftest import TestSessionLocal, writer_auth_headers

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


def _document_media(*, mime: str = "application/pdf", name: str = "doc.pdf", size: int = 1024):
    doc = SimpleNamespace(
        id=99,
        access_hash=1,
        file_reference=b"",
        mime_type=mime,
        size=size,
        attributes=[SimpleNamespace(file_name=name)],
    )
    return MessageMediaDocument(document=doc, nopremium=False, spoiler=False)


def _fake_message(
    msg_id: int,
    *,
    text: str = "",
    views: int = 100,
    grouped_id: int | None = None,
    media: Any = None,
    action: Any = None,
    file_size: int | None = None,
) -> SimpleNamespace:
    file_obj = None
    if media is not None:
        size = file_size if file_size is not None else 1024
        file_obj = SimpleNamespace(
            mime_type=getattr(getattr(media, "document", None), "mime_type", "image/jpeg"),
            name="photo.jpg",
            size=size,
        )
    return SimpleNamespace(
        id=msg_id,
        message=text,
        date=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        views=views,
        grouped_id=grouped_id,
        media=media,
        action=action,
        file=file_obj,
    )


class ImportScenario:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.fail_import = False


IMPORT_SCENARIO = ImportScenario()


@pytest.fixture(autouse=True)
def _patch_import_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    global IMPORT_SCENARIO
    IMPORT_SCENARIO = ImportScenario()
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", ImportFakeTelegramClient)
    monkeypatch.setattr(import_flow_module, "async_session_factory", TestSessionLocal)

    settings = get_settings().model_copy(
        update={
            "media_storage_root": str(tmp_path / "media"),
            "media_public_base_url": "http://localhost:8000",
            "telegram_import_post_limit": 200,
            "telegram_import_max_media_mb": 20.0,
            "telegram_import_timeout_seconds": 30.0,
        }
    )
    monkeypatch.setattr(import_flow_module, "get_settings", lambda: settings)
    yield


class ImportFakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        if IMPORT_SCENARIO.fail_import:
            raise errors.RPCError(None)

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: str) -> SimpleNamespace:
        return SimpleNamespace(id=555, title="Import Channel", broadcast=True, creator=True)

    async def iter_dialogs(self):
        if False:
            yield

    async def iter_messages(self, entity: Any, limit: int = 100):
        count = 0
        for message in IMPORT_SCENARIO.messages:
            if count >= limit:
                break
            yield message
            count += 1

    async def download_media(self, message: Any, file: str | None = None, **kwargs: Any):
        if file:
            path = __import__("pathlib").Path(file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-media-bytes")
        return file

    async def __call__(self, request: Any) -> Any:
        if isinstance(request, GetFullChannelRequest):
            return SimpleNamespace(chats=[SimpleNamespace(id=555, title="Import Channel")])
        if isinstance(request, GetParticipantRequest):
            return SimpleNamespace(
                participant=ChannelParticipantCreator(
                    user_id=1,
                    admin_rights=ChatAdminRights(post_messages=True),
                )
            )
        raise TypeError(type(request))


def _telegram_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "+79001234567",
        "sessionName": "",
        "sessionString": SESSION_VALUE,
        "channel": "@mychannel",
        "channelTitle": "Import Channel",
        "channelId": "-100555",
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 0,
        "importStatus": "importing",
        "importError": "",
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    payload.update(overrides)
    return payload


async def _seed_connected_profile(client: AsyncClient, headers: dict, **overrides: Any) -> None:
    resp = await client.put(
        "/api/v1/profile/telegram/",
        headers=headers,
        json=_telegram_payload(**overrides),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_connect_sets_importing_status(
    client: AsyncClient, writer_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import telegram_channel as telegram_channel_module
    from tests import test_telegram_channel as channel_test_module

    monkeypatch.setattr(telegram_channel_module, "run_channel_import", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(mtproto_client, "TelegramClient", channel_test_module.FakeTelegramClient)
    monkeypatch.setattr(mtproto_client, "StringSession", channel_test_module.FakeStringSession)

    await client.put(
        "/api/v1/profile/telegram/",
        headers=writer_auth_headers,
        json=_telegram_payload(authStatus="authorized", authStep="channel", channelStatus="idle"),
    )
    channel_test_module.SCENARIO.is_creator = True

    resp = await client.post(
        "/api/v1/telegram/channel/connect/",
        headers=writer_auth_headers,
        json={"channel": "@mychannel"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["importStatus"] == "importing"
    assert body["importError"] == ""


@pytest.mark.asyncio
async def test_import_text_photo_document_and_album(
    client: AsyncClient, writer_auth_headers: dict, writer_user
) -> None:
    IMPORT_SCENARIO.messages = [
        _fake_message(1, text="Hello channel"),
        _fake_message(2, text="", media=_photo_media()),
        _fake_message(3, text="", media=_document_media()),
        _fake_message(4, text="Album caption", grouped_id=999, media=_photo_media()),
        _fake_message(5, text="", grouped_id=999, media=_photo_media()),
        _fake_message(6, action=SimpleNamespace()),  # service — skipped
    ]
    await _seed_connected_profile(client, writer_auth_headers)
    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile is not None
        assert profile.telegram["importStatus"] == "done"
        assert profile.telegram["importedPosts"] == 4

        posts = (
            await session.execute(
                select(Post).where(Post.user_id == writer_user.id).order_by(Post.position)
            )
        ).scalars().all()
        assert len(posts) == 4
        assert posts[0].data["text"] == "Hello channel"
        assert posts[0].data["source"] == "telegram"
        assert posts[1].data.get("media")
        assert posts[2].data.get("media")
        album = next(p for p in posts if p.data["text"] == "Album caption")
        assert len(album.data.get("media", [])) == 2


@pytest.mark.asyncio
async def test_import_preserves_non_telegram_posts(
    client: AsyncClient, writer_auth_headers: dict, writer_user
) -> None:
    IMPORT_SCENARIO.messages = [_fake_message(10, text="From TG")]
    await _seed_connected_profile(client, writer_auth_headers)

    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=uuid4(),
                user_id=writer_user.id,
                position=0,
                data={
                    "id": "local-1",
                    "status": "draft",
                    "text": "My draft",
                    "notes": [],
                    "chats": [],
                    "rubric": None,
                },
            )
        )
        await session.commit()

    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        posts = (
            await session.execute(
                select(Post).where(Post.user_id == writer_user.id).order_by(Post.position)
            )
        ).scalars().all()
        assert len(posts) == 2
        assert posts[0].data["source"] == "telegram"
        assert posts[1].data["text"] == "My draft"
        assert posts[1].position == 1


@pytest.mark.asyncio
async def test_import_skips_oversized_media(
    client: AsyncClient, writer_auth_headers: dict, writer_user
) -> None:
    huge = 25 * 1024 * 1024
    IMPORT_SCENARIO.messages = [
        _fake_message(1, text="", media=_document_media(size=huge), file_size=huge),
    ]
    await _seed_connected_profile(client, writer_auth_headers)
    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        posts = (
            await session.execute(select(Post).where(Post.user_id == writer_user.id))
        ).scalars().all()
        assert len(posts) == 0
        profile = await session.get(Profile, writer_user.id)
        assert profile.telegram["importedPosts"] == 0
        assert profile.telegram["importStatus"] == "done"


@pytest.mark.asyncio
async def test_import_respects_post_limit(
    client: AsyncClient, writer_auth_headers: dict, writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(update={"telegram_import_post_limit": 3})
    monkeypatch.setattr(import_flow_module, "get_settings", lambda: settings)
    IMPORT_SCENARIO.messages = [_fake_message(i, text=f"Post {i}") for i in range(1, 10)]
    await _seed_connected_profile(client, writer_auth_headers)
    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile.telegram["importedPosts"] == 3


@pytest.mark.asyncio
async def test_import_publish_only_skipped(
    client: AsyncClient, writer_auth_headers: dict, writer_user
) -> None:
    IMPORT_SCENARIO.messages = [_fake_message(1, text="Should not import")]
    await _seed_connected_profile(client, writer_auth_headers, syncMode="publish-only", importStatus="idle")
    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        posts = (
            await session.execute(select(Post).where(Post.user_id == writer_user.id))
        ).scalars().all()
        assert posts == []
        profile = await session.get(Profile, writer_user.id)
        assert profile.telegram["importStatus"] == "idle"


@pytest.mark.asyncio
async def test_import_error_on_failure(
    client: AsyncClient, writer_auth_headers: dict, writer_user
) -> None:
    IMPORT_SCENARIO.fail_import = True
    await _seed_connected_profile(client, writer_auth_headers)
    await run_channel_import(writer_user.id)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, writer_user.id)
        assert profile.telegram["importStatus"] == "error"
        assert profile.telegram["importError"]
