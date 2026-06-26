"""Persist and sync per-tenant overlay notes for presentation/demo visitors."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.rag_worker import enqueue_note_job


async def upsert_tenant_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_key: str,
    scope: str,
    note_id: str,
    data: dict[str, Any],
    post_id: str | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO tenant_overlay_notes "
            "(user_id, tenant_key, scope, note_id, post_id, data, updated_at) "
            "VALUES (:uid, :tk, :scope, :nid, :pid, CAST(:data AS jsonb), now()) "
            "ON CONFLICT (user_id, tenant_key, scope, note_id) DO UPDATE "
            "SET data = EXCLUDED.data, post_id = EXCLUDED.post_id, updated_at = now()"
        ),
        {
            "uid": str(user_id),
            "tk": tenant_key,
            "scope": scope,
            "nid": note_id,
            "pid": post_id,
            "data": _json_dumps(data),
        },
    )
    await enqueue_note_job(
        session, user_id, "upsert", scope, note_id, post_id, tenant_key=tenant_key
    )


async def delete_tenant_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_key: str,
    scope: str,
    note_id: str,
    post_id: str | None = None,
) -> None:
    await session.execute(
        text(
            "DELETE FROM tenant_overlay_notes "
            "WHERE user_id = :uid AND tenant_key = :tk AND scope = :scope AND note_id = :nid"
        ),
        {"uid": str(user_id), "tk": tenant_key, "scope": scope, "nid": note_id},
    )
    await enqueue_note_job(
        session,
        user_id,
        "delete",
        scope,
        note_id,
        post_id=post_id,
        tenant_key=tenant_key,
    )


async def get_tenant_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_key: str,
    scope: str,
    note_id: str,
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT data FROM tenant_overlay_notes "
                "WHERE user_id = :uid AND tenant_key = :tk AND scope = :scope AND note_id = :nid"
            ),
            {"uid": str(user_id), "tk": tenant_key, "scope": scope, "nid": note_id},
        )
    ).fetchone()
    if row is None:
        return None
    return dict(row.data)


async def sync_tenant_overlay_notes(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_key: str,
    global_notes: list[dict[str, Any]],
    global_removed_ids: list[str],
    post_snapshots: list[dict[str, Any]],
) -> None:
    """Replace tenant overlay note snapshot and enqueue RAG jobs."""
    for note_id in global_removed_ids:
        if note_id:
            await delete_tenant_note(session, user_id, tenant_key, "global", note_id)

    for note in global_notes:
        note_id = str(note.get("id") or "")
        if not note_id:
            continue
        await upsert_tenant_note(session, user_id, tenant_key, "global", note_id, note)

    for snapshot in post_snapshots:
        post_id = str(snapshot.get("post_id") or "")
        if not post_id:
            continue
        notes = snapshot.get("notes") or []
        incoming_ids = {str(n.get("id") or "") for n in notes if n.get("id")}

        existing = (
            await session.execute(
                text(
                    "SELECT note_id FROM tenant_overlay_notes "
                    "WHERE user_id = :uid AND tenant_key = :tk AND scope = 'post' AND post_id = :pid"
                ),
                {"uid": str(user_id), "tk": tenant_key, "pid": post_id},
            )
        ).fetchall()
        for row in existing:
            if row.note_id not in incoming_ids:
                await delete_tenant_note(
                    session,
                    user_id,
                    tenant_key,
                    "post",
                    row.note_id,
                    post_id=post_id,
                )

        for note in notes:
            note_id = str(note.get("id") or "")
            if not note_id:
                continue
            await upsert_tenant_note(
                session, user_id, tenant_key, "post", note_id, note, post_id=post_id
            )


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)
