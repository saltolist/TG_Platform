"""Tests for Redis-backed Telegram sync SSE bridge."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.telegram import sync_events
from app.services.telegram.sync_events_redis import (
    publish_sync_event_to_redis,
    reset_sync_events_redis_storage,
    start_redis_sync_events_bridge,
)


@pytest.fixture(autouse=True)
async def _reset_redis_bridge() -> None:
    await reset_sync_events_redis_storage()
    yield
    await reset_sync_events_redis_storage()


@pytest.mark.asyncio
async def test_publish_sync_event_to_redis_publishes_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    published: list[tuple[str, str]] = []
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.publish = AsyncMock(side_effect=lambda ch, data: published.append((ch, data)))

    async def _fake_get_redis() -> AsyncMock:
        return mock_redis

    monkeypatch.setattr(
        "app.services.telegram.sync_events_redis._get_redis",
        _fake_get_redis,
    )

    payload = {"syncRevision": 3, "commentsRevision": 1, "metricsRevision": 0}
    await publish_sync_event_to_redis(user_id, payload)

    assert len(published) == 1
    channel, raw = published[0]
    assert channel == f"tg:sync-events:{user_id}"
    assert json.loads(raw) == payload


@pytest.mark.asyncio
async def test_redis_bridge_delivers_to_local_subscriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    stop_event = asyncio.Event()
    queue = await sync_events.subscribe_telegram_sync_events(user_id)

    messages: list[dict] = []

    class FakePubSub:
        def __init__(self) -> None:
            self._queue: asyncio.Queue[dict] = asyncio.Queue()

        async def psubscribe(self, *_patterns: str) -> None:
            return None

        async def punsubscribe(self, *_patterns: str) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def get_message(self, **_kwargs: object) -> dict | None:
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                return None

        def push(self, message: dict) -> None:
            self._queue.put_nowait(message)

    fake_pubsub = FakePubSub()
    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=fake_pubsub)

    async def _fake_get_redis() -> MagicMock:
        return mock_redis

    monkeypatch.setattr(
        "app.services.telegram.sync_events_redis._get_redis",
        _fake_get_redis,
    )

    bridge = asyncio.create_task(start_redis_sync_events_bridge(stop_event))
    await asyncio.sleep(0.05)

    payload = {"syncRevision": 9, "commentsRevision": 2, "metricsRevision": 1}
    fake_pubsub.push(
        {
            "type": "pmessage",
            "channel": f"tg:sync-events:{user_id}",
            "data": json.dumps(payload),
        }
    )
    await asyncio.sleep(0.1)
    stop_event.set()
    await bridge

    received = queue.get_nowait()
    assert received["syncRevision"] == 9
    assert received["commentsRevision"] == 2


@pytest.mark.asyncio
async def test_publish_telegram_sync_event_schedules_redis_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    publish_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.telegram.sync_events_redis.publish_sync_event_to_redis",
        publish_mock,
    )

    sync_events.publish_telegram_sync_event(
        user_id,
        {"syncRevision": 5, "commentsRevision": 0, "metricsRevision": 0},
    )
    await asyncio.sleep(0.05)
    publish_mock.assert_awaited_once()
