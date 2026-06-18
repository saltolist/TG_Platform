"""Dev-only runtime control for LLM context terminal logging."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.ai.context_log import get_chat_filter, set_chat_filter

router = APIRouter(prefix="/dev/ai-context-log", tags=["Dev"])
_logger = logging.getLogger("tg.ai.context")


class ChatFilterBody(BaseModel):
    chatId: str = Field(default="", description="gc1, post chat id, post:postId:chatId, or empty to clear")


def _require_enabled() -> None:
    if not get_settings().ai_context_log:
        raise HTTPException(status_code=404, detail="AI context log disabled (set AI_CONTEXT_LOG=1)")


@router.get("/")
async def read_chat_filter() -> dict[str, str | bool]:
    _require_enabled()
    chat_id = get_chat_filter()
    return {"enabled": True, "chatId": chat_id}


@router.put("/")
async def update_chat_filter(body: ChatFilterBody) -> dict[str, str | bool]:
    _require_enabled()
    set_chat_filter(body.chatId)
    chat_id = get_chat_filter()
    if chat_id:
        _logger.info("AI context log filter → %s", chat_id)
    else:
        _logger.info("AI context log filter cleared")
    return {"enabled": True, "chatId": chat_id}
