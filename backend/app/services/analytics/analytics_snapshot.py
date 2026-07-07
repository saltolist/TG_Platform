"""Periodic per-post and channel metric snapshots — source of real analytics history."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.core.metrics import SnapshotCycleMetrics
from app.db.models import ChannelMetricSnapshot, Post, PostMetricSnapshot, Profile
from app.services.analytics.channel_metrics import (
    published_posts,
    _totals_from_posts,
    parse_views_value,
    sum_reactions,
)
from app.services.telegram.channel_flow import fetch_channel_subscriber_count

logger = logging.getLogger(__name__)

SNAPSHOT_SLOT_MINUTES = 30


def snapshot_slot(moment: datetime | None = None) -> datetime:
    """Round *moment* down to the current 30-minute slot (:00 / :30 UTC)."""
    moment = moment or datetime.now(timezone.utc)
    moment = moment.astimezone(timezone.utc)
    minute = (moment.minute // SNAPSHOT_SLOT_MINUTES) * SNAPSHOT_SLOT_MINUTES
    return moment.replace(minute=minute, second=0, microsecond=0)


def _post_snapshot_metrics(post: Post) -> dict[str, int]:
    metrics = post.data.get("metrics") if isinstance(post.data.get("metrics"), dict) else {}
    return {
        "views": parse_views_value(metrics.get("views")),
        "reactions": sum_reactions(metrics),
        "reposts": int(metrics.get("reposts") or 0),
        "comments": len(post.data.get("comments") or []),
    }


def _posts_for_capture(
    posts: list[Post],
    settings: Settings,
    *,
    full_pass: bool,
) -> list[Post]:
    """Bound frequent captures to recent posts; full catalog once per UTC day.

    The daily full pass at the :00 slot catches long-tail metric changes on
    older posts without snapshotting every post every 30 minutes.
    """
    published = published_posts(posts)
    if full_pass:
        return published
    limit = max(1, settings.telegram_metrics_poll_window)
    return sorted(
        published,
        key=lambda post: (post.position or 0, post.created_at),
        reverse=True,
    )[:limit]


async def _load_published_posts(session: AsyncSession, user_id: UUID) -> list[Post]:
    result = await session.execute(select(Post).where(Post.user_id == user_id))
    return published_posts(list(result.scalars().all()))


async def capture_metrics_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: UUID,
    client: Any | None,
    entity: Any | None,
    settings: Settings,
    *,
    metrics: SnapshotCycleMetrics | None = None,
) -> bool:
    """Persist per-post and channel metrics for the current 30-minute slot.

    Reads current totals from published posts, optionally refreshes the
    subscriber count from Telegram when *client*/*entity* are provided,
    upserts snapshot rows and stamps the profile. Returns True when rows
    were written.
    """
    subscribers: int | None = None
    if client is not None and entity is not None:
        try:
            subscribers = await fetch_channel_subscriber_count(client, entity, settings)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Subscriber refresh failed for user %s — skipping for this cycle",
                user_id,
                exc_info=True,
            )
            if metrics is not None:
                metrics.record_error("subscriber_rpc")

    slot = snapshot_slot()
    now_iso = datetime.now(timezone.utc).isoformat()
    full_pass = slot.hour == 0 and slot.minute == 0

    async with session_factory() as session:
        posts = await _load_published_posts(session, user_id)
        posts_to_capture = _posts_for_capture(posts, settings, full_pass=full_pass)
        totals = _totals_from_posts(posts)

        if posts_to_capture:
            post_rows = [
                {
                    "post_id": post.id,
                    "user_id": user_id,
                    "captured_at": slot,
                    **_post_snapshot_metrics(post),
                }
                for post in posts_to_capture
            ]
            post_stmt = pg_insert(PostMetricSnapshot).values(post_rows)
            post_stmt = post_stmt.on_conflict_do_update(
                constraint="uq_post_metric_snapshots_slot",
                set_={
                    "views": post_stmt.excluded.views,
                    "reactions": post_stmt.excluded.reactions,
                    "reposts": post_stmt.excluded.reposts,
                    "comments": post_stmt.excluded.comments,
                },
            )
            await session.execute(post_stmt)

        channel_stmt = (
            pg_insert(ChannelMetricSnapshot)
            .values(
                user_id=user_id,
                captured_at=slot,
                subscribers=subscribers,
                views=int(totals["views"]),
                reactions=int(totals["reactions"]),
                comments=int(totals["comments"]),
                reposts=int(totals["reposts"]),
                posts_count=len(posts),
                er=float(totals["er"]),
            )
            .on_conflict_do_update(
                constraint="uq_channel_metric_snapshots_slot",
                set_={
                    "subscribers": subscribers,
                    "views": int(totals["views"]),
                    "reactions": int(totals["reactions"]),
                    "comments": int(totals["comments"]),
                    "reposts": int(totals["reposts"]),
                    "posts_count": len(posts),
                    "er": float(totals["er"]),
                },
            )
        )
        await session.execute(channel_stmt)

        telegram_payload: dict[str, Any] | None = None
        profile = await session.get(Profile, user_id)
        if profile is not None:
            telegram = dict(profile.telegram or {})
            if subscribers is not None:
                telegram["subscriberCount"] = subscribers
                telegram["subscriberCountAt"] = now_iso
            telegram["lastAnalyticsSnapshotAt"] = now_iso
            telegram["metricsRevision"] = int(telegram.get("metricsRevision") or 0) + 1
            profile.telegram = telegram
            flag_modified(profile, "telegram")
            telegram_payload = dict(telegram)

        retention_days = max(1, settings.analytics_snapshot_retention_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        await session.execute(
            delete(ChannelMetricSnapshot).where(
                ChannelMetricSnapshot.user_id == user_id,
                ChannelMetricSnapshot.captured_at < cutoff,
            )
        )
        await session.execute(
            delete(PostMetricSnapshot).where(
                PostMetricSnapshot.user_id == user_id,
                PostMetricSnapshot.captured_at < cutoff,
            )
        )

        await session.commit()

    if telegram_payload is not None:
        from app.services.telegram.sync_events import publish_telegram_sync_event

        publish_telegram_sync_event(user_id, telegram_payload)

    logger.debug(
        "Captured metrics snapshot for user %s (slot %s, posts=%s, subscribers=%s)",
        user_id,
        slot.isoformat(),
        len(posts_to_capture),
        subscribers,
    )
    return True


# Backwards-compatible alias for callers not yet migrated.
capture_channel_snapshot = capture_metrics_snapshot


async def load_snapshots(
    session: AsyncSession,
    user_id: UUID,
    *,
    since: datetime | None = None,
) -> list[ChannelMetricSnapshot]:
    """All channel snapshots for *user_id* ordered by ``captured_at`` (oldest first)."""
    query = select(ChannelMetricSnapshot).where(ChannelMetricSnapshot.user_id == user_id)
    if since is not None:
        query = query.where(ChannelMetricSnapshot.captured_at >= since)
    query = query.order_by(ChannelMetricSnapshot.captured_at)
    result = await session.execute(query)
    return list(result.scalars().all())


async def load_post_snapshots(
    session: AsyncSession,
    user_id: UUID,
    *,
    since: datetime | None = None,
) -> list[PostMetricSnapshot]:
    """All per-post snapshots for *user_id* ordered by ``captured_at`` (oldest first)."""
    query = select(PostMetricSnapshot).where(PostMetricSnapshot.user_id == user_id)
    if since is not None:
        query = query.where(PostMetricSnapshot.captured_at >= since)
    query = query.order_by(PostMetricSnapshot.captured_at)
    result = await session.execute(query)
    return list(result.scalars().all())
