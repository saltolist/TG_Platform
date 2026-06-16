import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.db.models import GlobalNote
from app.schemas.resources import GlobalNoteIn

router = APIRouter(prefix="/global-notes", tags=["GlobalNotes"])


@router.get("/")
async def list_notes(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(GlobalNote).where(GlobalNote.user_id == user.id).order_by(GlobalNote.created_at)
    )
    return [note.data for note in result.scalars().all()]


@router.put("/{note_id}/")
async def upsert_note(
    note_id: str, payload: GlobalNoteIn, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    if payload.id != note_id:
        raise HTTPException(status_code=422, detail="id в теле не совпадает с id в пути")
    try:
        nid = uuid.UUID(note_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный id заметки")

    data = payload.model_dump()
    note = await session.get(GlobalNote, nid)
    if note is None:
        session.add(GlobalNote(id=nid, user_id=user.id, data=data))
    elif note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    else:
        note.data = data
    await session.commit()
    return data


@router.delete("/{note_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: str, user: CurrentUser, session: DbSession) -> Response:
    try:
        nid = uuid.UUID(note_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Note not found")
    note = await session.get(GlobalNote, nid)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    await session.delete(note)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
