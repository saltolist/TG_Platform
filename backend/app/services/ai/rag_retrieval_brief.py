"""Deterministic retrieval brief for L2 agentic RAG (pre-plan context)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.ai.rag import NODE_POST_TEXT
from app.services.ai.rag_escalation import (
    TierAResult,
    _COMMENTS_QUERY_MARKERS,
    _NUMERIC_QUERY_MARKERS,
    _VISUAL_QUERY_MARKERS,
)
from app.services.ai.rag_retrieval_plan import POST_QUERY_MARKERS

_COMPARATIVE_VISUAL_MARKERS = (
    "какое изображ",
    "какой вариант",
    "какая картин",
    "подойд",
    "сравни",
    "что лучше",
    "выбер",
)

_REFERENT_CONTEXT_PATTERN = re.compile(
    r"([^.!?,\n]{0,40}(?:"
    + "|".join(re.escape(m) for m in POST_QUERY_MARKERS)
    + r")[^.!?,\n]{0,40})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievalBrief:
    task: str
    referent_phrases: tuple[str, ...]
    named_post_query: bool
    evidence_needed: tuple[str, ...]
    constraints: tuple[str, ...]
    ledger_lines: tuple[str, ...]


def _query_has_markers(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _extract_referent_phrases(user_text: str) -> tuple[str, ...]:
    text = (user_text or "").strip()
    if not text:
        return ()
    phrases: list[str] = []
    for match in _REFERENT_CONTEXT_PATTERN.finditer(text):
        phrase = " ".join(match.group(1).split())
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return tuple(phrases)


def _dialog_has_visual_intent(dialog_context: str) -> bool:
    dialog = (dialog_context or "").strip()
    if not dialog:
        return False
    return _query_has_markers(dialog, _VISUAL_QUERY_MARKERS) or _query_has_markers(
        dialog, _COMPARATIVE_VISUAL_MARKERS
    )


def _infer_task(user_text: str, *, dialog_context: str = "") -> str:
    if _query_has_markers(user_text, _COMPARATIVE_VISUAL_MARKERS) and _query_has_markers(
        user_text, _VISUAL_QUERY_MARKERS
    ):
        return "comparative_visual"
    if _query_has_markers(user_text, _VISUAL_QUERY_MARKERS):
        return "visual"
    if _query_has_markers(user_text, _NUMERIC_QUERY_MARKERS):
        return "analytics"
    if _query_has_markers(user_text, _COMMENTS_QUERY_MARKERS):
        return "comments"
    if _query_has_markers(user_text, POST_QUERY_MARKERS):
        if (
            _dialog_has_visual_intent(dialog_context)
            and not _query_has_markers(user_text, _COMMENTS_QUERY_MARKERS)
        ):
            return "comparative_visual"
        return "post_query"
    return "generic"


def format_brief_for_planner(brief: RetrievalBrief) -> str:
    """Render brief for structured planner / replan prompts."""
    lines = [
        "Retrieval brief (plan обязан собрать все evidence_needed):",
        f"- task: {brief.task}",
        f"- evidence_needed: {list(brief.evidence_needed)}",
    ]
    if brief.referent_phrases:
        lines.append(f"- referents: {list(brief.referent_phrases)!r}")
    if brief.named_post_query:
        lines.append(
            "- named_post_query: true — сначала discovery (SearchNodes/ListPosts), "
            "затем OpenPost target post по referent"
        )
    if brief.constraints:
        lines.append(f"- constraints: {list(brief.constraints)}")
    evidence = set(brief.evidence_needed)
    if evidence & {"attachments", "vision"}:
        lines.append(
            "- цепочка для attachments/vision: OpenPost → ListPostNotes → OpenNote → "
            "ListNoteAttachments → HydrateAttachment(mode=vision)"
        )
    if "comments" in evidence:
        lines.append("- для comments: ListPostComments после OpenPost")
    if "analytics" in evidence:
        lines.append("- для analytics: GetPostAnalytics после OpenPost")
    return "\n".join(lines)


def _infer_evidence_needed(task: str) -> tuple[str, ...]:
    if task == "comparative_visual":
        return ("post_text", "attachments", "vision")
    if task == "visual":
        return ("attachments", "vision")
    if task == "analytics":
        return ("post_text", "analytics")
    if task == "comments":
        return ("post_text", "comments")
    if task == "post_query":
        return ("post_text",)
    return ("context",)


def build_retrieval_brief(
    *,
    user_text: str,
    scope: str,
    seed_post_id: str | None = None,
    tier_a: TierAResult | None = None,
    l1_results: list[Mapping[str, Any]] | None = None,
    dialog_context: str = "",
) -> RetrievalBrief:
    """Build a deterministic brief before structured plan composition."""
    query = (user_text or "").strip()
    dialog = (dialog_context or "").strip()
    task = _infer_task(query, dialog_context=dialog)
    named_post_query = scope == "global" and _query_has_markers(query, POST_QUERY_MARKERS)
    referent_phrases = _extract_referent_phrases(query) if named_post_query else ()
    evidence_needed = _infer_evidence_needed(task)

    constraints: list[str] = []
    if scope == "post" and seed_post_id:
        constraints.append(f"target_post_id={seed_post_id}")
        constraints.append("scope=post")
    elif seed_post_id:
        constraints.append(f"seed_post_id={seed_post_id}")
    if tier_a and tier_a.escalate_post_id:
        constraints.append(f"tier_a_escalate_post_id={tier_a.escalate_post_id}")
    if scope == "global":
        constraints.append("cross_post=deny")

    l1_results = l1_results or []
    l1_has_post_text = any(
        str(item.get("node_type") or "") == NODE_POST_TEXT for item in l1_results
    )

    ledger: list[str] = [f"[brief-1] task={task}"]
    if task == "comparative_visual" and _query_has_markers(
        query, POST_QUERY_MARKERS
    ) and not _query_has_markers(query, _VISUAL_QUERY_MARKERS):
        ledger.append("[brief-1b] task upgraded from dialog visual follow-up")
    if referent_phrases:
        ledger.append(f'[brief-2] referents={list(referent_phrases)!r}')
    elif named_post_query:
        ledger.append("[brief-2] referents=(named post query, phrases not extracted)")
    if named_post_query:
        ledger.append("[brief-3] named_post_query=true — target post must be resolved via discovery")
    if evidence_needed:
        ledger.append(f"[brief-4] evidence_needed={list(evidence_needed)}")
    if constraints:
        ledger.append(f"[brief-5] constraints={constraints}")
    if l1_results and not l1_has_post_text and named_post_query:
        ledger.append(
            "[brief-6] L1 has no post_text hit — do not bind target post from note_chunk alone"
        )

    return RetrievalBrief(
        task=task,
        referent_phrases=referent_phrases,
        named_post_query=named_post_query,
        evidence_needed=evidence_needed,
        constraints=tuple(constraints),
        ledger_lines=tuple(ledger),
    )
