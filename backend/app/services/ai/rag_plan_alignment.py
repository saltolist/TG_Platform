"""Pre-flight plan alignment gate for L2 agentic RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.ai.providers import ProviderSpec
from app.services.ai.rag import NODE_NOTE_CHUNK, NODE_POST_TEXT
from app.services.ai.rag_escalation import TierAResult
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_retrieval_brief import RetrievalBrief
from app.services.ai.rag_retrieval_plan import (
    DISCOVERY_TOOLS,
    POST_QUERY_MARKERS,
    RetrievalPlan,
    format_l1_hits_for_plan,
)

from app.services.ai.rag_binding_policy import (
    collect_invalid_plan_ids,
    plan_has_off_target_discovery,
)

logger = logging.getLogger(__name__)

_BINDING_TOOLS = frozenset({"OpenPost", "OpenNote", "ListPostNotes", "HydrateAttachment"})
_ATTACHMENT_EVIDENCE = frozenset({"attachments", "vision"})
_POST_BINDING_TOOLS = frozenset({"OpenPost", "ListPostNotes", "OpenNote", "ListPostComments"})


def _plan_is_discovery_only(plan: RetrievalPlan) -> bool:
    return bool(plan.steps) and all(step.tool in DISCOVERY_TOOLS for step in plan.steps)


def _evaluate_evidence_coverage(
    brief: RetrievalBrief,
    plan: RetrievalPlan,
    *,
    discovery_completed: bool = False,
) -> tuple[str, str] | None:
    """Return (reason, fix_hint) when plan omits required evidence steps."""
    if _plan_is_discovery_only(plan) and not discovery_completed:
        return None

    tool_set = {step.tool for step in plan.steps}
    evidence = set(brief.evidence_needed)
    has_post_binding = bool(tool_set & _POST_BINDING_TOOLS) or discovery_completed
    if not has_post_binding:
        return None

    if evidence & _ATTACHMENT_EVIDENCE:
        has_list_notes = "ListPostNotes" in tool_set
        has_open_note = "OpenNote" in tool_set
        has_list_attach = "ListNoteAttachments" in tool_set
        has_hydrate = "HydrateAttachment" in tool_set

        if has_list_notes and not has_open_note and not has_list_attach:
            return (
                "missing_note_open",
                "ListPostNotes только перечисляет заметки — добавь OpenNote, "
                "ListNoteAttachments"
                + (" и HydrateAttachment(mode=vision)." if "vision" in evidence else "."),
            )

        needs_attachment_chain = has_list_notes or (
            discovery_completed and "OpenPost" in tool_set
        )
        if needs_attachment_chain and not has_open_note and not has_list_attach:
            return (
                "missing_attachment_evidence",
                "Добавь OpenNote → ListNoteAttachments для сбора вложений заметки.",
            )

        if "vision" in evidence and (has_open_note or has_list_attach or has_list_notes):
            if not has_hydrate:
                return (
                    "missing_vision_hydrate",
                    "После ListNoteAttachments добавь HydrateAttachment(mode=vision).",
                )

    if "comments" in evidence and "ListPostComments" not in tool_set:
        if not _plan_is_discovery_only(plan):
            return (
                "missing_comments",
                "Добавь ListPostComments для сбора комментариев к посту.",
            )

    if "analytics" in evidence and "GetPostAnalytics" not in tool_set:
        if not _plan_is_discovery_only(plan):
            return (
                "missing_analytics",
                "Добавь GetPostAnalytics для метрик поста.",
            )

    return None


@dataclass(frozen=True)
class PlanAlignmentVerdict:
    aligned: bool
    reason: str
    ledger_lines: list[str]
    fix_hint: str | None = None


def _query_has_markers(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _authorized_target_post_id(
    *,
    brief: RetrievalBrief,
    seed_post_id: str | None,
    tier_a: TierAResult | None,
    scope: str,
) -> str | None:
    if scope == "post" and seed_post_id:
        return seed_post_id
    if seed_post_id and any(c.startswith("target_post_id=") for c in brief.constraints):
        return seed_post_id
    if tier_a and tier_a.escalate_post_id:
        return tier_a.escalate_post_id
    for constraint in brief.constraints:
        if constraint.startswith("target_post_id="):
            return constraint.split("=", 1)[1]
        if constraint.startswith("seed_post_id="):
            return constraint.split("=", 1)[1]
    return None


def _l1_top_note_post_id(l1_results: list[Mapping[str, Any]]) -> str | None:
    for item in l1_results:
        if str(item.get("node_type") or "") != NODE_NOTE_CHUNK:
            continue
        post_id = str(item.get("post_id") or "").strip()
        if post_id:
            return post_id
    return None


def _l1_post_text_post_ids(l1_results: list[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in l1_results:
        if str(item.get("node_type") or "") != NODE_POST_TEXT:
            continue
        post_id = str(item.get("post_id") or "").strip()
        if post_id:
            ids.add(post_id)
    return ids


def _plan_has_discovery_first(plan: RetrievalPlan) -> bool:
    if not plan.steps:
        return False
    return plan.steps[0].tool in DISCOVERY_TOOLS


def _plan_first_binding_step(plan: RetrievalPlan) -> tuple[str, str | None, str | None] | None:
    for step in plan.steps:
        if step.tool not in _BINDING_TOOLS:
            continue
        post_id_raw = step.args.get("post_id")
        note_id_raw = step.args.get("note_id")
        post_id = str(post_id_raw).strip() if post_id_raw else None
        note_id = str(note_id_raw).strip() if note_id_raw else None
        return step.tool, post_id or None, note_id or None
    return None


def _plan_step_post_id(step_tool: str, args: dict[str, Any]) -> str | None:
    post_id_raw = args.get("post_id")
    if post_id_raw:
        return str(post_id_raw).strip() or None
    return None


def _goal_referent_mismatch(goal: str, post_id: str | None) -> bool:
    if not goal or not post_id:
        return False
    lowered_goal = goal.lower()
    if not _query_has_markers(lowered_goal, POST_QUERY_MARKERS):
        return False
    return True


def evaluate_plan_alignment(
    *,
    brief: RetrievalBrief,
    plan: RetrievalPlan,
    l1_results: list[Mapping[str, Any]],
    seed_post_id: str | None = None,
    tier_a: TierAResult | None = None,
    scope: str = "global",
    discovery_completed: bool = False,
    target_resolution_post_id: str | None = None,
    target_resolution_confidence: str | None = None,
) -> PlanAlignmentVerdict:
    """Deterministic pre-flight check: does the plan answer the user's query?"""
    ledger: list[str] = []
    authorized = _authorized_target_post_id(
        brief=brief,
        seed_post_id=seed_post_id,
        tier_a=tier_a,
        scope=scope,
    )

    if brief.referent_phrases:
        ledger.append(
            f'[align-1] intent: {brief.task} для referent={list(brief.referent_phrases)!r}'
        )
    else:
        ledger.append(f"[align-1] intent: task={brief.task}")

    if not plan.steps:
        ledger.append("[align-2] plan has no steps")
        ledger.append("[align-3] verdict: aligned=false, reason=empty_plan")
        return PlanAlignmentVerdict(
            aligned=False,
            reason="empty_plan",
            ledger_lines=ledger,
            fix_hint="Добавь шаги retrieval под задачу пользователя.",
        )

    first_binding = _plan_first_binding_step(plan)
    l1_note_post_id = _l1_top_note_post_id(l1_results)
    l1_post_text_ids = _l1_post_text_post_ids(l1_results)

    invalid_ids = collect_invalid_plan_ids(plan.steps)
    if invalid_ids:
        ledger.append(f"[align-2] plan содержит невалидные id: {invalid_ids}")
        ledger.append("[align-3] verdict: aligned=false, reason=invalid_plan_ids")
        return PlanAlignmentVerdict(
            aligned=False,
            reason="invalid_plan_ids",
            ledger_lines=ledger,
            fix_hint=(
                "Используй только реальные post_id/note_id/ref из результатов SearchNodes, "
                "ListPosts или transcript — без PLACEHOLDER и выдуманных id."
            ),
        )

    resolution_id = str(target_resolution_post_id or "").strip()
    resolution_conf = str(target_resolution_confidence or "").strip().lower()
    if resolution_id and resolution_conf in {"high", "medium"}:
        for step in plan.steps:
            step_post_id = _plan_step_post_id(step.tool, step.args)
            if step.tool == "OpenPost" and step_post_id and step_post_id != resolution_id:
                ledger.append(
                    f"[align-2] target resolution post_id={resolution_id}, "
                    f"но plan содержит OpenPost({step_post_id})"
                )
                ledger.append(
                    "[align-3] verdict: aligned=false, reason=target_resolution_mismatch"
                )
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="target_resolution_mismatch",
                    ledger_lines=ledger,
                    fix_hint=(
                        f"Target post уже определён resolver'ом: post_id={resolution_id}. "
                        "План должен открыть этот пост, не другой."
                    ),
                )
            if (
                step.tool in {"OpenNote", "ListNoteAttachments", "HydrateAttachment", "ListPostNotes"}
                and step_post_id
                and step_post_id != resolution_id
            ):
                ledger.append(
                    f"[align-2] target resolution post_id={resolution_id}, "
                    f"но {step.tool} использует post_id={step_post_id}"
                )
                ledger.append(
                    "[align-3] verdict: aligned=false, reason=target_resolution_mismatch"
                )
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="target_resolution_mismatch",
                    ledger_lines=ledger,
                    fix_hint=(
                        f"Media/notes только у target post {resolution_id}; "
                        "cross-post запрещён."
                    ),
                )

    if brief.named_post_query and scope == "global" and not authorized and not discovery_completed:
        if plan_has_off_target_discovery(plan.steps):
            ledger.append(
                "[align-2] named post query — discovery только по note_chunk без ListPosts/post_text"
            )
            ledger.append("[align-3] verdict: aligned=false, reason=discovery_off_target")
            return PlanAlignmentVerdict(
                aligned=False,
                reason="discovery_off_target",
                ledger_lines=ledger,
                fix_hint=(
                    "Referent post не найден: используй SearchNodes(post_text) и/или ListPosts, "
                    "затем OpenPost с id из каталога."
                ),
            )

    if brief.named_post_query and scope == "global" and l1_note_post_id:
        for step in plan.steps:
            step_post_id = _plan_step_post_id(step.tool, step.args)
            if (
                step.tool == "OpenPost"
                and step_post_id == l1_note_post_id
                and step_post_id not in l1_post_text_ids
            ):
                ledger.append(
                    f"[align-2] plan содержит OpenPost({step_post_id}) из L1 note_chunk — "
                    "не binding target post"
                )
                ledger.append("[align-3] verdict: aligned=false, reason=l1_note_binding_only")
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="l1_note_binding_only",
                    ledger_lines=ledger,
                    fix_hint=(
                        "Не используй post_id из L1 note_chunk. "
                        "Сначала ListPosts или SearchNodes(post_text) по referent, "
                        "затем OpenPost с id target post из каталога."
                    ),
                )
            if step.tool in {"OpenNote", "ListNoteAttachments", "HydrateAttachment", "ListPostNotes"}:
                if step_post_id == l1_note_post_id and step_post_id not in l1_post_text_ids:
                    ledger.append(
                        f"[align-2] {step.tool} на post {step_post_id} из L1 note_chunk — "
                        "media другого поста до binding target"
                    )
                    ledger.append(
                        "[align-3] verdict: aligned=false, reason=l1_note_media_before_target"
                    )
                    return PlanAlignmentVerdict(
                        aligned=False,
                        reason="l1_note_media_before_target",
                        ledger_lines=ledger,
                        fix_hint=(
                            "Заметки/media из L1 note_chunk относятся к другому посту. "
                            "Сначала discovery target post по referent, затем только его notes."
                        ),
                    )

    if brief.task == "comparative_visual" or "vision" in brief.evidence_needed:
        hydrate_index = next(
            (i for i, s in enumerate(plan.steps) if s.tool == "HydrateAttachment"),
            None,
        )
        list_attach_index = next(
            (i for i, s in enumerate(plan.steps) if s.tool == "ListNoteAttachments"),
            None,
        )
        if hydrate_index is not None and (
            list_attach_index is None or hydrate_index < list_attach_index
        ):
            ledger.append(
                "[align-2] comparative visual требует ListNoteAttachments до HydrateAttachment"
            )
            ledger.append("[align-3] verdict: aligned=false, reason=premature_hydrate")
            return PlanAlignmentVerdict(
                aligned=False,
                reason="premature_hydrate",
                ledger_lines=ledger,
                fix_hint="Сначала ListNoteAttachments, затем HydrateAttachment для каждого image.",
            )

    evidence_gap = _evaluate_evidence_coverage(
        brief,
        plan,
        discovery_completed=discovery_completed,
    )
    if evidence_gap is not None:
        reason, fix_hint = evidence_gap
        ledger.append(f"[align-2] plan не покрывает evidence_needed: {reason}")
        ledger.append(f"[align-3] verdict: aligned=false, reason={reason}")
        return PlanAlignmentVerdict(
            aligned=False,
            reason=reason,
            ledger_lines=ledger,
            fix_hint=fix_hint,
        )

    if brief.named_post_query and scope == "global" and not authorized and not discovery_completed:
        if first_binding and first_binding[0] == "OpenPost":
            bind_post_id = first_binding[1]
            if (
                bind_post_id
                and l1_note_post_id
                and bind_post_id == l1_note_post_id
                and bind_post_id not in l1_post_text_ids
            ):
                ledger.append(
                    f"[align-2] OpenPost({bind_post_id}) совпадает с L1 note_chunk — "
                    "это кандидат на media, не binding target post"
                )
                ledger.append("[align-3] verdict: aligned=false, reason=l1_note_binding_only")
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="l1_note_binding_only",
                    ledger_lines=ledger,
                    fix_hint=(
                        "L1 note_chunk дал post_id с медиа, но referent из вопроса не привязан. "
                        "Сначала SearchNodes(post_text) по referent, потом OpenPost найденного поста."
                    ),
                )

        if not _plan_has_discovery_first(plan):
            first_step = plan.steps[0]
            if first_step.tool in {"OpenPost", "OpenNote", "HydrateAttachment", "ListPostNotes"}:
                ledger.append(
                    f"[align-2] named post query без authorized target — "
                    f"первый шаг {first_step.tool}, discovery отсутствует"
                )
                ledger.append("[align-3] verdict: aligned=false, reason=discovery_required_first")
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="discovery_required_first",
                    ledger_lines=ledger,
                    fix_hint=(
                        "Сначала SearchNodes или ListPosts по referent из вопроса, "
                        "затем OpenPost с найденным post_id."
                    ),
                )

        if first_binding and _goal_referent_mismatch(plan.goal, first_binding[1]):
            if not _plan_has_discovery_first(plan) and first_binding[1] not in l1_post_text_ids:
                ledger.append(
                    f"[align-2] goal={plan.goal!r} упоминает referent, "
                    f"но plan открывает post_id={first_binding[1]!r} без discovery"
                )
                ledger.append("[align-3] verdict: aligned=false, reason=goal_binding_mismatch")
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="goal_binding_mismatch",
                    ledger_lines=ledger,
                    fix_hint="Привяжи target post через SearchNodes/ListPosts перед OpenPost.",
                )

    if authorized and brief.constraints and "cross_post=deny" in brief.constraints:
        for step in plan.steps:
            if step.tool not in {"HydrateAttachment", "OpenNote", "ListPostNotes"}:
                continue
            step_post_id = _plan_step_post_id(step.tool, step.args)
            if step_post_id and step_post_id != authorized:
                ledger.append(
                    f"[align-2] cross-post: {step.tool} post_id={step_post_id} "
                    f"≠ authorized target={authorized}"
                )
                ledger.append("[align-3] verdict: aligned=false, reason=cross_post_hydrate")
                return PlanAlignmentVerdict(
                    aligned=False,
                    reason="cross_post_hydrate",
                    ledger_lines=ledger,
                    fix_hint=(
                        f"Media/note от post {step_post_id} не относится к target post {authorized}. "
                        "Сначала собери evidence у target post; cross-post без approval запрещён."
                    ),
                )

    ledger.append("[align-2] plan согласован с brief")
    ledger.append("[align-3] verdict: aligned=true, reason=plan_aligned")
    return PlanAlignmentVerdict(
        aligned=True,
        reason="plan_aligned",
        ledger_lines=ledger,
    )


def _build_llm_auditor_messages(
    *,
    user_text: str,
    brief: RetrievalBrief,
    plan: RetrievalPlan,
    l1_results: list[Mapping[str, Any]],
    deterministic_verdict: PlanAlignmentVerdict,
) -> list[dict[str, str]]:
    plan_lines = [f"goal={plan.goal!r}"]
    for index, step in enumerate(plan.steps, start=1):
        plan_lines.append(
            f"{index}. {step.tool}({step.args!r}) purpose={step.purpose!r}"
        )
    user_block = "\n".join(
        [
            f"Вопрос пользователя:\n{user_text.strip()}",
            f"Brief: task={brief.task} referents={list(brief.referent_phrases)!r} "
            f"named_post_query={brief.named_post_query}",
            f"Deterministic verdict: aligned={deterministic_verdict.aligned} "
            f"reason={deterministic_verdict.reason}",
            format_l1_hits_for_plan(l1_results),
            "Plan:",
            *plan_lines,
            "Верни только JSON:",
            '{"aligned": true|false, "reasoning": "цепочка мыслей", '
            '"blockers": ["..."], "fix": "что изменить в plan"}',
        ]
    )
    return [
        {
            "role": "system",
            "content": (
                "Ты auditor plan alignment для agentic RAG. "
                "Проверь, ответит ли plan на вопрос пользователя и referent'ы. "
                "L1 id из note_chunk — кандидаты, не binding. "
                "Named post → discovery first."
            ),
        },
        {"role": "user", "content": user_block},
    ]


async def audit_plan_alignment_llm(
    *,
    user_text: str,
    brief: RetrievalBrief,
    plan: RetrievalPlan,
    l1_results: list[Mapping[str, Any]],
    deterministic_verdict: PlanAlignmentVerdict,
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> PlanAlignmentVerdict:
    """Optional LLM auditor when deterministic gate fails or is borderline."""
    from app.services.ai.llm import complete_chat_completion

    messages = _build_llm_auditor_messages(
        user_text=user_text,
        brief=brief,
        plan=plan,
        l1_results=l1_results,
        deterministic_verdict=deterministic_verdict,
    )
    try:
        raw = await complete_chat_completion(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        )
    except Exception as exc:
        logger.warning("RAG L2 plan alignment LLM audit failed: %s", exc)
        return deterministic_verdict

    payload = extract_json_object(raw or "")
    if not payload:
        return deterministic_verdict

    aligned = bool(payload.get("aligned"))
    reasoning = str(payload.get("reasoning") or "").strip()
    fix = str(payload.get("fix") or "").strip() or deterministic_verdict.fix_hint
    blockers = payload.get("blockers")
    ledger = list(deterministic_verdict.ledger_lines)
    ledger.append("[align-llm] LLM auditor:")
    if reasoning:
        ledger.append(f"[align-llm] {reasoning}")
    if isinstance(blockers, list) and blockers:
        ledger.append(f"[align-llm] blockers={blockers!r}")
    ledger.append(f"[align-llm] verdict: aligned={aligned}")

    reason = "llm_auditor_reject" if not aligned else "llm_auditor_accept"
    return PlanAlignmentVerdict(
        aligned=aligned,
        reason=reason,
        ledger_lines=ledger,
        fix_hint=fix if not aligned else None,
    )
