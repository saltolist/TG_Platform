"""Periodic channel metric snapshots — the source of real analytics history."""

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
from app.db.models import ChannelMetricSnapshot, Post, Profile
from app.services.analytics.channel_metrics import _published_posts, _totals_from_posts
from app.services.telegram.channel_flow import fetch_channel_subscriber_count

logger = logging.getLogger(__name__)

SNAPSHOT_SLOT_MINUTES = 30


def snapshot_slot(moment: datetime | None = None) -> datetime:
    """Round *moment* down to the current 30-minute slot (:00 / :30 UTC)."""
    moment = moment or datetime.now(timezone.utc)
    moment = moment.astimezone(timezone.utc)
    minute = (moment.minute // SNAPSHOT_SLOT_MINUTES) * SNAPSHOT_SLOT_MINUTES
    return moment.replace(minute=minute, second=0, microsecond=0)


async def _load_published_posts(session: AsyncSession, user_id: UUID) -> list[Post]:
    result = await session.execute(select(Post).where(Post.user_id == user_id))
    return _published_posts(list(result.scalars().all()))


async def capture_channel_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: UUID,
    client: Any,
    entity: Any,
    settings: Settings,
) -> bool:
    """Persist one metrics snapshot for the current 30-minute slot.

    Reads current totals from published posts, refreshes the subscriber count
    from Telegram, upserts the snapshot row and stamps the profile. Returns
    True when a snapshot row was written.
    """
    subscribers = await fetch_channel_subscriber_count(client, entity, settings)
    slot = snapshot_slot()
    now_iso = datetime.now(timezone.utc).isoformat()

    async with session_factory() as session:
        posts = await _load_published_posts(session, user_id)
        totals = _totals_from_posts(posts)

        stmt = (
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
        await session.execute(stmt)

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

        retention_days = max(1, settings.analytics_snapshot_retention_days)
        await session.execute(
            delete(ChannelMetricSnapshot).where(
                ChannelMetricSnapshot.user_id == user_id,
                ChannelMetricSnapshot.captured_at
                < datetime.now(timezone.utc) - timedelta(days=retention_days),
            )
        )

        await session.commit()

    logger.debug(
        "Captured channel metrics snapshot for user %s (slot %s, subscribers=%s)",
        user_id,
        slot.isoformat(),
        subscribers,
    )
    return True


async def load_snapshots(
    session: AsyncSession,
    user_id: UUID,
    *,
    since: datetime | None = None,
) -> list[ChannelMetricSnapshot]:
    """All snapshots for *user_id* ordered by ``captured_at`` (oldest first)."""
    query = select(ChannelMetricSnapshot).where(ChannelMetricSnapshot.user_id == user_id)
    if since is not None:
        query = query.where(ChannelMetricSnapshot.captured_at >= since)
    query = query.order_by(ChannelMetricSnapshot.captured_at)
    result = await session.execute(query)
    return list(result.scalars().all())
