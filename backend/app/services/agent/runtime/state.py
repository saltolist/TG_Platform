"""Serializable LangGraph state contracts (ADR-012)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


class AgentGraphState(TypedDict, total=False):
    """JSON-serializable graph state — no sessions, secrets, or bytes."""

    messages: Annotated[list[Any], add_messages]
    run_id: str
    user_id: str
    user_text: str
    scope: str
    post_id: str | None
    status: Literal["running", "interrupted", "completed", "failed", "cancelled"]
    evidence_records: dict[str, dict[str, Any]]
    evidence_ids: list[str]
    finish_retrieval: dict[str, Any] | None
    unresolved: list[str]
    repair_count: int
    rag_context: str
    # Versioned, verified handoff to answer_node. ``rag_context`` remains as a
    # compatibility rendering for legacy consumers and trace replay.
    evidence_pack: dict[str, Any]
    evidence_pack_schema: str
    cite_paths: list[str]
    # Human-readable evidence titles (one per cite) so answer_node can state
    # "N objects" explicitly in the prompt, instead of relying on the model to
    # count blocks itself — a scope-narrowing dialog frame (e.g. "заметки про
    # систему" from an earlier turn) can otherwise make it silently drop
    # objects present in evidence but absent from the discussed frame.
    evidence_titles: list[str]
    stopped_reason: str
    current_tool: str | None
    tool_call: dict[str, Any] | None
    answer_text: str
    claims: list[dict[str, Any]]
    result_contract_issues: list[str]
    output_schema: str
    output_validation: dict[str, Any]
    answer_repair_count: int
    step_count: int
    max_steps: int
    # Persistent research plan (agent-runtime persistent-plan): list of
    # {id, text, status: open|done|dropped, reason?, evidence_id?}. Carried
    # across planner steps so a stated intent ("проверить global notes") can't
    # silently evaporate between steps — the code re-inserts any open item the
    # model drops without an explicit done/dropped transition, and FinishRetrieval
    # is gated until no item is still `open`.
    plan: list[dict[str, Any]]
    # How many times the finish-gate has bounced a premature FinishRetrieval back
    # to the planner because open plan items remained. Capped so a model that
    # keeps re-emitting finish without closing items can't loop forever.
    plan_repair_count: int
    # Steps refunded because a tool returned recoverable precondition guidance
    # ("сначала OpenPost") rather than a real result. Capped so a planner that
    # keeps repeating the same broken call can't loop forever on free steps.
    step_refunds: int
    # Consecutive tool calls that produced no new evidence.
    no_progress_count: int
    research_transcript: list[str]
    research_hints: list[str]
    # Self-contained search query the workspace classifier resolved from the raw
    # user_text + dialog (anaphora expanded, e.g. "а сколько там?" → "сколько
    # постов в серии"). Seeds the semantic prefetch so relevant notes/posts
    # surface before the planner's first step, instead of the planner having to
    # guess to search (agent note-prefetch). Falls back to user_text when empty.
    search_query: str
    # Deterministic goal, referent, corpus and output requirements for the turn.
    turn_contract: dict[str, Any]
    # Phase-2 normalized contract is duplicated as a narrow checkpoint field so
    # downstream nodes can inspect targets/sources without reparsing prompts.
    target_contract: dict[str, Any]
    resolution_events: list[dict[str, Any]]
    # Structured semantic-prefetch hits from the seed node: [{ref, label,
    # similarity, node_type}]. Powers the finish-gate guard — a FinishRetrieval
    # is bounced once if a relevant hit here was never opened into evidence.
    prefetch_hits: list[dict[str, Any]]
    # Bounded counter for finish-gate bounces caused by unopened prefetch hits,
    # separate from plan_repair_count so the two gates don't starve each other.
    prefetch_repair_count: int
    # SearchIntentLedger: run-scoped canonical tool intents. Entries are plain
    # dicts so checkpoints remain JSON serializable and resumable.
    search_ledger: list[dict[str, Any]]
    # Set after the first LLM FinishRetrieval candidate is validated. A second
    # attempt becomes an internal ValidatorEvent instead of another planner
    # finish call.
    finish_retrieval_attempted: bool
    validator_events: list[dict[str, Any]]
    phase5_enabled: bool
    planner_calls_used: int
    search_calls_used: int
    deep_reads_used: int
    tool_calls_used: int
    planner_invalid_count: int
    sufficiency: dict[str, Any]
    deadline_exhausted: bool
    selected_candidate_ids: list[str]
    requested_status: str | None
    tool_action: dict[str, Any] | None
    # Accumulated planner decisions {step, observations, reasoning, gap, tool,
    # args, repair_hint?} for SSE emission and golden inspection
    # (agent-runtime-sprints §3.1/§3.3).
    planner_steps: list[dict[str, Any]]
    # Accumulated tool results {step, tool, args, summary, error, record_ids}
    # so the log shows not just the planner's decision but what the tool
    # actually returned — closing the "why did the agent decide this" chain
    # (agent-runtime-remaining.md Спринт 5).
    tool_outcomes: list[dict[str, Any]]
    verification_ok: bool
    proposal_ids: list[str]
    job_ids: list[str]
    media_result: dict[str, Any] | None
    media_decision: dict[str, Any] | None
    errors: list[str]
    interrupt: dict[str, Any] | None
