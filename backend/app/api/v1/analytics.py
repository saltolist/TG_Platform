"""Platform analytics API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.db.models import Post, Profile
from app.services.analytics.analytics_snapshot import load_post_snapshots, load_snapshots
from app.services.analytics.channel_metrics import (
    VALID_PERIODS,
    build_overview_from_history,
    build_top_posts,
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


@router.get("/overview/")
async def get_channel_overview(
    user: CurrentUser,
    session: DbSession,
    period: str = Query("30d"),
) -> dict[str, Any]:
    """Channel metrics overview: per-post snapshot history with legacy fallback."""
    period = _validate_period(period)
    posts = await _load_user_posts(session, user.id)
    profile = await session.get(Profile, user.id)
    telegram = profile.telegram if profile and profile.telegram else None
    channel_snapshots = await load_snapshots(session, user.id)
    post_snapshots = await load_post_snapshots(session, user.id)
    return build_overview_from_history(
        posts, channel_snapshots, post_snapshots, period, telegram
    )


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
