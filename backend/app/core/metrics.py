"""Prometheus metrics for analytics snapshot observability (Pushgateway batch push)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

PUSH_JOB = "analytics_snapshot"
PUSH_GROUPING_KEY = {"job": PUSH_JOB}

ERROR_TYPES = (
    "profile_missing",
    "telegram_connect",
    "metrics_poll",
    "subscriber_rpc",
    "db_error",
    "other",
)

_registry = CollectorRegistry()

_cycle_timestamp = Gauge(
    "analytics_snapshot_cycle_timestamp_seconds",
    "Unix time of the last completed analytics snapshot cycle",
    registry=_registry,
)
_channels_total = Gauge(
    "analytics_snapshot_channels_total",
    "Connected channels processed in the last cycle",
    registry=_registry,
)
_channels_overdue = Gauge(
    "analytics_snapshot_channels_overdue",
    "Channels past the overdue threshold in the last cycle",
    registry=_registry,
)
_last_cycle_success = Gauge(
    "analytics_snapshot_last_cycle_success",
    "Successful captures in the last cycle",
    registry=_registry,
)
_last_cycle_errors = Gauge(
    "analytics_snapshot_last_cycle_errors",
    "Errors in the last cycle by type",
    ["error_type"],
    registry=_registry,
)
_lag_seconds = Gauge(
    "analytics_snapshot_lag_seconds",
    "Seconds since last snapshot per channel",
    ["channel"],
    registry=_registry,
)


class SnapshotCycleMetrics:
    """Accumulates per-cycle analytics snapshot metrics, then pushes to Pushgateway."""

    def __init__(self) -> None:
        self.channels_total = 0
        self.channels_overdue = 0
        self.success_count = 0
        self.error_counts: dict[str, int] = {t: 0 for t in ERROR_TYPES}
        self.lag_by_channel: dict[str, float] = {}

    def record_channel(self, *, lag_seconds: float | None, overdue: bool) -> None:
        self.channels_total += 1
        if overdue:
            self.channels_overdue += 1

    def record_lag(self, channel_label: str, lag_seconds: float) -> None:
        self.lag_by_channel[channel_label] = lag_seconds

    def record_success(self) -> None:
        self.success_count += 1

    def record_error(self, error_type: str) -> None:
        if error_type not in self.error_counts:
            error_type = "other"
        self.error_counts[error_type] += 1

    def push(self, pushgateway_url: str) -> None:
        if not pushgateway_url:
            return

        _cycle_timestamp.set(time.time())
        _channels_total.set(self.channels_total)
        _channels_overdue.set(self.channels_overdue)
        _last_cycle_success.set(self.success_count)
        for error_type in ERROR_TYPES:
            _last_cycle_errors.labels(error_type=error_type).set(self.error_counts[error_type])
        _lag_seconds.clear()
        for channel, lag in self.lag_by_channel.items():
            _lag_seconds.labels(channel=channel).set(lag)

        try:
            push_to_gateway(
                pushgateway_url,
                job=PUSH_JOB,
                registry=_registry,
                timeout=5,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to push analytics snapshot metrics to %s",
                pushgateway_url,
                exc_info=True,
            )


def channel_label_from_telegram(telegram: dict, user_id: UUID) -> str:
    """Human-readable Prometheus label: Telegram handle or user_id fallback."""
    channel = telegram.get("channel")
    if channel:
        return str(channel).lstrip("@")
    return str(user_id)
