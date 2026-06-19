import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.deps import CurrentUser, CurrentWriter, DbSession
from app.db.models import GlobalChat
from app.db.resolve import get_owned_chat
from app.services.ai.chat_history import merge_history_stamps
from app.schemas.requests import MessageRequest
from app.schemas.resources import GlobalChatIn
from app.services.ai import generate_reply

router = APIRouter(prefix="/global-chats", tags=["GlobalChats"])


@router.get("/")
async def list_chats(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(GlobalChat).where(GlobalChat.user_id == user.id).order_by(GlobalChat.created_at)
    )
    return [chat.data for chat in result.scalars().all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_chat(
    payload: GlobalChatIn, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    try:
        chat_id = uuid.UUID(payload.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный id чата")

    data = payload.model_dump()
    session.add(GlobalChat(id=chat_id, user_id=user.id, data=data))
    await session.commit()
    return data


@router.post("/{chat_id}/messages/")
async def add_message(
    chat_id: str, payload: MessageRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    chat = await get_owned_chat(session, user.id, chat_id)

    history = list(chat.data.get("history", []))
    history.append({"role": "user", "text": payload.text})
    reply = generate_reply(payload.text, scope="global")
    history.append({"role": "ai", "text": reply})

    chat.data = {
        **chat.data,
        "history": history,
        "preview": reply[:120],
        "date": datetime.now(timezone.utc).isoformat(),
    }
    await session.commit()
    return chat.data


@router.patch("/{chat_id}/")
async def update_chat(
    chat_id: str, patch: dict[str, Any], user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    chat = await get_owned_chat(session, user.id, chat_id)
    merged = {**chat.data, **patch}
    if isinstance(patch.get("history"), list):
        merged["history"] = merge_history_stamps(
            list(chat.data.get("history") or []),
            patch["history"],
            strip_incoming=True,
        )
    merged["id"] = chat.data.get("id", str(chat.id))
    chat.data = merged
    await session.commit()
    return merged


@router.delete("/{chat_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: str, user: CurrentWriter, session: DbSession) -> Response:
    chat = await get_owned_chat(session, user.id, chat_id)
    await session.delete(chat)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
