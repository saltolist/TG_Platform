"""Tests for lazy writer MTProto session bootstrap."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.db.models import Post, Profile
from app.services.telegram import publish_flow, writer_session
from tests.conftest import TestSessionLocal, writer_user


@pytest.mark.asyncio
async def test_ensure_writer_session_returns_existing_without_export(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = AsyncMock()
    monkeypatch.setattr(writer_session, "export_writer_session", export)
    monkeypatch.setattr(
        writer_session,
        "decrypt_writer_session",
        lambda _tg, _s: "existing-writer-session",
    )

    profile = Profile(user_id=writer_user.id, telegram={"writerSessionString": "enc"})
    result = await writer_session.ensure_writer_session_string(
        profile, writer_user.id, get_settings()
    )

    assert result == "existing-writer-session"
    export.assert_not_called()


@pytest.mark.asyncio
async def test_export_writer_session_saves_imported_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    saved: list[str] = []

    class FakeSession:
        dc_id = 2

        def save(self) -> str:
            saved.append("writer-session-bytes")
            return "writer-session-bytes"

    class FakeWriterClient:
        session = FakeSession()

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def __call__(self, request: Any) -> Any:
            assert type(request).__name__ == "ImportAuthorizationRequest"
            return None

    class FakeReaderClient:
        session = FakeSession()

        async def __call__(self, request: Any) -> Any:
            assert type(request).__name__ == "ExportAuthorizationRequest"
            return SimpleNamespace(id=1, bytes=b"auth-bytes")

    monkeypatch.setattr(
        writer_session,
        "build_client",
        lambda *_a, **_k: FakeWriterClient(),
    )
    monkeypatch.setattr(writer_session, "connect_telegram_client", AsyncMock())
    monkeypatch.setattr(writer_session, "disconnect_safely", AsyncMock())
    monkeypatch.setattr(writer_session, "save_session", lambda client: client.session.save())

    result = await writer_session.export_writer_session(
        FakeReaderClient(), 1, "hash", settings
    )
    assert result == "writer-session-bytes"
    assert saved == ["writer-session-bytes"]


@pytest.mark.asyncio
async def test_ensure_writer_session_persists_exported_session(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = writer_user.id
    persist = AsyncMock()
    monkeypatch.setattr(writer_session, "decrypt_writer_session", lambda _tg, _s: None)
    monkeypatch.setattr(writer_session, "decrypt_field", lambda value, _s: value or "reader")
    monkeypatch.setattr(
        writer_session, "require_api_credentials", lambda _tg, _s: (1, "hash")
    )
    monkeypatch.setattr(
        writer_session,
        "export_writer_session",
        AsyncMock(return_value="new-writer-session"),
    )
    monkeypatch.setattr(writer_session, "persist_writer_session_string", persist)

    registry = SimpleNamespace(get_active_reader_client=lambda _uid: object())
    monkeypatch.setattr(
        "app.services.telegram.live_sync_worker.listener_registry",
        registry,
    )

    profile = Profile(
        user_id=user_id,
        telegram={"sessionString": "reader", "apiId": "1", "apiHash": "hash"},
    )
    result = await writer_session.ensure_writer_session_string(
        profile, user_id, get_settings()
    )

    assert result == "new-writer-session"
    persist.assert_awaited_once()
    assert persist.await_args.args[0] == user_id
    assert persist.await_args.args[1] == "new-writer-session"


@pytest.mark.asyncio
async def test_publish_does_not_stop_listener_when_writer_available(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    stop_listener = AsyncMock()

    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=user_id,
                telegram={
                    "authStatus": "connected",
                    "channelStatus": "connected",
                    "apiId": "12345678",
                    "apiHash": "abcdef1234567890abcdef1234567890",
                    "sessionString": "reader",
                    "writerSessionString": "writer",
                    "channel": "@ch",
                    "channelId": "-1001",
                    "syncMode": "history-and-live",
                },
            )
        )
        session.add(
            Post(
                id=post_id,
                user_id=user_id,
                position=0,
                data={"id": str(post_id), "status": "draft", "text": "Hello"},
            )
        )
        await session.commit()

    class FakeClient:
        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_entity(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=1, broadcast=True)

        async def send_message(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=42)

        async def get_messages(self, *_args: Any, **_kwargs: Any) -> list[Any]:
            return [SimpleNamespace(id=42, message="Hello", grouped_id=None)]

    @asynccontextmanager
    async def _fake_open(profile, uid, settings=None):
        yield FakeClient(), dict(profile.telegram or {})

    monkeypatch.setattr(publish_flow, "maybe_reconcile_after_rpc", AsyncMock())
    monkeypatch.setattr(
        publish_flow,
        "resolve_channel_entity_for_profile",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        publish_flow,
        "map_group_to_post",
        AsyncMock(return_value={"telegramMessageId": "42", "text": "Hello", "status": "published"}),
    )
    monkeypatch.setattr(publish_flow, "decrypt_field", lambda value, _s: value)
    monkeypatch.setattr(publish_flow, "require_api_credentials", lambda _tg, _s: (1, "hash"))
    monkeypatch.setattr(publish_flow, "open_outbound_telegram_client", _fake_open)
    monkeypatch.setattr(
        "app.services.telegram.live_sync_worker.listener_registry.await_stop_user_listener",
        stop_listener,
    )
    monkeypatch.setattr(publish_flow, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    monkeypatch.setattr(
        publish_flow,
        "telegram_sync_pending",
        lambda *_a, **_k: _null_async_context(),
    )

    await publish_flow.publish_post(user_id, post_id)

    stop_listener.assert_not_called()


class _null_async_context:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: Any) -> None:
        return None
