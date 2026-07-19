"""Hybrid prefetch: pgvector L1 + PostgreSQL FTS + metadata merge."""

from __future__ import annotations

import inspect
import uuid
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.rag_retrieval_policy import retrieve_for_chat


async def fts_search(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query_text: str,
    tenant_key: str | None,
    scope: str,
    post_id: str | None,
    k: int = 6,
) -> list[dict[str, Any]]:
    """Full-text search over indexed chunk_text (tenant-scoped)."""
    q = (query_text or "").strip()
    if len(q) < 2:
        return []

    tenant_clause = "AND tenant_key IS NOT DISTINCT FROM :tenant_key"
    scope_clause = ""
    params: dict[str, Any] = {
        "user_id": user_id,
        "tenant_key": tenant_key,
        "query": q,
        "limit": k,
    }
    if scope == "post" and post_id:
        scope_clause = "AND post_id = :post_id"
        params["post_id"] = post_id

    stmt = text(
        f"""
        SELECT note_id, post_id, node_type, file_id, chunk_text,
               ts_rank(to_tsvector('simple', chunk_text), plainto_tsquery('simple', :query)) AS rank
        FROM note_embeddings
        WHERE user_id = :user_id
          {tenant_clause}
          {scope_clause}
          AND chunk_text <> ''
          AND to_tsvector('simple', chunk_text) @@ plainto_tsquery('simple', :query)
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
                "similarity": float(row["rank"] or 0),
                "source": "fts",
            }
        )
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
    """Dedupe by canonical key and rerank blended scores."""
    merged: dict[str, dict[str, Any]] = {}
    for item in vector_results:
        key = _result_key(item)
        score = float(item.get("similarity") or 0) * vector_weight
        merged[key] = {**item, "blended_score": score, "sources": ["vector"]}
    for item in fts_results:
        key = _result_key(item)
        fts_score = float(item.get("similarity") or 0) * (1.0 - vector_weight)
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
) -> list[dict[str, Any]]:
    # Dependency injection keeps legacy callers/tests able to replace the
    # vector engine while the hybrid path owns the FTS merge.
    retrieve_vector = vector_retriever or retrieve_for_chat
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
    )
    fts = await fts_search(
        session,
        user_id=user_id,
        query_text=query_text,
        tenant_key=tenant_key,
        scope=scope,
        post_id=post_id,
        k=top_k,
    )
    for item in vector:
        item["source"] = "vector"
    return merge_and_rerank(vector_results=vector, fts_results=fts, top_k=top_k)
