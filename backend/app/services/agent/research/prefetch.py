"""Hybrid prefetch: pgvector L1 + PostgreSQL FTS + metadata merge."""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.rag import (
    CONTEXTUAL_NODE_TYPES,
    DISCOVERY_NODE_TYPES,
    NODE_NOTE_CHUNK,
    NODE_NOTE_SUMMARY,
    NODE_POST_TEXT,
    NODE_POST_SUMMARY,
    object_index_revision,
)
from app.services.ai.rag_retrieval_policy import retrieve_for_chat

DISCOVERY_FTS_DOCUMENT_SQL = """to_tsvector(
    'simple'::regconfig,
    COALESCE(object_title, '') || ' ' ||
    COALESCE(NULLIF(search_text, ''), chunk_text) || ' ' ||
    COALESCE(keywords::text, '')
)"""


async def resolve_current_source_revisions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    candidates: list[Mapping[str, Any]],
    max_candidates: int = 20,
) -> dict[str, int]:
    """Resolve note/post revisions in one tenant-scoped bounded DB statement."""

    ids = list(
        dict.fromkeys(
            str(item.get("note_id") or item.get("post_id") or item.get("id") or "")
            for item in candidates
            if str(item.get("note_id") or item.get("post_id") or item.get("id") or "")
        )
    )[: max(1, int(max_candidates))]
    if not ids:
        return {}
    placeholders = ", ".join(f":rid_{index}" for index in range(len(ids)))
    params: dict[str, Any] = {"user_id": user_id}
    params.update({f"rid_{index}": value for index, value in enumerate(ids)})
    stmt = text(
        f"""
        SELECT 'global_note' AS source_kind, id::text AS row_id, data
        FROM global_notes
        WHERE user_id = :user_id
          AND (id::text IN ({placeholders}) OR data->>'id' IN ({placeholders}))
        UNION ALL
        SELECT 'post' AS source_kind, id::text AS row_id, data
        FROM posts
        WHERE user_id = :user_id
          AND (
            data->>'id' IN ({placeholders})
            OR EXISTS (
              SELECT 1 FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(data->'notes') = 'array'
                     THEN data->'notes' ELSE '[]'::jsonb END
              ) note
              WHERE note->>'id' IN ({placeholders})
            )
          )
        """
    )
    try:
        result = await session.execute(stmt, params)
        mappings = result.mappings()
        if inspect.isawaitable(mappings):
            mappings = await mappings
        rows = mappings.all()
        if inspect.isawaitable(rows):
            rows = await rows
    except Exception:
        return {}
    revisions: dict[str, int] = {}
    for row in rows:
        data = dict(row.get("data") or {})
        if row.get("source_kind") == "global_note":
            object_id = str(data.get("id") or row.get("row_id") or "")
            revisions[object_id] = object_index_revision(data)
            continue
        post_id = str(data.get("id") or row.get("row_id") or "")
        revisions[post_id] = object_index_revision(data)
        for note in data.get("notes") or ():
            if isinstance(note, Mapping) and note.get("id"):
                revisions[str(note["id"])] = object_index_revision(note)
    return revisions


async def load_discovery_cards_for_objects(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    object_kind: str,
    objects: list[Mapping[str, Any]],
    source_requirement_id: str,
    tenant_key: str | None = None,
    current_source_revisions: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Load fresh summary nodes for an authoritative catalog, without ranking.

    Search ranking answers "which objects are relevant". A complete-coverage
    contract needs a different primitive: every catalog member must get its
    current semantic card, even when its wording has low similarity to the
    query. This query remains tenant-scoped and validates the indexed revision
    against the revision returned by the catalog.
    """

    node_type = NODE_POST_SUMMARY if object_kind == "posts" else NODE_NOTE_SUMMARY
    ids = list(dict.fromkeys(str(item.get("id") or "") for item in objects if str(item.get("id") or "")))
    if not ids:
        return []
    placeholders = ", ".join(f":card_id_{index}" for index in range(len(ids)))
    params: dict[str, Any] = {
        "user_id": user_id,
        "node_type": node_type,
        "tenant_key": tenant_key or "",
    }
    params.update({f"card_id_{index}": value for index, value in enumerate(ids)})
    stmt = text(
        f"""
        SELECT note_id, post_id, chunk_text, object_title, object_status,
               index_revision, summary_version, summary_model,
               selector_summary, selector_summary_version
        FROM note_embeddings
        WHERE user_id = :user_id
          AND (tenant_key = :tenant_key OR tenant_key = '')
          AND node_type = :node_type
          AND note_id IN ({placeholders})
          AND chunk_text <> ''
        """
    )
    try:
        result = await session.execute(stmt, params)
        mappings = result.mappings()
        if inspect.isawaitable(mappings):
            mappings = await mappings
        rows = mappings.all()
        if inspect.isawaitable(rows):
            rows = await rows
    except Exception:
        return []
    by_id = {str(row.get("note_id") or row.get("post_id") or ""): row for row in rows}
    result_rows: list[dict[str, Any]] = []
    for item in objects:
        object_id = str(item.get("id") or "")
        row = by_id.get(object_id)
        if row is None:
            continue
        if current_source_revisions is not None:
            catalog_revision = int(current_source_revisions.get(object_id) or 0)
        else:
            catalog_revision = int(
                item.get("index_revision") or item.get("revision") or 0
            )
        index_revision = int(row.get("index_revision") or 0)
        if catalog_revision <= 0 or index_revision != catalog_revision:
            continue
        result_rows.append(
            {
                "ref": f"{'post' if object_kind == 'posts' else 'note'}:{object_id}",
                "label": f"{'post' if object_kind == 'posts' else 'note'}:{object_id}",
                "origin": "authoritative_catalog",
                "semantic_score": None,
                "node_type": node_type,
                "summary_only": True,
                "index_revision": index_revision,
                "source_revision": catalog_revision,
                "summary_version": int(row.get("summary_version") or 0),
                "summary_model": str(row.get("summary_model") or ""),
                "selector_summary": str(row.get("selector_summary") or ""),
                "selector_summary_version": int(row.get("selector_summary_version") or 0),
                "title": str(row.get("object_title") or item.get("title") or ""),
                "preview": str(row.get("chunk_text") or "")[:480],
                "status": str(row.get("object_status") or item.get("status") or "active"),
                "parent_post_id": str(
                    item.get("parent_post_id") or row.get("post_id") or ""
                ) or None,
                "has_more": False,
                "source_requirement_id": source_requirement_id,
                **{
                    key: item.get(key)
                    for key in (
                        "file_count",
                        "image_count",
                        "has_files",
                        "has_images",
                        "direct_image_count",
                        "note_image_files_total",
                        "has_any_images",
                    )
                    if key in item
                },
            }
        )
    return result_rows


async def fts_search(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query_text: str,
    tenant_key: str | None,
    scope: str,
    post_id: str | None,
    k: int = 6,
    node_types_filter: frozenset[str] | None = None,
    object_ids: frozenset[str] | None = None,
    object_statuses: frozenset[str] | None = None,
    expected_revisions: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Full-text search over indexed chunk_text (tenant-scoped)."""
    q = (query_text or "").strip()
    if len(q) < 2:
        return []

    tenant_clause = (
        "AND (tenant_key = :tenant_key OR tenant_key = '')"
        if tenant_key
        else "AND tenant_key = ''"
    )
    scope_clause = ""
    params: dict[str, Any] = {
        "user_id": user_id,
        "tenant_key": tenant_key,
        "query": q,
        "limit": k,
    }
    if scope == "post" and post_id:
        scope_clause = "AND (scope = 'global' OR (scope = 'post' AND post_id = :post_id))"
        params["post_id"] = post_id

    type_clause = ""
    if node_types_filter:
        placeholders = ", ".join(f":ft_{i}" for i in range(len(node_types_filter)))
        type_clause = f"AND node_type IN ({placeholders})"
        for index, node_type in enumerate(sorted(node_types_filter)):
            params[f"ft_{index}"] = node_type
    object_clause = ""
    if object_ids:
        placeholders = ", ".join(f":fo_{i}" for i in range(len(object_ids)))
        object_clause = f"AND note_id IN ({placeholders})"
        for index, object_id in enumerate(sorted(object_ids)):
            params[f"fo_{index}"] = object_id
    status_clause = ""
    if object_statuses:
        placeholders = ", ".join(f":fs_{i}" for i in range(len(object_statuses)))
        status_clause = f"AND object_status IN ({placeholders})"
        for index, status in enumerate(sorted(object_statuses)):
            params[f"fs_{index}"] = status

    stmt = text(
        f"""
        SELECT note_id, post_id, node_type, file_id, chunk_text, search_text,
               object_title, object_status, index_revision, keywords,
               summary_version, summary_model, selector_summary, selector_summary_version,
               ts_rank({DISCOVERY_FTS_DOCUMENT_SQL},
                       plainto_tsquery('simple', :query)) AS rank
        FROM note_embeddings
        WHERE user_id = :user_id
          {tenant_clause}
          {scope_clause}
          {type_clause}
          {object_clause}
          {status_clause}
          AND chunk_text <> ''
          AND {DISCOVERY_FTS_DOCUMENT_SQL}
              @@ plainto_tsquery('simple', :query)
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    try:
        result = await session.execute(stmt, params)
        mappings = result.mappings()
        if inspect.isawaitable(mappings):
            mappings = await mappings
        rows = mappings.all()
        if inspect.isawaitable(rows):
            rows = await rows
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "note_id": row["note_id"],
                "post_id": row["post_id"],
                "node_type": row["node_type"],
                "file_id": row["file_id"],
                "chunk_text": row["chunk_text"],
                "search_text": row.get("search_text") or row["chunk_text"],
                "object_title": row.get("object_title") or "",
                "object_status": row.get("object_status") or "",
                "index_revision": int(row.get("index_revision") or 1),
                "summary_version": int(row.get("summary_version") or 0),
                "summary_model": str(row.get("summary_model") or ""),
                "selector_summary": str(row.get("selector_summary") or ""),
                "selector_summary_version": int(row.get("selector_summary_version") or 0),
                "keywords": (
                    json.loads(row.get("keywords"))
                    if isinstance(row.get("keywords"), str)
                    else list(row.get("keywords") or ())
                ),
                "is_discovery_node": str(row["node_type"] or "") in DISCOVERY_NODE_TYPES,
                "similarity": float(row["rank"] or 0),
                "source": "fts",
            }
        )
    if expected_revisions:
        results = [
            item
            for item in results
            if str(item.get("note_id") or "") not in expected_revisions
            or int(item.get("index_revision") or 1)
            == int(expected_revisions[str(item.get("note_id"))])
        ]
    return results


def _result_key(item: Mapping[str, Any]) -> str:
    return ":".join(
        [
            str(item.get("node_type") or ""),
            str(item.get("note_id") or ""),
            str(item.get("file_id") or ""),
            str(item.get("post_id") or ""),
        ]
    )


def merge_and_rerank(
    *,
    vector_results: list[dict[str, Any]],
    fts_results: list[dict[str, Any]],
    top_k: int = 8,
    vector_weight: float = 0.7,
) -> list[dict[str, Any]]:
    """Dedupe by canonical key and rank-fuse vector/lexical result lists."""
    merged: dict[str, dict[str, Any]] = {}
    rank_constant = 60
    for rank, item in enumerate(vector_results, start=1):
        key = _result_key(item)
        score = vector_weight / (rank_constant + rank)
        merged[key] = {**item, "blended_score": score, "sources": ["vector"]}
    for rank, item in enumerate(fts_results, start=1):
        key = _result_key(item)
        fts_score = (1.0 - vector_weight) / (rank_constant + rank)
        if key in merged:
            merged[key]["blended_score"] = merged[key].get("blended_score", 0) + fts_score
            merged[key]["sources"] = list(set(merged[key].get("sources", []) + ["fts"]))
        else:
            merged[key] = {**item, "blended_score": fts_score, "sources": ["fts"]}
    ranked = sorted(merged.values(), key=lambda x: x.get("blended_score", 0), reverse=True)
    return ranked[:top_k]


async def hybrid_prefetch(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    scope: str,
    query_text: str,
    embedding_backend: EmbeddingBackend,
    tenant_key: str | None,
    post_id: str | None = None,
    top_k: int = 8,
    min_similarity: float = 0.38,
    scope_bias: float = 0.04,
    vector_retriever=None,
    node_types_filter: frozenset[str] | None = None,
    object_ids: frozenset[str] | None = None,
    object_statuses: frozenset[str] | None = None,
    expected_revisions: Mapping[str, int] | None = None,
    query_vec: list[float] | None = None,
) -> list[dict[str, Any]]:
    # Dependency injection keeps legacy callers/tests able to replace the
    # vector engine while the hybrid path owns the FTS merge.
    retrieve_vector = vector_retriever or retrieve_for_chat
    if query_vec is None:
        query_vec = await embedding_backend.embed_query(query_text)
    vector = await retrieve_vector(
        session=session,
        user_id=user_id,
        chat_scope=scope,
        query_vec=query_vec,
        embedding_backend=embedding_backend,
        k=top_k,
        min_similarity=min_similarity,
        post_id=post_id,
        tenant_key=tenant_key,
        scope_bias=scope_bias,
        node_types_filter=node_types_filter,
        object_ids=object_ids,
        object_statuses=object_statuses,
        expected_revisions=expected_revisions,
    )
    fts = await fts_search(
        session,
        user_id=user_id,
        query_text=query_text,
        tenant_key=tenant_key,
        scope=scope,
        post_id=post_id,
        k=top_k,
        node_types_filter=node_types_filter,
        object_ids=object_ids,
        object_statuses=object_statuses,
        expected_revisions=expected_revisions,
    )
    for item in vector:
        item["source"] = "vector"
    if node_types_filter is not None:
        fts = [
            item
            for item in fts
            if str(item.get("node_type") or "") in node_types_filter
        ]
    return merge_and_rerank(vector_results=vector, fts_results=fts, top_k=top_k)


async def retrieve_for_discovery(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    scope: str,
    query_text: str,
    embedding_backend: EmbeddingBackend,
    tenant_key: str | None,
    post_id: str | None = None,
    top_k: int = 8,
    min_similarity: float = 0.38,
    scope_bias: float = 0.04,
    node_types_filter: frozenset[str] | None = None,
    vector_retriever=None,
    candidate_limit: int = 5,
    selected_object_ids: frozenset[str] | None = None,
    expected_revisions: Mapping[str, int] | None = None,
    object_statuses: frozenset[str] | None = None,
    query_vec: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Candidate-first discovery followed by scoped contextual chunk search.

    The first pass fuses object summaries with a bounded contextual fallback.
    A selected object-id set switches
    the same policy to chunk-only retrieval, preventing a follow-up query from
    scanning the whole tenant again.
    """
    limit = max(1, min(10, int(candidate_limit or 6)))
    if query_vec is None:
        query_vec = await embedding_backend.embed_query(query_text)
    if selected_object_ids:
        return await hybrid_prefetch(
            session,
            user_id=user_id,
            scope=scope,
            query_text=query_text,
            embedding_backend=embedding_backend,
            tenant_key=tenant_key,
            post_id=post_id,
            top_k=max(1, int(top_k or 8)),
            min_similarity=min_similarity,
            scope_bias=scope_bias,
            node_types_filter=node_types_filter or CONTEXTUAL_NODE_TYPES,
            object_ids=selected_object_ids,
            expected_revisions=expected_revisions,
            object_statuses=object_statuses,
            vector_retriever=vector_retriever,
            query_vec=query_vec,
        )
    summary_filter = (
        frozenset(node_types_filter & DISCOVERY_NODE_TYPES)
        if node_types_filter is not None
        else DISCOVERY_NODE_TYPES
    )
    contextual_filter = (
        frozenset(node_types_filter & CONTEXTUAL_NODE_TYPES)
        if node_types_filter is not None
        else CONTEXTUAL_NODE_TYPES
    )
    summary_hits = await hybrid_prefetch(
        session,
        user_id=user_id,
        scope=scope,
        query_text=query_text,
        embedding_backend=embedding_backend,
        tenant_key=tenant_key,
        post_id=post_id,
        top_k=limit + 1,
        min_similarity=min_similarity,
        scope_bias=scope_bias,
        node_types_filter=summary_filter,
        expected_revisions=expected_revisions,
        object_statuses=object_statuses,
        vector_retriever=vector_retriever,
        query_vec=query_vec,
    ) if summary_filter else []
    contextual_hits = await hybrid_prefetch(
        session,
        user_id=user_id,
        scope=scope,
        query_text=query_text,
        embedding_backend=embedding_backend,
        tenant_key=tenant_key,
        post_id=post_id,
        top_k=limit + 1,
        min_similarity=min_similarity,
        scope_bias=scope_bias,
        node_types_filter=contextual_filter,
        expected_revisions=expected_revisions,
        object_statuses=object_statuses,
        vector_retriever=vector_retriever,
        query_vec=query_vec,
    ) if contextual_filter else []

    def object_key(item: Mapping[str, Any]) -> str:
        node_type = str(item.get("node_type") or "")
        kind = (
            "note"
            if node_type in {NODE_NOTE_CHUNK, NODE_NOTE_SUMMARY}
            else "post"
            if node_type in {NODE_POST_TEXT, NODE_POST_SUMMARY}
            else node_type
        )
        return ":".join(
            [
                kind,
                str(item.get("note_id") or ""),
                str(item.get("post_id") or ""),
            ]
        )

    fused: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(summary_hits):
        key = object_key(item)
        fused[key] = {
            **item,
            "blended_score": float(item.get("blended_score") or item.get("similarity") or 0),
            "sources": list(item.get("sources") or ["summary"]),
            "candidate": True,
            "summary_only": True,
            "summary_rank": rank + 1,
            "rank_fusion_score": 1.0 / (60 + rank + 1),
        }
    for rank, item in enumerate(contextual_hits):
        key = object_key(item)
        current = fused.get(key)
        score = float(item.get("blended_score") or item.get("similarity") or 0)
        if current is None:
            fused[key] = {
                **item,
                "blended_score": score,
                "candidate": True,
                "context_rank": rank + 1,
                "rank_fusion_score": 1.0 / (60 + rank + 1),
            }
            continue
        current["blended_score"] = max(float(current.get("blended_score") or 0), score)
        current["sources"] = sorted(
            set(current.get("sources") or ()) | set(item.get("sources") or ()) | {"context"}
        )
        current["context_rank"] = rank + 1
        current["rank_fusion_score"] = float(current.get("rank_fusion_score") or 0) + (
            1.0 / (60 + rank + 1)
        )
    ranked = sorted(
        fused.values(),
        key=lambda item: (
            float(item.get("rank_fusion_score") or 0),
            float(item.get("blended_score") or 0),
        ),
        reverse=True,
    )
    has_more = len(ranked) > limit
    selected = ranked[:limit]
    revisions = await resolve_current_source_revisions(
        session,
        user_id=user_id,
        candidates=selected,
    )
    selected = [
        {
            **item,
            "source_revision": revisions.get(
                str(item.get("note_id") or item.get("post_id") or "")
            ),
            "has_more": has_more,
        }
        for item in selected
    ]

    # A contextual chunk may rank above (or pass the threshold when) its
    # semantic summary does not. Discovery still needs to expose the object's
    # durable card, not an arbitrary slice of source text. Resolve the cards by
    # exact object ID after ranking; this is a bounded DB read and does not call
    # an LLM during the dialog.
    card_objects: dict[str, list[dict[str, Any]]] = {"notes": [], "posts": []}
    for item in selected:
        node_type = str(item.get("node_type") or "")
        object_kind = (
            "notes"
            if node_type == NODE_NOTE_CHUNK
            else "posts"
            if node_type == NODE_POST_TEXT
            else ""
        )
        object_id = str(item.get("note_id") or item.get("post_id") or "")
        if not object_kind or not object_id:
            continue
        card_objects[object_kind].append(
            {
                "id": object_id,
                "revision": int(
                    item.get("source_revision") or item.get("index_revision") or 0
                ),
                "title": str(item.get("object_title") or ""),
                "status": str(item.get("object_status") or "active"),
                "parent_post_id": str(item.get("post_id") or "") or None,
            }
        )

    cards_by_ref: dict[str, dict[str, Any]] = {}
    for object_kind, objects in card_objects.items():
        if not objects:
            continue
        cards = await load_discovery_cards_for_objects(
            session,
            user_id=user_id,
            object_kind=object_kind,
            objects=objects,
            source_requirement_id="",
            tenant_key=tenant_key,
        )
        cards_by_ref.update({str(card.get("ref") or ""): card for card in cards})

    promoted: list[dict[str, Any]] = []
    for item in selected:
        node_type = str(item.get("node_type") or "")
        prefix = (
            "note"
            if node_type == NODE_NOTE_CHUNK
            else "post"
            if node_type == NODE_POST_TEXT
            else ""
        )
        object_id = str(item.get("note_id") or item.get("post_id") or "")
        card = (
            cards_by_ref.get(f"{prefix}:{object_id}")
            if prefix and object_id
            else None
        )
        if card is None:
            promoted.append(item)
            continue
        promoted.append(
            {
                **item,
                **card,
                # Preserve query-specific ranking separately from the exact
                # card lookup that supplied the durable summary.
                "origin": "semantic_search",
                "semantic_score": item.get("similarity"),
                "similarity": item.get("similarity"),
                "blended_score": item.get("blended_score"),
                "rank_fusion_score": item.get("rank_fusion_score"),
                "sources": item.get("sources"),
                "has_more": item.get("has_more"),
                "source_revision": item.get("source_revision"),
            }
        )
    return promoted
