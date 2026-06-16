import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalChat, GlobalNote, Post


async def get_owned_post(session: AsyncSession, user_id: uuid.UUID, post_id: str) -> Post:
    try:
        pid = uuid.UUID(post_id)
        post = await session.get(Post, pid)
        if post is not None and post.user_id == user_id:
            return post
    except ValueError:
        pass

    result = await session.execute(
        select(Post).where(Post.user_id == user_id, Post.data["id"].astext == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


async def get_owned_chat(session: AsyncSession, user_id: uuid.UUID, chat_id: str) -> GlobalChat:
    try:
        cid = uuid.UUID(chat_id)
        chat = await session.get(GlobalChat, cid)
        if chat is not None and chat.user_id == user_id:
            return chat
    except ValueError:
        pass

    result = await session.execute(
        select(GlobalChat).where(GlobalChat.user_id == user_id, GlobalChat.data["id"].astext == chat_id)
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


async def get_owned_note(session: AsyncSession, user_id: uuid.UUID, note_id: str) -> GlobalNote:
    try:
        nid = uuid.UUID(note_id)
        note = await session.get(GlobalNote, nid)
        if note is not None and note.user_id == user_id:
            return note
    except ValueError:
        pass

    result = await session.execute(
        select(GlobalNote).where(GlobalNote.user_id == user_id, GlobalNote.data["id"].astext == note_id)
    )
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note
