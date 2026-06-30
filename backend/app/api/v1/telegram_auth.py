"""Real MTProto (Telethon) authorization endpoints — Phase 3 / Step 1.

All endpoints return the same masked profile shape as ``GET/PUT /profile/telegram/``
(via ``mask_telegram_secrets``, which also strips internal auth-flow fields).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v1._telegram_shared import apply_telegram_flow, get_or_create_profile
from app.core.deps import CurrentWriter, DbSession
from app.schemas.requests import (
    TelegramSendCodeRequest,
    TelegramVerify2faRequest,
    TelegramVerifyCodeRequest,
)
from app.services.telegram.auth_flow import reset_auth, send_code, verify_code, verify_password

router = APIRouter(prefix="/telegram/auth", tags=["Telegram"])


@router.post("/send-code/")
async def telegram_send_code(
    payload: TelegramSendCodeRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    return await apply_telegram_flow(
        session, profile, lambda telegram, settings: send_code(telegram, payload.phone, settings)
    )


@router.post("/verify/")
async def telegram_verify_code(
    payload: TelegramVerifyCodeRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    return await apply_telegram_flow(
        session, profile, lambda telegram, settings: verify_code(telegram, payload.code, settings)
    )


@router.post("/verify-2fa/")
async def telegram_verify_2fa(
    payload: TelegramVerify2faRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    return await apply_telegram_flow(
        session,
        profile,
        lambda telegram, settings: verify_password(telegram, payload.password, settings),
    )


@router.post("/reset/")
async def telegram_reset_auth(user: CurrentWriter, session: DbSession) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    return await apply_telegram_flow(
        session, profile, lambda telegram, settings: reset_auth(telegram, settings)
    )
