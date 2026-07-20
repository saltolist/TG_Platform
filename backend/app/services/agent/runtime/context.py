"""Runtime context — non-serializable dependencies resolved per node."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import User
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_tools import AgentState


@dataclass
class RuntimeContext:
    """Holds DB session factory, user, provider specs — never checkpointed."""

    session_factory: async_sessionmaker[AsyncSession]
    user_id: uuid.UUID
    user: User | None
    tenant_key: str | None
    settings: Settings
    embedding_backend: EmbeddingBackend
    scope: str
    post_data: dict[str, Any] | None
    ai_profile: dict[str, Any]
    # Channel voice/tone/rules (Profile.channel) and Telegram identity
    # (Profile.telegram) — fed into generating nodes' system prompt so the
    # agent writes in the channel's voice, same as the legacy /ai/reply/ path's
    # primer. Never routed through RAG: this is ambient behavior, not a fact
    # to retrieve. None when the profile has no channel set up yet.
    channel_profile: dict[str, Any] | None = None
    telegram_profile: dict[str, Any] | None = None
    reasoner_spec: ProviderSpec | None = None
    reasoner_model: str = ""
    reasoner_api_key: str = ""
    # Phase 6 model separation. reasoner_* remains the planner compatibility
    # alias for persisted runs and older tests.
    planner_spec: ProviderSpec | None = None
    planner_model: str = ""
    planner_api_key: str = ""
    answer_spec: ProviderSpec | None = None
    answer_model: str = ""
    answer_api_key: str = ""
    # Recent chat turns as text, threaded into configurable["dialog_context"]
    # for the research planner (agent-runtime-sprints §2.1). Deliberately a
    # string, not native state["messages"] — see agent-runtime-remaining.md §2.
    dialog_context: str = ""
    # Verified object refs from recent message manifests. These are compact
    # provenance cards for exact-by-ID reuse, never implicit targets.
    known_context_refs: tuple[dict[str, Any], ...] = ()
    # One deterministic goal/referent contract shared by classifier, planner
    # and answer generation for this turn.
    turn_contract: dict[str, Any] = field(default_factory=dict)
    # Durable cross-turn entity/artifact memory. It stays outside checkpoints
    # with the rest of RuntimeContext and is passed through configurable.
    dialog_ledger: tuple[Any, ...] = ()
    ledger_key: str | None = None
    # HTML body of the most recently proposed edit_post action in this thread
    # (approved, rejected, or pending), if any. dialog_context above only
    # carries display text and drops the `proposal` payload, so a follow-up
    # instruction referring back to a prior edit ("сделай ЕЁ через пробел")
    # had nothing to resolve against — see extract_last_proposed_edit.
    last_proposed_post_html: str | None = None
    # IANA zone name (e.g. "Europe/Moscow") from the browser, used by
    # resolve_schedule_time_node to interpret relative schedule_post phrasing
    # ("сегодня через полчаса") in the user's local time rather than UTC.
    # None (legacy runs, or a client that never sent one) falls back to UTC.
    user_timezone: str | None = None
    min_similarity: float = 0.38
    search_k: int = 4
    scope_bias: float = 0.04
    agent_tool_state: AgentState | None = None
    # Absolute time.monotonic() by which the run must finish (agent-runtime-sprints
    # §6). Set by execute_agent_run/resume_agent_graph from rag_agent_deadline_s;
    # None disables the wall-clock cap (e.g. legacy call sites). See runtime/budget.py.
    deadline_monotonic: float | None = None
    soft_deadline_monotonic: float | None = None
    # Shared httpx client for all LLM calls within a single agent run — avoids
    # creating a new TCP/TLS connection per call (was one AsyncClient per call).
    # Created in execute_agent_run and threaded through budget.py into llm.py.
    # None falls back to the old per-call client behaviour (safe default).
    llm_client: httpx.AsyncClient | None = None
    # Per-call phase/timing/token estimates collected by budget.py and emitted
    # once as a durable run_metrics event. Never checkpointed and contains no
    # prompt/response text or API keys.
    llm_metrics: list[dict[str, Any]] = field(default_factory=list)
    # Durable phase totals are assembled by the graph executor and emitted in
    # workspace.run-metrics/v1. They remain outside checkpoints because resume
    # emits a separate leg while retaining the same run id.
    phase_timings: dict[str, float] = field(default_factory=dict)

    def planner_llm(self) -> tuple[ProviderSpec | None, str, str]:
        return (
            self.planner_spec or self.reasoner_spec,
            self.planner_model or self.reasoner_model,
            self.planner_api_key or self.reasoner_api_key,
        )

    def answer_llm(self) -> tuple[ProviderSpec | None, str, str]:
        return (
            self.answer_spec or self.reasoner_spec,
            self.answer_model or self.reasoner_model,
            self.answer_api_key or self.reasoner_api_key,
        )

    def bind_agent_state(self, session: AsyncSession) -> AgentState:
        if self.agent_tool_state is not None:
            self.agent_tool_state.session = session
            return self.agent_tool_state
        self.agent_tool_state = AgentState(
            session=session,
            user_id=self.user_id,
            scope=self.scope,
            tenant_key=self.tenant_key,
            embedding_backend=self.embedding_backend,
            base_post_data=self.post_data,
            min_similarity=self.min_similarity,
            search_k=self.search_k,
            ai_profile=self.ai_profile,
            user=self.user,
            settings=self.settings,
            scope_bias=self.scope_bias,
        )
        return self.agent_tool_state

    def fork_agent_state(self, session: AsyncSession) -> AgentState:
        """Copy tool state for independent read actions in one planner batch."""

        if self.agent_tool_state is None:
            return self.bind_agent_state(session)
        base = self.agent_tool_state
        fork = AgentState(
            session=session,
            user_id=base.user_id,
            scope=base.scope,
            tenant_key=base.tenant_key,
            embedding_backend=base.embedding_backend,
            base_post_data=base.base_post_data,
            min_similarity=base.min_similarity,
            search_k=base.search_k,
            visited=set(base.visited),
            context_blocks=list(base.context_blocks),
            opened_posts=dict(base.opened_posts),
            query_vector_cache=dict(base.query_vector_cache),
            catalog_members={
                path: [dict(item) for item in members]
                for path, members in base.catalog_members.items()
            },
            vision_calls_used=base.vision_calls_used,
            hydrated_text_files=set(base.hydrated_text_files),
            listed_image_attachment_refs=list(base.listed_image_attachment_refs),
            listed_image_media_refs=list(base.listed_image_media_refs),
            decision_ledger=list(base.decision_ledger),
            resolved_target_post_id=base.resolved_target_post_id,
            target_evidence_gap=base.target_evidence_gap,
            scope_bias=base.scope_bias,
            ai_profile=base.ai_profile,
            user=base.user,
            settings=base.settings,
        )
        if hasattr(base, "catalog_posts"):
            fork.catalog_posts = list(base.catalog_posts)
        return fork
