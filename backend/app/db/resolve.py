import uuid
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalChat, GlobalNote, Post

_T = TypeVar("_T", Post, GlobalChat, GlobalNote)


async def _get_owned(
    session: AsyncSession,
    model: type[_T],
    user_id: uuid.UUID,
    entity_id: str,
    not_found_detail: str,
) -> _T:
    """Resolve owned entity by UUID PK first, then by JSONB data['id'] fallback."""
    try:
        eid = uuid.UUID(entity_id)
        row = await session.get(model, eid)
        if row is not None and row.user_id == user_id:
            return row
    except ValueError:
        pass

    result = await session.execute(
        select(model).where(model.user_id == user_id, model.data["id"].astext == entity_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row


async def get_owned_post(session: AsyncSession, user_id: uuid.UUID, post_id: str) -> Post:
    return await _get_owned(session, Post, user_id, post_id, "Post not found")


async def get_owned_chat(session: AsyncSession, user_id: uuid.UUID, chat_id: str) -> GlobalChat:
    return await _get_owned(session, GlobalChat, user_id, chat_id, "Chat not found")


async def get_owned_note(session: AsyncSession, user_id: uuid.UUID, note_id: str) -> GlobalNote:
    return await _get_owned(session, GlobalNote, user_id, note_id, "Note not found")
