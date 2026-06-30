"""Real channel connect (Telethon) endpoint — Phase 3 / Steps 2–3.

Returns the same masked profile shape as ``GET/PUT /profile/telegram/``
(via ``mask_telegram_secrets``). On success, starts background history import
(Step 3) unless ``syncMode`` is ``publish-only``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from app.api.v1._telegram_shared import apply_telegram_flow, get_or_create_profile
from app.core.config import get_settings
from app.core.deps import CurrentWriter, DbSession
from app.schemas.requests import TelegramConnectChannelRequest
from app.services.telegram.channel_flow import connect_channel
from app.services.telegram.import_flow import run_channel_import

router = APIRouter(prefix="/telegram/channel", tags=["Telegram"])


@router.post("/connect/")
async def telegram_connect_channel(
    payload: TelegramConnectChannelRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    result = await apply_telegram_flow(
        session,
        profile,
        lambda telegram, settings: connect_channel(telegram, payload.channel, settings),
    )
    if result.get("importStatus") == "importing":
        asyncio.create_task(run_channel_import(user.id, get_settings()))
    return result
