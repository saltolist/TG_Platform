"""Tests for real channel analytics: snapshots, overview v2, heatmap, subscribers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import get_settings
from app.db.models import ChannelMetricSnapshot, Post, PostMetricSnapshot, Profile, User
from app.services.analytics.analytics_snapshot import (
    capture_metrics_snapshot,
    load_post_snapshots,
    load_snapshots,
    snapshot_slot,
)
from app.services.analytics.channel_metrics import (
    build_heatmap,
    build_overview_from_history,
    subscriber_count_from_profile,
)
from app.services.telegram.channel_flow import extract_subscriber_count
from app.tasks import analytics_snapshot as analytics_snapshot_task
from tests.conftest import TestSessionLocal, writer_user  # noqa: F401


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


def test_build_overview_no_history_uses_live_subscribers_and_zeroed_days() -> None:
    posts = [
        _published_post(
            "p1",
            date=datetime.now(timezone.utc).isoformat(),
            views="9 500",
        )
    ]
    overview = build_overview_from_history(posts, [], [], "7d", {"subscriberCount": 42})
    assert overview["historySource"] == "no_history"
    assert overview["trackingSince"] is None
    assert overview["endTotals"]["subscribers"] == 42
    assert overview["subscribersAvailable"] is True
    assert all(day["views"] == 0 for day in overview["days"])

    hidden = build_overview_from_history(posts, [], [], "7d", None)
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


def test_build_overview_from_history_legacy_channel_snapshot_deltas() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    # Today's row is always rebuilt from live posts, so the fixture posts must
    # match the last snapshot's totals (150 views) for the deltas to line up.
    posts = [_published_post("p1", date=now.isoformat(), views="150")]
    snapshots = [
        _snapshot(yesterday.replace(hour=10, minute=0), views=100, subscribers=50),
        _snapshot(yesterday.replace(hour=23, minute=30), views=120, subscribers=52, er=3.0),
        _snapshot(now, views=150, subscribers=55, er=3.5),
    ]

    overview = build_overview_from_history(
        posts, snapshots, [], "7d", {"subscriberCount": 55}
    )
    assert overview["version"] == 2
    assert overview["granularity"] == "day"
    assert overview["historySource"] == "legacy_channel_snapshots"
    assert overview["subscribersAvailable"] is True
    assert overview["endTotals"]["views"] == 150
    assert overview["endTotals"]["subscribers"] == 55

    today_row = overview["days"][-1]
    yesterday_row = overview["days"][-2]
    # "Yesterday" is the first day with any snapshot in this window — no earlier
    # baseline exists, so growth is counted from zero (not silently zeroed out).
    assert yesterday_row["views"] == 120
    assert today_row["views"] == 30
    assert today_row["subscribers"] == 3
    # Today's ER is recomputed from today's own delta (30 views, 0 reactions),
    # not the snapshot's stored level — the fixture post has no reactions.
    assert today_row["er"] == 0.0


def test_build_overview_from_history_legacy_first_day_counts_grow_from_zero() -> None:
    """Regression: counts must grow from an implicit zero baseline, like ER already did.

    Previously ``_delta_row`` returned 0 for every count metric whenever no
    earlier snapshot existed in range (the first tracked day), while ``er``
    (a level, not a delta) still showed a real number — making it look like
    only ER was "growing" while views/reactions stayed flat.
    """
    now = datetime.now(timezone.utc)
    posts = [_published_post("p1", date=now.isoformat(), views="35", reactions=3)]
    snapshots = [
        _snapshot(now, views=35, reactions=3, er=8.6),
    ]

    overview = build_overview_from_history(posts, snapshots, [], "7d", {"subscriberCount": 1})

    only_row = overview["days"][-1]
    assert only_row["views"] == 35
    assert only_row["reactions"] == 3
    assert only_row["er"] == 8.6


def test_build_overview_from_history_24h_uses_30m_slots() -> None:
    now = datetime.now(timezone.utc)
    # The current slot is always rebuilt live, so give it a matching post —
    # 150 views, i.e. no further growth since the last captured snapshot.
    posts = [_published_post("p1", date=now.isoformat(), views="150")]
    snapshots = [
        _snapshot(now - timedelta(hours=30), views=90, subscribers=48),
        _snapshot(now - timedelta(hours=2), views=100, subscribers=50),
        _snapshot(now - timedelta(hours=1), views=130, subscribers=51),
        _snapshot(now - timedelta(minutes=30), views=150, subscribers=52),
    ]

    overview = build_overview_from_history(
        posts, snapshots, [], "24h", {"subscriberCount": 52}
    )
    assert overview["version"] == 2
    assert overview["granularity"] == "30m"
    assert overview["dayCount"] == 4
    assert overview["historySource"] == "legacy_channel_snapshots"
    assert [day["views"] for day in overview["days"]] == [10, 30, 20, 0]
    assert overview["startTotals"]["views"] == 90
    assert overview["endTotals"]["views"] == 150


def test_build_overview_from_history_without_snapshots_returns_no_history() -> None:
    overview = build_overview_from_history([], [], [], "30d", None)
    assert overview["version"] == 2
    assert overview["granularity"] == "day"
    assert overview["historySource"] == "no_history"
    assert overview["trackingSince"] is None
    assert "heatmap" in overview


def test_build_overview_end_totals_always_from_live_posts() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    snapshots = [
        _snapshot(yesterday.replace(hour=10, minute=0), views=100, reactions=5),
        _snapshot(now.replace(hour=10, minute=0), views=120, reactions=5),
    ]
    posts = [
        _published_post("p1", date=now.isoformat(), views="150", reactions=12),
    ]

    overview = build_overview_from_history(posts, snapshots, [], "7d", None)

    assert overview["endTotals"]["views"] == 150
    assert overview["endTotals"]["reactions"] == 12


def test_post_snapshot_new_post_shows_full_growth_from_zero() -> None:
    now = datetime.now(timezone.utc)
    post_id = uuid.uuid4()
    posts = [
        _published_post(
            "new-post",
            date=now.isoformat(),
            views="50",
            reactions=4,
            db_id=post_id,
        )
    ]
    post_snapshots = [
        _post_snapshot(post_id, now.replace(hour=12, minute=0), views=50, reactions=4),
    ]

    overview = build_overview_from_history(posts, [], post_snapshots, "7d", None)

    assert overview["historySource"] == "post_snapshots"
    today_row = overview["days"][-1]
    assert today_row["views"] == 50
    assert today_row["reactions"] == 4


def test_overview_current_slot_reflects_live_growth_since_last_capture() -> None:
    """The current bucket is always rebuilt from live posts, not the stale last capture.

    Simulates a post-snapshot capture that ran a few hours ago, followed by
    more live growth that hasn't been captured yet — the chart's current slot
    must show that live growth immediately, without waiting for another
    scheduled capture.
    """
    now = datetime.now(timezone.utc)
    post_id = uuid.uuid4()
    posts = [
        _published_post("p1", date=now.isoformat(), views="80", reactions=8, db_id=post_id)
    ]
    post_snapshots = [
        _post_snapshot(post_id, now - timedelta(hours=3), views=50, reactions=3),
    ]

    overview = build_overview_from_history(posts, [], post_snapshots, "24h", None)

    assert overview["granularity"] == "30m"
    assert len(overview["days"]) == 2
    captured_row, live_row = overview["days"]
    # The historical capture keeps its own recorded delta...
    assert captured_row["views"] == 50
    assert captured_row["reactions"] == 3
    # ...while the current slot reflects growth that happened since, live.
    assert live_row["views"] == 30
    assert live_row["reactions"] == 5
    # ER must be recomputed from *this slot's* delta (5/30), not swapped out
    # for the channel's cumulative level (8/80 = 10.0) — mixing the two would
    # put this bar on a different scale than every other bar in the series.
    assert live_row["er"] == 16.7
    assert overview["endTotals"]["views"] == 80


def test_build_overview_from_history_mixed_legacy_and_post_snapshots() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    post_id = uuid.uuid4()
    posts = [_published_post("p1", date=now.isoformat(), views="80", db_id=post_id)]

    channel_snapshots = [
        _snapshot(yesterday.replace(hour=12, minute=0), views=100, subscribers=40),
        _snapshot(yesterday.replace(hour=23, minute=0), views=110, subscribers=41),
    ]
    post_snapshots = [
        _post_snapshot(post_id, now.replace(hour=12, minute=0), views=80),
    ]

    overview = build_overview_from_history(
        posts, channel_snapshots, post_snapshots, "7d", {"subscriberCount": 41}
    )

    assert overview["historySource"] == "mixed"
    assert overview["trackingSince"] == yesterday.date().isoformat()


def test_post_snapshot_er_recomputed_from_daily_deltas() -> None:
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    post_id = uuid.uuid4()
    posts = [
        _published_post(
            "p1", date=now.isoformat(), views="100", reactions=10, comments=5, db_id=post_id
        )
    ]
    post_snapshots = [
        _post_snapshot(post_id, yesterday.replace(hour=12, minute=0), views=0, reactions=0),
        _post_snapshot(post_id, now.replace(hour=12, minute=0), views=100, reactions=10, comments=5),
    ]

    overview = build_overview_from_history(posts, [], post_snapshots, "7d", None)
    today_row = overview["days"][-1]
    assert today_row["views"] == 100
    assert today_row["reactions"] == 10
    assert today_row["comments"] == 5
    assert today_row["er"] == 15.0


@pytest.mark.asyncio
async def test_capture_metrics_snapshot_publishes_sync_event(writer_user) -> None:  # noqa: F811
    from app.services.telegram.sync_events import subscribe_telegram_sync_events, unsubscribe_telegram_sync_events

    user_id = writer_user.id
    queue = await subscribe_telegram_sync_events(user_id)
    try:
        async with TestSessionLocal() as session:
            session.add(
                Post(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    position=0,
                    data={
                        "id": "snap-event-post",
                        "status": "published",
                        "text": "Snapshot post",
                        "date": datetime.now(timezone.utc).isoformat(),
                        "metrics": {"views": "100", "reposts": 0, "reactions": []},
                        "comments": [],
                    },
                )
            )
            session.add(Profile(user_id=user_id, telegram={"channelStatus": "connected"}))
            await session.commit()

        settings = get_settings()
        client = _FakeSnapshotClient()
        assert await capture_metrics_snapshot(
            TestSessionLocal, user_id, client, object(), settings
        )

        payload = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert payload["metricsRevision"] == 1
        assert payload["channelStatus"] == "connected"
    finally:
        await unsubscribe_telegram_sync_events(user_id, queue)


class _FakeSnapshotClient:
    async def __call__(self, request) -> SimpleNamespace:  # noqa: ANN001
        return SimpleNamespace(full_chat=SimpleNamespace(participants_count=321))


@pytest.mark.asyncio
async def test_capture_metrics_snapshot_upserts_slot(writer_user) -> None:  # noqa: F811
    user_id = writer_user.id
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=post_id,
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
    assert await capture_metrics_snapshot(TestSessionLocal, user_id, client, object(), settings)
    # Same 30-minute slot — must upsert, not insert a second row.
    assert await capture_metrics_snapshot(TestSessionLocal, user_id, client, object(), settings)

    async with TestSessionLocal() as session:
        channel_snapshots = await load_snapshots(session, user_id)
        assert len(channel_snapshots) == 1
        snapshot = channel_snapshots[0]
        assert snapshot.captured_at == snapshot_slot()
        assert snapshot.subscribers == 321
        assert snapshot.views == 1200
        assert snapshot.reactions == 10
        assert snapshot.comments == 1
        assert snapshot.reposts == 4
        assert snapshot.posts_count == 1

        post_snapshots = await load_post_snapshots(session, user_id)
        assert len(post_snapshots) == 1
        post_snapshot = post_snapshots[0]
        assert post_snapshot.post_id == post_id
        assert post_snapshot.views == 1200
        assert post_snapshot.reactions == 10
        assert post_snapshot.comments == 1
        assert post_snapshot.reposts == 4

        profile = await session.get(Profile, user_id)
        assert profile is not None
        assert profile.telegram["subscriberCount"] == 321
        assert profile.telegram["subscriberCountAt"]
        assert profile.telegram["lastAnalyticsSnapshotAt"]


@pytest.mark.asyncio
async def test_capture_metrics_snapshot_db_only_when_client_missing(writer_user) -> None:  # noqa: F811
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=uuid.uuid4(),
                user_id=user_id,
                position=0,
                data={
                    "id": "db-only-post",
                    "status": "published",
                    "text": "DB only",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "metrics": {"views": "42", "reposts": 0, "reactions": []},
                    "comments": [],
                },
            )
        )
        session.add(Profile(user_id=user_id, telegram={"channelStatus": "connected"}))
        await session.commit()

    settings = get_settings()
    assert await capture_metrics_snapshot(
        TestSessionLocal, user_id, None, None, settings
    )

    async with TestSessionLocal() as session:
        snapshots = await load_snapshots(session, user_id)
        assert len(snapshots) == 1
        assert snapshots[0].subscribers is None
        assert snapshots[0].views == 42
        post_snapshots = await load_post_snapshots(session, user_id)
        assert len(post_snapshots) == 1


@pytest.mark.asyncio
async def test_capture_all_channel_snapshots_processes_connected_channels(
    writer_user, monkeypatch
) -> None:  # noqa: F811
    user_id = writer_user.id
    other_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        session.add(User(id=other_id, email=f"other-{other_id}@example.com", password_hash="x"))
        await session.flush()
        session.add(
            Profile(
                user_id=user_id,
                telegram={"channelStatus": "connected", "syncMode": "publish-only"},
            )
        )
        session.add(
            Profile(
                user_id=other_id,
                telegram={"channelStatus": "disconnected"},
            )
        )
        await session.commit()

    captured: list[uuid.UUID] = []

    async def fake_capture_for_user(uid: uuid.UUID, settings) -> None:  # noqa: ANN001
        captured.append(uid)

    monkeypatch.setattr(analytics_snapshot_task, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(analytics_snapshot_task, "_capture_for_user", fake_capture_for_user)
    await analytics_snapshot_task._capture_all_channel_snapshots()

    assert user_id in captured
    assert other_id not in captured


@pytest.mark.asyncio
async def test_capture_all_channel_snapshots_continues_after_failure(
    writer_user, monkeypatch
) -> None:  # noqa: F811
    user_id = writer_user.id
    other_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        session.add(User(id=other_id, email=f"other2-{other_id}@example.com", password_hash="x"))
        await session.flush()
        session.add(Profile(user_id=user_id, telegram={"channelStatus": "connected"}))
        session.add(Profile(user_id=other_id, telegram={"channelStatus": "connected"}))
        await session.commit()

    captured: list[uuid.UUID] = []

    async def fake_capture_for_user(uid: uuid.UUID, settings) -> None:  # noqa: ANN001
        if uid == user_id:
            raise RuntimeError("telethon down")
        captured.append(uid)

    monkeypatch.setattr(analytics_snapshot_task, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(analytics_snapshot_task, "_capture_for_user", fake_capture_for_user)
    await analytics_snapshot_task._capture_all_channel_snapshots()

    assert other_id in captured
    assert user_id not in captured


def test_subscriber_refresh_due_when_missing_or_stale() -> None:
    settings = get_settings()
    assert analytics_snapshot_task._subscriber_refresh_due({}, settings) is True
    assert (
        analytics_snapshot_task._subscriber_refresh_due(
            {"subscriberCountAt": "not-a-date"},
            settings,
        )
        is True
    )
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert (
        analytics_snapshot_task._subscriber_refresh_due(
            {"subscriberCountAt": stale},
            settings,
        )
        is True
    )
    fresh = datetime.now(timezone.utc).isoformat()
    assert (
        analytics_snapshot_task._subscriber_refresh_due(
            {"subscriberCountAt": fresh},
            settings,
        )
        is False
    )


def test_log_if_snapshot_overdue_warns_when_stale(caplog: pytest.LogCaptureFixture) -> None:
    settings = get_settings()
    interval = settings.telegram_analytics_snapshot_seconds
    stale_at = (
        datetime.now(timezone.utc)
        - timedelta(seconds=interval * analytics_snapshot_task._MISSED_SNAPSHOT_MULTIPLIER + 60)
    ).isoformat()
    profile = Profile(
        user_id=uuid.uuid4(),
        telegram={"channelStatus": "connected", "lastAnalyticsSnapshotAt": stale_at},
    )

    with caplog.at_level("WARNING"):
        analytics_snapshot_task._log_if_snapshot_overdue(
            profile,
            settings,
            datetime.now(timezone.utc),
        )

    assert any("Analytics snapshot overdue" in record.message for record in caplog.records)


def test_log_if_snapshot_overdue_silent_when_fresh(caplog: pytest.LogCaptureFixture) -> None:
    settings = get_settings()
    fresh_at = datetime.now(timezone.utc).isoformat()
    profile = Profile(
        user_id=uuid.uuid4(),
        telegram={"channelStatus": "connected", "lastAnalyticsSnapshotAt": fresh_at},
    )

    with caplog.at_level("WARNING"):
        analytics_snapshot_task._log_if_snapshot_overdue(
            profile,
            settings,
            datetime.now(timezone.utc),
        )

    assert not any("Analytics snapshot overdue" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_capture_for_user_skips_telethon_when_subscriber_fresh(
    writer_user, monkeypatch
) -> None:  # noqa: F811
    user_id = writer_user.id
    fresh_at = datetime.now(timezone.utc).isoformat()
    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=user_id,
                telegram={
                    "channelStatus": "connected",
                    "subscriberCountAt": fresh_at,
                    "subscriberCount": 100,
                },
            )
        )
        await session.commit()

    def fail_if_called(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("Telethon client should not be built when subscriber is fresh")

    captured: list[tuple[Any | None, Any | None]] = []

    async def fake_capture(_factory, uid, client, entity, settings) -> bool:  # noqa: ANN001
        captured.append((client, entity))
        return True

    monkeypatch.setattr(analytics_snapshot_task, "build_client", fail_if_called)
    monkeypatch.setattr(analytics_snapshot_task, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(analytics_snapshot_task, "capture_metrics_snapshot", fake_capture)

    await analytics_snapshot_task._capture_for_user(user_id, get_settings())

    assert len(captured) == 1
    assert captured[0] == (None, None)


@pytest.mark.asyncio
async def test_capture_for_user_polls_before_capture_when_subscriber_stale(
    writer_user, monkeypatch
) -> None:  # noqa: F811
    user_id = writer_user.id
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=user_id,
                telegram={
                    "channelStatus": "connected",
                    "channel": "@testchannel",
                    "sessionString": "enc:test",
                    "subscriberCountAt": stale_at,
                },
            )
        )
        await session.commit()

    call_order: list[str] = []
    fake_entity = object()

    async def fake_connect(client, settings) -> None:  # noqa: ANN001
        call_order.append("connect")

    async def fake_resolve(client, parsed, settings):  # noqa: ANN001
        call_order.append("resolve")
        return fake_entity

    async def fake_poll(client, entity, uid, settings, factory) -> int:  # noqa: ANN001
        call_order.append("poll")
        return 0

    async def fake_capture(_factory, uid, client, entity, settings) -> bool:  # noqa: ANN001
        call_order.append("capture")
        return True

    async def fake_disconnect(client) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(analytics_snapshot_task, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(analytics_snapshot_task, "connect_telegram_client", fake_connect)
    monkeypatch.setattr(analytics_snapshot_task, "resolve_channel_entity", fake_resolve)
    monkeypatch.setattr(analytics_snapshot_task, "require_api_credentials", lambda t, s: (1, "hash"))
    monkeypatch.setattr(analytics_snapshot_task, "decrypt_field", lambda v, s: "session")
    monkeypatch.setattr(analytics_snapshot_task, "parse_channel_input", lambda v: object())
    monkeypatch.setattr(analytics_snapshot_task, "disconnect_safely", fake_disconnect)
    monkeypatch.setattr(analytics_snapshot_task, "poll_recent_post_metrics", fake_poll)
    monkeypatch.setattr(analytics_snapshot_task, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(analytics_snapshot_task, "capture_metrics_snapshot", fake_capture)

    await analytics_snapshot_task._capture_for_user(user_id, get_settings())

    assert call_order == ["connect", "resolve", "poll", "capture"]


@pytest.mark.asyncio
async def test_capture_for_user_continues_when_poll_fails(
    writer_user, monkeypatch
) -> None:  # noqa: F811
    user_id = writer_user.id
    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=user_id,
                telegram={
                    "channelStatus": "connected",
                    "channel": "@testchannel",
                    "sessionString": "enc:test",
                },
            )
        )
        await session.commit()

    captured: list[bool] = []

    async def fail_poll(*_args, **_kwargs) -> int:  # noqa: ANN001
        raise RuntimeError("poll failed")

    async def fake_capture(_factory, uid, client, entity, settings) -> bool:  # noqa: ANN001
        captured.append(True)
        return True

    async def fake_connect(client, settings) -> None:  # noqa: ANN001
        pass

    async def fake_resolve(client, parsed, settings):  # noqa: ANN001
        return object()

    async def fake_disconnect(client) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(analytics_snapshot_task, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(analytics_snapshot_task, "connect_telegram_client", fake_connect)
    monkeypatch.setattr(analytics_snapshot_task, "resolve_channel_entity", fake_resolve)
    monkeypatch.setattr(analytics_snapshot_task, "require_api_credentials", lambda t, s: (1, "hash"))
    monkeypatch.setattr(analytics_snapshot_task, "decrypt_field", lambda v, s: "session")
    monkeypatch.setattr(analytics_snapshot_task, "parse_channel_input", lambda v: object())
    monkeypatch.setattr(analytics_snapshot_task, "disconnect_safely", fake_disconnect)
    monkeypatch.setattr(analytics_snapshot_task, "poll_recent_post_metrics", fail_poll)
    monkeypatch.setattr(analytics_snapshot_task, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(analytics_snapshot_task, "capture_metrics_snapshot", fake_capture)

    await analytics_snapshot_task._capture_for_user(user_id, get_settings())

    assert captured == [True]
