"""Platform analytics API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import Post, Profile
from app.services.analytics.analytics_snapshot import load_post_snapshots, load_snapshots
from app.services.analytics.channel_metrics import (
    MISSED_SNAPSHOT_MULTIPLIER,
    VALID_PERIODS,
    aggregate_reactions,
    build_channel_summary,
    build_channel_trend,
    build_heatmap,
    build_top_posts,
    published_posts,
)
from app.services.analytics.platform_models import get_platform_model_analytics
from app.services.profile_defaults import empty_ai_profile

router = APIRouter(prefix="/analytics", tags=["Analytics"])


async def _load_user_posts(session: DbSession, user_id: Any) -> list[Post]:
    result = await session.execute(
        select(Post).where(Post.user_id == user_id).order_by(Post.position, Post.created_at)
    )
    return list(result.scalars().all())


def _validate_period(period: str) -> str:
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=422, detail="Некорректный период аналитики")
    return period


async def _load_channel_context(
    session: DbSession,
    user_id: Any,
) -> tuple[list[Post], list, list, dict[str, Any] | None]:
    posts = await _load_user_posts(session, user_id)
    profile = await session.get(Profile, user_id)
    telegram = profile.telegram if profile and profile.telegram else None
    channel_snapshots = await load_snapshots(session, user_id)
    post_snapshots = await load_post_snapshots(session, user_id)
    return posts, channel_snapshots, post_snapshots, telegram


def _snapshot_stale_after_seconds() -> float | None:
    settings = get_settings()
    if settings.telegram_analytics_snapshot_seconds <= 0:
        return None
    return settings.telegram_analytics_snapshot_seconds * MISSED_SNAPSHOT_MULTIPLIER


@router.get("/summary/")
async def get_channel_summary(
    user: CurrentUser,
    session: DbSession,
    period: str = Query("30d"),
) -> dict[str, Any]:
    """Channel period totals and data-freshness metadata."""
    period = _validate_period(period)
    posts, channel_snapshots, post_snapshots, telegram = await _load_channel_context(
        session, user.id
    )
    return build_channel_summary(
        posts,
        channel_snapshots,
        post_snapshots,
        period,
        telegram,
        snapshot_stale_after_seconds=_snapshot_stale_after_seconds(),
    )


@router.get("/trend/")
async def get_channel_trend(
    user: CurrentUser,
    session: DbSession,
    period: str = Query("30d"),
) -> dict[str, Any]:
    """Channel metric growth time series for the selected period."""
    period = _validate_period(period)
    posts, channel_snapshots, post_snapshots, telegram = await _load_channel_context(
        session, user.id
    )
    return build_channel_trend(
        posts, channel_snapshots, post_snapshots, period, telegram
    )


@router.get("/heatmap/")
async def get_channel_heatmap(
    user: CurrentUser,
    session: DbSession,
    period: str = Query("30d"),
) -> dict[str, Any]:
    """Views heatmap by weekday and publish-hour slot."""
    period = _validate_period(period)
    posts = await _load_user_posts(session, user.id)
    return build_heatmap(posts, period)


@router.get("/reactions/")
async def get_channel_reactions(
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    """Aggregated emoji reaction counts across all published posts."""
    posts = await _load_user_posts(session, user.id)
    return {"reactions": aggregate_reactions(published_posts(posts))}


@router.get("/top-posts/")
async def get_top_posts(
    user: CurrentUser,
    session: DbSession,
    period: str = Query("30d"),
) -> dict[str, Any]:
    """Top published posts ranked by views for the selected period."""
    period = _validate_period(period)
    posts = await _load_user_posts(session, user.id)
    return {"posts": build_top_posts(posts, period)}


@router.get("/platform-models/")
async def get_platform_models(
    user: CurrentUser,
    session: DbSession,
    period: int = Query(2, ge=0, le=4),
    points: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    profile = await session.get(Profile, user.id)
    ai_profile = profile.ai if profile and profile.ai else empty_ai_profile()
    return await get_platform_model_analytics(
        session,
        user_id=user.id,
        ai_profile=ai_profile,
        period=period,
        points=points,
    )
