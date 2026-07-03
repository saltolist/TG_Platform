"""Tests for lightweight Telegram metrics sync (reactions poll + live updates)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.db.models import Post, Profile
from app.services.telegram.metrics_flow import (
    MetricsThrottleBuffer,
    extract_reactions_list,
    handle_live_message_reactions,
    persist_metrics_for_message_ids,
    poll_recent_post_metrics,
)
from tests.conftest import TestSessionLocal, writer_user


def test_extract_reactions_list_maps_emoticons() -> None:
    reactions = SimpleNamespace(
        results=[
            SimpleNamespace(count=3, reaction=SimpleNamespace(emoticon="🔥")),
            SimpleNamespace(count=0, reaction=SimpleNamespace(emoticon="❤️")),
        ]
    )
    assert extract_reactions_list(reactions) == [{"emoji": "🔥", "count": 3}]


@pytest.mark.asyncio
async def test_handle_live_message_reactions_updates_metrics(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        post = Post(
            id=post_id,
            user_id=user_id,
            position=0,
            data={
                "id": "post-r",
                "status": "published",
                "text": "Hello",
                "telegramMessageId": "55",
                "source": "telegram",
                "metrics": {"views": "10", "reposts": 0, "reactions": []},
            },
        )
        session.add(post)
        await session.commit()

    message = SimpleNamespace(
        id=55,
        message="Hello",
        date=None,
        views=99,
        forwards=2,
        reactions=SimpleNamespace(
            results=[
                SimpleNamespace(count=4, reaction=SimpleNamespace(emoticon="👍")),
            ]
        ),
        media=None,
    )
    get_calls: list[list[int]] = []

    class FakeClient:
        async def get_messages(self, entity: object, ids: int | list[int]) -> SimpleNamespace:
            id_list = [ids] if isinstance(ids, int) else list(ids)
            get_calls.append(id_list)
            if len(id_list) == 1:
                return message
            return [message]

    update = SimpleNamespace(
        msg_id=55,
        reactions=SimpleNamespace(
            results=[
                SimpleNamespace(count=4, reaction=SimpleNamespace(emoticon="👍")),
            ]
        ),
    )

    buffer = MetricsThrottleBuffer(
        FakeClient(),
        object(),
        user_id,
        TestSessionLocal,
        min_interval_seconds=0,
    )
    await handle_live_message_reactions(update, buffer)

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["views"] == "10"
        assert refreshed.data["metrics"]["reactions"] == [{"emoji": "👍", "count": 4}]
        profile = await session.get(Profile, user_id)
        assert profile is not None
        assert int(profile.telegram.get("metricsRevision") or 0) == 1
    assert get_calls == []


@pytest.mark.asyncio
async def test_metrics_throttle_coalesces_burst_into_one_batch(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        post = Post(
            id=post_id,
            user_id=user_id,
            position=0,
            data={
                "id": "post-t",
                "status": "published",
                "text": "Throttle",
                "telegramMessageId": "88",
                "source": "telegram",
                "metrics": {"views": "1", "reposts": 0, "reactions": []},
            },
        )
        session.add(post)
        await session.commit()

    message = SimpleNamespace(
        id=88,
        message="Throttle",
        date=None,
        views=200,
        forwards=0,
        reactions=SimpleNamespace(
            results=[
                SimpleNamespace(count=9, reaction=SimpleNamespace(emoticon="🔥")),
            ]
        ),
        media=None,
    )
    get_calls: list[list[int]] = []

    class FakeClient:
        async def get_messages(self, entity: object, ids: list[int]) -> list[SimpleNamespace]:
            get_calls.append(list(ids))
            return [message]

    buffer = MetricsThrottleBuffer(
        FakeClient(),
        object(),
        user_id,
        TestSessionLocal,
        min_interval_seconds=0.2,
    )
    for _ in range(5):
        await buffer.mark_dirty(88)
    await asyncio.sleep(0.35)

    assert len(get_calls) == 1
    assert get_calls[0] == [88]

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["views"] == "200"


@pytest.mark.asyncio
async def test_poll_recent_post_metrics_batch(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        post = Post(
            id=post_id,
            user_id=user_id,
            position=0,
            data={
                "id": "post-p",
                "status": "published",
                "text": "Poll me",
                "telegramMessageId": "77",
                "source": "telegram",
                "metrics": {"views": "1", "reposts": 0, "reactions": []},
            },
        )
        session.add(post)
        await session.commit()

    message = SimpleNamespace(
        id=77,
        message="Poll me",
        date=None,
        views=500,
        forwards=0,
        reactions=SimpleNamespace(results=[]),
        media=None,
    )

    class FakeClient:
        async def get_messages(self, entity: object, ids: list[int]) -> list[SimpleNamespace]:
            return [message]

    settings = Settings(telegram_metrics_poll_window=5)
    updated = await poll_recent_post_metrics(
        FakeClient(),
        object(),
        user_id,
        settings,
        TestSessionLocal,
    )
    assert updated == 1

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["views"] == "500"


@pytest.mark.asyncio
async def test_persist_metrics_for_message_ids_single_commit(writer_user) -> None:
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "a",
                    "status": "published",
                    "text": "A",
                    "telegramMessageId": "1",
                    "source": "telegram",
                    "metrics": {"views": "1", "reposts": 0, "reactions": []},
                },
            )
        )
        await session.commit()

    messages = [
        SimpleNamespace(
            id=1,
            message="A",
            date=None,
            views=10,
            forwards=0,
            reactions=SimpleNamespace(results=[]),
            media=None,
        ),
    ]

    class FakeClient:
        async def get_messages(self, entity: object, ids: list[int]) -> list[SimpleNamespace]:
            return messages

    count = await persist_metrics_for_message_ids(
        FakeClient(),
        object(),
        user_id,
        [1],
        TestSessionLocal,
    )
    assert count == 1


@pytest.mark.asyncio
async def test_reaction_flush_can_skip_telegram_rpc(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        session.add(
            Post(
                id=post_id,
                user_id=user_id,
                position=0,
                data={
                    "id": "rx",
                    "status": "published",
                    "text": "Rx",
                    "telegramMessageId": "91",
                    "source": "telegram",
                    "metrics": {"views": "5", "reposts": 0, "reactions": []},
                },
            )
        )
        await session.commit()

    get_calls: list[Any] = []

    class FakeClient:
        async def get_messages(self, entity: object, ids: list[int]) -> list[Any]:
            get_calls.append(ids)
            return []

    update = SimpleNamespace(
        msg_id=91,
        reactions=SimpleNamespace(
            results=[SimpleNamespace(count=2, reaction=SimpleNamespace(emoticon="🔥"))]
        ),
    )

    updated = await persist_metrics_for_message_ids(
        FakeClient(),
        object(),
        user_id,
        [91],
        TestSessionLocal,
        reaction_updates={91: update},
    )
    assert updated == 1
    assert get_calls == []

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["reactions"] == [{"emoji": "🔥", "count": 2}]


@pytest.mark.asyncio
async def test_live_channel_message_forwards_updates_reposts(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        session.add(
            Post(
                id=post_id,
                user_id=user_id,
                position=0,
                data={
                    "id": "fwd",
                    "status": "published",
                    "text": "Shared",
                    "telegramMessageId": "12",
                    "source": "telegram",
                    "metrics": {"views": "10", "reposts": 0, "reactions": []},
                },
            )
        )
        await session.commit()

    from app.services.telegram.metrics_flow import handle_live_channel_message_forwards

    entity = SimpleNamespace(id=12345, broadcast=True)
    update = SimpleNamespace(channel_id=12345, id=12, forwards=3)

    await handle_live_channel_message_forwards(
        update, entity, user_id, TestSessionLocal
    )

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["reposts"] == 3


@pytest.mark.asyncio
async def test_live_channel_message_views_updates_views(writer_user) -> None:
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        if await session.get(Profile, user_id) is None:
            session.add(Profile(user_id=user_id, telegram={}))
        session.add(
            Post(
                id=post_id,
                user_id=user_id,
                position=0,
                data={
                    "id": "vw",
                    "status": "published",
                    "text": "Seen",
                    "telegramMessageId": "13",
                    "source": "telegram",
                    "metrics": {"views": "1", "reposts": 0, "reactions": []},
                },
            )
        )
        await session.commit()

    from app.services.telegram.metrics_flow import handle_live_channel_message_views

    entity = SimpleNamespace(id=99, broadcast=True)
    update = SimpleNamespace(channel_id=99, id=13, views=420)

    await handle_live_channel_message_views(
        update, entity, user_id, TestSessionLocal
    )

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        assert refreshed.data["metrics"]["views"] == "420"
