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
    monkeypatch.setattr(
        writer_session, "require_api_credentials", lambda _tg, _s: (1, "hash")
    )
    monkeypatch.setattr(
        writer_session, "_writer_session_is_valid", AsyncMock(return_value=True)
    )

    profile = Profile(user_id=writer_user.id, telegram={"writerSessionString": "enc"})
    result = await writer_session.ensure_writer_session_string(
        profile, writer_user.id, get_settings()
    )

    assert result == "existing-writer-session"
    export.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_writer_session_reexports_when_existing_is_revoked(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (chat b0d11b7c): Telegram can revoke the writer auth key
    out-of-band (password change, "terminate all sessions") while the reader
    session — a separate auth key powering incoming sync — keeps working.
    ensure_writer_session_string used to trust a cached writerSessionString
    unconditionally, so every publish/edit/delete failed forever with
    AuthKeyUnregisteredError even though the user could still see messages
    arrive from Telegram. It must probe the cached session and re-export a
    fresh one when Telegram no longer recognizes it."""
    user_id = writer_user.id
    persist = AsyncMock()
    monkeypatch.setattr(
        writer_session, "decrypt_writer_session", lambda _tg, _s: "revoked-writer-session"
    )
    monkeypatch.setattr(writer_session, "decrypt_field", lambda value, _s: value or "reader")
    monkeypatch.setattr(
        writer_session, "require_api_credentials", lambda _tg, _s: (1, "hash")
    )
    monkeypatch.setattr(
        writer_session,
        "_writer_session_is_valid",
        AsyncMock(side_effect=[False, True]),
    )
    monkeypatch.setattr(
        writer_session,
        "export_writer_session",
        AsyncMock(return_value="fresh-writer-session"),
    )
    monkeypatch.setattr(writer_session, "persist_writer_session_string", persist)

    registry = SimpleNamespace(get_active_reader_client=lambda _uid: object())
    monkeypatch.setattr(
        "app.services.telegram.live_sync_worker.listener_registry",
        registry,
    )

    profile = Profile(
        user_id=user_id,
        telegram={
            "sessionString": "reader",
            "writerSessionString": "revoked",
            "apiId": "1",
            "apiHash": "hash",
        },
    )
    result = await writer_session.ensure_writer_session_string(
        profile, user_id, get_settings()
    )

    assert result == "fresh-writer-session"
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_writer_export_dc_picks_different_dc() -> None:
    settings = get_settings()

    class FakeSession:
        dc_id = 2

    class FakeReaderClient:
        session = FakeSession()

        async def __call__(self, request: Any) -> Any:
            assert type(request).__name__ == "GetConfigRequest"
            return SimpleNamespace(
                dc_options=[
                    SimpleNamespace(id=2, ip_address="1.2.3.4", port=443, cdn=False),
                    SimpleNamespace(id=4, ip_address="5.6.7.8", port=443, cdn=False),
                ]
            )

    dc_id, ip, port = await writer_session._resolve_writer_export_dc(
        FakeReaderClient(), settings
    )
    assert dc_id == 4
    assert ip == "5.6.7.8"
    assert port == 443


@pytest.mark.asyncio
async def test_export_writer_session_saves_imported_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    saved: list[str] = []
    set_dc_calls: list[tuple[int, str, int]] = []

    class FakeSession:
        dc_id = 2

        def set_dc(self, dc_id: int, ip: str, port: int) -> None:
            set_dc_calls.append((dc_id, ip, port))
            self.dc_id = dc_id

        def save(self) -> str:
            saved.append("writer-session-bytes")
            return "writer-session-bytes"

    class FakeWriterClient:
        session = FakeSession()

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_me(self) -> SimpleNamespace:
            return SimpleNamespace(id=1)

        async def __call__(self, request: Any) -> Any:
            assert type(request).__name__ == "ImportAuthorizationRequest"
            return None

    class FakeReaderClient:
        session = FakeSession()

        async def __call__(self, request: Any) -> Any:
            name = type(request).__name__
            if name == "GetConfigRequest":
                return SimpleNamespace(
                    dc_options=[
                        SimpleNamespace(id=2, ip_address="1.2.3.4", port=443, cdn=False),
                        SimpleNamespace(id=4, ip_address="5.6.7.8", port=443, cdn=False),
                    ]
                )
            assert name == "ExportAuthorizationRequest"
            assert request.dc_id == 4
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
    assert set_dc_calls == [(4, "5.6.7.8", 443)]


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
    monkeypatch.setattr(
        writer_session, "_writer_session_is_valid", AsyncMock(return_value=True)
    )

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
async def test_ensure_writer_session_raises_when_freshly_exported_key_is_dead(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (chat b0d11b7c): some accounts have Telegram revoke the
    freshly imported auth key on the very next request — export_writer_session
    "succeeds" (Import returns full user data) but the key is already dead.
    Persisting and returning that string would repeat AuthKeyUnregisteredError
    forever; ensure_writer_session_string must instead raise so the caller
    (open_outbound_telegram_client) falls back to the reader session, which is
    the already-designed degraded path."""
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
        AsyncMock(return_value="dead-on-arrival-session"),
    )
    monkeypatch.setattr(writer_session, "persist_writer_session_string", persist)
    monkeypatch.setattr(
        writer_session, "_writer_session_is_valid", AsyncMock(return_value=False)
    )

    registry = SimpleNamespace(get_active_reader_client=lambda _uid: object())
    monkeypatch.setattr(
        "app.services.telegram.live_sync_worker.listener_registry",
        registry,
    )

    profile = Profile(
        user_id=user_id,
        telegram={"sessionString": "reader", "apiId": "1", "apiHash": "hash"},
    )
    with pytest.raises(writer_session.TelegramAuthError):
        await writer_session.ensure_writer_session_string(profile, user_id, get_settings())

    persist.assert_not_called()


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
