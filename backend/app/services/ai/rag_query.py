"""RAG query building: history expansion and conditional LLM rewrite on retrieval miss."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag import format_rag_context, retrieve_top_k
from app.services.ai.rolling_summary import exchanges_from_messages

logger = logging.getLogger(__name__)

RAG_REWRITE_SYSTEM = (
    "Ты переформулируешь последний запрос пользователя в самодостаточный поисковый запрос "
    "для семантического поиска по заметкам. "
    "Разреши местоимения и отсылки («это», «он», «второй пункт», «подробнее») по контексту диалога, "
    "включая прошлые ответы ассистента. "
    "Верни только текст запроса, без кавычек и пояснений."
)

_META_REWRITE_MARKERS = (
    "переформулиру",
    "поисковый запрос",
    "контекст диалога",
    "последний запрос",
)


def _is_invalid_rag_rewrite_response(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered or len(lowered) < 3:
        return True
    if lowered.startswith("переформулиру"):
        return True
    marker_hits = sum(1 for marker in _META_REWRITE_MARKERS if marker in lowered)
    if marker_hits >= 2:
        return True
    return marker_hits >= 1 and len(lowered) < 40


def _history_pairs_excluding_current(
    history: list[Mapping[str, Any]] | None,
    user_text: str,
) -> list[tuple[str, str]]:
    pairs = filter_alternating_roles(linearize_for_llm(history or []))
    current = user_text.strip()
    if pairs and pairs[-1][0] == "user" and pairs[-1][1].strip() == current:
        pairs = pairs[:-1]
    return pairs


def build_rag_query_from_history(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    *,
    history_turns: int = 2,
    max_chars: int = 2000,
) -> str:
    """Build an embedding query from recent dialogue plus the current user message."""
    current = user_text.strip()
    if not current:
        return ""

    pairs = _history_pairs_excluding_current(history, current)
    if not pairs or history_turns <= 0:
        return current

    exchanges = exchanges_from_messages(pairs)
    recent = exchanges[-history_turns:] if history_turns > 0 else []
    if not recent:
        return current

    lines: list[str] = ["Предыдущий диалог:"]
    for user_msg, assistant_msg in recent:
        if user_msg.strip():
            lines.append(f"Пользователь: {user_msg.strip()}")
        if assistant_msg.strip():
            lines.append(f"Ассистент: {assistant_msg.strip()}")
    lines.append(f"Текущий запрос: {current}")

    query = "\n".join(lines)
    if len(query) <= max_chars:
        return query

    # Keep the current query; trim older context from the top.
    tail = f"Текущий запрос: {current}"
    if len(tail) >= max_chars:
        return current

    budget = max_chars - len(tail) - 1
    trimmed_context = query[:budget].rsplit("\n", 1)[0]
    return f"{trimmed_context}\n{tail}"


def build_rag_rewrite_messages(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    *,
    history_turns: int = 4,
) -> list[dict[str, str]]:
    pairs = _history_pairs_excluding_current(history, user_text)
    exchanges = exchanges_from_messages(pairs)
    recent = exchanges[-history_turns:] if history_turns > 0 else []

    dialogue_lines: list[str] = []
    for user_msg, assistant_msg in recent:
        if user_msg.strip():
            dialogue_lines.append(f"Пользователь: {user_msg.strip()}")
        if assistant_msg.strip():
            dialogue_lines.append(f"Ассистент: {assistant_msg.strip()}")

    dialogue = "\n".join(dialogue_lines) if dialogue_lines else "(нет предыдущих реплик)"
    user_content = (
        f"Диалог:\n{dialogue}\n\n"
        f"Последний запрос пользователя:\n{user_text.strip()}\n\n"
        "Самодостаточный поисковый запрос:"
    )
    return [
        {"role": "system", "content": RAG_REWRITE_SYSTEM},
        {"role": "user", "content": user_content},
    ]


async def rewrite_rag_query_llm(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    history_turns: int = 4,
) -> str | None:
    from app.services.ai.llm import complete_chat_completion

    messages = build_rag_rewrite_messages(user_text, history, history_turns=history_turns)
    try:
        rewritten = await complete_chat_completion(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        )
    except Exception as exc:
        logger.warning("RAG query rewrite failed: %s", exc)
        return None

    candidate = rewritten.strip().strip("\"'«»")
    if _is_invalid_rag_rewrite_response(candidate):
        return None
    return candidate


async def _retrieve_top_k_for_query(
    *,
    session: AsyncSession,
    user_id: Any,
    scope: str,
    query_text: str,
    embedding_backend: EmbeddingBackend,
    k: int,
    min_similarity: float,
    post_id: str | None,
    tenant_key: str | None,
) -> list[dict[str, Any]]:
    if not query_text.strip():
        return []
    query_vec = await embedding_backend.embed_query(query_text)
    return await retrieve_top_k(
        session=session,
        user_id=user_id,
        scope=scope,
        query_vec=query_vec,
        model_key=embedding_backend.model_key,
        k=k,
        min_similarity=min_similarity,
        post_id=post_id,
        tenant_key=tenant_key,
    )


async def retrieve_rag_for_reply(
    *,
    session: AsyncSession,
    user_id: Any,
    scope: str,
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    embedding_backend: EmbeddingBackend,
    post_data: Mapping[str, Any] | None,
    tenant_key: str | None,
    post_id: str | None,
    top_k: int,
    min_similarity: float,
    history_turns: int,
    query_max_chars: int,
    rewrite_on_miss: bool,
    rewrite_spec: ProviderSpec | None = None,
    rewrite_model: str | None = None,
    rewrite_api_key: str | None = None,
) -> tuple[str, list[NoteCite]]:
    """Retrieve note context using history-expanded query and optional rewrite-on-miss."""
    base_query = build_rag_query_from_history(
        user_text,
        history,
        history_turns=history_turns,
        max_chars=query_max_chars,
    )
    results = await _retrieve_top_k_for_query(
        session=session,
        user_id=user_id,
        scope=scope,
        query_text=base_query,
        embedding_backend=embedding_backend,
        k=top_k,
        min_similarity=min_similarity,
        post_id=post_id,
        tenant_key=tenant_key,
    )

    query_used = base_query
    if (
        not results
        and rewrite_on_miss
        and rewrite_spec is not None
        and rewrite_model
        and rewrite_api_key
    ):
        rewritten = await rewrite_rag_query_llm(
            user_text,
            history,
            spec=rewrite_spec,
            model=rewrite_model,
            api_key=rewrite_api_key,
            history_turns=max(history_turns, 4),
        )
        if rewritten and rewritten.strip() != user_text.strip():
            retry_results = await _retrieve_top_k_for_query(
                session=session,
                user_id=user_id,
                scope=scope,
                query_text=rewritten,
                embedding_backend=embedding_backend,
                k=top_k,
                min_similarity=min_similarity,
                post_id=post_id,
                tenant_key=tenant_key,
            )
            if retry_results:
                results = retry_results
                query_used = rewritten

    if not results:
        return "", []

    rag_context, rag_cites = await format_rag_context(
        session=session,
        user_id=user_id,
        results=results,
        scope=scope,
        post_data=post_data,
        tenant_key=tenant_key,
    )
    if not rag_cites and rewrite_on_miss and query_used == base_query:
        logger.debug("RAG retrieval returned rows but no note content for query")
    return rag_context, rag_cites
