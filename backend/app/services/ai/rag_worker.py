"""Async background worker for RAG note indexing (Phase 2, step 4).

Architecture:
- enqueue_note_job(): called at upsert/delete time (in the same DB transaction).
- embedding_worker(): long-running asyncio task started in app lifespan.
  Uses SELECT ... FOR UPDATE SKIP LOCKED for concurrent-safe job processing.
- enqueue_backfill(): enqueue all notes for a user (called on model change).

The worker polls every POLL_INTERVAL_S seconds.  When RAG_ENABLED=0 it exits
immediately.  Errors are logged and retried up to MAX_ATTEMPTS times.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import GlobalNote, Post, User

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5
MAX_ATTEMPTS = 3
BATCH_SIZE = 10


async def enqueue_note_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    op: str,        # "upsert" | "delete"
    scope: str,     # "global" | "post"
    note_id: str,
    post_id: str | None = None,
    tenant_key: str = "",
) -> None:
    """Insert an embedding job into the queue (fast, same transaction as note save)."""
    settings = get_settings()
    if not settings.rag_enabled:
        return
    await session.execute(
        text(
            "INSERT INTO embedding_jobs (user_id, tenant_key, op, scope, note_id, post_id) "
            "VALUES (:uid, :tk, :op, :scope, :nid, :pid)"
        ),
        {
            "uid": str(user_id),
            "tk": tenant_key,
            "op": op,
            "scope": scope,
            "nid": note_id,
            "pid": post_id,
        },
    )


async def enqueue_backfill(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Enqueue all notes for a user for re-indexing (e.g. after model change)."""
    settings = get_settings()
    if not settings.rag_enabled:
        return

    # Global notes
    result = await session.execute(
        select(GlobalNote).where(GlobalNote.user_id == user_id)
    )
    for note in result.scalars().all():
        note_id = str(note.data.get("id") or note.id)
        await enqueue_note_job(session, user_id, "upsert", "global", note_id)

    # Post notes
    result2 = await session.execute(
        select(Post).where(Post.user_id == user_id)
    )
    for post in result2.scalars().all():
        post_id = str(post.data.get("id") or post.id)
        for note in (post.data.get("notes") or []):
            note_id = str(note.get("id") or "")
            if note_id:
                await enqueue_note_job(session, user_id, "upsert", "post", note_id, post_id)


async def _process_job(
    job_id: str,
    user_id: uuid.UUID,
    op: str,
    scope: str,
    note_id: str,
    post_id: str | None,
    tenant_key: str,
    session: AsyncSession,
) -> None:
    """Process a single embedding job."""
    from app.services.ai.embeddings import resolve_embedding_backend
    from app.services.ai.rag import index_note, remove_note
    from app.services.overlay.tenant_notes import get_tenant_note

    settings = get_settings()

    if op == "delete":
        await remove_note(session, user_id, scope, note_id, tenant_key=tenant_key)
        return

    # Resolve embedding backend (global config, no per-user profile needed for local)
    user_result = await session.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": str(user_id)},
    )
    if user_result.fetchone() is None:
        return  # user deleted

    from app.db.models import User
    user = await session.get(User, user_id)
    if user is None:
        return

    backend = resolve_embedding_backend(user, {}, settings)

    if tenant_key:
        note_data = await get_tenant_note(session, user_id, tenant_key, scope, note_id)
        if note_data is None:
            return
        title = note_data.get("title", "")
        body = note_data.get("body", "")
        await index_note(
            session,
            user_id,
            scope,
            note_id,
            title,
            body,
            backend,
            post_id=post_id or note_data.get("postId"),
            max_chars=settings.rag_max_note_chars,
            tenant_key=tenant_key,
        )
        return

    if scope == "global":
        result = await session.execute(
            select(GlobalNote).where(
                GlobalNote.user_id == user_id,
                GlobalNote.data["id"].astext == note_id,
            )
        )
        note_row = result.scalar_one_or_none()
        if note_row is None:
            return
        title = note_row.data.get("title", "")
        body = note_row.data.get("body", "")
        await index_note(
            session, user_id, scope, note_id, title, body, backend,
            max_chars=settings.rag_max_note_chars,
        )

    elif scope == "post" and post_id:
        result2 = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["id"].astext == post_id,
            )
        )
        post_row = result2.scalar_one_or_none()
        if post_row is None:
            return
        for note in (post_row.data.get("notes") or []):
            if str(note.get("id", "")) == note_id:
                title = note.get("title", "")
                body = note.get("body", "")
                await index_note(
                    session, user_id, scope, note_id, title, body, backend,
                    post_id=post_id,
                    max_chars=settings.rag_max_note_chars,
                )
                break


async def startup_backfill_all(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Enqueue indexing jobs for all notes that have no embeddings yet.

    Called once when the embedding worker starts so notes created while RAG was
    disabled (or before first deploy) get indexed without manual intervention.
    """
    settings = get_settings()
    if not settings.rag_enabled:
        return

    async with session_factory() as session:
        async with session.begin():
            users = (await session.execute(select(User.id))).scalars().all()
            enqueued = 0
            for user_id in users:
                # Global notes without any embedding row
                gn_rows = (
                    await session.execute(
                        select(GlobalNote).where(GlobalNote.user_id == user_id)
                    )
                ).scalars().all()
                for note in gn_rows:
                    note_id = str(note.data.get("id") or note.id)
                    exists = await session.execute(
                        text(
                            "SELECT 1 FROM note_embeddings "
                            "WHERE user_id = :uid AND scope = 'global' AND note_id = :nid LIMIT 1"
                        ),
                        {"uid": str(user_id), "nid": note_id},
                    )
                    if exists.fetchone() is None:
                        await enqueue_note_job(session, user_id, "upsert", "global", note_id)
                        enqueued += 1

                # Post notes without embeddings
                post_rows = (
                    await session.execute(select(Post).where(Post.user_id == user_id))
                ).scalars().all()
                for post in post_rows:
                    post_id = str(post.data.get("id") or post.id)
                    for note in (post.data.get("notes") or []):
                        note_id = str(note.get("id") or "")
                        if not note_id:
                            continue
                        exists = await session.execute(
                            text(
                                "SELECT 1 FROM note_embeddings "
                                "WHERE user_id = :uid AND scope = 'post' AND note_id = :nid LIMIT 1"
                            ),
                            {"uid": str(user_id), "nid": note_id},
                        )
                        if exists.fetchone() is None:
                            await enqueue_note_job(
                                session, user_id, "upsert", "post", note_id, post_id
                            )
                            enqueued += 1

    if enqueued:
        logger.info("RAG startup backfill: enqueued %d note(s) for indexing", enqueued)


async def embedding_worker(
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event | None = None,
) -> None:
    """Long-running worker.  Exits when stop_event is set or RAG_ENABLED=0."""
    settings = get_settings()
    if not settings.rag_enabled:
        logger.info("RAG disabled — embedding worker not started.")
        return

    logger.info("Embedding worker started.")
    await startup_backfill_all(session_factory)
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            await _process_batch(session_factory)
        except Exception as exc:
            logger.exception("Embedding worker batch error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_S)

    logger.info("Embedding worker stopped.")


async def _process_batch(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    text(
                        "SELECT id, user_id, tenant_key, op, scope, note_id, post_id, attempts "
                        "FROM embedding_jobs "
                        "WHERE status = 'pending' AND attempts < :max_att "
                        "ORDER BY enqueued_at "
                        "LIMIT :batch "
                        "FOR UPDATE SKIP LOCKED"
                    ),
                    {"max_att": MAX_ATTEMPTS, "batch": BATCH_SIZE},
                )
            ).fetchall()

            if not rows:
                return

            # Mark as processing
            job_ids = [str(row.id) for row in rows]
            await session.execute(
                text(
                    "UPDATE embedding_jobs SET status = 'processing', "
                    "locked_at = now(), attempts = attempts + 1 "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": job_ids},
            )

        for row in rows:
            jid = str(row.id)
            try:
                async with session_factory() as s:
                    async with s.begin():
                        await _process_job(
                            jid,
                            uuid.UUID(str(row.user_id)),
                            row.op,
                            row.scope,
                            row.note_id,
                            row.post_id,
                            row.tenant_key or "",
                            s,
                        )
                async with session_factory() as s:
                    async with s.begin():
                        await s.execute(
                            text("UPDATE embedding_jobs SET status = 'done' WHERE id = :id"),
                            {"id": jid},
                        )
            except Exception as exc:
                logger.warning("Embedding job %s failed: %s", jid, exc)
                async with session_factory() as s:
                    async with s.begin():
                        await s.execute(
                            text(
                                "UPDATE embedding_jobs SET status = "
                                "CASE WHEN attempts >= :max_att THEN 'failed' ELSE 'pending' END, "
                                "error = :err WHERE id = :id"
                            ),
                            {"id": jid, "max_att": MAX_ATTEMPTS, "err": str(exc)[:500]},
                        )
