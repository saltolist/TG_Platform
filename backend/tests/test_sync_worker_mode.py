"""Tests for dedicated sync-worker deployment mode."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import get_settings
from app.services.telegram.listener_control import (
    effective_sync_status_async,
    request_listener_pause,
    reset_listener_control_storage,
    uses_remote_listener,
)


@pytest.fixture(autouse=True)
async def _reset_listener_control() -> None:
    await reset_listener_control_storage()
    yield
    await reset_listener_control_storage()


def test_uses_remote_listener_when_live_sync_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_live_sync_enabled", False)
    assert uses_remote_listener() is True


@pytest.mark.asyncio
async def test_request_listener_pause_publishes_when_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(get_settings(), "telegram_live_sync_enabled", False)

    published: list[str] = []
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.publish = AsyncMock(side_effect=lambda ch, _data: published.append(ch))
    mock_redis.exists = AsyncMock(return_value=0)

    async def _fake_get_redis() -> AsyncMock:
        return mock_redis

    monkeypatch.setattr(
        "app.services.telegram.listener_control._get_redis",
        _fake_get_redis,
    )

    await request_listener_pause(user_id, timeout=0.5)
    assert published == [f"tg:listener:pause:{user_id}"]


@pytest.mark.asyncio
async def test_effective_sync_status_remote_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(get_settings(), "telegram_live_sync_enabled", False)
    monkeypatch.setattr(
        "app.services.telegram.listener_control.is_listener_active_remote",
        AsyncMock(return_value=True),
    )

    telegram = {
        "channelStatus": "connected",
        "authStatus": "connected",
        "sessionString": "x",
        "channel": "@ch",
        "syncMode": "history-and-live",
        "importStatus": "done",
    }
    status, error = await effective_sync_status_async(telegram, user_id)
    assert status == "listening"
    assert error == ""


@pytest.mark.asyncio
async def test_telegram_live_sync_worker_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.telegram.live_sync_worker import telegram_live_sync_worker

    monkeypatch.setattr(get_settings(), "telegram_live_sync_enabled", False)
    reconcile = AsyncMock()
    monkeypatch.setattr(
        "app.services.telegram.live_sync_worker.listener_registry.reconcile_from_db",
        reconcile,
    )

    await telegram_live_sync_worker(AsyncMock(), None)
    reconcile.assert_not_called()
