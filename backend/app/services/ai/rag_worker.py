"""Async background worker for RAG indexing (Phase 2, step 4+).

Architecture:
- enqueue_note_job() / enqueue_post_text_job(): called at upsert/delete time.
- embedding_worker(): long-running asyncio task started in app lifespan.
- enqueue_backfill(): enqueue all notes/posts for a user.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import GlobalNote, Post, Profile, User
from app.services.ai.rag_retrieval_policy import post_id_aliases
from app.services.ai.attachment_text import (
    bytes_content_hash,
    decode_data_url,
    extract_attachment_text,
    media_meta_index_text,
    note_file_record,
    post_media_record,
)
from app.services.ai.rag import (
    NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META,
    NODE_NOTE_CHUNK,
    NODE_NOTE_SUMMARY,
    NODE_POST_TEXT,
    NODE_POST_SUMMARY,
    discovery_keywords,
    index_discovery_summary,
    index_note,
    index_text_node,
    object_index_revision,
    remove_file_nodes_for_parent,
    remove_note,
    remove_text_node,
    upsert_attachment_extraction,
)
from app.services.ai.semantic_summary import (
    DISCOVERY_SUMMARY_VERSION,
    SELECTOR_SUMMARY_VERSION,
    SemanticSummaryProjections,
    build_semantic_summary_projections,
    semantic_summary_model_key,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5


async def _semantic_card(
    *,
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Any,
    object_kind: str,
    title: str,
    text_value: str,
) -> SemanticSummaryProjections:
    return await build_semantic_summary_projections(
        user=user,
        ai_profile=ai_profile,
        settings=settings,
        object_kind=object_kind,
        title=title,
        text_value=text_value,
    )


def is_post_deleted(post_data: Mapping[str, Any]) -> bool:
    return str(post_data.get("status") or "").strip() == "deleted"


def _clean_object_title(value: Any) -> str:
    """Collapse editor/import title repetition to one discovery title."""

    return next(
        (line.strip() for line in str(value or "").splitlines() if line.strip()),
        "",
    )


def _summary_row_is_fresh(
    indexed: set[tuple[str, int, int, str, str, int, int]],
    *,
    node_type: str,
    revision: int,
    model_key: str,
) -> bool:
    if not model_key.startswith("llm:"):
        return False
    return any(
        item[0] == node_type
        and item[1] == revision
        and item[2] == DISCOVERY_SUMMARY_VERSION
        and item[3] == model_key
        and item[3].startswith("llm:")
        and bool(item[4])
        and item[5] == SELECTOR_SUMMARY_VERSION
        and item[6] == 1
        for item in indexed
    )


async def resolve_post_row(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_key: str,
) -> Post | None:
    """Resolve a post by DB UUID or JSONB data.id."""
    key = str(post_key or "").strip()
    if not key:
        return None
    try:
        eid = uuid.UUID(key)
        row = await session.get(Post, eid)
        if row is not None and row.user_id == user_id:
            return row
    except ValueError:
        pass
    result = await session.execute(
        select(Post).where(
            Post.user_id == user_id,
            Post.data["id"].astext == key,
        )
    )
    return result.scalar_one_or_none()


def canonical_post_content_id(post_row: Post) -> str:
    return str(post_row.data.get("id") or post_row.id)


def post_embedding_aliases(post_row: Post) -> frozenset[str]:
    return post_id_aliases(dict(post_row.data), row_post_id=str(post_row.id))


async def purge_post_text_embeddings(
    session: AsyncSession,
    user_id: uuid.UUID,
    aliases: set[str] | frozenset[str],
) -> None:
    """Remove global post_text and media_meta nodes for all known post identifiers."""
    for alias in aliases:
        value = str(alias or "").strip()
        if not value:
            continue
        await remove_text_node(
            session, user_id, "global", NODE_POST_TEXT, value, tenant_key=""
        )
        await remove_text_node(
            session, user_id, "global", NODE_POST_SUMMARY, value, tenant_key=""
        )
        await remove_file_nodes_for_parent(
            session,
            user_id,
            "global",
            value,
            keep_file_ids=set(),
            tenant_key="",
        )


MAX_ATTEMPTS = 3
BATCH_SIZE = 10
SUMMARY_BACKFILL_MAX_JOBS_PER_MINUTE = int(BATCH_SIZE * 60 / POLL_INTERVAL_S)


async def summary_backfill_observability(session: AsyncSession) -> dict[str, Any]:
    """Return explicit queue/failure availability without treating unknown cost as zero."""

    rows = (
        await session.execute(
            text(
                "SELECT status, count(*) AS count FROM embedding_jobs "
                "WHERE op = 'upsert' AND node_type IN (:note_type, :post_type) "
                "GROUP BY status"
            ),
            {"note_type": NODE_NOTE_CHUNK, "post_type": NODE_POST_TEXT},
        )
    ).fetchall()
    counts = {str(row.status): int(row.count or 0) for row in rows}
    return {
        "schema": "workspace.selector-summary-backfill-observability/v1",
        "queue_depth": counts.get("pending", 0) + counts.get("processing", 0),
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "failed": counts.get("failed", 0),
        "done": counts.get("done", 0),
        "rate_limit_jobs_per_minute": SUMMARY_BACKFILL_MAX_JOBS_PER_MINUTE,
        "provider_token_usage": {"availability": "unavailable", "value": None},
        "estimated_cost": {"availability": "unavailable", "value_usd": None},
    }


async def enqueue_note_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    op: str,
    scope: str,
    note_id: str,
    post_id: str | None = None,
    tenant_key: str = "",
    node_type: str = NODE_NOTE_CHUNK,
    file_id: str = "",
) -> None:
    """Insert an embedding job into the queue."""
    settings = get_settings()
    if not settings.rag_enabled:
        return
    await session.execute(
        text(
            "INSERT INTO embedding_jobs "
            "(user_id, tenant_key, op, scope, note_id, post_id, node_type, file_id) "
            "VALUES (:uid, :tk, :op, :scope, :nid, :pid, :nt, :fid)"
        ),
        {
            "uid": str(user_id),
            "tk": tenant_key,
            "op": op,
            "scope": scope,
            "nid": note_id,
            "pid": post_id,
            "nt": node_type,
            "fid": file_id or "",
        },
    )


async def enqueue_post_text_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_id: str,
    op: str = "upsert",
    *,
    post_data: Mapping[str, Any] | None = None,
) -> None:
    """Enqueue indexing for a post's text and media metadata."""
    if op == "upsert" and post_data is not None and is_post_deleted(post_data):
        return
    await enqueue_note_job(
        session,
        user_id,
        op,
        "global",
        post_id,
        post_id=post_id,
        node_type=NODE_POST_TEXT,
    )


async def enqueue_post_rag_delete_jobs(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_data: Mapping[str, Any],
    *,
    db_row_id: str | None = None,
) -> None:
    """Remove all RAG nodes for a post (post_text + post-scoped notes)."""
    settings = get_settings()
    if not settings.rag_enabled:
        return

    effective_post_id = str(post_data.get("id") or "").strip()
    delete_key = str(db_row_id or effective_post_id).strip()
    if not delete_key:
        return

    await enqueue_post_text_job(session, user_id, delete_key, op="delete")
    notes = post_data.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if not isinstance(note, Mapping):
                continue
            note_id = str(note.get("id") or "").strip()
            if note_id:
                await enqueue_note_job(
                    session,
                    user_id,
                    "delete",
                    "post",
                    note_id,
                    effective_post_id or delete_key,
                )


async def enqueue_post_rag_restore_jobs(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_data: Mapping[str, Any],
) -> None:
    """Re-index a restored post's text and notes."""
    if is_post_deleted(post_data):
        return

    effective_post_id = str(post_data.get("id") or "").strip()
    if not effective_post_id:
        return

    await enqueue_post_text_job(session, user_id, effective_post_id)
    notes = post_data.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if not isinstance(note, Mapping):
                continue
            note_id = str(note.get("id") or "").strip()
            if note_id:
                await enqueue_note_job(
                    session,
                    user_id,
                    "upsert",
                    "post",
                    note_id,
                    effective_post_id,
                )


async def enqueue_backfill(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Enqueue all notes and posts for a user for re-indexing."""
    settings = get_settings()
    if not settings.rag_enabled:
        return

    result = await session.execute(
        select(GlobalNote).where(GlobalNote.user_id == user_id)
    )
    for note in result.scalars().all():
        note_id = str(note.data.get("id") or note.id)
        await enqueue_note_job(session, user_id, "upsert", "global", note_id)

    result2 = await session.execute(
        select(Post).where(Post.user_id == user_id)
    )
    for post in result2.scalars().all():
        post_data = dict(post.data)
        if is_post_deleted(post_data):
            continue
        post_id = str(post_data.get("id") or post.id)
        for note in (post_data.get("notes") or []):
            note_id = str(note.get("id") or "")
            if note_id:
                await enqueue_note_job(session, user_id, "upsert", "post", note_id, post_id)
        await enqueue_post_text_job(session, user_id, post_id, post_data=post_data)


async def _index_note_file_nodes(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    note_data: dict[str, Any],
    backend: Any,
    *,
    post_id: str | None,
    tenant_key: str,
    max_chars: int,
) -> None:
    files = [rec for item in (note_data.get("files") or []) if (rec := note_file_record(item))]
    keep_ids = {item["id"] for item in files}
    await remove_file_nodes_for_parent(
        session,
        user_id,
        scope,
        note_id,
        keep_file_ids=keep_ids,
        tenant_key=tenant_key,
    )

    for file_item in files:
        file_id = file_item["id"]
        try:
            decoded = decode_data_url(file_item["url"]) if file_item["url"] else None
            extracted_text: str | None = None
            content_hash_value = ""
            mime_type = file_item["type"]
            if decoded is not None:
                raw_bytes, mime_type = decoded
                content_hash_value = bytes_content_hash(raw_bytes)
                extracted_text = extract_attachment_text(mime_type, raw_bytes)
                await upsert_attachment_extraction(
                    session,
                    user_id,
                    scope,
                    note_id,
                    file_id,
                    content_hash_value,
                    mime_type,
                    extracted_text,
                    tenant_key=tenant_key,
                )

            if extracted_text:
                await index_text_node(
                    session,
                    user_id,
                    scope,
                    NODE_ATTACHMENT_TEXT,
                    note_id,
                    file_id,
                    extracted_text,
                    backend,
                    post_id=post_id,
                    max_chars=max_chars,
                    tenant_key=tenant_key,
                )
            else:
                meta_text = media_meta_index_text(file_item["name"])
                await index_text_node(
                    session,
                    user_id,
                    scope,
                    NODE_MEDIA_META,
                    note_id,
                    file_id,
                    meta_text,
                    backend,
                    post_id=post_id,
                    max_chars=max_chars,
                    tenant_key=tenant_key,
                )
        except Exception as exc:
            logger.warning(
                "Failed to index note file %s for note %s: %s", file_id, note_id, exc
            )


async def _index_post_media_nodes(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_id: str,
    post_data: dict[str, Any],
    backend: Any,
    *,
    max_chars: int,
) -> None:
    media_items = [
        post_media_record(item, index)
        for index, item in enumerate(post_data.get("media") or [])
        if isinstance(item, dict)
    ]
    keep_ids = {item["id"] for item in media_items}
    await remove_file_nodes_for_parent(
        session,
        user_id,
        "global",
        post_id,
        keep_file_ids=keep_ids,
        tenant_key="",
    )

    for media_item in media_items:
        try:
            meta_text = media_meta_index_text(media_item["name"])
            await index_text_node(
                session,
                user_id,
                "global",
                NODE_MEDIA_META,
                post_id,
                media_item["id"],
                meta_text,
                backend,
                post_id=post_id,
                max_chars=max_chars,
                tenant_key="",
            )
        except Exception as exc:
            logger.warning(
                "Failed to index post media %s for post %s: %s",
                media_item["id"],
                post_id,
                exc,
            )


async def _process_job(
    job_id: str,
    user_id: uuid.UUID,
    op: str,
    scope: str,
    note_id: str,
    post_id: str | None,
    tenant_key: str,
    node_type: str,
    file_id: str,
    session: AsyncSession,
) -> str | None:
    from app.services.ai.embeddings import resolve_embedding_backend
    from app.services.overlay.tenant_notes import get_tenant_note

    settings = get_settings()

    if op == "delete":
        if node_type == NODE_POST_TEXT:
            post_row = await resolve_post_row(session, user_id, note_id)
            if post_row is not None:
                await purge_post_text_embeddings(
                    session, user_id, post_embedding_aliases(post_row)
                )
            else:
                await purge_post_text_embeddings(session, user_id, {note_id})
        else:
            await remove_note(session, user_id, scope, note_id, tenant_key=tenant_key)
            await remove_file_nodes_for_parent(
                session, user_id, scope, note_id, keep_file_ids=set(), tenant_key=tenant_key
            )
        return None

    user_result = await session.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": str(user_id)},
    )
    if user_result.fetchone() is None:
        return None

    user = await session.get(User, user_id)
    if user is None:
        return None

    backend = resolve_embedding_backend(user, {}, settings)
    max_chars = settings.rag_max_note_chars
    profile = await session.get(Profile, user_id)
    ai_profile = dict(profile.ai or {}) if profile and isinstance(profile.ai, Mapping) else {}

    if node_type == NODE_POST_TEXT:
        post_row = await resolve_post_row(session, user_id, note_id)
        if post_row is None:
            await purge_post_text_embeddings(session, user_id, {note_id})
            logger.debug(
                "post_text upsert: no post for key %s, purged orphan embedding(s)",
                note_id,
            )
            return
        aliases = post_embedding_aliases(post_row)
        post_data = dict(post_row.data)
        if is_post_deleted(post_data):
            await purge_post_text_embeddings(session, user_id, aliases)
            return
        canonical_id = canonical_post_content_id(post_row)
        await purge_post_text_embeddings(session, user_id, aliases)
        text_value = str(post_data.get("text") or "").strip()
        post_title = str(post_data.get("title") or "").strip()
        if not post_title and text_value:
            post_title = text_value.splitlines()[0].strip()[:160]
        post_status = str(post_data.get("status") or "draft").strip().lower()
        post_revision = object_index_revision(post_data)
        semantic_retry_reason: str | None = None
        if text_value:
            summaries = await _semantic_card(
                user=user,
                ai_profile=ai_profile,
                settings=settings,
                object_kind="post",
                title=post_title,
                text_value=text_value,
            )
            await index_text_node(
                session,
                user_id,
                "global",
                NODE_POST_TEXT,
                canonical_id,
                "",
                text_value,
                backend,
                post_id=canonical_id,
                max_chars=max_chars,
                object_title=post_title,
                object_status=post_status,
                index_revision=post_revision,
                keywords=discovery_keywords(f"{post_title} {text_value}"),
            )
            await index_discovery_summary(
                session,
                user_id,
                "global",
                NODE_POST_SUMMARY,
                canonical_id,
                post_title,
                text_value,
                backend,
                post_id=canonical_id,
                object_status=post_status,
                index_revision=post_revision,
                keywords=discovery_keywords(f"{post_title} {text_value}"),
                max_chars=max_chars,
                summary_text=summaries.discovery_summary,
                summary_version=DISCOVERY_SUMMARY_VERSION,
                summary_model=summaries.model_key,
                selector_summary=summaries.selector_summary,
                selector_summary_version=summaries.selector_summary_version,
                selector_semantic_flags=summaries.selector_semantic_flags,
            )
            if summaries.selector_summary_version != SELECTOR_SUMMARY_VERSION:
                semantic_retry_reason = summaries.generation_status
        else:
            await remove_text_node(
                session, user_id, "global", NODE_POST_TEXT, canonical_id, tenant_key=""
            )
            await remove_text_node(
                session, user_id, "global", NODE_POST_SUMMARY, canonical_id, tenant_key=""
            )
        await _index_post_media_nodes(
            session, user_id, canonical_id, post_data, backend, max_chars=max_chars
        )
        return semantic_retry_reason

    if tenant_key:
        note_data = await get_tenant_note(session, user_id, tenant_key, scope, note_id)
        if note_data is None:
            return None
        title = _clean_object_title(note_data.get("title", ""))
        body = note_data.get("body", "")
        summaries = await _semantic_card(
            user=user,
            ai_profile=ai_profile,
            settings=settings,
            object_kind="note",
            title=title,
            text_value=body,
        )
        await index_note(
            session,
            user_id,
            scope,
            note_id,
            title,
            body,
            backend,
            post_id=post_id or note_data.get("postId"),
            max_chars=max_chars,
            tenant_key=tenant_key,
            object_status=str(note_data.get("status") or "active"),
            index_revision=object_index_revision(note_data),
            discovery_summary=summaries.discovery_summary,
            discovery_summary_version=DISCOVERY_SUMMARY_VERSION,
            discovery_summary_model=summaries.model_key,
            selector_summary=summaries.selector_summary,
            selector_summary_version=summaries.selector_summary_version,
            selector_semantic_flags=summaries.selector_semantic_flags,
        )
        await _index_note_file_nodes(
            session,
            user_id,
            scope,
            note_id,
            note_data,
            backend,
            post_id=post_id or note_data.get("postId"),
            tenant_key=tenant_key,
            max_chars=max_chars,
        )
        return (
            None
            if summaries.selector_summary_version == SELECTOR_SUMMARY_VERSION
            else summaries.generation_status
        )

    if scope == "global":
        result = await session.execute(
            select(GlobalNote).where(
                GlobalNote.user_id == user_id,
                GlobalNote.data["id"].astext == note_id,
            )
        )
        note_row = result.scalar_one_or_none()
        if note_row is None:
            return None
        note_data = dict(note_row.data)
        summaries = await _semantic_card(
            user=user,
            ai_profile=ai_profile,
            settings=settings,
            object_kind="note",
            title=_clean_object_title(note_data.get("title", "")),
            text_value=str(note_data.get("body") or ""),
        )
        await index_note(
            session,
            user_id,
            scope,
            note_id,
            _clean_object_title(note_data.get("title", "")),
            note_data.get("body", ""),
            backend,
            max_chars=max_chars,
            object_status=str(note_data.get("status") or "active"),
            index_revision=object_index_revision(note_data),
            discovery_summary=summaries.discovery_summary,
            discovery_summary_version=DISCOVERY_SUMMARY_VERSION,
            discovery_summary_model=summaries.model_key,
            selector_summary=summaries.selector_summary,
            selector_summary_version=summaries.selector_summary_version,
            selector_semantic_flags=summaries.selector_semantic_flags,
        )
        await _index_note_file_nodes(
            session,
            user_id,
            scope,
            note_id,
            note_data,
            backend,
            post_id=None,
            tenant_key="",
            max_chars=max_chars,
        )
        return (
            None
            if summaries.selector_summary_version == SELECTOR_SUMMARY_VERSION
            else summaries.generation_status
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
            return None
        if is_post_deleted(dict(post_row.data)):
            await remove_note(session, user_id, scope, note_id, tenant_key=tenant_key)
            await remove_file_nodes_for_parent(
                session, user_id, scope, note_id, keep_file_ids=set(), tenant_key=tenant_key
            )
            return
        for note in (post_row.data.get("notes") or []):
            if str(note.get("id", "")) == note_id:
                note_data = dict(note)
                summaries = await _semantic_card(
                    user=user,
                    ai_profile=ai_profile,
                    settings=settings,
                    object_kind="note",
                    title=_clean_object_title(note_data.get("title", "")),
                    text_value=str(note_data.get("body") or ""),
                )
                await index_note(
                    session,
                    user_id,
                    scope,
                    note_id,
                    _clean_object_title(note_data.get("title", "")),
                    note_data.get("body", ""),
                    backend,
                    post_id=post_id,
                    max_chars=max_chars,
                    object_status=str(note_data.get("status") or "active"),
                    index_revision=object_index_revision(note_data),
                    discovery_summary=summaries.discovery_summary,
                    discovery_summary_version=DISCOVERY_SUMMARY_VERSION,
                    discovery_summary_model=summaries.model_key,
                    selector_summary=summaries.selector_summary,
                    selector_summary_version=summaries.selector_summary_version,
                    selector_semantic_flags=summaries.selector_semantic_flags,
                )
                await _index_note_file_nodes(
                    session,
                    user_id,
                    scope,
                    note_id,
                    note_data,
                    backend,
                    post_id=post_id,
                    tenant_key="",
                    max_chars=max_chars,
                )
                return (
                    None
                    if summaries.selector_summary_version == SELECTOR_SUMMARY_VERSION
                    else summaries.generation_status
                )
    return None


async def startup_backfill_all(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Enqueue indexing jobs for notes/posts missing embeddings."""
    from app.services.ai.embeddings import resolve_embedding_backend

    settings = get_settings()
    if not settings.rag_enabled:
        return

    async with session_factory() as session:
        async with session.begin():
            user_query = select(User)
            backfill_email = str(
                settings.rag_startup_backfill_user_email or ""
            ).strip().lower()
            if backfill_email:
                user_query = user_query.where(
                    func.lower(func.trim(User.email)) == backfill_email
                )
            users = (await session.execute(user_query)).scalars().all()
            enqueued = 0
            for user in users:
                user_id = user.id
                model_key = resolve_embedding_backend(user, {}, settings).model_key
                profile = await session.get(Profile, user_id)
                ai_profile = (
                    dict(profile.ai or {})
                    if profile and isinstance(profile.ai, Mapping)
                    else {}
                )
                expected_summary_model = semantic_summary_model_key(
                    user, ai_profile, settings
                )
                gn_rows = (
                    await session.execute(
                        select(GlobalNote).where(GlobalNote.user_id == user_id)
                    )
                ).scalars().all()
                for note in gn_rows:
                    note_id = str(note.data.get("id") or note.id)
                    expected_revision = object_index_revision(
                        {**dict(note.data), "status": note.data.get("status") or "active"}
                    )
                    exists = await session.execute(
                        text(
                            "SELECT node_type, index_revision, summary_version, summary_model, "
                            "selector_summary, selector_summary_version, selector_semantic_flags "
                            "FROM note_embeddings "
                            "WHERE user_id = :uid AND scope = 'global' AND note_id = :nid "
                            "AND node_type IN (:chunk_nt, :summary_nt) AND model_key = :mk"
                        ),
                        {
                            "uid": str(user_id),
                            "nid": note_id,
                            "chunk_nt": NODE_NOTE_CHUNK,
                            "summary_nt": NODE_NOTE_SUMMARY,
                            "mk": model_key,
                        },
                    )
                    indexed = {
                        (
                            str(row.node_type),
                            int(row.index_revision or 1),
                            int(row.summary_version or 0),
                            str(row.summary_model or ""),
                            str(row.selector_summary or ""),
                            int(row.selector_summary_version or 0),
                            int((row.selector_semantic_flags or {}).get("v") or 0),
                        )
                        for row in exists.fetchall()
                    }
                    if (
                        not any(
                            item[0] == NODE_NOTE_CHUNK and item[1] == expected_revision
                            for item in indexed
                        )
                        or not _summary_row_is_fresh(
                            indexed,
                            node_type=NODE_NOTE_SUMMARY,
                            revision=expected_revision,
                            model_key=expected_summary_model,
                        )
                    ):
                        await enqueue_note_job(session, user_id, "upsert", "global", note_id)
                        enqueued += 1

                post_rows = (
                    await session.execute(select(Post).where(Post.user_id == user_id))
                ).scalars().all()
                for post in post_rows:
                    post_data = dict(post.data)
                    if is_post_deleted(post_data):
                        continue
                    canonical_id = canonical_post_content_id(post)
                    aliases = post_embedding_aliases(post)
                    for note in (post_data.get("notes") or []):
                        note_id = str(note.get("id") or "")
                        if not note_id:
                            continue
                        expected_revision = object_index_revision(
                            {**dict(note), "status": note.get("status") or "active"}
                        )
                        exists = await session.execute(
                            text(
                                "SELECT node_type, index_revision, summary_version, summary_model, "
                                "selector_summary, selector_summary_version, selector_semantic_flags "
                                "FROM note_embeddings "
                                "WHERE user_id = :uid AND scope = 'post' AND note_id = :nid "
                                "AND node_type IN (:chunk_nt, :summary_nt) AND model_key = :mk"
                            ),
                            {
                                "uid": str(user_id),
                                "nid": note_id,
                                "chunk_nt": NODE_NOTE_CHUNK,
                                "summary_nt": NODE_NOTE_SUMMARY,
                                "mk": model_key,
                            },
                        )
                        indexed = {
                            (
                                str(row.node_type),
                                int(row.index_revision or 1),
                                int(row.summary_version or 0),
                                str(row.summary_model or ""),
                                str(row.selector_summary or ""),
                                int(row.selector_summary_version or 0),
                                int((row.selector_semantic_flags or {}).get("v") or 0),
                            )
                            for row in exists.fetchall()
                        }
                        if (
                            not any(
                                item[0] == NODE_NOTE_CHUNK and item[1] == expected_revision
                                for item in indexed
                            )
                            or not _summary_row_is_fresh(
                                indexed,
                                node_type=NODE_NOTE_SUMMARY,
                                revision=expected_revision,
                                model_key=expected_summary_model,
                            )
                        ):
                            await enqueue_note_job(
                                session, user_id, "upsert", "post", note_id, canonical_id
                            )
                            enqueued += 1

                    expected_post_revision = object_index_revision(post_data)
                    exists_canonical = await session.execute(
                        text(
                            "SELECT node_type, index_revision, summary_version, summary_model, "
                            "selector_summary, selector_summary_version, selector_semantic_flags "
                            "FROM note_embeddings "
                            "WHERE user_id = :uid AND scope = 'global' AND note_id = :pid "
                            "AND node_type IN (:text_nt, :summary_nt) AND model_key = :mk"
                        ),
                        {
                            "uid": str(user_id),
                            "pid": canonical_id,
                            "text_nt": NODE_POST_TEXT,
                            "summary_nt": NODE_POST_SUMMARY,
                            "mk": model_key,
                        },
                    )
                    indexed = {
                        (
                            str(row.node_type),
                            int(row.index_revision or 1),
                            int(row.summary_version or 0),
                            str(row.summary_model or ""),
                            str(row.selector_summary or ""),
                            int(row.selector_summary_version or 0),
                            int((row.selector_semantic_flags or {}).get("v") or 0),
                        )
                        for row in exists_canonical.fetchall()
                    }
                    canonical_exists = (
                        any(
                            item[0] == NODE_POST_TEXT and item[1] == expected_post_revision
                            for item in indexed
                        )
                        and _summary_row_is_fresh(
                            indexed,
                            node_type=NODE_POST_SUMMARY,
                            revision=expected_post_revision,
                            model_key=expected_summary_model,
                        )
                    )
                    has_stale_alias = False
                    if canonical_exists:
                        for alias in aliases:
                            if alias == canonical_id:
                                continue
                            stale = await session.execute(
                                text(
                                    "SELECT 1 FROM note_embeddings "
                                    "WHERE user_id = :uid AND scope = 'global' AND note_id = :nid "
                                    "AND node_type IN (:pt, :mm) LIMIT 1"
                                ),
                                {
                                    "uid": str(user_id),
                                    "nid": alias,
                                    "pt": NODE_POST_TEXT,
                                    "mm": NODE_MEDIA_META,
                                },
                            )
                            if stale.fetchone() is not None:
                                has_stale_alias = True
                                break

                    if not canonical_exists or has_stale_alias:
                        await enqueue_post_text_job(
                            session, user_id, canonical_id, post_data=post_data
                        )
                        enqueued += 1

    if enqueued:
        logger.info("RAG startup backfill: enqueued %d job(s) for indexing", enqueued)


async def cleanup_deleted_post_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Enqueue delete jobs for embeddings tied to soft-deleted posts."""
    settings = get_settings()
    if not settings.rag_enabled:
        return 0

    enqueued = 0
    async with session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    text(
                        "SELECT DISTINCT p.user_id, p.data "
                        "FROM posts p "
                        "WHERE p.data->>'status' = 'deleted'"
                    )
                )
            ).fetchall()
            for row in rows:
                post_data = row.data if isinstance(row.data, dict) else {}
                if not post_data.get("id"):
                    continue
                await enqueue_post_rag_delete_jobs(
                    session,
                    uuid.UUID(str(row.user_id)),
                    post_data,
                )
                enqueued += 1

    if enqueued:
        logger.info(
            "RAG deleted-post cleanup: enqueued delete jobs for %d post(s)",
            enqueued,
        )
    return enqueued


async def embedding_worker(
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event | None = None,
) -> None:
    """Long-running worker. Exits when stop_event is set or RAG_ENABLED=0."""
    settings = get_settings()
    if not settings.rag_enabled:
        logger.info("RAG disabled — embedding worker not started.")
        return

    logger.info("Embedding worker started.")
    await cleanup_deleted_post_embeddings(session_factory)
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
                        "SELECT id, user_id, tenant_key, op, scope, note_id, post_id, "
                        "node_type, file_id, attempts "
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
                        semantic_retry_reason = await _process_job(
                            jid,
                            uuid.UUID(str(row.user_id)),
                            row.op,
                            row.scope,
                            row.note_id,
                            row.post_id,
                            row.tenant_key or "",
                            row.node_type or NODE_NOTE_CHUNK,
                            row.file_id or "",
                            s,
                        )
                async with session_factory() as s:
                    async with s.begin():
                        if semantic_retry_reason:
                            await s.execute(
                                text(
                                    "UPDATE embedding_jobs SET status = "
                                    "CASE WHEN attempts >= :max_att THEN 'failed' ELSE 'pending' END, "
                                    "error = :err WHERE id = :id"
                                ),
                                {
                                    "id": jid,
                                    "max_att": MAX_ATTEMPTS,
                                    "err": f"selector_summary:{semantic_retry_reason}"[:500],
                                },
                            )
                        else:
                            await s.execute(
                                text(
                                    "UPDATE embedding_jobs SET status = 'done', error = NULL "
                                    "WHERE id = :id"
                                ),
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
