"""Platform analytics API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.deps import CurrentUser, DbSession
from app.db.models import Profile
from app.services.analytics.platform_models import get_platform_model_analytics
from app.services.profile_defaults import empty_ai_profile

router = APIRouter(prefix="/analytics", tags=["Analytics"])


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
