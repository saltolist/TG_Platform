"""Tests for real channel analytics: snapshots, overview v2, heatmap, subscribers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.db.models import ChannelMetricSnapshot, Post, Profile
from app.services.analytics.analytics_snapshot import (
    capture_channel_snapshot,
    load_snapshots,
    snapshot_slot,
)
from app.services.analytics.channel_metrics import (
    build_heatmap,
    build_overview,
    build_overview_from_history,
    subscriber_count_from_profile,
)
from app.services.telegram.channel_flow import extract_subscriber_count
from tests.conftest import TestSessionLocal, writer_user  # noqa: F401


def _published_post(post_id: str, *, date: str, views: str, reactions: int = 0) -> Post:
    return Post(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        position=0,
        data={
            "id": post_id,
            "status": "published",
            "text": f"Post {post_id}",
            "date": date,
            "metrics": {
                "views": views,
                "reposts": 0,
                "reactions": [{"emoji": "🔥", "count": reactions}] if reactions else [],
            },
            "comments": [],
        },
    )


def _snapshot(
    captured_at: datetime,
    *,
    views: int,
    subscribers: int | None = None,
    reactions: int = 0,
    comments: int = 0,
    reposts: int = 0,
    posts_count: int = 0,
    er: float = 0.0,
) -> ChannelMetricSnapshot:
    return ChannelMetricSnapshot(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        captured_at=captured_at,
        subscribers=subscribers,
        views=views,
        reactions=reactions,
        comments=comments,
        reposts=reposts,
        posts_count=posts_count,
        er=er,
    )


def test_subscriber_count_from_profile_parsing() -> None:
    assert subscriber_count_from_profile(None) is None
    assert subscriber_count_from_profile({}) is None
    assert subscriber_count_from_profile({"subscriberCount": None}) is None
    assert subscriber_count_from_profile({"subscriberCount": "123"}) == 123
    assert subscriber_count_from_profile({"subscriberCount": 0}) == 0
    assert subscriber_count_from_profile({"subscriberCount": -5}) is None


def test_extract_subscriber_count_reads_participants() -> None:
    full = SimpleNamespace(full_chat=SimpleNamespace(participants_count=321))
    assert extract_subscriber_count(full) == 321
    assert extract_subscriber_count(SimpleNamespace(full_chat=None)) is None
    assert extract_subscriber_count(SimpleNamespace()) is None


def test_build_overview_uses_real_subscribers_not_views_ratio() -> None:
    posts = [
        _published_post(
            "p1",
            date=datetime.now(timezone.utc).isoformat(),
            views="9 500",
        )
    ]
    overview = build_overview(posts, "7d", {"subscriberCount": 42})
    assert overview["endTotals"]["subscribers"] == 42
    assert overview["subscribersAvailable"] is True
    # Per-day subscriber deltas are unknown without snapshots.
    assert all(day["subscribers"] == 0 for day in overview["days"])

    hidden = build_overview(posts, "7d", None)
    assert hidden["endTotals"]["subscribers"] == 0
    assert hidden["subscribersAvailable"] is False


def test_build_heatmap_levels_and_empty_state() -> None:
    # 2026-06-29 is a Monday, 2026-06-30 is a Tuesday.
    posts = [
        _published_post("mon", date="2026-06-29T09:05:00+00:00", views="1 000"),
        _published_post("tue", date="2026-06-30T18:10:00+00:00", views="100"),
    ]
    heatmap = build_heatmap(posts, "all")
    assert heatmap["hasData"] is True
    assert heatmap["hours"] == ["09", "12", "15", "18", "21"]
    monday = next(row for row in heatmap["rows"] if row["day"] == "Пн")
    tuesday = next(row for row in heatmap["rows"] if row["day"] == "Вт")
    assert monday["values"][0] == 5  # busiest slot
    assert tuesday["values"][3] >= 2  # has data, scaled against peak
    # Slots without posts stay at the base level.
    assert monday["values"][1] == 1

    empty = build_heatmap([], "30d")
    assert empty["hasData"] is False
    assert all(value == 1 for row in empty["rows"] for value in row["values"])


def test_build_overview_from_history_daily_snapshot_deltas() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    snapshots = [
        _snapshot(yesterday.replace(hour=10, minute=0), views=100, subscribers=50),
        _snapshot(yesterday.replace(hour=23, minute=30), views=120, subscribers=52, er=3.0),
        _snapshot(now, views=150, subscribers=55, er=3.5),
    ]

    overview = build_overview_from_history(
        [], snapshots, "7d", {"subscriberCount": 55}
    )
    assert overview["version"] == 2
    assert overview["granularity"] == "day"
    assert overview["subscribersAvailable"] is True
    assert overview["endTotals"]["views"] == 150
    assert overview["endTotals"]["subscribers"] == 55

    today_row = overview["days"][-1]
    yesterday_row = overview["days"][-2]
    # First snapshot day has no baseline — growth is 0, not the absolute total.
    assert yesterday_row["views"] == 0
    assert today_row["views"] == 30
    assert today_row["subscribers"] == 3
    assert today_row["er"] == 3.5


def test_build_overview_from_history_24h_uses_30m_slots() -> None:
    now = datetime.now(timezone.utc)
    snapshots = [
        _snapshot(now - timedelta(hours=30), views=90, subscribers=48),
        _snapshot(now - timedelta(hours=2), views=100, subscribers=50),
        _snapshot(now - timedelta(hours=1), views=130, subscribers=51),
        _snapshot(now - timedelta(minutes=30), views=150, subscribers=52),
    ]

    overview = build_overview_from_history(
        [], snapshots, "24h", {"subscriberCount": 52}
    )
    assert overview["version"] == 2
    assert overview["granularity"] == "30m"
    assert overview["dayCount"] == 3
    assert [day["views"] for day in overview["days"]] == [10, 30, 20]
    assert overview["startTotals"]["views"] == 90
    assert overview["endTotals"]["views"] == 150


def test_build_overview_from_history_without_snapshots_falls_back() -> None:
    overview = build_overview_from_history([], [], "30d", None)
    assert overview["version"] == 2
    assert overview["granularity"] == "day"
    assert overview["historySource"] == "publish_backfill"
    assert "heatmap" in overview


class _FakeSnapshotClient:
    async def __call__(self, request) -> SimpleNamespace:  # noqa: ANN001
        return SimpleNamespace(full_chat=SimpleNamespace(participants_count=321))


@pytest.mark.asyncio
async def test_capture_channel_snapshot_upserts_slot(writer_user) -> None:  # noqa: F811
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "snap-post",
                    "status": "published",
                    "text": "Snapshot post",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "metrics": {
                        "views": "1 200",
                        "reposts": 4,
                        "reactions": [{"emoji": "🔥", "count": 10}],
                    },
                    "comments": [{"id": "c1", "author": "A", "date": "2026-07-01", "text": "hi"}],
                },
            )
        )
        session.add(Profile(user_id=user_id, telegram={"channelStatus": "connected"}))
        await session.commit()

    settings = get_settings()
    client = _FakeSnapshotClient()
    assert await capture_channel_snapshot(TestSessionLocal, user_id, client, object(), settings)
    # Same 30-minute slot — must upsert, not insert a second row.
    assert await capture_channel_snapshot(TestSessionLocal, user_id, client, object(), settings)

    async with TestSessionLocal() as session:
        snapshots = await load_snapshots(session, user_id)
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        assert snapshot.captured_at == snapshot_slot()
        assert snapshot.subscribers == 321
        assert snapshot.views == 1200
        assert snapshot.reactions == 10
        assert snapshot.comments == 1
        assert snapshot.reposts == 4
        assert snapshot.posts_count == 1

        profile = await session.get(Profile, user_id)
        assert profile is not None
        assert profile.telegram["subscriberCount"] == 321
        assert profile.telegram["subscriberCountAt"]
        assert profile.telegram["lastAnalyticsSnapshotAt"]
