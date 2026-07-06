"""Telegram emoji catalog and preview endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.v1._telegram_shared import get_or_create_profile
from app.core.deps import CurrentUser, DbSession
from app.services.telegram.emoji_flow import (
    fetch_custom_emoji_preview_bytes,
    fetch_emoji_catalog_for_user,
)
from app.services.telegram.net import TelegramAuthError

router = APIRouter(prefix="/telegram/emoji", tags=["Telegram"])


@router.get("/catalog/")
async def telegram_emoji_catalog(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = await get_or_create_profile(session, user.id)
    try:
        return await fetch_emoji_catalog_for_user(profile, user.id)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/{document_id}/preview/")
async def telegram_emoji_preview(
    document_id: str, user: CurrentUser, session: DbSession
) -> Response:
    profile = await get_or_create_profile(session, user.id)
    try:
        data, mime = await fetch_custom_emoji_preview_bytes(profile, user.id, document_id)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})
