"""Celery Beat task: periodic per-post and channel metric snapshots."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.metrics import SnapshotCycleMetrics, channel_label_from_telegram
from app.db.models import Profile
from app.db.session import async_session_factory
from app.services.analytics.analytics_snapshot import capture_metrics_snapshot
from app.services.analytics.channel_metrics import MISSED_SNAPSHOT_MULTIPLIER
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.metrics_flow import poll_recent_post_metrics
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
)
from app.tasks.publish import _run_async

logger = logging.getLogger(__name__)


def _subscriber_refresh_due(telegram: dict[str, Any], settings: Settings) -> bool:
    """True when the subscriber count (and pre-snapshot metrics poll) should run."""
    refresh_seconds = settings.telegram_analytics_subscriber_refresh_seconds
    if refresh_seconds <= 0:
        return False

    raw = telegram.get("subscriberCountAt")
    if not raw:
        return True
    try:
        captured = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
    return age >= refresh_seconds


def _snapshot_age_seconds(profile: Profile, now: datetime) -> float | None:
    """Seconds since last analytics snapshot, or None if unknown."""
    telegram = profile.telegram or {}
    raw = telegram.get("lastAnalyticsSnapshotAt")
    if not raw:
        return None
    try:
        last_at = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    return (now - last_at.astimezone(timezone.utc)).total_seconds()


def _log_if_snapshot_overdue(profile: Profile, settings: Settings, now: datetime) -> None:
    """Emit a structured warning when a channel has missed several snapshot cycles."""
    age_seconds = _snapshot_age_seconds(profile, now)
    if age_seconds is None:
        return

    interval = settings.telegram_analytics_snapshot_seconds
    if interval <= 0:
        return

    threshold = interval * MISSED_SNAPSHOT_MULTIPLIER
    if age_seconds <= threshold:
        return

    logger.warning(
        "Analytics snapshot overdue for user %s: last capture %ss ago "
        "(expected every %ss, threshold %ss)",
        profile.user_id,
        int(age_seconds),
        int(interval),
        int(threshold),
    )


def _is_snapshot_overdue(profile: Profile, settings: Settings, now: datetime) -> bool:
    age_seconds = _snapshot_age_seconds(profile, now)
    if age_seconds is None:
        return False
    interval = settings.telegram_analytics_snapshot_seconds
    if interval <= 0:
        return False
    return age_seconds > interval * MISSED_SNAPSHOT_MULTIPLIER


async def _capture_for_user(
    user_id: UUID,
    settings: Settings,
    metrics: SnapshotCycleMetrics | None = None,
) -> None:
    cycle_metrics = metrics or SnapshotCycleMetrics()

    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            cycle_metrics.record_error("profile_missing")
            return
        telegram = dict(profile.telegram or {})
        if telegram.get("channelStatus") != "connected":
            return

    client = None
    entity = None
    if _subscriber_refresh_due(telegram, settings):
        try:
            api_id, api_hash = require_api_credentials(telegram, settings)
            session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
            parsed = parse_channel_input(str(telegram.get("channel") or ""))
            if parsed and session_string:
                client = build_client(api_id, api_hash, session_string)
                await connect_telegram_client(client, settings)
                entity = await resolve_channel_entity(client, parsed, settings)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Telethon unavailable for analytics snapshot user %s — DB-only capture",
                user_id,
                exc_info=True,
            )
            cycle_metrics.record_error("telegram_connect")
            client = None
            entity = None

        if client is not None and entity is not None:
            try:
                await poll_recent_post_metrics(
                    client,
                    entity,
                    user_id,
                    settings,
                    async_session_factory,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Pre-snapshot metrics poll failed for user %s — continuing with DB state",
                    user_id,
                    exc_info=True,
                )
                cycle_metrics.record_error("metrics_poll")

    try:
        await capture_metrics_snapshot(
            async_session_factory,
            user_id,
            client,
            entity,
            settings,
            metrics=cycle_metrics,
        )
    finally:
        if client is not None:
            await disconnect_safely(client)


async def _capture_all_channel_snapshots() -> None:
    settings = get_settings()
    if settings.telegram_analytics_snapshot_seconds <= 0:
        return

    async with async_session_factory() as session:
        result = await session.execute(select(Profile))
        profiles = list(result.scalars().all())

    metrics = SnapshotCycleMetrics()
    now = datetime.now(timezone.utc)
    for profile in profiles:
        telegram = profile.telegram or {}
        if telegram.get("channelStatus") != "connected":
            continue

        overdue = _is_snapshot_overdue(profile, settings, now)
        age_seconds = _snapshot_age_seconds(profile, now)
        metrics.record_channel(lag_seconds=age_seconds, overdue=overdue)
        if age_seconds is not None:
            label = channel_label_from_telegram(telegram, profile.user_id)
            metrics.record_lag(label, age_seconds)

        _log_if_snapshot_overdue(profile, settings, now)
        try:
            await _capture_for_user(profile.user_id, settings, metrics=metrics)
            metrics.record_success()
        except SQLAlchemyError:
            logger.exception(
                "Analytics snapshot failed for user %s (db)",
                profile.user_id,
            )
            metrics.record_error("db_error")
        except Exception:  # noqa: BLE001
            logger.exception(
                "Analytics snapshot failed for user %s",
                profile.user_id,
            )
            metrics.record_error("other")

    metrics.push(settings.prometheus_pushgateway_url)


@celery_app.task(name="app.tasks.analytics_snapshot.capture_all_channel_snapshots")
def capture_all_channel_snapshots() -> None:
    """Capture metric snapshots for every connected channel."""
    _run_async(_capture_all_channel_snapshots())
