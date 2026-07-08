"""L2 agentic RAG read tools (deterministic executor)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag import (
    NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META,
    NODE_NOTE_CHUNK,
    NODE_POST_TEXT,
    get_note_data,
    markdown_to_index_text,
    resolve_post_data,
    retrieve_top_k,
    _post_title_from_text,
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
        results = await retrieve_top_k(
            session=state.session,
            user_id=state.user_id,
            scope=state.scope,
            query_vec=query_vec,
            model_key=state.embedding_backend.model_key,
            k=k or state.search_k,
            min_similarity=state.min_similarity,
            post_id=str((state.base_post_data or {}).get("id") or "") or None,
            tenant_key=state.tenant_key,
        )
    except Exception as exc:
        return ToolOutcome(summary="Поиск не выполнен.", error=str(exc))

    if node_types:
        allowed = {str(nt) for nt in node_types}
        results = [item for item in results if str(item.get("node_type") or "") in allowed]

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

    ref = f"post:{post_id}"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    try:
        post_data = await resolve_post_data(state.session, state.user_id, post_id)
    except Exception as exc:
        return ToolOutcome(summary=f"Пост {post_id} не открыт.", error=str(exc))

    if not post_data:
        return ToolOutcome(summary=f"Пост {post_id} не найден.", error="not_found")

    _mark_visited(state, ref)
    state.opened_posts[post_id] = post_data

    text_value = str(post_data.get("text") or "").strip()
    if text_value:
        cite = NoteCite(path=f"/post/{post_id}/", title=_post_title_from_text(text_value))
        state.context_blocks.append((cite, text_value))

    notes_count = len(post_data.get("notes") or [])
    media_count = len(post_data.get("media") or [])
    comments_count = len(post_data.get("comments") or [])
    return ToolOutcome(
        summary=(
            f"Открыт пост {post_id}. "
            f"notes={notes_count}, media={media_count}, comments={comments_count}."
        )
    )


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
