"""Tests for Telegram sync SSE (revision push to the frontend)."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.db.models import Profile
from app.services.telegram.post_sync import touch_telegram_profile
from app.services.telegram.sync_events import (
    publish_telegram_sync_event,
    stream_telegram_sync_events,
    subscribe_telegram_sync_events,
    telegram_sync_event_payload,
    unsubscribe_telegram_sync_events,
)
from tests.conftest import TestSessionLocal, writer_user


def parse_sse_meta_events(body: str) -> list[dict]:
    events: list[dict] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = json.loads(block[6:])
        meta = payload.get("meta")
        if isinstance(meta, dict):
            events.append(meta)
    return events


def test_telegram_sync_event_payload_defaults() -> None:
    payload = telegram_sync_event_payload({})
    assert payload["syncRevision"] == 0
    assert payload["commentsRevision"] == 0
    assert payload["metricsRevision"] == 0
    assert payload["syncStatus"] == "idle"


@pytest.mark.asyncio
async def test_publish_telegram_sync_event_notifies_subscriber(writer_user) -> None:
    user_id = writer_user.id
    queue = await subscribe_telegram_sync_events(user_id)
    try:
        publish_telegram_sync_event(
            user_id,
            {
                "syncRevision": 3,
                "commentsRevision": 1,
                "metricsRevision": 2,
                "lastSync": "2026-01-01T00:00:00+00:00",
                "syncStatus": "listening",
                "syncError": "",
            },
        )
        payload = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert payload["syncRevision"] == 3
        assert payload["commentsRevision"] == 1
        assert payload["metricsRevision"] == 2
    finally:
        await unsubscribe_telegram_sync_events(user_id, queue)


@pytest.mark.asyncio
async def test_touch_telegram_profile_publishes_sync_event(writer_user) -> None:
    user_id = writer_user.id
    queue = await subscribe_telegram_sync_events(user_id)
    try:
        async with TestSessionLocal() as session:
            profile = await session.get(Profile, user_id)
            if profile is None:
                profile = Profile(user_id=user_id, telegram={"syncRevision": 0})
                session.add(profile)
                await session.flush()
            await touch_telegram_profile(session, profile, last_message_id="42")
            await session.commit()

        payload = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert payload["syncRevision"] == 1
        assert payload["syncStatus"] == "listening"
    finally:
        await unsubscribe_telegram_sync_events(user_id, queue)


@pytest.mark.asyncio
async def test_stream_telegram_sync_events_yields_initial_meta(writer_user) -> None:
    user_id = writer_user.id
    stream = stream_telegram_sync_events(
        user_id,
        {
            "syncRevision": 7,
            "commentsRevision": 2,
            "metricsRevision": 4,
            "lastSync": "2026-07-06T12:00:00+00:00",
            "syncStatus": "listening",
        },
    )
    first = await stream.__anext__()
    events = parse_sse_meta_events(first)
    assert events[0]["syncRevision"] == 7
    assert events[0]["commentsRevision"] == 2
    await stream.aclose()


@pytest.mark.asyncio
async def test_profile_telegram_sync_events_sse_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/profile/telegram/sync-events/")
    assert response.status_code == 401
