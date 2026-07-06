"""Tests for background FloodWait backoff on Telethon RPCs."""

from __future__ import annotations

import pytest
from telethon import errors

from app.services.telegram.net import call_with_flood_wait


@pytest.mark.asyncio
async def test_call_with_flood_wait_retries_after_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.telegram.net.asyncio.sleep", fake_sleep)

    attempts = 0

    async def factory() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise errors.FloodWaitError(request=None, capture=2)
        return "ok"

    result = await call_with_flood_wait(factory, max_retries=3, max_sleep_seconds=60.0)

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [2, 2]


@pytest.mark.asyncio
async def test_call_with_flood_wait_raises_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.telegram.net.asyncio.sleep", fake_sleep)

    async def factory() -> str:
        raise errors.FloodWaitError(request=None, capture=5)

    with pytest.raises(errors.FloodWaitError):
        await call_with_flood_wait(factory, max_retries=1, max_sleep_seconds=60.0)
