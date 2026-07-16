"""RAG query building: history expansion and conditional LLM rewrite on retrieval miss."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag import format_rag_context
from app.services.ai.rag_retrieval_policy import (
    effective_post_id,
    post_id_aliases,
    retrieve_for_chat,
)
from app.services.ai.rag_dialog_ledger import (
    append_turn,
    build_snapshot_from_agent_state,
    chat_ledger_key,
    ledger_chat_id,
    load_ledger,
    referential_hints_from_ledger,
)
from app.services.ai.rag_escalation import TierAResult, evaluate_tier_a
from app.services.ai.rag_gate import l0_skip_reason
from app.services.ai.intent_router import classify_intent
from app.services.ai.rag_manifest import filter_unopened_neighbors
from app.services.ai.rag_sufficiency import TierBResult, evaluate_tier_b
from app.services.ai.reply_pipeline_log import format_retrieval_hits, trace_step
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


def _preview_query(text: str, limit: int = 200) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


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


def build_planner_dialog_context(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    *,
    history_turns: int = 2,
    max_chars: int = 1500,
) -> str:
    """Recent dialogue for L2 brief/planner (excludes duplicate current user turn)."""
    pairs = _history_pairs_excluding_current(history, user_text)
    if not pairs or history_turns <= 0:
        return ""

    exchanges = exchanges_from_messages(pairs)
    recent = exchanges[-history_turns:] if history_turns > 0 else []
    if not recent:
        return ""

    lines: list[str] = []
    for user_msg, assistant_msg in recent:
        if user_msg.strip():
            lines.append(f"Пользователь: {user_msg.strip()}")
        if assistant_msg.strip():
            snippet = assistant_msg.strip()
            if len(snippet) > 400:
                snippet = f"{snippet[:399]}…"
            lines.append(f"Ассистент: {snippet}")

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


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
    scope_bias: float = 0.04,
) -> list[dict[str, Any]]:
    if not query_text.strip():
        return []
    from app.core.config import get_settings

    settings = get_settings()
    if settings.rag_l2_engine == "langgraph":
        from app.services.agent.research.prefetch import hybrid_prefetch

        return await hybrid_prefetch(
            session,
            user_id=user_id,
            scope=scope,
            query_text=query_text,
            embedding_backend=embedding_backend,
            tenant_key=tenant_key,
            post_id=post_id,
            top_k=k,
            min_similarity=min_similarity,
            scope_bias=scope_bias,
        )
    query_vec = await embedding_backend.embed_query(query_text)
    return await retrieve_for_chat(
        session=session,
        user_id=user_id,
        chat_scope=scope,
        query_vec=query_vec,
        embedding_backend=embedding_backend,
        k=k,
        min_similarity=min_similarity,
        post_id=post_id,
        tenant_key=tenant_key,
        scope_bias=scope_bias,
    )


def _should_escalate(
    rag_mode: str,
    tier_a: TierAResult,
    tier_b: TierBResult | None,
) -> bool:
    if rag_mode == "off":
        return False
    if rag_mode == "flat":
        return False
    if rag_mode == "agentic":
        return True
    if rag_mode == "auto":
        if tier_a.fast_path is not None:
            return True
        if tier_b is not None and not tier_b.sufficient:
            return True
    return False


def _seed_and_hints(
    tier_a: TierAResult,
    tier_b: TierBResult | None,
    *,
    user_text: str = "",
    scope: str = "global",
    chat_post_id: str | None = None,
    intent_routing_enabled: bool = False,
) -> tuple[str | None, str | None, list[str]]:
    candidates: list[str] = []
    if tier_a.escalate_target:
        candidates.append(tier_a.escalate_target)
    if tier_b and tier_b.open_next:
        candidates.extend(tier_b.open_next)

    seed_ref: str | None = None
    seed_post_id: str | None = tier_a.escalate_post_id
    hints: list[str] = []
    if scope == "post" and chat_post_id:
        seed_post_id = seed_post_id or chat_post_id
        hints.append(f"OpenPost post_id={chat_post_id} — пользователь уже в post-чате этого поста")
    for ref in candidates:
        text = str(ref).strip()
        if not text:
            continue
        if seed_ref is None and text.startswith("note:"):
            seed_ref = text
        elif text.startswith("post:"):
            post_id = text[len("post:") :].strip()
            if post_id:
                hints.append(f"OpenPost post_id={post_id}")
        else:
            hints.append(text)

    if intent_routing_enabled and scope == "global":
        intent = classify_intent(user_text, has_post_context=False)
        if intent == "post_analytics":
            hints.append(
                "Похоже, вопрос про статистику поста — сначала найди пост через "
                "SearchNodes/OpenPost, затем вызови GetPostAnalytics."
            )
        elif intent == "channel_analytics":
            # TODO(Priority 3): route to GetChannelAnalytics / GetTopPosts
            logger.debug("RAG intent channel_analytics detected — deferred to Priority 3")

    for index, hint in enumerate(hints):
        lowered = hint.lower()
        if "comment" in lowered or "комментар" in lowered:
            hints[index] = f"{hint} (используй ListPostComments)"
    return seed_ref, seed_post_id, hints


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
    l0_enabled: bool = True,
    escalate_min_similarity: float = 0.72,
    escalate_on_miss: bool = True,
    tier_b_enabled: bool = False,
    rag_mode: str = "off",
    rag_agent_max_steps: int = 4,
    rag_agent_planning_mode: str = "auto",
    user: Any | None = None,
    ai_profile: Mapping[str, Any] | None = None,
    intent_routing_enabled: bool = False,
    scope_bias: float = 0.04,
    chat_id: str | None = None,
    post_chat_id: str | None = None,
) -> tuple[str, list[NoteCite]]:
    """Retrieve note context using history-expanded query and optional rewrite-on-miss."""
    row_post_id = post_id
    rag_post_id = effective_post_id(post_data, post_id) if scope == "post" else post_id
    rag_post_aliases = (
        post_id_aliases(post_data, row_post_id=row_post_id) if scope == "post" else frozenset()
    )

    if l0_enabled:
        reason = l0_skip_reason(user_text)
        if reason:
            logger.debug("RAG L0 skip (%s): %r", reason, user_text[:80])
            trace_step(
                "3. rag.L0",
                [
                    f"skip reason={reason}",
                    "→ no embed, no vector search, no L2",
                ],
            )
            trace_step("8. rag.result", "context_chars=0 cites=0")
            return "", []

    trace_step("3. rag.L0", "pass — running L1 retrieval")

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
        post_id=rag_post_id,
        tenant_key=tenant_key,
        scope_bias=scope_bias,
    )

    trace_step(
        "4. rag.L1.query",
        [
            f"effective_post_id={rag_post_id or '—'}",
            f"query_chars={len(base_query)}",
            f"query_preview: {_preview_query(base_query)}",
        ],
    )
    trace_step("4. rag.L1.hits", format_retrieval_hits(results))

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
                post_id=rag_post_id,
                tenant_key=tenant_key,
                scope_bias=scope_bias,
            )
            if retry_results:
                results = retry_results
                query_used = rewritten
                trace_step(
                    "4. rag.L1.rewrite",
                    [
                        f"rewritten_query_chars={len(rewritten)}",
                        f"rewritten_preview: {_preview_query(rewritten)}",
                        f"retry_hits={len(retry_results)}",
                    ],
                )

    tier_a = evaluate_tier_a(
        user_text=user_text,
        history=history,
        results=results,
        post_data=post_data,
        min_similarity_escalate=escalate_min_similarity,
        escalate_on_miss=escalate_on_miss,
        chat_scope=scope,
        chat_post_id=rag_post_id,
        chat_post_id_aliases=rag_post_aliases,
    )
    logger.info(
        "RAG Tier A: fast_path=%s target=%s signals=%s",
        tier_a.fast_path,
        tier_a.escalate_target,
        tier_a.signals,
    )
    trace_step(
        "5. rag.tier_a",
        [
            f"fast_path={tier_a.fast_path}",
            f"escalate_target={tier_a.escalate_target or '—'}",
            f"escalate_post_id={tier_a.escalate_post_id or '—'}",
            (
                "signals: "
                f"pointer_phrase={tier_a.signals.pointer_phrase} "
                f"answer_type_mismatch={tier_a.signals.answer_type_mismatch} "
                f"chunk_too_short={tier_a.signals.chunk_too_short} "
                f"is_followup={tier_a.signals.is_followup}"
            ),
            f"manifest_neighbors={tier_a.neighbors or {}}",
        ],
    )

    if not results and rag_mode not in ("agentic", "auto"):
        trace_step(
            "8. rag.result",
            [
                f"rag_mode={rag_mode} — early exit on empty L1",
                "context_chars=0 cites=0",
            ],
        )
        return "", []

    tier_b: TierBResult | None = None
    tier_b_task: asyncio.Task[TierBResult] | None = None
    if (
        results
        and tier_b_enabled
        and tier_a.fast_path in (None, "miss")
        and rewrite_spec is not None
        and rewrite_model
        and rewrite_api_key
    ):
        tier_b_task = asyncio.create_task(
            evaluate_tier_b(
                user_text=user_text,
                chunk_text=str(results[0].get("chunk_text") or ""),
                signals=tier_a.signals,
                neighbors=filter_unopened_neighbors(tier_a.neighbors, results),
                spec=rewrite_spec,
                model=rewrite_model,
                api_key=rewrite_api_key,
            )
        )

    rag_context, rag_cites = "", []

    if tier_b_task is not None:
        tier_b = await tier_b_task
        logger.info(
            "RAG Tier B: sufficient=%s open_next=%s error=%s",
            tier_b.sufficient,
            tier_b.open_next,
            tier_b.error,
        )
        trace_step(
            "6. rag.tier_b",
            [
                f"sufficient={tier_b.sufficient}",
                f"open_next={tier_b.open_next or []}",
                f"error={tier_b.error or '—'}",
            ],
        )
    elif tier_b_enabled:
        if not results:
            tier_b_skip = "no L1 hits"
        elif tier_a.fast_path not in (None, "miss"):
            tier_b_skip = f"fast_path={tier_a.fast_path}"
        elif not (rewrite_spec and rewrite_model and rewrite_api_key):
            tier_b_skip = "no reasoner LLM"
        else:
            tier_b_skip = "unknown"
        trace_step("6. rag.tier_b", f"skipped — {tier_b_skip}")
    else:
        trace_step("6. rag.tier_b", "disabled (RAG_TIER_B_ENABLED=0)")

    should_escalate = _should_escalate(rag_mode, tier_a, tier_b)
    l2_will_run = (
        should_escalate
        and rewrite_spec is not None
        and rewrite_model
        and rewrite_api_key
    )

    if results and not l2_will_run:
        rag_context, rag_cites = await format_rag_context(
            session=session,
            user_id=user_id,
            results=results,
            scope=scope,
            post_data=post_data,
            tenant_key=tenant_key,
        )

    if l2_will_run:
        seed_ref, seed_post_id, hints = _seed_and_hints(
            tier_a,
            tier_b,
            user_text=user_text,
            scope=scope,
            chat_post_id=rag_post_id,
            intent_routing_enabled=intent_routing_enabled,
        )
        from app.core.config import get_settings
        from app.db.session import async_session_factory
        from app.services.agent.research.graph import run_research_graph
        from app.services.agent.runtime.context import RuntimeContext

        settings = get_settings()
        ledger_key = chat_ledger_key(
            scope=scope,
            chat_id=ledger_chat_id(
                scope=scope,
                chat_id=chat_id,
                post_chat_id=post_chat_id,
            ),
            post_id=rag_post_id,
        )
        dialog_ledger = await load_ledger(
            session,
            user_id=user_id,
            chat_key=ledger_key,
        )
        hints.extend(referential_hints_from_ledger(user_text, dialog_ledger))

        trace_step(
            "7. rag.L2",
            [
                f"rag_mode={rag_mode}",
                f"engine={settings.rag_l2_engine}",
                "should_escalate=True — starting research graph",
                f"seed_ref={seed_ref or '—'}",
                f"seed_post_id={seed_post_id or '—'}",
                f"hints={hints}",
                f"max_steps={rag_agent_max_steps}",
            ],
        )

        runtime_ctx = RuntimeContext(
            session_factory=async_session_factory,
            user_id=user_id,
            user=user,
            tenant_key=tenant_key,
            settings=settings,
            embedding_backend=embedding_backend,
            scope=scope,
            post_data=post_data,
            ai_profile=ai_profile or {},
            reasoner_spec=rewrite_spec,
            reasoner_model=rewrite_model or "",
            reasoner_api_key=rewrite_api_key or "",
            min_similarity=min_similarity,
            search_k=top_k,
            scope_bias=scope_bias,
        )
        research = await run_research_graph(
            runtime_ctx,
            user_text=user_text,
            seed_ref=seed_ref,
            seed_post_id=seed_post_id,
            hints=hints,
            dialog_context=build_planner_dialog_context(
                user_text,
                history,
                history_turns=history_turns,
            ),
            dialog_ledger=dialog_ledger,
            l1_results=results,
            max_steps=rag_agent_max_steps,
            spec=rewrite_spec,
            model=rewrite_model or "",
            api_key=rewrite_api_key or "",
        )

        agent_state = runtime_ctx.agent_tool_state
        if agent_state is not None:
            snapshot = build_snapshot_from_agent_state(agent_state, user_text=user_text)
            await append_turn(
                session,
                user_id=user_id,
                chat_key=ledger_key,
                snapshot=snapshot,
            )
            trace_step(
                "7. rag.L2.ledger_snapshot",
                [
                    f"chat_key={ledger_key or '—'}",
                    f"entities={len(snapshot.entities)}",
                    f"target_post_id={snapshot.target_post_id or '—'}",
                ],
            )

        if research.rag_context:
            rag_context = research.rag_context
            rag_cites = list(research.cites)
        elif results and not rag_context:
            rag_context, rag_cites = await format_rag_context(
                session=session,
                user_id=user_id,
                results=results,
                scope=scope,
                post_data=post_data,
                tenant_key=tenant_key,
            )
        logger.info(
            "RAG L2: stopped_reason=%s cites=%s steps=%s",
            research.stopped_reason,
            len(research.cites),
            research.step_count,
        )
        trace_step(
            "7. rag.L2.result",
            [
                f"stopped_reason={research.stopped_reason}",
                f"agent_cites={len(research.cites)}",
                f"agent_context_chars={len(research.rag_context)}",
                f"steps={research.step_count}",
            ],
        )
    elif should_escalate:
        trace_step(
            "7. rag.L2",
            f"should_escalate=True but no reasoner LLM — L2 skipped (rag_mode={rag_mode})",
        )
    else:
        trace_step(
            "7. rag.L2",
            f"skipped — should_escalate=False (rag_mode={rag_mode})",
        )

    if not rag_cites and rewrite_on_miss and query_used == base_query:
        logger.debug("RAG retrieval returned rows but no note content for query")
    cite_paths = [cite.path for cite in rag_cites]
    trace_step(
        "8. rag.result",
        [
            f"context_chars={len(rag_context)}",
            f"cites={len(rag_cites)}",
            *(f"  - {path}" for path in cite_paths[:8]),
            *(["  …"] if len(cite_paths) > 8 else []),
            f"context_preview: {_preview_query(rag_context, 240)}" if rag_context else "context_preview: (empty)",
        ],
    )
    return rag_context, rag_cites
