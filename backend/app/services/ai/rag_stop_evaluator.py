"""Deterministic Stop-evaluator for the L2 agentic RAG loop."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_escalation import (
    _COMMENTS_QUERY_MARKERS,
    _NUMERIC_QUERY_MARKERS,
    _VISUAL_QUERY_MARKERS,
)
from app.services.ai.rag_retrieval_plan import POST_QUERY_MARKERS
from app.services.ai.rag_tools import AgentState

_WHY_PERFORM_MARKERS = (
    "почему заш",
    "почему сработ",
    "почему выстрел",
    "почему попал",
    "почему зацеп",
    "почему отклик",
    "почему сработал",
    "почему зашёл",
    "почему зашел",
)

_COMPARATIVE_VISUAL_MARKERS = (
    "какое изображ",
    "какой вариант",
    "какая картин",
    "подойд",
    "сравни",
    "что лучше",
    "выбер",
)


@dataclass(frozen=True)
class StopVerdict:
    allowed: bool
    reason: str


def _query_markers(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _is_comparative_visual_query(text: str) -> bool:
    return _query_markers(text, _COMPARATIVE_VISUAL_MARKERS)


def _visited_matches(state: AgentState, predicate) -> bool:
    return any(predicate(ref) for ref in state.visited)


def _is_attachment_hydrated(state: AgentState, ref: str) -> bool:
    return (
        f"hydrate:vision:{ref}" in state.visited
        or f"hydrate:{ref}" in state.visited
    )


def _required_image_attachment_refs(state: AgentState) -> list[str]:
    settings: Settings = state.settings or get_settings()
    max_vision = max(0, int(settings.rag_agent_max_vision))
    if max_vision <= 0:
        return []
    return list(state.listed_image_attachment_refs[:max_vision])


def _evaluate_visual_stop(user_text: str, state: AgentState) -> StopVerdict:
    brief = state.retrieval_brief
    comparative = _is_comparative_visual_query(user_text) or (
        brief is not None and brief.task == "comparative_visual"
    )
    if comparative and state.listed_image_attachment_refs:
        required = _required_image_attachment_refs(state)
        if required and not all(_is_attachment_hydrated(state, ref) for ref in required):
            return StopVerdict(allowed=False, reason="missing_hydrate_attachment")
        if required:
            return StopVerdict(allowed=True, reason="attachments_hydrated")

    if _visited_matches(state, lambda ref: ref.startswith("hydrate:")):
        return StopVerdict(allowed=True, reason="attachment_hydrated")
    return StopVerdict(allowed=False, reason="missing_hydrate_attachment")


def _evaluate_brief_attachment_stop(state: AgentState) -> StopVerdict | None:
    brief = state.retrieval_brief
    if brief is None:
        return None
    evidence = set(brief.evidence_needed)
    if not evidence.intersection({"attachments", "vision"}):
        return None

    if state.target_evidence_gap:
        return StopVerdict(allowed=True, reason="evidence_gap_on_target")

    listed_notes = _visited_matches(state, lambda ref: ref.endswith(":notes"))
    opened_note = _visited_matches(
        state,
        lambda ref: ref.startswith("note:") and not ref.endswith(":comments"),
    )
    if listed_notes and not opened_note:
        return StopVerdict(allowed=False, reason="missing_open_note")

    if "vision" in evidence:
        return _evaluate_visual_stop("", state)

    if state.listed_image_attachment_refs:
        return StopVerdict(allowed=True, reason="attachments_listed")
    if _visited_matches(state, lambda ref: "attachments" in ref):
        return StopVerdict(allowed=True, reason="attachments_listed")
    if opened_note:
        return StopVerdict(allowed=False, reason="missing_list_attachments")
    if listed_notes:
        return StopVerdict(allowed=False, reason="missing_open_note")
    return None


def _has_note_context(context_blocks: list[tuple[NoteCite, str]]) -> bool:
    return any(plain.strip() for cite, plain in context_blocks if cite.path.startswith("/note/"))


def _has_post_context(
    state: AgentState,
    context_blocks: list[tuple[NoteCite, str]],
) -> bool:
    if _visited_matches(
        state,
        lambda ref: ref.startswith("post:") and ref.count(":") == 1,
    ):
        return True
    return any(
        cite.path.startswith("/post/") and plain.strip()
        for cite, plain in context_blocks
    )


def _has_post_context_for_id(
    state: AgentState,
    context_blocks: list[tuple[NoteCite, str]],
    post_id: str,
) -> bool:
    ref = f"post:{post_id}"
    if ref in state.visited:
        return True
    path_prefix = f"/post/{post_id}/"
    return any(
        cite.path.startswith(path_prefix) and plain.strip()
        for cite, plain in context_blocks
    )


def evaluate_stop(
    user_text: str,
    state: AgentState,
    context_blocks: list[tuple[NoteCite, str]],
    *,
    scope: str = "global",
) -> StopVerdict:
    """Reject planner Stop when required evidence has not been opened."""
    query = (user_text or "").strip()
    if not query:
        return StopVerdict(allowed=True, reason="empty_query")

    brief = state.retrieval_brief
    evidence = set(brief.evidence_needed) if brief else set()

    if brief and brief.named_post_query and scope == "global":
        if not state.resolved_target_post_id:
            return StopVerdict(allowed=False, reason="missing_target_post_binding")
        target_id = state.resolved_target_post_id
        if not _has_post_context_for_id(state, context_blocks, target_id):
            return StopVerdict(allowed=False, reason="missing_open_post")

    brief_attachment = _evaluate_brief_attachment_stop(state)
    if brief_attachment is not None:
        return brief_attachment

    if _query_markers(query, _COMMENTS_QUERY_MARKERS) or "comments" in evidence:
        if _visited_matches(state, lambda ref: ref.endswith(":comments")):
            return StopVerdict(allowed=True, reason="comments_opened")
        return StopVerdict(allowed=False, reason="missing_list_post_comments")

    if _query_markers(query, _VISUAL_QUERY_MARKERS) or evidence.intersection({"attachments", "vision"}):
        return _evaluate_visual_stop(query, state)

    if _query_markers(query, _NUMERIC_QUERY_MARKERS) or "analytics" in evidence:
        if _visited_matches(state, lambda ref: ":analytics:" in ref):
            return StopVerdict(allowed=True, reason="analytics_opened")
        if _has_note_context(context_blocks) and any(
            re.search(r"\d", plain) for _, plain in context_blocks
        ):
            return StopVerdict(allowed=True, reason="numeric_note_context")
        if "analytics" in evidence or _query_markers(query, _NUMERIC_QUERY_MARKERS):
            return StopVerdict(allowed=False, reason="missing_analytics_or_numeric_note")

    if _query_markers(query, _WHY_PERFORM_MARKERS):
        if _visited_matches(state, lambda ref: ref.startswith("note:")) or _has_note_context(
            context_blocks
        ):
            return StopVerdict(allowed=True, reason="note_opened")
        if _visited_matches(state, lambda ref: ref.startswith("post:")) or _has_post_context(
            state, context_blocks
        ):
            return StopVerdict(allowed=True, reason="post_opened")
        if _visited_matches(state, lambda ref: ":analytics:" in ref):
            return StopVerdict(allowed=True, reason="analytics_opened")
        return StopVerdict(allowed=False, reason="missing_note_for_why_question")

    if scope == "global" and _query_markers(query, POST_QUERY_MARKERS):
        if brief and brief.named_post_query and state.resolved_target_post_id:
            return StopVerdict(allowed=True, reason="target_post_bound")
        if _has_post_context(state, context_blocks):
            return StopVerdict(allowed=True, reason="post_opened")
        return StopVerdict(allowed=False, reason="missing_open_post")

    if _has_post_context(state, context_blocks):
        return StopVerdict(allowed=True, reason="post_context_present")

    if _has_note_context(context_blocks):
        return StopVerdict(allowed=True, reason="note_context_present")

    if state.context_blocks:
        return StopVerdict(allowed=True, reason="context_present")

    if state.visited - {ref for ref in state.visited if ref.startswith("search:")}:
        return StopVerdict(allowed=True, reason="tools_used")

    return StopVerdict(allowed=False, reason="no_context_opened")
