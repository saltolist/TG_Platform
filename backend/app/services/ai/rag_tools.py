"""L2 agentic RAG read tools (deterministic executor)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Profile, User
from app.db.resolve import get_owned_post
from app.services.ai.attachment_fetch import resolve_attachment_bytes
from app.services.ai.attachment_text import (
    bytes_content_hash,
    extract_attachment_text,
    note_file_record,
    post_media_file_id,
    post_media_record,
)
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag import (
    NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META,
    NODE_NOTE_CHUNK,
    NODE_POST_TEXT,
    get_attachment_extraction,
    get_attachment_extraction_by_hash,
    get_note_data,
    markdown_to_index_text,
    resolve_post_data,
    upsert_attachment_extraction,
    _post_title_from_text,
)
from app.services.ai.rag_retrieval_policy import post_id_aliases, retrieve_for_chat
from app.services.analytics.analytics_snapshot import load_post_snapshots
from app.services.analytics.channel_metrics import VALID_PERIODS
from app.services.analytics.post_metrics import build_post_trend

logger = logging.getLogger(__name__)

_VISION_CAPTION_PROMPT = (
    "Опиши, что изображено, включая видимый текст/цифры на изображении."
)


@dataclass
class AgentState:
    session: AsyncSession
    user_id: uuid.UUID
    scope: str
    tenant_key: str | None
    embedding_backend: EmbeddingBackend
    base_post_data: Mapping[str, Any] | None = None
    min_similarity: float = 0.38
    search_k: int = 4
    visited: set[str] = field(default_factory=set)
    context_blocks: list[tuple[NoteCite, str]] = field(default_factory=list)
    opened_posts: dict[str, dict[str, Any]] = field(default_factory=dict)
    vision_calls_used: int = 0
    hydrated_text_files: set[str] = field(default_factory=set)
    scope_bias: float = 0.04
    ai_profile: Mapping[str, Any] = field(default_factory=dict)
    user: User | None = None
    settings: Settings | None = None


@dataclass(frozen=True)
class ToolOutcome:
    summary: str
    error: str | None = None


def _already_visited(state: AgentState, ref: str) -> ToolOutcome | None:
    if ref in state.visited:
        return ToolOutcome(summary=f"Узел {ref} уже открыт ранее в этом запросе.")
    return None


def _mark_visited(state: AgentState, ref: str) -> None:
    state.visited.add(ref)


def _is_current_chat_post(state: AgentState, canonical_post_id: str) -> bool:
    """True when opening the post the user is already editing in a post-scoped chat."""
    if state.scope != "post" or not state.base_post_data:
        return False
    post_id = str(canonical_post_id or "").strip()
    if not post_id:
        return False
    aliases = post_id_aliases(state.base_post_data)
    return post_id in aliases


def _post_data_for(state: AgentState, post_id: str) -> dict[str, Any] | None:
    if state.opened_posts.get(post_id):
        return state.opened_posts[post_id]
    base_id = str((state.base_post_data or {}).get("id") or "")
    if base_id == post_id and state.base_post_data:
        return dict(state.base_post_data)
    return None


def _node_label(item: dict[str, Any]) -> str:
    node_type = str(item.get("node_type") or "")
    note_id = str(item.get("note_id") or "")
    file_id = str(item.get("file_id") or "")
    if node_type == NODE_POST_TEXT:
        return f"post:{note_id}"
    if node_type == NODE_NOTE_CHUNK:
        return f"note:{note_id}"
    if node_type in (NODE_ATTACHMENT_TEXT, NODE_MEDIA_META) and file_id:
        return f"file:{file_id}"
    return f"{node_type}:{note_id}"


async def tool_search_nodes(
    state: AgentState,
    *,
    query: str,
    node_types: list[str] | None = None,
    k: int | None = None,
) -> ToolOutcome:
    ref = f"search:{query.strip()[:120]}"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    query_text = (query or "").strip()
    if not query_text:
        return ToolOutcome(summary="Пустой поисковый запрос.", error="empty_query")

    try:
        query_vec = await state.embedding_backend.embed_query(query_text)
        allowed_filter = frozenset(str(nt) for nt in node_types) if node_types else None
        results = await retrieve_for_chat(
            session=state.session,
            user_id=state.user_id,
            chat_scope=state.scope,
            query_vec=query_vec,
            embedding_backend=state.embedding_backend,
            k=k or state.search_k,
            min_similarity=state.min_similarity,
            post_id=str((state.base_post_data or {}).get("id") or "") or None,
            tenant_key=state.tenant_key,
            scope_bias=state.scope_bias,
            node_types_filter=allowed_filter,
        )
    except Exception as exc:
        return ToolOutcome(summary="Поиск не выполнен.", error=str(exc))

    if not results:
        return ToolOutcome(summary="Поиск не дал результатов.")

    lines = ["Результаты поиска:"]
    for item in results[: k or state.search_k]:
        label = _node_label(item)
        similarity = float(item.get("similarity") or 0.0)
        chunk = str(item.get("chunk_text") or "").strip()
        preview = chunk[:120] + ("…" if len(chunk) > 120 else "")
        lines.append(f"- {label} similarity={similarity:.2f} preview={preview!r}")
    return ToolOutcome(summary="\n".join(lines))


async def tool_open_post(state: AgentState, *, post_id: str) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    try:
        post_data = await resolve_post_data(state.session, state.user_id, post_id)
    except Exception as exc:
        return ToolOutcome(summary=f"Пост {post_id} не открыт.", error=str(exc))

    if not post_data:
        return ToolOutcome(summary=f"Пост {post_id} не найден.", error="not_found")

    canonical_post_id = str(post_data.get("id") or post_id).strip() or post_id
    ref = f"post:{canonical_post_id}"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    _mark_visited(state, ref)
    state.opened_posts[canonical_post_id] = post_data

    skip_text = _is_current_chat_post(state, canonical_post_id)
    text_value = str(post_data.get("text") or "").strip()
    if text_value and not skip_text:
        cite = NoteCite(
            path=f"/post/{canonical_post_id}/",
            title=_post_title_from_text(text_value),
        )
        state.context_blocks.append((cite, text_value))

    notes_count = len(post_data.get("notes") or [])
    media_count = len(post_data.get("media") or [])
    comments_count = len(post_data.get("comments") or [])
    primer_note = " (текст уже в primer)" if skip_text else ""
    return ToolOutcome(
        summary=(
            f"Открыт пост {canonical_post_id}{primer_note}. "
            f"notes={notes_count}, media={media_count}, comments={comments_count}."
        )
    )


async def tool_list_posts(
    state: AgentState,
    *,
    status: str | None = None,
) -> ToolOutcome:
    from sqlalchemy import select

    from app.db.models import Post
    from app.services.ai.rag import _post_title_from_text

    status_filter = str(status or "all").strip().lower() or "all"
    ref = f"list_posts:{status_filter}"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    try:
        result = await state.session.execute(
            select(Post)
            .where(Post.user_id == state.user_id)
            .order_by(Post.position, Post.created_at)
        )
        rows = list(result.scalars().all())
    except Exception as exc:
        return ToolOutcome(summary="Не удалось получить список постов.", error=str(exc))

    lines = [f"Посты пользователя (status={status_filter}):"]
    matched = 0
    for row in rows:
        data = dict(row.data) if isinstance(row.data, dict) else {}
        post_id = str(data.get("id") or "").strip()
        if not post_id:
            continue
        post_status = str(data.get("status") or "draft").strip().lower()
        if status_filter != "all" and post_status != status_filter:
            continue
        matched += 1
        text_value = str(data.get("text") or "").strip()
        title = _post_title_from_text(text_value) if text_value else f"Пост {post_id}"
        preview = text_value[:80] + ("…" if len(text_value) > 80 else "")
        notes_count = len(data.get("notes") or [])
        lines.append(
            f"- id={post_id} status={post_status} title={title!r} "
            f"notes={notes_count} preview={preview!r}"
        )

    if matched == 0:
        return ToolOutcome(summary=f"Постов со статусом {status_filter!r} не найдено.")
    return ToolOutcome(summary="\n".join(lines))


def tool_list_post_notes(state: AgentState, *, post_id: str) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    ref = f"post:{post_id}:notes"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    post_data = _post_data_for(state, post_id)
    if not post_data:
        return ToolOutcome(
            summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
            error="post_not_open",
        )

    notes = [
        item
        for item in (post_data.get("notes") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    if not notes:
        return ToolOutcome(summary=f"У поста {post_id} нет заметок.")

    lines = [f"Заметки поста {post_id}:"]
    for item in notes:
        note_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or note_id).strip() or note_id
        lines.append(f"- note:{note_id} title={title!r}")
    return ToolOutcome(summary="\n".join(lines))


def _note_cite_path(
    state: AgentState,
    note_id: str,
    post_id: str | None,
) -> str:
    if state.scope == "global":
        return f"/note/global/{note_id}/"
    resolved_post_id = post_id or str((state.base_post_data or {}).get("id") or "")
    if resolved_post_id:
        return f"/note/post/{resolved_post_id}/{note_id}/"
    return f"/note/global/{note_id}/"


async def tool_open_note(
    state: AgentState,
    *,
    note_id: str,
    post_id: str | None = None,
) -> ToolOutcome:
    note_id = str(note_id or "").strip()
    if not note_id:
        return ToolOutcome(summary="note_id не указан.", error="missing_note_id")

    ref = f"note:{note_id}"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    post_data = _post_data_for(state, post_id) if post_id else state.base_post_data
    try:
        note_data = await get_note_data(
            state.session,
            state.user_id,
            state.scope,
            note_id,
            tenant_key=state.tenant_key,
            post_data=post_data,
            opened_posts=state.opened_posts,
        )
    except Exception as exc:
        return ToolOutcome(summary=f"Заметка {note_id} не открыта.", error=str(exc))

    if not note_data:
        return ToolOutcome(summary=f"Заметка {note_id} не найдена.", error="not_found")

    _mark_visited(state, ref)
    title = str(note_data.get("title") or note_id).strip() or note_id
    body = str(note_data.get("body") or "")
    plain = markdown_to_index_text(title, body)
    if plain.strip():
        cite = NoteCite(
            path=_note_cite_path(state, note_id, post_id),
            title=title,
        )
        state.context_blocks.append((cite, plain))

    files_count = len(note_data.get("files") or [])
    return ToolOutcome(summary=f"Открыта заметка note:{note_id} ({title!r}), files={files_count}.")


async def tool_list_note_attachments(
    state: AgentState,
    *,
    note_id: str,
    post_id: str | None = None,
) -> ToolOutcome:
    note_id = str(note_id or "").strip()
    if not note_id:
        return ToolOutcome(summary="note_id не указан.", error="missing_note_id")

    ref = f"note:{note_id}:attachments"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    post_data = _post_data_for(state, post_id) if post_id else state.base_post_data
    try:
        note_data = await get_note_data(
            state.session,
            state.user_id,
            state.scope,
            note_id,
            tenant_key=state.tenant_key,
            post_data=post_data,
            opened_posts=state.opened_posts,
        )
    except Exception as exc:
        return ToolOutcome(
            summary=f"Заметка {note_id} не найдена.",
            error=str(exc),
        )

    if note_data is None:
        return ToolOutcome(
            summary=f"Заметка {note_id} не найдена — сначала вызови OpenNote.",
            error="note_not_found",
        )

    files = [
        item
        for item in (note_data.get("files") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    if not files:
        return ToolOutcome(summary=f"У заметки {note_id} нет вложений.")

    lines = [f"Вложения заметки {note_id}:"]
    for item in files:
        file_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or file_id).strip() or file_id
        mime = str(item.get("type") or item.get("mimeType") or "").strip()
        lines.append(f"- attachment:{file_id} name={name!r} type={mime!r}")
    return ToolOutcome(summary="\n".join(lines))


def _settings_for(state: AgentState) -> Settings:
    return state.settings or get_settings()


def _find_note_file_by_id(note_data: dict[str, Any] | None, file_id: str) -> dict[str, str] | None:
    if not note_data:
        return None
    for item in note_data.get("files") or []:
        if not isinstance(item, dict):
            continue
        record = note_file_record(item)
        if record and record["id"] == file_id:
            return record
    return None


def _find_post_media_by_id(post_data: dict[str, Any] | None, file_id: str) -> dict[str, str] | None:
    if not post_data:
        return None
    for index, item in enumerate(post_data.get("media") or []):
        if not isinstance(item, dict):
            continue
        record = post_media_record(item, index)
        if record["id"] == file_id:
            return record
    return None


def _attachment_cite_path(
    *,
    ref_kind: str,
    file_id: str,
    note_id: str | None,
    post_id: str | None,
    state: AgentState,
) -> str:
    if ref_kind == "file" and post_id:
        return f"/post/{post_id}/media/{file_id}/"
    if note_id:
        if state.scope == "global":
            return f"/note/global/{note_id}/attachment/{file_id}/"
        resolved_post = post_id or str((state.base_post_data or {}).get("id") or "")
        if resolved_post:
            return f"/note/post/{resolved_post}/{note_id}/attachment/{file_id}/"
        return f"/note/global/{note_id}/attachment/{file_id}/"
    return f"/attachment/{file_id}/"


async def _resolve_attachment_record(
    state: AgentState,
    *,
    ref: str,
    note_id: str | None,
    post_id: str | None,
) -> tuple[str, str, str, dict[str, str]] | ToolOutcome:
    ref = str(ref or "").strip()
    if ref.startswith("attachment:"):
        file_id = ref[len("attachment:") :].strip()
        if not file_id:
            return ToolOutcome(summary="ref не указан.", error="missing_ref")
        if not note_id:
            return ToolOutcome(summary="note_id обязателен для attachment.", error="missing_note_id")
        post_data = _post_data_for(state, post_id) if post_id else state.base_post_data
        note_data = await get_note_data(
            state.session,
            state.user_id,
            state.scope,
            note_id,
            tenant_key=state.tenant_key,
            post_data=post_data,
            opened_posts=state.opened_posts,
        )
        if note_data is None:
            return ToolOutcome(
                summary=f"Заметка {note_id} не найдена — сначала вызови OpenNote.",
                error="note_not_found",
            )
        record = _find_note_file_by_id(note_data, file_id)
        if record is None:
            return ToolOutcome(summary=f"Вложение {ref} не найдено.", error="file_not_found")
        scope = state.scope
        parent_id = note_id
        return "attachment", scope, parent_id, record

    if ref.startswith("file:"):
        file_id = ref[len("file:") :].strip()
        if not file_id:
            return ToolOutcome(summary="ref не указан.", error="missing_ref")
        if not post_id:
            return ToolOutcome(summary="post_id обязателен для file.", error="missing_post_id")
        post_data = _post_data_for(state, post_id)
        if not post_data:
            return ToolOutcome(
                summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
                error="post_not_open",
            )
        record = _find_post_media_by_id(post_data, file_id)
        if record is None:
            for index, item in enumerate(post_data.get("media") or []):
                if isinstance(item, dict) and post_media_file_id(item, index) == file_id:
                    record = post_media_record(item, index)
                    break
        if record is None:
            return ToolOutcome(summary=f"Медиа {ref} не найдено.", error="file_not_found")
        return "file", "global", post_id, record

    return ToolOutcome(summary=f"Неизвестный ref: {ref!r}", error="invalid_ref")


async def _append_extracted_text(
    state: AgentState,
    *,
    ref_kind: str,
    ref: str,
    file_id: str,
    note_id: str | None,
    post_id: str | None,
    record: dict[str, str],
    text_value: str,
) -> None:
    cite_path = _attachment_cite_path(
        ref_kind=ref_kind,
        file_id=file_id,
        note_id=note_id,
        post_id=post_id,
        state=state,
    )
    cite = NoteCite(path=cite_path, title=record["name"])
    state.context_blocks.append((cite, text_value.strip()))
    state.hydrated_text_files.add(ref)


def _format_post_trend_text(trend: Mapping[str, Any], *, period: str) -> str:
    end_totals = trend.get("endTotals") or {}
    start_totals = trend.get("startTotals") or {}
    lines = [
        f"Период: {period}",
        f"Просмотры: {end_totals.get('views', 0)} (старт периода: {start_totals.get('views', 0)})",
        f"Реакции: {end_totals.get('reactions', 0)} (старт: {start_totals.get('reactions', 0)})",
        f"Комментарии: {end_totals.get('comments', 0)} (старт: {start_totals.get('comments', 0)})",
        f"Репосты: {end_totals.get('reposts', 0)} (старт: {start_totals.get('reposts', 0)})",
        f"ER: {end_totals.get('er', 0)}",
    ]
    return "\n".join(lines)


async def build_post_analytics_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_id: str,
    period: str,
    *,
    snapshot_stale_after_seconds: float | None = None,
) -> tuple[str, list[NoteCite], str | None]:
    """Fetch post analytics and return (context_text, cites, error)."""
    if period not in VALID_PERIODS:
        period = "30d"
    try:
        post_row = await get_owned_post(session, user_id, post_id)
    except Exception as exc:
        return "", [], str(exc)

    if post_row.data.get("status") != "published":
        return "", [], "unpublished"

    profile = await session.get(Profile, user_id)
    telegram = profile.telegram if profile and profile.telegram else None
    try:
        post_snapshots = await load_post_snapshots(session, user_id, post_row.id)
        trend = build_post_trend(
            post_row,
            post_snapshots,
            period,
            telegram,
            snapshot_stale_after_seconds=snapshot_stale_after_seconds,
        )
    except Exception as exc:
        return "", [], str(exc)

    body = _format_post_trend_text(trend, period=period)
    cite = NoteCite(path=f"/post/{post_id}/", title="Аналитика поста")
    context = (
        "---\n**Контекст из базы знаний:**\n\n"
        f"[1] cite-path: {cite.path} cite-title: {cite.title}\n"
        f"**{cite.title}**\n{body}\n---"
    )
    return context, [cite], None


async def _load_post_trend_body(
    state: AgentState,
    post_id: str,
    period: str,
) -> tuple[str, NoteCite, str | None]:
    settings = _settings_for(state)
    stale_after: float | None = None
    if settings.telegram_analytics_snapshot_seconds > 0:
        from app.services.analytics.channel_metrics import MISSED_SNAPSHOT_MULTIPLIER

        stale_after = settings.telegram_analytics_snapshot_seconds * MISSED_SNAPSHOT_MULTIPLIER

    if period not in VALID_PERIODS:
        period = "30d"

    try:
        post_row = await get_owned_post(state.session, state.user_id, post_id)
    except Exception as exc:
        return "", NoteCite(path=f"/post/{post_id}/", title="Аналитика поста"), str(exc)

    if post_row.data.get("status") != "published":
        return "", NoteCite(path=f"/post/{post_id}/", title="Аналитика поста"), "unpublished"

    profile = await state.session.get(Profile, state.user_id)
    telegram = profile.telegram if profile and profile.telegram else None
    try:
        post_snapshots = await load_post_snapshots(state.session, state.user_id, post_row.id)
        trend = build_post_trend(
            post_row,
            post_snapshots,
            period,
            telegram,
            snapshot_stale_after_seconds=stale_after,
        )
    except Exception as exc:
        return "", NoteCite(path=f"/post/{post_id}/", title="Аналитика поста"), str(exc)

    cite = NoteCite(path=f"/post/{post_id}/", title="Аналитика поста")
    return _format_post_trend_text(trend, period=period), cite, None


async def tool_hydrate_attachment(
    state: AgentState,
    *,
    ref: str,
    mode: str = "text",
    note_id: str | None = None,
    post_id: str | None = None,
) -> ToolOutcome:
    mode = str(mode or "text").strip().lower()
    ref = str(ref or "").strip()
    if not ref:
        return ToolOutcome(summary="ref не указан.", error="missing_ref")

    if mode == "vision":
        return await _tool_hydrate_attachment_vision(
            state, ref=ref, note_id=note_id, post_id=post_id
        )
    if mode != "text":
        return ToolOutcome(summary=f"Неизвестный mode: {mode!r}", error="invalid_mode")

    visit_ref = f"hydrate:{ref}"
    existing = _already_visited(state, visit_ref)
    if existing:
        return existing
    _mark_visited(state, visit_ref)

    try:
        resolved = await _resolve_attachment_record(
            state, ref=ref, note_id=note_id, post_id=post_id
        )
        if isinstance(resolved, ToolOutcome):
            return resolved
        ref_kind, scope, parent_id, record = resolved
        file_id = record["id"]

        cached = await get_attachment_extraction(
            state.session,
            state.user_id,
            scope,
            parent_id,
            file_id,
            tenant_key=state.tenant_key or "",
        )
        text_value = (cached or "").strip()
        settings = _settings_for(state)

        if not text_value:
            decoded = await resolve_attachment_bytes(record["url"], state.user_id, settings)
            if decoded is None:
                return ToolOutcome(
                    summary=(
                        f"Вложение {ref} не текстовое или не удалось извлечь текст — "
                        "попробуй HydrateAttachment mode=vision."
                    ),
                    error="no_text",
                )
            raw_bytes, mime_type = decoded
            content_hash_value = bytes_content_hash(raw_bytes)
            extracted = extract_attachment_text(mime_type, raw_bytes)
            if not extracted:
                return ToolOutcome(
                    summary=(
                        f"Вложение {ref} не текстовое или не удалось извлечь текст — "
                        "попробуй HydrateAttachment mode=vision."
                    ),
                    error="no_text",
                )
            text_value = extracted.strip()
            await upsert_attachment_extraction(
                state.session,
                state.user_id,
                scope,
                parent_id,
                file_id,
                content_hash_value,
                mime_type,
                text_value,
                tenant_key=state.tenant_key or "",
            )
            try:
                from app.services.ai.rag_worker import enqueue_note_job

                await enqueue_note_job(
                    state.session,
                    state.user_id,
                    "upsert",
                    scope,
                    parent_id,
                    post_id=post_id,
                    tenant_key=state.tenant_key or "",
                    node_type=NODE_ATTACHMENT_TEXT,
                    file_id=file_id,
                )
            except Exception as exc:
                logger.debug("HydrateAttachment enqueue failed: %s", exc)

        await _append_extracted_text(
            state,
            ref_kind=ref_kind,
            ref=ref,
            file_id=file_id,
            note_id=note_id,
            post_id=post_id,
            record=record,
            text_value=text_value,
        )
        return ToolOutcome(summary=f"Гидратировано {ref} (text), символов={len(text_value)}.")
    except Exception as exc:
        logger.warning("HydrateAttachment text failed for %s: %s", ref, exc)
        return ToolOutcome(summary=f"Гидратация {ref} не выполнена.", error=str(exc))


async def _tool_hydrate_attachment_vision(
    state: AgentState,
    *,
    ref: str,
    note_id: str | None,
    post_id: str | None,
) -> ToolOutcome:
    visit_ref = f"hydrate:vision:{ref}"
    existing = _already_visited(state, visit_ref)
    if existing:
        return existing

    if ref in state.hydrated_text_files or f"hydrate:{ref}" in state.visited:
        return ToolOutcome(
            summary=f"Вложение {ref} уже прочитано как текст — vision не нужен.",
            error="already_text",
        )

    settings = _settings_for(state)
    if state.vision_calls_used >= settings.rag_agent_max_vision:
        return ToolOutcome(summary="Лимит vision-вызовов исчерпан.", error="vision_budget_exhausted")

    _mark_visited(state, visit_ref)

    try:
        resolved = await _resolve_attachment_record(
            state, ref=ref, note_id=note_id, post_id=post_id
        )
        if isinstance(resolved, ToolOutcome):
            return resolved
        ref_kind, scope, parent_id, record = resolved
        file_id = record["id"]

        decoded = await resolve_attachment_bytes(record["url"], state.user_id, settings)
        if decoded is None:
            return ToolOutcome(summary=f"Не удалось прочитать файл {ref}.", error="fetch_failed")
        raw_bytes, mime_type = decoded
        if not mime_type.startswith("image/"):
            return ToolOutcome(
                summary=f"Файл {ref} не является изображением.",
                error="not_image",
            )

        content_hash_value = bytes_content_hash(raw_bytes)
        caption = await get_attachment_extraction_by_hash(
            state.session, state.user_id, content_hash_value
        )
        caption = (caption or "").strip()

        if not caption:
            if state.user is None:
                return ToolOutcome(summary="Vision-модель недоступна.", error="no_vision_model")
            from app.services.ai.llm import complete_vision_completion
            from app.services.ai.rag_vision import resolve_vision_llm

            vision_llm = resolve_vision_llm(state.user, state.ai_profile, settings)
            if vision_llm is None:
                return ToolOutcome(summary="Vision-модель недоступна.", error="no_vision_model")
            spec, model, api_key = vision_llm
            caption = (
                await complete_vision_completion(
                    spec=spec,
                    model=model,
                    api_key=api_key,
                    prompt=_VISION_CAPTION_PROMPT,
                    image_bytes=raw_bytes,
                    mime_type=mime_type,
                )
            ).strip()
            state.vision_calls_used += 1
            if caption:
                await upsert_attachment_extraction(
                    state.session,
                    state.user_id,
                    scope,
                    parent_id,
                    file_id,
                    content_hash_value,
                    mime_type,
                    caption,
                    tenant_key=state.tenant_key or "",
                )

        if not caption:
            return ToolOutcome(summary=f"Vision не дал описание для {ref}.", error="empty_caption")

        await _append_extracted_text(
            state,
            ref_kind=ref_kind,
            ref=ref,
            file_id=file_id,
            note_id=note_id,
            post_id=post_id,
            record=record,
            text_value=caption,
        )
        return ToolOutcome(summary=f"Гидратировано {ref} (vision), символов={len(caption)}.")
    except Exception as exc:
        logger.warning("HydrateAttachment vision failed for %s: %s", ref, exc)
        return ToolOutcome(summary=f"Vision-гидратация {ref} не выполнена.", error=str(exc))


def tool_list_post_comments(state: AgentState, *, post_id: str) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    ref = f"post:{post_id}:comments"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    post_data = _post_data_for(state, post_id)
    if not post_data:
        return ToolOutcome(
            summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
            error="post_not_open",
        )

    comments = [
        item
        for item in (post_data.get("comments") or [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not comments:
        return ToolOutcome(summary=f"У поста {post_id} нет комментариев.")

    def _sort_key(item: dict[str, Any]) -> str:
        return str(item.get("date") or "")

    sorted_comments = sorted(comments, key=_sort_key, reverse=True)
    cap = max(state.search_k * 5, 20)
    included = sorted_comments[:cap]

    lines = []
    for item in included:
        author = str(item.get("author") or "Аноним").strip()
        date_value = str(item.get("date") or "").strip()
        text_value = str(item.get("text") or "").strip()
        lines.append(f"{author} ({date_value}): {text_value}")

    body = "\n".join(lines)
    cite = NoteCite(path=f"/post/{post_id}/comments/", title=f"Комментарии поста {post_id}")
    state.context_blocks.append((cite, body))
    return ToolOutcome(
        summary=f"Прочитано {len(included)} из {len(comments)} комментариев поста {post_id}."
    )


async def tool_get_post_analytics(
    state: AgentState,
    *,
    post_id: str,
    period: str,
) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    period = str(period or "30d").strip()
    ref = f"post:{post_id}:analytics:{period}"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    body, cite, error = await _load_post_trend_body(state, post_id, period)
    if error:
        if error == "unpublished":
            return ToolOutcome(
                summary="Аналитика доступна только для опубликованных постов.",
                error=error,
            )
        return ToolOutcome(summary=f"Аналитика поста {post_id} недоступна.", error=error)

    state.context_blocks.append((cite, body))
    return ToolOutcome(summary=f"Загружена аналитика поста {post_id} за период {period}.")

