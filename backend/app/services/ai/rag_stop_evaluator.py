"""Deterministic Stop-evaluator for the L2 agentic RAG loop."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_escalation import (
    _COMMENTS_QUERY_MARKERS,
    _NUMERIC_QUERY_MARKERS,
    _VISUAL_QUERY_MARKERS,
)
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


@dataclass(frozen=True)
class StopVerdict:
    allowed: bool
    reason: str


def _query_markers(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _visited_matches(state: AgentState, predicate) -> bool:
    return any(predicate(ref) for ref in state.visited)


def _has_note_context(context_blocks: list[tuple[NoteCite, str]]) -> bool:
    return any(plain.strip() for _, plain in context_blocks)


def evaluate_stop(
    user_text: str,
    state: AgentState,
    context_blocks: list[tuple[NoteCite, str]],
) -> StopVerdict:
    """Reject planner Stop when required evidence has not been opened."""
    query = (user_text or "").strip()
    if not query:
        return StopVerdict(allowed=True, reason="empty_query")

    if _query_markers(query, _COMMENTS_QUERY_MARKERS):
        if _visited_matches(state, lambda ref: ref.endswith(":comments")):
            return StopVerdict(allowed=True, reason="comments_opened")
        return StopVerdict(allowed=False, reason="missing_list_post_comments")

    if _query_markers(query, _VISUAL_QUERY_MARKERS):
        if _visited_matches(state, lambda ref: ref.startswith("hydrate:")):
            return StopVerdict(allowed=True, reason="attachment_hydrated")
        return StopVerdict(allowed=False, reason="missing_hydrate_attachment")

    if _query_markers(query, _NUMERIC_QUERY_MARKERS):
        if _visited_matches(state, lambda ref: ":analytics:" in ref):
            return StopVerdict(allowed=True, reason="analytics_opened")
        if _has_note_context(context_blocks) and any(
            re.search(r"\d", plain) for _, plain in context_blocks
        ):
            return StopVerdict(allowed=True, reason="numeric_note_context")
        return StopVerdict(allowed=False, reason="missing_analytics_or_numeric_note")

    if _query_markers(query, _WHY_PERFORM_MARKERS):
        if _visited_matches(state, lambda ref: ref.startswith("note:")) or _has_note_context(
            context_blocks
        ):
            return StopVerdict(allowed=True, reason="note_opened")
        if _visited_matches(state, lambda ref: ":analytics:" in ref):
            return StopVerdict(allowed=True, reason="analytics_opened")
        return StopVerdict(allowed=False, reason="missing_note_for_why_question")

    if _has_note_context(context_blocks) or state.context_blocks:
        return StopVerdict(allowed=True, reason="context_present")

    if state.visited - {ref for ref in state.visited if ref.startswith("search:")}:
        return StopVerdict(allowed=True, reason="tools_used")

    return StopVerdict(allowed=False, reason="no_context_opened")
