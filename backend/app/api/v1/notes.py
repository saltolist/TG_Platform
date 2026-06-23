import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.deps import CurrentUser, CurrentWriter, DbSession
from app.db.models import GlobalNote
from app.db.resolve import get_owned_note
from app.db.seed_ids import seed_entity_uuid
from app.schemas.resources import GlobalNoteIn
from app.services.ai.rag_worker import enqueue_note_job

router = APIRouter(prefix="/global-notes", tags=["GlobalNotes"])


@router.get("/")
async def list_notes(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(GlobalNote).where(GlobalNote.user_id == user.id).order_by(GlobalNote.created_at)
    )
    return [note.data for note in result.scalars().all()]


@router.put("/{note_id}/")
async def upsert_note(
    note_id: str, payload: GlobalNoteIn, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    if payload.id != note_id:
        raise HTTPException(status_code=422, detail="id в теле не совпадает с id в пути")
    data = payload.model_dump()
    try:
        nid = uuid.UUID(note_id)
    except ValueError:
        nid = seed_entity_uuid("global_note", note_id)

    note = await session.get(GlobalNote, nid)
    if note is None:
        result = await session.execute(
            select(GlobalNote).where(
                GlobalNote.user_id == user.id, GlobalNote.data["id"].astext == note_id
            )
        )
        note = result.scalar_one_or_none()

    if note is None:
        session.add(GlobalNote(id=nid, user_id=user.id, data=data))
    elif note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    else:
        note.data = data
    await enqueue_note_job(session, user.id, "upsert", "global", note_id)
    await session.commit()
    return data


@router.delete("/{note_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: str, user: CurrentWriter, session: DbSession) -> Response:
    note = await get_owned_note(session, user.id, note_id)
    await enqueue_note_job(session, user.id, "delete", "global", note_id)
    await session.delete(note)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
