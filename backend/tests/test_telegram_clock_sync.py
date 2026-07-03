"""Tests for Docker clock-skew workaround (Telethon time_offset pre-seed)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings

from app.services.telegram.clock_sync import (
    apply_preferred_time_offset,
    apply_time_offset_to_client,
    choose_clock_offset,
    measure_http_time_offset_seconds,
    offset_from_message_date,
    refine_clock_from_live_message,
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


def test_apply_preferred_time_offset_keeps_stronger_telethon_value() -> None:
    state = SimpleNamespace(time_offset=-34, _last_msg_id=0)
    client = SimpleNamespace(_sender=SimpleNamespace(_state=state))

    result = apply_preferred_time_offset(client, 0)

    assert result == -34
    assert state.time_offset == -34


def test_apply_preferred_time_offset_upgrades_weaker_value() -> None:
    state = SimpleNamespace(time_offset=0, _last_msg_id=99)
    client = SimpleNamespace(_sender=SimpleNamespace(_state=state))

    previous = apply_preferred_time_offset(client, -32)

    assert previous == 0
    assert state.time_offset == -32
    assert state._last_msg_id == 0


def test_choose_clock_offset_prefers_telegram_when_http_is_zero() -> None:
    assert choose_clock_offset(0, -31) == -31
    assert choose_clock_offset(None, -31) == -31


def test_choose_clock_offset_prefers_stronger_http() -> None:
    assert choose_clock_offset(-32, -31) == -32


def test_choose_clock_offset_ignores_corrupt_telethon_offset() -> None:
    assert choose_clock_offset(-32, -1_783_037_447) == -32


def test_offset_from_message_date_uses_utc_timestamp() -> None:
    now = 1_783_037_600.0
    message = SimpleNamespace(date=datetime.fromtimestamp(now - 400, tz=timezone.utc))
    with patch("app.services.telegram.clock_sync.time.time", return_value=now):
        assert offset_from_message_date(message) == -400


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
async def test_measure_http_prefers_nonzero_over_zero_samples() -> None:
    import email.utils

    date_header = "Wed, 01 Jul 2026 12:00:00 GMT"
    server_ts = int(email.utils.parsedate_to_datetime(date_header).timestamp())
    local_ts = server_ts - 32

    zero_response = MagicMock()
    zero_response.headers = {"Date": date_header}
    skew_response = MagicMock()
    skew_response.headers = {"Date": date_header}

    with patch(
        "app.services.telegram.clock_sync.httpx.AsyncClient",
    ) as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.head = AsyncMock(side_effect=[zero_response] * 8 + [skew_response])
        client_cls.return_value = client

        times = [float(server_ts)] * 8 + [float(server_ts - 32)]
        with patch("app.services.telegram.clock_sync.time.time", side_effect=times):
            offset = await measure_http_time_offset_seconds()

    assert offset == 32


def test_refine_clock_from_live_message_updates_stronger_offset() -> None:
    now = 1_783_037_632.0
    message = SimpleNamespace(
        date=datetime.fromtimestamp(now - 32, tz=timezone.utc),
    )
    state = SimpleNamespace(time_offset=-28, _last_msg_id=0)
    client = SimpleNamespace(_sender=SimpleNamespace(_state=state))
    settings = Settings(telegram_clock_sync_enabled=True)

    with patch("app.services.telegram.clock_sync.time.time", return_value=now):
        applied = refine_clock_from_live_message(client, message, settings)

    assert applied == -32
    assert state.time_offset == -32


@pytest.mark.asyncio
async def test_connect_telegram_client_applies_offset_when_enabled() -> None:
    client = MagicMock()
    client.connect = AsyncMock()
    client.get_me = AsyncMock()
    settings = Settings(telegram_clock_sync_enabled=True, telegram_rpc_timeout_seconds=5.0)

    with (
        patch(
            "app.services.telegram.net.measure_http_time_offset_seconds",
            new=AsyncMock(return_value=32),
        ) as measure,
        patch(
            "app.services.telegram.net.reinforce_clock_after_telegram_rpc",
            new=AsyncMock(return_value=32),
        ) as reinforce,
    ):
        await connect_telegram_client(client, settings)

    client.connect.assert_awaited_once()
    client.get_me.assert_awaited_once()
    measure.assert_awaited_once()
    reinforce.assert_awaited_once_with(client, settings)


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
        patch("app.services.telegram.net.apply_preferred_time_offset") as apply_offset,
    ):
        await connect_telegram_client(client, settings)

    client.connect.assert_awaited_once()
    measure.assert_not_awaited()
    apply_offset.assert_not_called()
