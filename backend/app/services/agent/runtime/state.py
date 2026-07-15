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
    cite_paths: list[str]
    stopped_reason: str
    current_tool: str | None
    tool_call: dict[str, Any] | None
    answer_text: str
    claims: list[dict[str, Any]]
    step_count: int
    max_steps: int
    research_transcript: list[str]
    research_hints: list[str]
    tool_action: dict[str, Any] | None
    # Accumulated planner decisions {step, observations, reasoning, gap, tool,
    # args, repair_hint?} for SSE emission and golden inspection
    # (agent-runtime-sprints §3.1/§3.3).
    planner_steps: list[dict[str, Any]]
    verification_ok: bool
    proposal_ids: list[str]
    job_ids: list[str]
    media_result: dict[str, Any] | None
    media_decision: dict[str, Any] | None
    errors: list[str]
    interrupt: dict[str, Any] | None
