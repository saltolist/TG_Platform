"""Retrieval pool policy and merged ranking for global/post chat scopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.rag import (
    NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META,
    NODE_NOTE_CHUNK,
    NODE_POST_TEXT,
    retrieve_top_k,
)

TEXT_NODE_TYPES = frozenset(
    {NODE_NOTE_CHUNK, NODE_POST_TEXT, NODE_ATTACHMENT_TEXT, NODE_MEDIA_META}
)
NOTE_CHUNK_TYPES = frozenset({NODE_NOTE_CHUNK, NODE_ATTACHMENT_TEXT, NODE_MEDIA_META})


def effective_post_id(
    post_data: Mapping[str, Any] | None,
    post_id: str | None,
) -> str | None:
    """Return the post id used in note_embeddings (data.id), not the Postgres row UUID."""
    if post_data is not None:
        effective = str(post_data.get("id") or "").strip()
        if effective:
            return effective
    if post_id:
        return str(post_id).strip() or None
    return None


def post_id_aliases(
    post_data: Mapping[str, Any] | None,
    *,
    row_post_id: str | None = None,
) -> frozenset[str]:
    """All identifiers that refer to the same post in API paths and embeddings."""
    aliases: set[str] = set()
    if row_post_id:
        value = str(row_post_id).strip()
        if value:
            aliases.add(value)
    if post_data is not None:
        effective = str(post_data.get("id") or "").strip()
        if effective:
            aliases.add(effective)
    return frozenset(aliases)


@dataclass(frozen=True)
class RetrievalPass:
    scope: str
    node_types: frozenset[str] | None = None
    post_id: str | None = None
    post_id_eq: str | None = None
    post_id_neq: str | None = None
    is_home: bool = False


def pools_for_chat(chat_scope: str, post_id: str | None) -> list[RetrievalPass]:
    """Return retrieval passes for the current chat context."""
    if chat_scope == "post" and post_id:
        return [
            RetrievalPass(
                scope="post",
                post_id=post_id,
                node_types=NOTE_CHUNK_TYPES,
                is_home=True,
            ),
            RetrievalPass(
                scope="global",
                node_types=frozenset({NODE_NOTE_CHUNK}),
                is_home=False,
            ),
            RetrievalPass(
                scope="global",
                node_types=frozenset({NODE_POST_TEXT}),
                post_id_eq=post_id,
                is_home=False,
            ),
            RetrievalPass(
                scope="global",
                node_types=frozenset({NODE_POST_TEXT}),
                post_id_neq=post_id,
                is_home=False,
            ),
        ]

    return [
        RetrievalPass(scope="global", node_types=TEXT_NODE_TYPES, is_home=True),
        RetrievalPass(
            scope="post",
            node_types=frozenset({NODE_NOTE_CHUNK}),
            is_home=False,
        ),
    ]


def merge_hits(
    pass_results: list[tuple[RetrievalPass, list[dict[str, Any]]]],
    *,
    scope_bias: float,
    k: int,
) -> list[dict[str, Any]]:
    """Merge multi-pass hits with optional home-scope bias."""
    combined: list[dict[str, Any]] = []
    for pass_cfg, hits in pass_results:
        boost = scope_bias if pass_cfg.is_home else 0.0
        for hit in hits:
            item = dict(hit)
            raw_similarity = float(item.get("similarity") or 0.0)
            item["raw_similarity"] = raw_similarity
            item["similarity"] = raw_similarity + boost
            combined.append(item)

    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in combined:
        key = (
            str(item.get("node_type") or ""),
            str(item.get("note_id") or ""),
            str(item.get("file_id") or ""),
        )
        if key not in seen or float(item["similarity"]) > float(seen[key]["similarity"]):
            seen[key] = item

    return sorted(seen.values(), key=lambda row: float(row["similarity"]), reverse=True)[:k]


async def retrieve_for_chat(
    *,
    session: AsyncSession,
    user_id: Any,
    chat_scope: str,
    query_vec: list[float],
    embedding_backend: EmbeddingBackend,
    k: int,
    min_similarity: float,
    post_id: str | None = None,
    tenant_key: str | None = None,
    scope_bias: float = 0.04,
    node_types_filter: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Run all retrieval passes for a chat and return merged top-k."""
    passes = pools_for_chat(chat_scope, post_id)
    pass_results: list[tuple[RetrievalPass, list[dict[str, Any]]]] = []

    for pass_cfg in passes:
        allowed_types = pass_cfg.node_types
        if node_types_filter is not None:
            if allowed_types is None:
                allowed_types = node_types_filter
            else:
                allowed_types = allowed_types & node_types_filter
            if not allowed_types:
                continue

        hits = await retrieve_top_k(
            session=session,
            user_id=user_id,
            scope=pass_cfg.scope,
            query_vec=query_vec,
            model_key=embedding_backend.model_key,
            k=k,
            min_similarity=min_similarity,
            post_id=pass_cfg.post_id,
            tenant_key=tenant_key,
            node_types=allowed_types,
            post_id_eq=pass_cfg.post_id_eq,
            post_id_neq=pass_cfg.post_id_neq,
            exclude_deleted_posts=True,
        )
        pass_results.append((pass_cfg, hits))

    return merge_hits(pass_results, scope_bias=scope_bias, k=k)
