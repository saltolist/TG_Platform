"""Tests that outbound Telegram RPCs trigger post-RPC reconcile."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.db import session as db_session_module
from app.db.models import Post, Profile
from app.services.telegram import delete_flow, edit_flow, publish_flow
from tests.conftest import TestSessionLocal, writer_user


def _fake_open_outbound(client: Any, telegram: dict[str, Any] | None = None):
    @asynccontextmanager
    async def _cm(*_args: Any, **_kwargs: Any):
        yield client, telegram or {}

    return _cm()


@pytest.mark.asyncio
async def test_publish_post_calls_maybe_reconcile_after_rpc(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    reconcile = AsyncMock()
    monkeypatch.setattr(publish_flow, "maybe_reconcile_after_rpc", reconcile)

    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=user_id,
                telegram={
                    "authStatus": "connected",
                    "channelStatus": "connected",
                    "apiId": "12345678",
                    "apiHash": "abcdef1234567890abcdef1234567890",
                    "sessionString": "enc:fake",
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

    fake_client = FakeClient()
    monkeypatch.setattr(
        publish_flow,
        "open_outbound_telegram_client",
        lambda *_a, **_k: _fake_open_outbound(fake_client),
    )
    monkeypatch.setattr(publish_flow, "decrypt_field", lambda value, _settings: value)
    monkeypatch.setattr(publish_flow, "require_api_credentials", lambda _tg, _s: (1, "hash"))
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
    monkeypatch.setattr(db_session_module, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(publish_flow, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(publish_flow, "telegram_sync_pending", lambda *_a, **_k: _null_async_context())

    await publish_flow.publish_post(user_id, post_id)

    reconcile.assert_awaited_once()
    assert reconcile.await_args.kwargs["force"] is True
    assert reconcile.await_args.kwargs["include_new_scan"] is True


@pytest.mark.asyncio
async def test_delete_message_calls_maybe_reconcile_after_rpc(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = writer_user.id
    reconcile = AsyncMock()
    monkeypatch.setattr(delete_flow, "maybe_reconcile_after_rpc", reconcile)

    class FakeClient:
        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_entity(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=1, broadcast=True)

        async def get_messages(self, *_args: Any, **_kwargs: Any) -> list[Any]:
            return [SimpleNamespace(id=99)]

        async def delete_messages(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    fake_client = FakeClient()
    monkeypatch.setattr(delete_flow, "decrypt_field", lambda value, _settings: value)
    monkeypatch.setattr(delete_flow, "require_api_credentials", lambda _tg, _s: (1, "hash"))
    monkeypatch.setattr(
        delete_flow,
        "resolve_channel_entity_for_profile",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        delete_flow,
        "open_outbound_telegram_client",
        lambda *_a, **_k: _fake_open_outbound(fake_client),
    )

    profile = Profile(
        user_id=user_id,
        telegram={
            "authStatus": "connected",
            "channelStatus": "connected",
            "apiId": "12345678",
            "apiHash": "abcdef1234567890abcdef1234567890",
            "sessionString": "fake",
            "channel": "@ch",
            "channelId": "-1001",
        },
    )
    await delete_flow.delete_message_in_telegram(profile, "99", user_id)

    reconcile.assert_awaited_once()
    assert reconcile.await_args.kwargs["force"] is True
    assert reconcile.await_args.kwargs["include_new_scan"] is False


@pytest.mark.asyncio
async def test_edit_message_calls_maybe_reconcile_after_rpc(
    writer_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = writer_user.id
    reconcile = AsyncMock()
    monkeypatch.setattr(edit_flow, "maybe_reconcile_after_rpc", reconcile)

    class FakeClient:
        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def get_entity(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=1, broadcast=True)

        async def get_messages(self, *_args: Any, **_kwargs: Any) -> list[Any]:
            return [SimpleNamespace(id=88, message="old")]

        async def edit_message(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(id=88)

    fake_client = FakeClient()
    monkeypatch.setattr(edit_flow, "decrypt_field", lambda value, _settings: value)
    monkeypatch.setattr(edit_flow, "require_api_credentials", lambda _tg, _s: (1, "hash"))
    monkeypatch.setattr(
        edit_flow,
        "resolve_channel_entity_for_profile",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        edit_flow,
        "open_outbound_telegram_client",
        lambda *_a, **_k: _fake_open_outbound(fake_client),
    )

    profile = Profile(
        user_id=user_id,
        telegram={
            "authStatus": "connected",
            "channelStatus": "connected",
            "apiId": "12345678",
            "apiHash": "abcdef1234567890abcdef1234567890",
            "sessionString": "fake",
            "channel": "@ch",
            "channelId": "-1001",
        },
    )
    result = await edit_flow.sync_edit_to_telegram(profile, "88", "new text", user_id)

    assert result.error is None
    reconcile.assert_awaited_once()
    assert reconcile.await_args.kwargs["include_new_scan"] is False


class _null_async_context:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: Any) -> None:
        return None
