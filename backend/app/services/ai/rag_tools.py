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
    NODE_NOTE_SUMMARY,
    NODE_POST_TEXT,
    NODE_POST_SUMMARY,
    get_attachment_extraction,
    get_attachment_extraction_by_hash,
    get_note_data,
    list_global_notes,
    markdown_to_index_text,
    object_index_revision,
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

# Patterns that indicate a model refused/failed to process the image rather than
# returning a real description. Sonar-pro (and other providers that don't support
# inline base64 data: URLs) return these refusals as 200 OK text responses. We
# must NOT cache them — a stale "I cannot see" caption would permanently block
# legitimate vision calls on the same content hash.
_VISION_REFUSAL_FRAGMENTS = (
    "cannot view",
    "can't view",
    "cannot see",
    "can't see",
    "unable to view",
    "unable to see",
    "unable to process",
    "cannot process",
    "can't process",
    "no image",
    "i don't see",
    "i do not see",
    "не вижу изображени",
    "не могу видеть",
    "не могу просмотреть",
    "не могу обработать",
    "изображение недоступно",
    "не удаётся",
)


def _is_vision_refusal(caption: str) -> bool:
    """Return True if the caption looks like a model refusal rather than a real description."""
    lower = caption.lower()
    return any(frag in lower for frag in _VISION_REFUSAL_FRAGMENTS)


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
    query_vector_cache: dict[str, list[float]] = field(default_factory=dict)
    catalog_members: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    vision_calls_used: int = 0
    hydrated_text_files: set[str] = field(default_factory=set)
    listed_image_attachment_refs: list[str] = field(default_factory=list)
    listed_image_media_refs: list[str] = field(default_factory=list)
    decision_ledger: list[str] = field(default_factory=list)
    resolved_target_post_id: str | None = None
    target_evidence_gap: str | None = None
    scope_bias: float = 0.04
    ai_profile: Mapping[str, Any] = field(default_factory=dict)
    user: User | None = None
    settings: Settings | None = None


@dataclass(frozen=True)
class ToolOutcome:
    summary: str
    error: str | None = None
    # Structured search hits [{ref, label, similarity, node_type}], populated
    # only by tool_search_nodes. Lets the seed prefetch record candidates for
    # the finish-gate guard without re-parsing the human-readable summary.
    hits: tuple[dict[str, Any], ...] = ()
    # Phase-7 typed/tool observability fields. ``error`` remains for legacy
    # callers; planners and traces should prefer the structured fields.
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    next_action: str | None = None
    response_mode: str = "compact"
    result_count: int = 0
    cache_hit: bool = False
    duration_ms: float = 0.0
    items: tuple[dict[str, Any], ...] = ()


def _already_visited(state: AgentState, ref: str) -> ToolOutcome | None:
    if ref in state.visited:
        return ToolOutcome(summary=f"Узел {ref} уже открыт ранее в этом запросе.")
    return None


def _mark_visited(state: AgentState, ref: str) -> None:
    state.visited.add(ref)


def _record_listing(
    state: AgentState,
    *,
    path: str,
    title: str,
    body: str,
    members: list[dict[str, Any]] | None = None,
) -> ToolOutcome:
    """Make a listing tool's output first-class citable evidence (§1.4 tail).

    List tools used to return only a `summary` — visible to the planner via the
    transcript but never to the answer model, which sees only the verified pack.
    So a question the *listing itself* answers ("сколько у меня постов про X?",
    "какие вложения у заметки?") could not be grounded: the answer guard saw an
    empty pack and refused despite the data existing. Appending the listing as a
    context block (same mechanism OpenPost/OpenNote use) turns it into a record
    keyed by a stable listing path, so FinishRetrieval can cite it and the answer
    can be grounded. Only valid results (incl. an honest empty listing) are
    recorded; error/guidance returns are not — they are control flow, not facts.
    """
    state.context_blocks.append((NoteCite(path=path, title=title), body))
    if members is not None:
        state.catalog_members[path] = [dict(item) for item in members[:100]]
    return ToolOutcome(summary=body, items=tuple(members or ()))


def _attachment_suffix(files: Any) -> str:
    """`files=N` / `images=M` decoration for a note in a listing.

    Attachment presence is structured data (files[].type) the listing tools
    already hold in memory, but they used to print title only — so «заметка с
    вложениями/картинками» was not findable from a listing, forcing the planner
    to open notes one-by-one or open a topically-similar note blindly (chat
    9f3d5fdf). Surfacing counts here makes attachments discoverable across BOTH
    sources (global notes + post notes) without a new tool or extra query.
    Covers all attachments, not only images: `images` is a subset of `files`.
    """
    items = [f for f in (files or []) if isinstance(f, dict)]
    if not items:
        return ""
    images = sum(
        1
        for f in items
        if str(f.get("type") or f.get("mimeType") or "").startswith("image/")
    )
    parts = [f"files={len(items)}"]
    if images:
        parts.append(f"images={images}")
    return " " + " ".join(parts)


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


# The planner invents node_type values from the natural words in the question
# ("post", "note", "заметка") — it was never given the internal vocabulary. The
# retrieval filter intersects against the real node types (note_chunk/post_text/
# attachment_text/media_meta), so an alien value silently zeroes every pass
# (`allowed_types & {"post","note"} == ∅` → pass skipped) and SearchNodes returns
# "нет результатов" even when the text plainly exists. Map the aliases to real
# types; drop anything unrecognisable so a stray value degrades to "no filter"
# (search everything) instead of "match nothing".
_NODE_TYPE_ALIASES: dict[str, str] = {
    NODE_NOTE_CHUNK: NODE_NOTE_CHUNK,
    NODE_POST_TEXT: NODE_POST_TEXT,
    NODE_ATTACHMENT_TEXT: NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META: NODE_MEDIA_META,
    "note": NODE_NOTE_CHUNK,
    "notes": NODE_NOTE_CHUNK,
    "note_chunk": NODE_NOTE_CHUNK,
    "note_summary": NODE_NOTE_SUMMARY,
    "заметка": NODE_NOTE_CHUNK,
    "заметки": NODE_NOTE_CHUNK,
    "post": NODE_POST_TEXT,
    "posts": NODE_POST_TEXT,
    "пост": NODE_POST_TEXT,
    "посты": NODE_POST_TEXT,
    "post_summary": NODE_POST_SUMMARY,
    "attachment": NODE_ATTACHMENT_TEXT,
    "attachment_text": NODE_ATTACHMENT_TEXT,
    "document": NODE_ATTACHMENT_TEXT,
    "media": NODE_MEDIA_META,
    "media_meta": NODE_MEDIA_META,
}


def _normalize_node_types(node_types: list[str] | None) -> frozenset[str] | None:
    """Translate planner-supplied node_types to real DB types.

    Returns None (no filter → search all types) when nothing maps, so an
    unrecognised value can never silently kill recall. See _NODE_TYPE_ALIASES.
    """
    if not node_types:
        return None
    mapped = {
        real
        for raw in node_types
        if (real := _NODE_TYPE_ALIASES.get(str(raw).strip().lower()))
    }
    return frozenset(mapped) or None


def _node_label(item: dict[str, Any]) -> str:
    node_type = str(item.get("node_type") or "")
    note_id = str(item.get("note_id") or "")
    file_id = str(item.get("file_id") or "")
    if node_type in (NODE_POST_TEXT, NODE_POST_SUMMARY):
        return f"post:{note_id}"
    if node_type in (NODE_NOTE_CHUNK, NODE_NOTE_SUMMARY):
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
    expected_revisions: Mapping[str, int] | None = None,
    object_statuses: frozenset[str] | None = None,
) -> ToolOutcome:
    types_key = ",".join(sorted(str(nt) for nt in node_types)) if node_types else ""
    status_key = ",".join(sorted(object_statuses or ()))
    revision_key = ",".join(
        f"{key}={value}" for key, value in sorted((expected_revisions or {}).items())
    )
    ref = (
        f"search:{query.strip()[:120]}:{types_key}:{k or state.search_k}:"
        f"{status_key}:{revision_key}"
    )
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    query_text = (query or "").strip()
    if not query_text:
        return ToolOutcome(summary="Пустой поисковый запрос.", error="empty_query")

    try:
        from app.services.agent.research.prefetch import hybrid_prefetch, retrieve_for_discovery

        allowed_filter = _normalize_node_types(node_types)
        candidate_limit = min(10, max(1, int(k or state.search_k)))
        query_cache_key = " ".join(query_text.casefold().split())
        query_vec = state.query_vector_cache.get(query_cache_key)
        if query_vec is None:
            query_vec = await state.embedding_backend.embed_query(query_text)
            state.query_vector_cache[query_cache_key] = query_vec
        search = (
            retrieve_for_discovery
            if state.settings is None or state.settings.agent_retrieval_phase4_enabled
            else hybrid_prefetch
        )
        results = await search(
            session=state.session,
            user_id=state.user_id,
            scope=state.scope,
            query_text=query_text,
            embedding_backend=state.embedding_backend,
            top_k=candidate_limit,
            min_similarity=state.min_similarity,
            post_id=str((state.base_post_data or {}).get("id") or "") or None,
            tenant_key=state.tenant_key,
            scope_bias=state.scope_bias,
            node_types_filter=allowed_filter,
            vector_retriever=retrieve_for_chat,
            expected_revisions=expected_revisions,
            object_statuses=object_statuses,
            query_vec=query_vec,
        )
    except Exception as exc:
        return ToolOutcome(summary="Поиск не выполнен.", error=str(exc))

    if not results:
        return ToolOutcome(summary="Поиск не дал результатов.")

    lines = ["Результаты поиска:"]
    hits: list[dict[str, Any]] = []
    for item in results[: min(8, k or state.search_k)]:
        label = _node_label(item)
        similarity = float(item.get("similarity") or 0.0)
        chunk = str(item.get("chunk_text") or "").strip()
        preview = chunk[:320] + ("…" if len(chunk) > 320 else "")
        lines.append(f"- {label} similarity={similarity:.2f} preview={preview!r}")
        hits.append(
            {
                "ref": label,
                "label": label,
                "similarity": similarity,
                "node_type": str(item.get("node_type") or ""),
                "summary_only": bool(item.get("summary_only")),
                "index_revision": int(item.get("index_revision") or 1),
                "source_revision": int(item.get("source_revision") or 0),
                "summary_version": int(item.get("summary_version") or 0),
                "summary_model": str(item.get("summary_model") or ""),
                "title": str(item.get("object_title") or ""),
                "preview": preview,
                "status": str(item.get("object_status") or ""),
                "has_more": bool(item.get("has_more")),
            }
        )
    return ToolOutcome(
        summary="\n".join(lines),
        hits=tuple(hits),
        result_count=len(hits),
    )


async def tool_search_object_chunks(
    state: AgentState,
    *,
    query: str,
    object_ids: list[str],
    k: int | None = None,
    expected_revisions: Mapping[str, int] | None = None,
    object_statuses: frozenset[str] | None = None,
) -> ToolOutcome:
    """Search contextual chunks only inside already selected objects.

    This is intentionally separate from ``SearchNodes``: object discovery is
    bounded at five candidates, while a chunk query must carry an explicit
    selected object set and can never widen back to the tenant corpus.
    """
    ids = frozenset(str(item).strip() for item in object_ids if str(item).strip())
    if not ids:
        return ToolOutcome(summary="Не указаны выбранные объекты.", error="missing_object_ids")
    ref = (
        f"chunk-search:{str(query).strip()[:120]}:{','.join(sorted(ids))}:"
        f"{','.join(sorted(object_statuses or ()))}:{k or 8}:"
        f"{','.join(f'{key}={value}' for key, value in sorted((expected_revisions or {}).items()))}"
    )
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)
    try:
        from app.services.agent.research.prefetch import retrieve_for_discovery
        from app.services.ai.rag import CONTEXTUAL_NODE_TYPES

        results = await retrieve_for_discovery(
            session=state.session,
            user_id=state.user_id,
            scope=state.scope,
            query_text=str(query or "").strip(),
            embedding_backend=state.embedding_backend,
            top_k=max(1, int(k or 8)),
            min_similarity=state.min_similarity,
            post_id=str((state.base_post_data or {}).get("id") or "") or None,
            tenant_key=state.tenant_key,
            scope_bias=state.scope_bias,
            node_types_filter=CONTEXTUAL_NODE_TYPES,
            selected_object_ids=ids,
            vector_retriever=retrieve_for_chat,
            expected_revisions=expected_revisions,
            object_statuses=object_statuses,
        )
    except Exception as exc:
        return ToolOutcome(summary="Поиск фрагментов не выполнен.", error=str(exc))

    if not results:
        return ToolOutcome(summary="В выбранных объектах фрагменты не найдены.")

    lines = ["Фрагменты выбранных объектов:"]
    hits: list[dict[str, Any]] = []
    for item in results[: max(1, int(k or 8))]:
        label = _node_label(item)
        chunk = str(item.get("chunk_text") or "").strip()
        title = str(item.get("object_title") or label)
        if chunk:
            if item.get("node_type") == NODE_POST_TEXT:
                cite_path = f"/post/{item.get('note_id')}/"
            else:
                cite_path = f"/note/{state.scope}/{item.get('note_id')}/"
            state.context_blocks.append((NoteCite(path=cite_path, title=title), chunk))
        lines.append(
            f"- {label} similarity={float(item.get('similarity') or 0):.2f} "
            f"chunk={chunk[:180]!r}"
        )
        hits.append(
            {
                "ref": label,
                "label": label,
                "similarity": float(item.get("similarity") or 0),
                "node_type": str(item.get("node_type") or ""),
                "selected_object": True,
            }
        )
    return ToolOutcome(summary="\n".join(lines), hits=tuple(hits))


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
            f"Открыт пост tech_id={canonical_post_id}{primer_note}. "
            f"notes={notes_count}, media={media_count}, comments={comments_count}."
        )
    )


async def tool_list_posts(
    state: AgentState,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int | None = None,
) -> ToolOutcome:
    from sqlalchemy import select

    from app.db.models import Post
    from app.services.ai.rag import _post_title_from_text

    status_filter = str(status or "all").strip().lower() or "all"
    query_filter = str(query or "").strip().lower()
    result_limit = max(1, int(limit)) if limit is not None else None
    ref = f"list_posts:{status_filter}:{query_filter}:{result_limit or 'all'}"
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

    # tech_id (не «id»): опубликованные посты несут tg message_id (маленькое
    # число), черновики — UUID. Метка + пояснение не дают модели принять число
    # в ключе за порядковый номер поста / позицию в серии (чат 74b0ef7d).
    lines = [""]
    matched = 0
    shown = 0
    state.catalog_posts = []
    catalog_members: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row.data) if isinstance(row.data, dict) else {}
        post_id = str(data.get("id") or "").strip()
        if not post_id:
            continue
        post_status = str(data.get("status") or "draft").strip().lower()
        if status_filter == "all" and post_status == "deleted":
            continue
        if status_filter != "all" and post_status != status_filter:
            continue
        text_value = str(data.get("text") or "").strip()
        title = _post_title_from_text(text_value) if text_value else f"Пост {post_id}"
        if query_filter and query_filter not in f"{title} {text_value}".lower():
            continue
        matched += 1
        preview = text_value[:80] + ("…" if len(text_value) > 80 else "")
        catalog_members.append(
            {
                "kind": "post",
                "id": post_id,
                "title": title,
                "status": post_status,
                "preview": preview,
                "revision": object_index_revision(data),
            }
        )
        if result_limit is not None and shown >= result_limit:
            continue
        shown += 1
        post_notes = data.get("notes") or []
        notes_count = len(post_notes)
        # Aggregate attachment presence across THIS post's notes, so a post whose
        # notes carry images/files is findable from the catalog without opening
        # each post then each note (chat 9f3d5fdf — the note with images lived
        # under a post and was never located). Structured data already in memory.
        note_files = 0
        note_images = 0
        for note in post_notes:
            for f in (note.get("files") or []) if isinstance(note, dict) else []:
                if not isinstance(f, dict):
                    continue
                note_files += 1
                if str(f.get("type") or f.get("mimeType") or "").startswith("image/"):
                    note_images += 1
        state.catalog_posts.append(
            {
                "id": post_id,
                "text": text_value,
                "status": post_status,
                "notes_count": notes_count,
                "notes": post_notes,
            }
        )
        att_suffix = ""
        if note_files:
            att_suffix = f" note_files={note_files}"
            if note_images:
                att_suffix += f" note_images={note_images}"
        lines.append(
            f"- title={title!r} tech_id={post_id} status={post_status} "
            f"notes={notes_count}{att_suffix} preview={preview!r}"
        )
    lines[0] = (
        f"Посты пользователя (status={status_filter}, total={matched}, shown={shown}). "
        "tech_id — технический ключ для OpenPost/GetPostAnalytics, НЕ порядковый номер:"
    )

    # Encode the filter into the path so distinct listings (all posts vs.
    # query=запуск vs. status=draft) get distinct records and are not collapsed
    # by the pack's first-path-wins dedup.
    if query_filter:
        listing_path = f"/posts/q:{query_filter}/"
        listing_title = f"Список постов по запросу {query_filter!r}"
    elif status_filter != "all":
        listing_path = f"/posts/status:{status_filter}/"
        listing_title = f"Список постов (статус {status_filter})"
    else:
        listing_path = "/posts/"
        listing_title = "Список постов"

    if matched == 0:
        empty = (
            f"Постов по запросу {query_filter!r} не найдено."
            if query_filter
            else f"Постов со статусом {status_filter!r} не найдено."
        )
        return _record_listing(
            state, path=listing_path, title=listing_title, body=empty, members=[]
        )
    return _record_listing(
        state,
        path=listing_path,
        title=listing_title,
        body="\n".join(lines),
        members=catalog_members,
    )


def tool_list_post_notes(state: AgentState, *, post_id: str) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    ref = f"post:{post_id}:notes"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    post_data = _post_data_for(state, post_id)
    if not post_data:
        # Do NOT mark visited on a precondition failure: "сначала OpenPost" is
        # recoverable guidance, not a completed visit. Marking here poisons the
        # ref so the legitimate retry after OpenPost returns "уже открыт ранее"
        # and never lists the notes — the agent then burns its whole step budget
        # looping on this call. Mark only once the listing actually succeeds.
        return ToolOutcome(
            summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
            error="post_not_open",
        )
    _mark_visited(state, ref)

    notes = [
        item
        for item in (post_data.get("notes") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    listing_path = f"/post/{post_id}/notes/"
    listing_title = f"Заметки поста {post_id}"
    if not notes:
        return _record_listing(
            state, path=listing_path, title=listing_title,
            body=f"У поста {post_id} нет заметок.",
        )

    lines = [f"Заметки поста {post_id}:"]
    for item in notes:
        note_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or note_id).strip() or note_id
        lines.append(f"- note:{note_id} title={title!r}{_attachment_suffix(item.get('files'))}")
    return _record_listing(
        state, path=listing_path, title=listing_title, body="\n".join(lines),
    )


async def tool_list_global_notes(state: AgentState) -> ToolOutcome:
    ref = "global_notes"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)

    try:
        notes = await list_global_notes(state.session, state.user_id, tenant_key=state.tenant_key)
    except Exception as exc:
        return ToolOutcome(summary="Не удалось получить список заметок вне постов.", error=str(exc))

    listing_path = "/global/notes/"
    listing_title = "Заметки вне постов"
    if not notes:
        return _record_listing(
            state, path=listing_path, title=listing_title,
            body="У пользователя нет заметок вне постов.", members=[],
        )

    lines = ["Заметки вне постов:"]
    members: list[dict[str, Any]] = []
    for item in notes:
        note_id = str(item.get("id") or "").strip()
        if not note_id:
            continue
        title_lines = [
            line.strip()
            for line in str(item.get("title") or note_id).splitlines()
            if line.strip()
        ]
        title = (title_lines[0] if title_lines else note_id) or note_id
        created_at = str(item.get("_created_at") or item.get("date") or "").strip()
        date_suffix = f" created_at={created_at!r}" if created_at else ""
        lines.append(
            f"- note:{note_id} title={title!r}{date_suffix}"
            f"{_attachment_suffix(item.get('files'))}"
        )
        body = str(item.get("body") or "").strip()
        members.append(
            {
                "kind": "note",
                "id": note_id,
                "title": title,
                "status": str(item.get("status") or "active"),
                "preview": body[:80] + ("…" if len(body) > 80 else ""),
                "revision": object_index_revision(item),
            }
        )
    return _record_listing(
        state,
        path=listing_path,
        title=listing_title,
        body="\n".join(lines),
        members=members,
    )


async def tool_list_all_notes(state: AgentState) -> ToolOutcome:
    """Enumerate the complete note corpus across global and post-owned notes."""

    from sqlalchemy import select

    from app.db.models import Post

    ref = "all_notes"
    existing = _already_visited(state, ref)
    if existing:
        return existing
    _mark_visited(state, ref)
    try:
        global_notes = await list_global_notes(
            state.session, state.user_id, tenant_key=state.tenant_key
        )
        posts = list(
            (
                await state.session.scalars(
                    select(Post).where(Post.user_id == state.user_id).order_by(Post.position)
                )
            ).all()
        )
    except Exception as exc:
        return ToolOutcome(summary="Не удалось получить полный список заметок.", error=str(exc))

    members: list[dict[str, Any]] = []
    def note_title(value: Any) -> str:
        return next(
            (line.strip() for line in str(value or "").splitlines() if line.strip()),
            "Без названия",
        )

    for item in global_notes:
        note_id = str(item.get("id") or "").strip()
        if not note_id:
            continue
        body = str(item.get("body") or "").strip()
        members.append(
            {
                "kind": "note",
                "id": note_id,
                "title": note_title(item.get("title") or note_id),
                "status": str(item.get("status") or "active"),
                "preview": body[:80] + ("…" if len(body) > 80 else ""),
                "revision": object_index_revision(item),
                "parent_post_id": None,
            }
        )
    for row in posts:
        post_data = dict(row.data or {})
        if str(post_data.get("status") or "").strip().lower() == "deleted":
            continue
        parent_post_id = str(post_data.get("id") or row.id)
        for item in post_data.get("notes") or ():
            if not isinstance(item, Mapping):
                continue
            note_id = str(item.get("id") or "").strip()
            if not note_id:
                continue
            body = str(item.get("body") or "").strip()
            members.append(
                {
                    "kind": "note",
                    "id": note_id,
                    "title": note_title(item.get("title") or note_id),
                    "status": str(item.get("status") or "active"),
                    "preview": body[:80] + ("…" if len(body) > 80 else ""),
                    "revision": object_index_revision(item),
                    "parent_post_id": parent_post_id,
                }
            )
    lines = [f"Все заметки пользователя (total={len(members)}):"]
    lines.extend(
        f"- note:{item['id']} title={item['title']!r}"
        + (f" parent_post={item['parent_post_id']}" if item.get("parent_post_id") else "")
        for item in members
    )
    return _record_listing(
        state,
        path="/notes/",
        title="Все заметки",
        body="\n".join(lines),
        members=members,
    )


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
    title_lines = [
        line.strip()
        for line in str(note_data.get("title") or note_id).splitlines()
        if line.strip()
    ]
    title = (title_lines[0] if title_lines else note_id) or note_id
    body = str(note_data.get("body") or "")
    plain = markdown_to_index_text(title, body)

    # Surface the note's attachments as first-class evidence, not just a count.
    # The answer model only ever sees the verified pack, so a bare `files=2` in
    # the tool summary (planner-only) could never ground "какая заметка с
    # изображениями?" — the pack held text but no file metadata, so the model
    # honestly said "нет информации о вложениях". Listing name+type here (and
    # recording the note even when it has no body but does have files) makes the
    # attachment facts citable without a separate ListNoteAttachments round-trip.
    files = [
        record
        for item in (note_data.get("files") or [])
        if isinstance(item, dict) and (record := note_file_record(item))
    ]
    attachment_lines = [
        f"- {rec['name']} (тип: {rec['type'] or 'неизвестно'}, ref: attachment:{rec['id']})"
        for rec in files
    ]
    parts = [plain.strip()] if plain.strip() else []
    if attachment_lines:
        parts.append("Вложения заметки:\n" + "\n".join(attachment_lines))
    content = "\n\n".join(parts)
    if content:
        cite = NoteCite(
            path=_note_cite_path(state, note_id, post_id),
            title=title,
        )
        state.context_blocks.append((cite, content))

    return ToolOutcome(summary=f"Открыта заметка note:{note_id} ({title!r}), files={len(files)}.")


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
    listing_path = f"/note/{note_id}/attachments/"
    listing_title = f"Вложения заметки {note_id}"
    if not files:
        return _record_listing(
            state, path=listing_path, title=listing_title,
            body=f"У заметки {note_id} нет вложений.",
        )

    image_refs: list[str] = []
    lines = [f"Вложения заметки {note_id}:"]
    for item in files:
        file_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or file_id).strip() or file_id
        mime = str(item.get("type") or item.get("mimeType") or "").strip()
        ref = f"attachment:{file_id}"
        if mime.startswith("image/"):
            image_refs.append(ref)
        lines.append(f"- {ref} name={name!r} type={mime!r}")
    state.listed_image_attachment_refs = image_refs
    return _record_listing(
        state, path=listing_path, title=listing_title, body="\n".join(lines),
    )


def tool_list_post_media(state: AgentState, *, post_id: str) -> ToolOutcome:
    """List a post's directly-attached media as file:-refs the planner can hydrate.

    OpenPost only reports a media count, so the planner had no way to discover
    the file:<mediaKey|idx-N> refs that HydrateAttachment already accepts. This
    closes that gap: documents (PDF/DOCX/text) become readable via
    HydrateAttachment mode=text and images via mode=vision. Voice/video/stickers
    are surfaced by name+type only — there is no ASR/video understanding yet.
    """
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    ref = f"post:{post_id}:media"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    post_data = _post_data_for(state, post_id)
    if not post_data:
        # Recoverable guidance — do not poison the ref (see tool_list_post_notes).
        return ToolOutcome(
            summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
            error="post_not_open",
        )
    _mark_visited(state, ref)

    media = [
        post_media_record(item, index)
        for index, item in enumerate(post_data.get("media") or [])
        if isinstance(item, dict)
    ]
    listing_path = f"/post/{post_id}/media/"
    listing_title = f"Медиа поста {post_id}"
    if not media:
        return _record_listing(
            state, path=listing_path, title=listing_title,
            body=f"У поста {post_id} нет медиа.",
        )

    image_refs: list[str] = []
    lines = [f"Медиа поста {post_id}:"]
    for record in media:
        file_id = record["id"]
        name = record["name"]
        mime = record["type"]
        ref_str = f"file:{file_id}"
        if mime.startswith("image/"):
            image_refs.append(ref_str)
        lines.append(f"- {ref_str} name={name!r} type={mime!r}")
    state.listed_image_media_refs = image_refs
    return _record_listing(
        state, path=listing_path, title=listing_title, body="\n".join(lines),
    )


def _settings_for(state: AgentState) -> Settings:
    return state.settings or get_settings()


def _find_note_file_by_id(note_data: dict[str, Any] | None, file_id: str) -> dict[str, str] | None:
    if not note_data:
        return None
    name_fallback: dict[str, str] | None = None
    for item in note_data.get("files") or []:
        if not isinstance(item, dict):
            continue
        record = note_file_record(item)
        if record and record["id"] == file_id:
            return record
        # Fallback: the planner may use the display name instead of UUID ref
        # (OpenNote summary shows names; planner constructs "attachment:name").
        if record and not name_fallback and record["name"] == file_id:
            name_fallback = record
    return name_fallback


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
) -> str:
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
    # Return the cite_path so callers can surface it in tool summaries — the
    # planner must copy evidence IDs verbatim from the transcript (see AGENT_SYSTEM
    # §evidence_ids rule), but without an explicit path in the summary it falls
    # back to reconstructing from memory and drops UUID characters (chat 9f3d5fdf:
    # last 6 chars of note UUID consistently dropped in FinishRetrieval).
    return cite_path


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
        _mark_visited(state, visit_ref)
        cite_path = _attachment_cite_path(
            ref_kind=ref_kind, file_id=file_id,
            note_id=note_id, post_id=post_id, state=state,
        )
        return ToolOutcome(
            summary=f"Гидратировано {ref} (text), символов={len(text_value)}. [id: {cite_path}]"
        )
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
                return ToolOutcome(
                    summary=(
                        "Vision-модель недоступна: нет OpenAI-совместимой модели с поддержкой "
                        "изображений в настройках профиля. Добавь GPT-4o или аналог в visionModels."
                    ),
                    error="no_vision_model",
                )
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
            if caption and _is_vision_refusal(caption):
                logger.warning(
                    "HydrateAttachment vision refusal for %s (model=%s): %s",
                    ref, model, caption[:120],
                )
                caption = ""
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
        _mark_visited(state, visit_ref)
        # Surface the canonical citation path in the summary so the planner can
        # copy it verbatim into FinishRetrieval evidence_ids — without this it
        # reconstructs from memory and silently truncates UUIDs (chat 9f3d5fdf:
        # last 6 chars of note UUID dropped every time, second image not found).
        cite_path = _attachment_cite_path(
            ref_kind=ref_kind, file_id=file_id,
            note_id=note_id, post_id=post_id, state=state,
        )
        return ToolOutcome(
            summary=f"Гидратировано {ref} (vision), символов={len(caption)}. [id: {cite_path}]"
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        exc_msg = str(exc)[:200]
        logger.warning("HydrateAttachment vision failed for %s: %s: %s", ref, exc_name, exc_msg)
        return ToolOutcome(
            summary=f"Vision-гидратация {ref} не выполнена: {exc_name}: {exc_msg}",
            error=f"{exc_name}: {exc_msg}",
        )


def tool_list_post_comments(state: AgentState, *, post_id: str) -> ToolOutcome:
    post_id = str(post_id or "").strip()
    if not post_id:
        return ToolOutcome(summary="post_id не указан.", error="missing_post_id")

    ref = f"post:{post_id}:comments"
    existing = _already_visited(state, ref)
    if existing:
        return existing

    post_data = _post_data_for(state, post_id)
    if not post_data:
        # See tool_list_post_notes: don't poison the ref on a recoverable
        # "open the post first" guidance return — mark only on success.
        return ToolOutcome(
            summary=f"Пост {post_id} не открыт — сначала вызови OpenPost.",
            error="post_not_open",
        )
    _mark_visited(state, ref)

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
