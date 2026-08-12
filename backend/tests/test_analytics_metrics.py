"""Tests for analytics snapshot Prometheus metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.metrics import ERROR_TYPES, SnapshotCycleMetrics, channel_label_from_telegram
from app.db.models import Profile
from app.services.analytics.channel_metrics import MISSED_SNAPSHOT_MULTIPLIER
from app.tasks import analytics_snapshot as analytics_snapshot_task


def _fake_session_factory(profiles: list[Profile] | None = None):
    """Return a callable that mimics async_session_factory() for tests."""

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, query):
            result = MagicMock()
            result.scalars.return_value.all.return_value = profiles or []
            return result

    return lambda: FakeSession()


def test_snapshot_cycle_metrics_accumulates_counts() -> None:
    metrics = SnapshotCycleMetrics()
    metrics.record_channel(lag_seconds=120.0, overdue=True)
    metrics.record_channel(lag_seconds=30.0, overdue=False)
    metrics.record_success()
    metrics.record_error("telegram_connect")
    metrics.record_error("other")
    metrics.record_lag("@mychannel", 120.0)
    metrics.record_lag("user-123", 30.0)

    assert metrics.channels_total == 2
    assert metrics.channels_overdue == 1
    assert metrics.success_count == 1
    assert metrics.error_counts["telegram_connect"] == 1
    assert metrics.error_counts["other"] == 1
    assert metrics.error_counts["db_error"] == 0
    assert metrics.lag_by_channel["@mychannel"] == 120.0


def test_snapshot_cycle_metrics_initializes_all_error_types_to_zero() -> None:
    metrics = SnapshotCycleMetrics()
    assert set(metrics.error_counts.keys()) == set(ERROR_TYPES)
    assert all(count == 0 for count in metrics.error_counts.values())


def test_snapshot_cycle_metrics_unknown_error_type_becomes_other() -> None:
    metrics = SnapshotCycleMetrics()
    metrics.record_error("not_a_real_type")
    assert metrics.error_counts["other"] == 1


def test_channel_label_from_telegram_prefers_handle() -> None:
    user_id = uuid.uuid4()
    assert channel_label_from_telegram({"channel": "@testchannel"}, user_id) == "testchannel"
    assert channel_label_from_telegram({}, user_id) == str(user_id)


@patch("app.core.metrics.push_to_gateway")
def test_snapshot_cycle_metrics_push_sets_gauges(mock_push: MagicMock) -> None:
    metrics = SnapshotCycleMetrics()
    metrics.record_channel(lag_seconds=60.0, overdue=False)
    metrics.record_success()
    metrics.record_lag("mychannel", 60.0)

    metrics.push("http://pushgateway:9091")

    mock_push.assert_called_once()
    args, kwargs = mock_push.call_args
    assert args[0] == "http://pushgateway:9091"
    assert kwargs["job"] == "analytics_snapshot"
    assert kwargs["timeout"] == 5


@patch("app.core.metrics.push_to_gateway", side_effect=RuntimeError("gateway down"))
def test_snapshot_cycle_metrics_push_swallows_errors(mock_push: MagicMock) -> None:
    metrics = SnapshotCycleMetrics()
    metrics.push("http://pushgateway:9091")  # must not raise


def test_snapshot_cycle_metrics_push_skips_empty_url() -> None:
    metrics = SnapshotCycleMetrics()
    with patch("app.core.metrics.push_to_gateway") as mock_push:
        metrics.push("")
        mock_push.assert_not_called()


def test_snapshot_age_seconds_parses_profile_timestamp() -> None:
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=5)).isoformat()
    profile = Profile(
        user_id=uuid.uuid4(),
        telegram={"lastAnalyticsSnapshotAt": recent},
    )
    age = analytics_snapshot_task._snapshot_age_seconds(profile, now)
    assert age is not None
    assert 290 <= age <= 310


def test_snapshot_age_seconds_returns_none_when_missing() -> None:
    profile = Profile(user_id=uuid.uuid4(), telegram={})
    assert analytics_snapshot_task._snapshot_age_seconds(profile, datetime.now(timezone.utc)) is None


def test_log_if_snapshot_overdue_warns_when_stale(caplog: pytest.LogCaptureFixture) -> None:
    settings = get_settings()
    interval = settings.telegram_analytics_snapshot_seconds
    stale_at = (
        datetime.now(timezone.utc)
        - timedelta(seconds=interval * MISSED_SNAPSHOT_MULTIPLIER + 60)
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
async def test_capture_all_channel_snapshots_pushes_when_url_set(monkeypatch) -> None:
    user_id = uuid.uuid4()
    profile = Profile(
        user_id=user_id,
        telegram={"channelStatus": "connected", "channel": "@test"},
    )

    pushed: list[str] = []

    def fake_push(self, url: str) -> None:
        pushed.append(url)

    async def fake_capture(uid, settings, metrics=None) -> None:
        pass

    monkeypatch.setattr(SnapshotCycleMetrics, "push", fake_push)
    monkeypatch.setattr(
        analytics_snapshot_task,
        "async_session_factory",
        _fake_session_factory([profile]),
    )
    monkeypatch.setattr(analytics_snapshot_task, "_capture_for_user", fake_capture)
    monkeypatch.setattr(
        analytics_snapshot_task,
        "get_settings",
        lambda: get_settings().model_copy(update={"prometheus_pushgateway_url": "http://pushgateway:9091"}),
    )

    await analytics_snapshot_task._capture_all_channel_snapshots()
    assert pushed == ["http://pushgateway:9091"]


@pytest.mark.asyncio
async def test_capture_all_channel_snapshots_skips_push_when_url_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        analytics_snapshot_task,
        "async_session_factory",
        _fake_session_factory([]),
    )
    monkeypatch.setattr(
        analytics_snapshot_task,
        "get_settings",
        lambda: get_settings().model_copy(update={"prometheus_pushgateway_url": ""}),
    )

    with patch("app.core.metrics.push_to_gateway") as mock_push:
        await analytics_snapshot_task._capture_all_channel_snapshots()
        mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_capture_all_channel_snapshots_classifies_db_errors(monkeypatch) -> None:
    user_id = uuid.uuid4()
    profile = Profile(user_id=user_id, telegram={"channelStatus": "connected"})

    async def fail_capture(uid, settings, metrics=None) -> None:
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(
        analytics_snapshot_task,
        "async_session_factory",
        _fake_session_factory([profile]),
    )
    monkeypatch.setattr(analytics_snapshot_task, "_capture_for_user", fail_capture)
    monkeypatch.setattr(SnapshotCycleMetrics, "push", lambda self, url: None)
    monkeypatch.setattr(
        analytics_snapshot_task,
        "get_settings",
        lambda: get_settings().model_copy(update={"prometheus_pushgateway_url": "http://x"}),
    )

    metrics_instances: list[SnapshotCycleMetrics] = []
    original_init = SnapshotCycleMetrics.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        metrics_instances.append(self)

    monkeypatch.setattr(SnapshotCycleMetrics, "__init__", capture_init)

    await analytics_snapshot_task._capture_all_channel_snapshots()
    assert len(metrics_instances) == 1
    assert metrics_instances[0].error_counts["db_error"] == 1
    assert metrics_instances[0].success_count == 0


@pytest.mark.asyncio
async def test_capture_all_channel_snapshots_classifies_generic_errors(monkeypatch) -> None:
    user_id = uuid.uuid4()
    profile = Profile(user_id=user_id, telegram={"channelStatus": "connected"})

    async def fail_capture(uid, settings, metrics=None) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(
        analytics_snapshot_task,
        "async_session_factory",
        _fake_session_factory([profile]),
    )
    monkeypatch.setattr(analytics_snapshot_task, "_capture_for_user", fail_capture)
    monkeypatch.setattr(SnapshotCycleMetrics, "push", lambda self, url: None)
    monkeypatch.setattr(
        analytics_snapshot_task,
        "get_settings",
        lambda: get_settings().model_copy(update={"prometheus_pushgateway_url": "http://x"}),
    )

    metrics_instances: list[SnapshotCycleMetrics] = []
    original_init = SnapshotCycleMetrics.__init__

    def capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        metrics_instances.append(self)

    monkeypatch.setattr(SnapshotCycleMetrics, "__init__", capture_init)

    await analytics_snapshot_task._capture_all_channel_snapshots()
    assert metrics_instances[0].error_counts["other"] == 1
