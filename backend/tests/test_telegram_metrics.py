"""Tests for Telegram metrics extraction and channel analytics (Phase 3 / Step 5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.db.models import Post, Profile
from app.services.analytics.channel_metrics import build_overview, build_top_posts
from app.services.telegram.message_mapping import extract_metrics_from_message
from app.services.telegram.post_sync import update_telegram_post
from tests.conftest import TestSessionLocal, writer_auth_headers


def test_extract_metrics_from_message_maps_reactions_and_forwards() -> None:
    message = SimpleNamespace(
        views=1280,
        forwards=17,
        reactions=SimpleNamespace(
            results=[
                SimpleNamespace(count=4, reaction=SimpleNamespace(emoticon="🔥")),
                SimpleNamespace(count=2, reaction=SimpleNamespace(emoticon="❤️")),
            ]
        ),
    )

    metrics = extract_metrics_from_message(message)

    assert metrics == {
        "views": "1280",
        "reposts": 17,
        "reactions": [
            {"emoji": "🔥", "count": 4},
            {"emoji": "❤️", "count": 2},
        ],
    }


@pytest.mark.asyncio
async def test_update_telegram_post_persists_metrics_only_change() -> None:
    user_id = uuid.uuid4()
    async with TestSessionLocal() as db_session:
        db_session.add(Profile(user_id=user_id, telegram={}))
        post = Post(
        id=uuid.uuid4(),
        user_id=user_id,
        position=0,
        data={
            "id": "post-1",
            "status": "published",
            "text": "Same text",
            "telegramMessageId": "9001",
            "source": "telegram",
            "metrics": {"views": "10", "reposts": 0, "reactions": []},
        },
    )
        db_session.add(post)
        await db_session.commit()

        await update_telegram_post(
            db_session,
            user_id,
            {
                "telegramMessageId": "9001",
                "text": "Same text",
                "metrics": {
                    "views": "42",
                    "reposts": 3,
                    "reactions": [{"emoji": "👍", "count": 5}],
                },
            },
        )
        await db_session.refresh(post)

        assert post.data["metrics"]["views"] == "42"
        assert post.data["metrics"]["reposts"] == 3
        assert post.data["metrics"]["reactions"] == [{"emoji": "👍", "count": 5}]


@pytest.mark.asyncio
async def test_channel_analytics_endpoints(
    client: AsyncClient,
    writer_auth_headers: dict,
    writer_user,
) -> None:
    async with TestSessionLocal() as db_session:
        post = Post(
            id=uuid.uuid4(),
            user_id=writer_user.id,
        position=0,
        data={
            "id": "analytics-post",
            "status": "published",
            "text": "Analytics headline",
            "date": datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc).isoformat(),
            "metrics": {
                "views": "1 200",
                "reposts": 4,
                "reactions": [{"emoji": "🔥", "count": 10}],
            },
            "comments": [{"id": "c1", "author": "A", "date": "2026-06-28", "text": "hi"}],
            },
        )
        db_session.add(post)
        await db_session.commit()

    overview = await client.get(
        "/api/v1/analytics/overview/?period=30d",
        headers=writer_auth_headers,
    )
    assert overview.status_code == 200
    overview_body = overview.json()
    assert overview_body["endTotals"]["views"] == 1200
    assert overview_body["reactions"] == [{"emoji": "🔥", "count": 10}]

    top_posts = await client.get(
        "/api/v1/analytics/top-posts/?period=30d",
        headers=writer_auth_headers,
    )
    assert top_posts.status_code == 200
    rows = top_posts.json()["posts"]
    assert len(rows) == 1
    assert rows[0]["id"] == "analytics-post"
    assert rows[0]["views"] == 1200
    assert rows[0]["reactions"] == 10


def test_build_top_posts_sorts_by_views() -> None:
    posts = [
        Post(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            position=0,
            data={
                "id": "low",
                "status": "published",
                "text": "Low",
                "date": datetime(2026, 6, 20, tzinfo=timezone.utc).isoformat(),
                "metrics": {"views": "100", "reposts": 0, "reactions": []},
            },
        ),
        Post(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            position=1,
            data={
                "id": "high",
                "status": "published",
                "text": "High",
                "date": datetime(2026, 6, 25, tzinfo=timezone.utc).isoformat(),
                "metrics": {"views": "500", "reposts": 1, "reactions": []},
            },
        ),
    ]

    rows = build_top_posts(posts, "30d")
    assert [row["id"] for row in rows] == ["high", "low"]


def test_build_overview_aggregates_reactions() -> None:
    posts = [
        Post(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            position=0,
            data={
                "id": "p1",
                "status": "published",
                "text": "One",
                "date": datetime.now(timezone.utc).isoformat(),
                "metrics": {
                    "views": "200",
                    "reposts": 1,
                    "reactions": [{"emoji": "🔥", "count": 3}],
                },
            },
        )
    ]

    overview = build_overview(posts, "7d")
    assert overview["endTotals"]["views"] == 200
    assert overview["reactions"] == [{"emoji": "🔥", "count": 3}]
