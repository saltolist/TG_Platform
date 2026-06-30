"""Shared router glue for Telegram flow endpoints (auth + channel connect).

Both ``telegram_auth.py`` and ``telegram_channel.py`` run a
``profile.telegram`` -> ``profile.telegram`` coroutine and persist the
result (success or error patch) the same way — see ``apply_telegram_flow``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.deps import DbSession
from app.db.models import Profile
from app.services.profile_defaults import empty_telegram_profile
from app.services.telegram.net import TelegramAuthError
from app.services.telegram.byok_telegram import mask_telegram_secrets


async def get_or_create_profile(session: DbSession, user_id: UUID) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
        await session.flush()
    return profile


async def apply_telegram_flow(
    session: DbSession,
    profile: Profile,
    coro,
) -> dict[str, Any]:
    """Run a Telegram-flow coroutine, persist its result (success or error patch)."""
    telegram = profile.telegram if profile.telegram else empty_telegram_profile()
    settings = get_settings()
    try:
        updated = await coro(telegram, settings)
    except TelegramAuthError as exc:
        if exc.profile_patch is not None:
            profile.telegram = exc.profile_patch
            await session.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    profile.telegram = updated
    await session.commit()
    return mask_telegram_secrets(updated, settings)
