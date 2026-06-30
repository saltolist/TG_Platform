"""Real MTProto (Telethon) authorization endpoints — Phase 3 / Step 1.

All endpoints return the same masked profile shape as ``GET/PUT /profile/telegram/``
(via ``mask_telegram_secrets``, which also strips internal auth-flow fields).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.deps import CurrentWriter, DbSession
from app.db.models import Profile
from app.schemas.requests import (
    TelegramSendCodeRequest,
    TelegramVerify2faRequest,
    TelegramVerifyCodeRequest,
)
from app.services.profile_defaults import empty_telegram_profile
from app.services.telegram.auth_flow import TelegramAuthError, reset_auth, send_code, verify_code, verify_password
from app.services.telegram.byok_telegram import mask_telegram_secrets

router = APIRouter(prefix="/telegram/auth", tags=["Telegram"])


async def _get_or_create_profile(session: DbSession, user_id) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
        await session.flush()
    return profile


async def _apply(
    session: DbSession,
    profile: Profile,
    coro,
) -> dict[str, Any]:
    """Run an auth_flow coroutine, persist its result (success or error patch)."""
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


@router.post("/send-code/")
async def telegram_send_code(
    payload: TelegramSendCodeRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await _get_or_create_profile(session, user.id)
    return await _apply(
        session, profile, lambda telegram, settings: send_code(telegram, payload.phone, settings)
    )


@router.post("/verify/")
async def telegram_verify_code(
    payload: TelegramVerifyCodeRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await _get_or_create_profile(session, user.id)
    return await _apply(
        session, profile, lambda telegram, settings: verify_code(telegram, payload.code, settings)
    )


@router.post("/verify-2fa/")
async def telegram_verify_2fa(
    payload: TelegramVerify2faRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await _get_or_create_profile(session, user.id)
    return await _apply(
        session,
        profile,
        lambda telegram, settings: verify_password(telegram, payload.password, settings),
    )


@router.post("/reset/")
async def telegram_reset_auth(user: CurrentWriter, session: DbSession) -> dict[str, Any]:
    profile = await _get_or_create_profile(session, user.id)
    return await _apply(session, profile, lambda telegram, settings: reset_auth(telegram, settings))
