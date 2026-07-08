"""Tests for per-post analytics trend."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import Post, PostMetricSnapshot
from app.services.analytics.post_metrics import build_post_trend


def _published_post(
    post_id: str,
    *,
    date: str,
    views: str,
    reactions: int = 0,
    comments: int = 0,
    db_id: uuid.UUID | None = None,
) -> Post:
    return Post(
        id=db_id or uuid.uuid4(),
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
            "comments": [{} for _ in range(comments)],
        },
    )


def _post_snapshot(
    post_id: uuid.UUID,
    captured_at: datetime,
    *,
    views: int,
    reactions: int = 0,
    comments: int = 0,
    reposts: int = 0,
) -> PostMetricSnapshot:
    return PostMetricSnapshot(
        id=uuid.uuid4(),
        post_id=post_id,
        user_id=uuid.uuid4(),
        captured_at=captured_at,
        views=views,
        reactions=reactions,
        comments=comments,
        reposts=reposts,
    )


def test_post_trend_no_history_zeros_days() -> None:
    now = datetime.now(timezone.utc)
    post = _published_post("p1", date=now.isoformat(), views="120", reactions=5)
    trend = build_post_trend(post, [], "7d", None)
    assert trend["historySource"] == "no_history"
    assert trend["endTotals"]["views"] == 120
    assert trend["endTotals"]["reactions"] == 5
    assert trend["subscribersAvailable"] is False
    assert all(day["views"] == 0 for day in trend["days"])


def test_post_trend_live_slot_reflects_growth_since_capture() -> None:
    now = datetime.now(timezone.utc)
    post_id = uuid.uuid4()
    post = _published_post(
        "p1",
        date=now.isoformat(),
        views="80",
        reactions=8,
        db_id=post_id,
    )
    snapshots = [
        _post_snapshot(post_id, now - timedelta(hours=3), views=50, reactions=3),
    ]

    trend = build_post_trend(post, snapshots, "24h", None)

    assert trend["granularity"] == "30m"
    assert trend["historySource"] == "post_snapshots"
    assert len(trend["days"]) == 2
    captured_row, live_row = trend["days"]
    assert captured_row["views"] == 50
    assert captured_row["reactions"] == 3
    assert live_row["views"] == 30
    assert live_row["reactions"] == 5
    assert live_row["er"] == 16.7


def test_post_trend_daily_uses_snapshot_history() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    post_id = uuid.uuid4()
    post = _published_post(
        "p1",
        date=yesterday.isoformat(),
        views="100",
        reactions=10,
        comments=5,
        db_id=post_id,
    )
    snapshots = [
        _post_snapshot(
            post_id,
            yesterday.replace(hour=12, minute=0),
            views=40,
            reactions=4,
            comments=2,
        ),
        _post_snapshot(
            post_id,
            now.replace(hour=10, minute=0),
            views=70,
            reactions=7,
            comments=3,
        ),
    ]

    trend = build_post_trend(post, snapshots, "7d", None)

    assert trend["historySource"] == "post_snapshots"
    assert trend["trackingSince"] == yesterday.date().isoformat()
    yesterday_row = trend["days"][-2]
    today_row = trend["days"][-1]
    assert yesterday_row["views"] == 40
    assert today_row["views"] == 60
    assert today_row["reactions"] == 6
