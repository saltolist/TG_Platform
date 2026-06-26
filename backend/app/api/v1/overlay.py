"""Overlay sync API for presentation/demo per-visitor note storage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser, DbSession, TenantKey
from app.core.tenant import is_overlay_tenant
from app.services.overlay.tenant_notes import sync_tenant_overlay_notes

router = APIRouter(prefix="/overlay", tags=["Overlay"])


class PostNotesSnapshot(BaseModel):
    post_id: str
    notes: list[dict[str, Any]] = Field(default_factory=list)


class OverlayNotesSyncRequest(BaseModel):
    global_notes: list[dict[str, Any]] = Field(default_factory=list)
    global_removed_ids: list[str] = Field(default_factory=list)
    post_snapshots: list[PostNotesSnapshot] = Field(default_factory=list)


@router.put("/notes/", status_code=status.HTTP_204_NO_CONTENT)
async def sync_overlay_notes(
    payload: OverlayNotesSyncRequest,
    user: CurrentUser,
    session: DbSession,
    tenant_key: TenantKey,
) -> Response:
    if not user.is_seed:
        raise HTTPException(status_code=403, detail="Overlay sync is only for seed accounts")
    if not is_overlay_tenant(tenant_key):
        raise HTTPException(
            status_code=422,
            detail="X-Tenant-Session header with guest: or demo: key is required",
        )

    await sync_tenant_overlay_notes(
        session=session,
        user_id=user.id,
        tenant_key=tenant_key,
        global_notes=payload.global_notes,
        global_removed_ids=payload.global_removed_ids,
        post_snapshots=[s.model_dump() for s in payload.post_snapshots],
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
