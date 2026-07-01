"""Tests for effective live-sync status exposed via profile API."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.telegram.live_sync_worker import (
    apply_effective_sync_fields,
    effective_sync_status,
    listener_registry,
)


def test_effective_sync_status_idle_when_listener_not_running() -> None:
    user_id = uuid4()
    telegram = {
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "sessionString": "x",
        "importStatus": "done",
        "syncStatus": "listening",
        "syncError": "",
    }
    status, error = effective_sync_status(telegram, user_id)
    assert status == "idle"
    assert error == ""


def test_apply_effective_sync_fields_overrides_stale_listening() -> None:
    user_id = uuid4()
    telegram = {
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "sessionString": "x",
        "importStatus": "done",
        "syncStatus": "listening",
        "syncError": "old",
    }
    result = apply_effective_sync_fields(telegram, user_id)
    assert result["syncStatus"] == "idle"
    assert result["syncError"] == "old"


@pytest.mark.asyncio
async def test_effective_sync_status_listening_when_task_running() -> None:
    user_id = uuid4()

    async def _hang() -> None:
        await asyncio.Event().wait()

    listener_registry._tasks[user_id] = asyncio.create_task(_hang())
    listener_registry._stop_events[user_id] = asyncio.Event()
    try:
        telegram = {
            "channelStatus": "connected",
            "syncMode": "history-and-live",
            "sessionString": "x",
            "importStatus": "done",
            "syncStatus": "idle",
            "syncError": "stale",
        }
        status, error = effective_sync_status(telegram, user_id)
        assert status == "listening"
        assert error == ""
    finally:
        listener_registry.stop_user_listener(user_id)
