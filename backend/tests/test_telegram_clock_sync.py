"""Tests for Docker clock-skew workaround (Telethon time_offset pre-seed)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.telegram.clock_sync import (
    apply_time_offset_to_client,
    measure_http_time_offset_seconds,
)
from app.services.telegram.net import connect_telegram_client


def test_apply_time_offset_to_client_updates_state() -> None:
    state = SimpleNamespace(time_offset=0, _last_msg_id=99)
    client = SimpleNamespace(_sender=SimpleNamespace(_state=state))

    previous = apply_time_offset_to_client(client, 32)

    assert previous == 0
    assert state.time_offset == 32
    assert state._last_msg_id == 0


def test_apply_time_offset_to_client_without_sender_returns_none() -> None:
    client = SimpleNamespace(_sender=None)
    assert apply_time_offset_to_client(client, 10) is None


@pytest.mark.asyncio
async def test_measure_http_time_offset_seconds_from_date_header() -> None:
    import email.utils

    date_header = "Wed, 01 Jul 2026 12:00:00 GMT"
    server_ts = int(email.utils.parsedate_to_datetime(date_header).timestamp())
    local_ts = server_ts - 32

    response = MagicMock()
    response.headers = {"Date": date_header}

    with patch(
        "app.services.telegram.clock_sync.httpx.AsyncClient",
    ) as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.head = AsyncMock(return_value=response)
        client_cls.return_value = client

        with patch("app.services.telegram.clock_sync.time.time", return_value=float(local_ts)):
            offset = await measure_http_time_offset_seconds()

    assert offset == 32


@pytest.mark.asyncio
async def test_connect_telegram_client_applies_offset_when_enabled() -> None:
    client = MagicMock()
    client.connect = AsyncMock()
    settings = Settings(telegram_clock_sync_enabled=True, telegram_rpc_timeout_seconds=5.0)

    with (
        patch(
            "app.services.telegram.net.measure_http_time_offset_seconds",
            new=AsyncMock(return_value=32),
        ) as measure,
        patch("app.services.telegram.net.apply_time_offset_to_client") as apply_offset,
    ):
        await connect_telegram_client(client, settings)

    client.connect.assert_awaited_once()
    measure.assert_awaited_once()
    apply_offset.assert_called_once_with(client, 32)


@pytest.mark.asyncio
async def test_connect_telegram_client_skips_offset_when_disabled() -> None:
    client = MagicMock()
    client.connect = AsyncMock()
    settings = Settings(telegram_clock_sync_enabled=False, telegram_rpc_timeout_seconds=5.0)

    with (
        patch(
            "app.services.telegram.net.measure_http_time_offset_seconds",
            new=AsyncMock(return_value=32),
        ) as measure,
        patch("app.services.telegram.net.apply_time_offset_to_client") as apply_offset,
    ):
        await connect_telegram_client(client, settings)

    client.connect.assert_awaited_once()
    measure.assert_not_awaited()
    apply_offset.assert_not_called()
