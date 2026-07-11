"""L2 agentic RAG planner loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_json import extract_json_object
from app.core.config import get_settings
from app.services.ai.rag_plan_alignment import (
    PlanAlignmentVerdict,
    audit_plan_alignment_llm,
    evaluate_plan_alignment,
)
from app.services.ai.rag_binding_policy import (
    can_bind_target_post,
    format_target_evidence_gap,
    should_block_post_scoped_tool,
)
from app.services.ai.rag_retrieval_brief import RetrievalBrief, build_retrieval_brief
from app.services.ai.reply_pipeline_log import trace_step
from app.services.ai.rag_target_resolver import (
    TargetPostResolution,
    format_catalog_for_planner,
    format_resolution_for_planner,
    format_resolver_trace_lines,
    resolve_target_post,
)
from app.services.ai.rag_retrieval_plan import (
    DISCOVERY_TOOLS,
    L2PlanContext,
    MAX_PLAN_REPLANS,
    RetrievalPlan,
    RetrievalPlanStep,
    compose_retrieval_plan,
    decide_structured_plan,
    format_plan_compose_trace_lines,
)
from app.services.ai.rag_tools import (
    AgentState,
    ToolOutcome,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_note_attachments,
    tool_list_post_comments,
    tool_list_post_notes,
    tool_list_posts,
    tool_open_note,
    tool_open_post,
    tool_search_nodes,
)

logger = logging.getLogger(__name__)

_AGENT_SYSTEM = (
    "Ты planner для agentic RAG. Выбирай один инструмент за шаг и верни только JSON: "
    '{"tool": "<имя>", "args": {...}}. '
    "Доступные инструменты:\n"
    '- ListPosts: {"status": "all"|"published"|"draft"|"scheduled"}\n'
    '- SearchNodes: {"query": "...", "node_types": ["post_text","note_chunk",...], "k": 4}\n'
    '- OpenPost: {"post_id": "..."}\n'
    '- ListPostNotes: {"post_id": "..."}\n'
    '- OpenNote: {"note_id": "...", "post_id": "..."?}\n'
    '- ListNoteAttachments: {"note_id": "...", "post_id": "..."?}\n'
    '- HydrateAttachment: {"ref": "attachment:<id>|file:<id>", "mode": "text"|"vision", '
    '"note_id": "..."?, "post_id": "..."?}\n'
    '- ListPostComments: {"post_id": "..."}\n'
    '- GetPostAnalytics: {"post_id": "...", "period": "7d|30d|90d|24h|all"}\n'
    '- Stop: {"reason": "sufficient"}\n'
    "SearchNodes возвращает кандидатов без содержимого — для текста вызывай OpenPost/OpenNote. "
    "HydrateAttachment mode=vision используй только если вопрос про содержимое изображения — "
    "не для обычных текстовых вопросов. "
    "ListPostComments используй, если вопрос про реакцию аудитории или комментарии. "
    "Когда контекста достаточно — Stop."
)

_KNOWN_TOOLS = frozenset(
    {
        "ListPosts",
        "SearchNodes",
        "OpenPost",
        "ListPostNotes",
        "OpenNote",
        "ListNoteAttachments",
        "HydrateAttachment",
        "ListPostComments",
        "GetPostAnalytics",
        "Stop",
    }
)


@dataclass(frozen=True)
class PlannerAction:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    rag_context: str
    cites: list[NoteCite]
    stopped_reason: str


def parse_planner_action(raw: str) -> PlannerAction | None:
    payload = extract_json_object(raw or "")
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if not tool:
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    return PlannerAction(tool=tool, args=args)


def _preview_planner_raw(raw: str, limit: int = 800) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def format_planner_trace_lines(
    *,
    step_index: int,
    max_steps: int,
    raw: str,
    action: PlannerAction | None = None,
    raw_limit: int = 800,
) -> list[str]:
    """Build trace lines for one L2 planner LLM turn."""
    lines = [
        f"step={step_index}/{max_steps}",
        f"raw: {_preview_planner_raw(raw, raw_limit)}",
    ]
    if action is not None:
        lines.append(f"parsed_tool={action.tool}")
        if action.args:
            lines.append(f"parsed_args={action.args!r}")
    return lines


def build_agent_messages(
    user_text: str,
    transcript: list[str],
    hints: list[str],
) -> list[dict[str, str]]:
    lines = [f"Вопрос пользователя:\n{user_text.strip()}"]
    if hints:
        lines.append("Подсказки эскалации (информационно):")
        lines.extend(f"- {hint}" for hint in hints)
    if transcript:
        lines.append("Ход выполнения:")
        lines.extend(transcript)
    lines.append("Следующий инструмент (JSON):")
    return [
        {"role": "system", "content": _AGENT_SYSTEM},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def render_agent_context(blocks: list[tuple[NoteCite, str]]) -> tuple[str, list[NoteCite]]:
    if not blocks:
        return "", []

    lines: list[str] = ["---", "**Контекст из базы знаний:**"]
    cites: list[NoteCite] = []
    for index, (cite, plain) in enumerate(blocks, start=1):
        cites.append(cite)
        label = f"**{cite.title}**"
        lines.append(
            f"\n[{index}] cite-path: {cite.path} cite-title: {cite.title}\n{label}\n{plain}"
        )
    if len(lines) <= 2:
        return "", []
    lines.append("---")
    return "\n".join(lines), cites


async def _dispatch_tool(state: AgentState, action: PlannerAction) -> ToolOutcome:
    tool = action.tool
    args = action.args
    try:
        if tool == "ListPosts":
            return await tool_list_posts(
                state,
                status=str(args.get("status") or "all") or None,
            )
        if tool == "SearchNodes":
            return await tool_search_nodes(
                state,
                query=str(args.get("query") or ""),
                node_types=args.get("node_types") if isinstance(args.get("node_types"), list) else None,
                k=int(args["k"]) if isinstance(args.get("k"), (int, float)) else None,
            )
        if tool == "OpenPost":
            return await tool_open_post(state, post_id=str(args.get("post_id") or ""))
        if tool == "ListPostNotes":
            return tool_list_post_notes(state, post_id=str(args.get("post_id") or ""))
        if tool == "OpenNote":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            return await tool_open_note(
                state,
                note_id=str(args.get("note_id") or ""),
                post_id=post_id or None,
            )
        if tool == "ListNoteAttachments":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            return await tool_list_note_attachments(
                state,
                note_id=str(args.get("note_id") or ""),
                post_id=post_id or None,
            )
        if tool == "HydrateAttachment":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            note_id_raw = args.get("note_id")
            note_id = str(note_id_raw).strip() if note_id_raw else None
            return await tool_hydrate_attachment(
                state,
                ref=str(args.get("ref") or ""),
                mode=str(args.get("mode") or "text"),
                note_id=note_id or None,
                post_id=post_id or None,
            )
        if tool == "ListPostComments":
            return tool_list_post_comments(state, post_id=str(args.get("post_id") or ""))
        if tool == "GetPostAnalytics":
            return await tool_get_post_analytics(
                state,
                post_id=str(args.get("post_id") or ""),
                period=str(args.get("period") or "30d"),
            )
        return ToolOutcome(summary=f"Неизвестный инструмент: {tool}", error="unknown_tool")
    except Exception as exc:
        logger.warning("RAG tool %s failed: %s", tool, exc)
        return ToolOutcome(summary=f"Инструмент {tool} завершился с ошибкой.", error=str(exc))


async def _maybe_accept_stop(
    *,
    user_text: str,
    state: AgentState,
    action: PlannerAction,
    steps_used: int,
    max_steps: int,
    transcript: list[str],
    default_reason: str,
) -> tuple[str | None, bool]:
    """Return (stopped_reason, should_break) when Stop is accepted."""
    from app.services.ai.rag_stop_evaluator import evaluate_stop

    verdict = evaluate_stop(
        user_text,
        state,
        state.context_blocks,
        scope=state.scope,
    )
    if verdict.allowed:
        stopped_reason = str(action.args.get("reason") or default_reason)
        logger.info("RAG L2: Stop accepted reason=%s", verdict.reason)
        state.decision_ledger.append(f"[ledger] Stop accepted: {verdict.reason}")
        trace_step(
            "7. rag.L2.step",
            f"Stop({stopped_reason}) accepted — {verdict.reason}",
        )
        return stopped_reason, True

    logger.info(
        "RAG L2: Stop rejected reason=%s steps_left=%s",
        verdict.reason,
        max_steps - steps_used,
    )
    transcript.append(f"Stop отклонён: {verdict.reason}")
    state.decision_ledger.append(f"[ledger] Stop rejected: {verdict.reason}")
    trace_step("7. rag.L2.step", f"Stop rejected — {verdict.reason}")
    return None, False


async def _run_tool_step(
    *,
    state: AgentState,
    action: PlannerAction,
    transcript: list[str],
) -> ToolOutcome:
    outcome = await _dispatch_tool(state, action)
    transcript.append(f"{action.tool}({action.args}): {outcome.summary}")
    trace_step(
        "7. rag.L2.step",
        f"{action.tool}({action.args}): {outcome.summary}"
        + (f" [error={outcome.error}]" if outcome.error else ""),
    )
    if outcome.error:
        logger.warning("RAG L2 tool %s error: %s", action.tool, outcome.error)
    return outcome


def _chat_post_id(state: AgentState, seed_post_id: str | None = None) -> str | None:
    value = (
        str(seed_post_id or "").strip()
        or str((state.base_post_data or {}).get("id") or "").strip()
    )
    return value or None


def _is_valid_hydrate_ref(ref: str) -> bool:
    cleaned = str(ref or "").strip()
    if not cleaned or "<" in cleaned:
        return False
    if cleaned.startswith("attachment:"):
        return bool(cleaned[len("attachment:") :].strip())
    if cleaned.startswith("file:"):
        return bool(cleaned[len("file:") :].strip())
    return False


_IMAGE_NOTE_TITLE_MARKERS = (
    "изображ",
    "картин",
    "png",
    "jpg",
    "jpeg",
    "фото",
    "скрин",
    "вариант",
)


def _outcome_lists_image_notes(summary: str) -> bool:
    lowered = (summary or "").lower()
    if "note:" not in lowered:
        return False
    return any(marker in lowered for marker in _IMAGE_NOTE_TITLE_MARKERS)


def _needs_attachment_replan_after_list_notes(
    brief: RetrievalBrief | None,
    action: PlannerAction,
    outcome: ToolOutcome,
) -> bool:
    if brief is None or action.tool != "ListPostNotes" or outcome.error:
        return False
    evidence = set(brief.evidence_needed)
    if not evidence.intersection({"attachments", "vision"}):
        return False
    return _outcome_lists_image_notes(outcome.summary)


def _planner_context_blocks(state: AgentState) -> tuple[str, str]:
    resolution = TargetPostResolution(
        post_id=state.target_resolution_post_id,
        rationale=state.target_resolution_rationale or "—",
        confidence=state.target_resolution_confidence or "none",
    )
    return (
        format_catalog_for_planner(state.catalog_posts),
        format_resolution_for_planner(resolution),
    )


async def _ensure_post_catalog(state: AgentState, transcript: list[str]) -> None:
    if state.catalog_posts or any(ref.startswith("list_posts:") for ref in state.visited):
        return
    outcome = await tool_list_posts(state, status="all")
    state.discovery_completed = True
    transcript.append(f"[prefetch] ListPosts: {outcome.summary}")
    trace_step(
        "7. rag.L2.step",
        f"[prefetch] ListPosts: {outcome.summary}"
        + (f" [error={outcome.error}]" if outcome.error else ""),
    )
    state.decision_ledger.append("[ledger] prefetch ListPosts for planner/resolver")


async def _run_target_resolver(
    *,
    state: AgentState,
    user_text: str,
    dialog_context: str,
    brief: RetrievalBrief,
    plan_context: L2PlanContext,
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> None:
    if not brief.named_post_query or state.scope != "global" or not state.catalog_posts:
        return

    resolution = await resolve_target_post(
        user_text=user_text,
        dialog_context=dialog_context,
        brief=brief,
        catalog_posts=state.catalog_posts,
        l1_results=plan_context.l1_results,
        spec=spec,
        model=model,
        api_key=api_key,
    )
    state.target_resolution_post_id = resolution.post_id
    state.target_resolution_rationale = resolution.rationale
    state.target_resolution_confidence = resolution.confidence
    if resolution.is_confident:
        state.resolved_target_post_id = resolution.post_id
    state.decision_ledger.append(
        "[ledger] target resolver: "
        f"post_id={resolution.post_id!r} confidence={resolution.confidence!r}"
    )
    trace_step("7. rag.L2.resolver", format_resolver_trace_lines(resolution=resolution))


def _store_brief(
    *,
    state: AgentState,
    user_text: str,
    plan_context: L2PlanContext,
    seed_post_id: str | None,
    dialog_context: str = "",
) -> RetrievalBrief:
    brief = build_retrieval_brief(
        user_text=user_text,
        scope=state.scope,
        seed_post_id=_chat_post_id(state, seed_post_id),
        tier_a=plan_context.tier_a,
        l1_results=plan_context.l1_results,
        dialog_context=dialog_context,
    )
    state.retrieval_brief = brief
    state.decision_ledger.extend(brief.ledger_lines)
    trace_step("7. rag.L2.brief", list(brief.ledger_lines))
    return brief


def _record_alignment_verdict(state: AgentState, verdict: PlanAlignmentVerdict) -> None:
    state.decision_ledger.extend(verdict.ledger_lines)
    trace_step(
        "7. rag.L2.plan_align",
        verdict.ledger_lines
        + [f"aligned={verdict.aligned}", f"reason={verdict.reason}"],
    )


async def _evaluate_alignment_verdict(
    *,
    user_text: str,
    state: AgentState,
    brief: RetrievalBrief,
    plan: RetrievalPlan,
    plan_context: L2PlanContext,
    seed_post_id: str | None,
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> PlanAlignmentVerdict:
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=plan_context.l1_results,
        seed_post_id=_chat_post_id(state, seed_post_id),
        tier_a=plan_context.tier_a,
        scope=state.scope,
        discovery_completed=state.discovery_completed,
        target_resolution_post_id=state.target_resolution_post_id,
        target_resolution_confidence=state.target_resolution_confidence,
    )
    settings = state.settings or get_settings()
    if not verdict.aligned and settings.rag_agent_plan_alignment_llm:
        verdict = await audit_plan_alignment_llm(
            user_text=user_text,
            brief=brief,
            plan=plan,
            l1_results=plan_context.l1_results,
            deterministic_verdict=verdict,
            spec=spec,
            model=model,
            api_key=api_key,
        )
    return verdict


def _update_entity_bindings(
    *,
    state: AgentState,
    action: PlannerAction,
    seed_post_id: str | None,
    tier_a_post_id: str | None,
    l1_results: list | None = None,
) -> None:
    if action.tool in DISCOVERY_TOOLS:
        state.discovery_completed = True
    if action.tool != "OpenPost":
        return
    post_id = str(action.args.get("post_id") or "").strip()
    if not post_id:
        return
    post_data = state.opened_posts.get(post_id)
    allowed, reason = can_bind_target_post(
        brief=state.retrieval_brief,
        scope=state.scope,
        post_id=post_id,
        post_data=post_data,
        discovery_completed=state.discovery_completed,
        seed_post_id=seed_post_id,
        tier_a_post_id=tier_a_post_id,
        l1_results=l1_results,
        target_resolution_post_id=state.target_resolution_post_id,
        target_resolution_confidence=state.target_resolution_confidence,
    )
    if allowed:
        state.resolved_target_post_id = post_id
        state.decision_ledger.append(f"[ledger] bound target post_id={post_id} ({reason})")
    else:
        state.decision_ledger.append(
            f"[ledger] OpenPost({post_id}) without binding ({reason})"
        )


def _blocked_binding_action(
    *,
    state: AgentState,
    action: PlannerAction,
    plan_context: L2PlanContext | None,
    seed_post_id: str | None,
    tier_a_post_id: str | None,
) -> ToolOutcome | None:
    brief = state.retrieval_brief
    l1_results = plan_context.l1_results if plan_context else []
    post_id = str(action.args.get("post_id") or "").strip() or None

    blocked, summary, error_code = should_block_post_scoped_tool(
        tool=action.tool,
        post_id=post_id,
        brief=brief,
        scope=state.scope,
        resolved_target_post_id=state.resolved_target_post_id,
        l1_results=l1_results,
        target_resolution_post_id=state.target_resolution_post_id,
        target_resolution_confidence=state.target_resolution_confidence,
    )
    if blocked:
        return ToolOutcome(summary=summary, error=error_code or "binding_blocked")
    return None


def _maybe_record_target_evidence_gap(
    *,
    state: AgentState,
    action: PlannerAction,
    outcome: ToolOutcome,
) -> None:
    if outcome.error:
        return
    brief = state.retrieval_brief
    if brief is None:
        return
    evidence = set(brief.evidence_needed)
    if not evidence.intersection({"attachments", "vision"}):
        return

    post_id = str(action.args.get("post_id") or "").strip()
    target_id = str(state.resolved_target_post_id or "").strip()
    if not target_id or post_id != target_id:
        return

    if action.tool == "ListPostNotes" and "нет заметок" in outcome.summary:
        state.target_evidence_gap = "no_notes_on_target"
        state.decision_ledger.append(
            f"[ledger] evidence gap: target post {target_id} has no notes"
        )
        return

    if action.tool == "ListNoteAttachments" and not state.listed_image_attachment_refs:
        lowered = outcome.summary.lower()
        if "нет вложений" in lowered:
            state.target_evidence_gap = "no_image_attachments_on_target"
            state.decision_ledger.append(
                f"[ledger] evidence gap: target post {target_id} has no image attachments"
            )


async def _maybe_run_discovery_ladder(
    *,
    state: AgentState,
    action: PlannerAction,
    outcome: ToolOutcome,
    transcript: list[str],
) -> ToolOutcome | None:
    if action.tool != "SearchNodes":
        return None
    if "Поиск не дал результатов" not in outcome.summary:
        return None
    brief = state.retrieval_brief
    if brief is None or not brief.named_post_query or state.resolved_target_post_id:
        return None
    node_types = action.args.get("node_types")
    if not isinstance(node_types, list):
        return None
    normalized = {str(item).strip() for item in node_types}
    if "post_text" not in normalized:
        return None
    if any(ref.startswith("list_posts:") for ref in state.visited):
        return None

    list_outcome = await tool_list_posts(state, status="all")
    state.discovery_completed = True
    transcript.append(
        f"[ladder] ListPosts after empty SearchNodes(post_text): {list_outcome.summary}"
    )
    trace_step(
        "7. rag.L2.step",
        f"[ladder] ListPosts: {list_outcome.summary}"
        + (f" [error={list_outcome.error}]" if list_outcome.error else ""),
    )
    state.decision_ledger.append(
        "[ledger] discovery ladder: ListPosts after empty SearchNodes(post_text)"
    )
    return list_outcome


async def _validate_replanned_plan(
    *,
    user_text: str,
    state: AgentState,
    plan: RetrievalPlan | None,
    brief: RetrievalBrief | None,
    plan_context: L2PlanContext,
    seed_post_id: str | None,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    transcript: list[str],
    trigger: str,
) -> RetrievalPlan | None:
    if plan is None or brief is None:
        return plan
    verdict = await _evaluate_alignment_verdict(
        user_text=user_text,
        state=state,
        brief=brief,
        plan=plan,
        plan_context=plan_context,
        seed_post_id=seed_post_id,
        spec=spec,
        model=model,
        api_key=api_key,
    )
    _record_alignment_verdict(state, verdict)
    if verdict.aligned:
        return plan
    transcript.append(f"[plan_check] replan rejected ({trigger}): {verdict.reason}")
    if verdict.fix_hint:
        transcript.append(f"[plan_check] fix: {verdict.fix_hint}")
    state.decision_ledger.append(f"[ledger] replan rejected: {verdict.reason}")
    return None


def _l1_results(plan_context: L2PlanContext | None) -> list:
    if plan_context is None:
        return []
    return list(plan_context.l1_results)


async def _adopt_replanned_plan(
    *,
    new_plan: RetrievalPlan | None,
    trigger: str,
    user_text: str,
    state: AgentState,
    brief: RetrievalBrief | None,
    plan_context: L2PlanContext | None,
    transcript: list[str],
    spec: ProviderSpec,
    model: str,
    api_key: str,
    seed_post_id: str | None,
) -> RetrievalPlan | None:
    if new_plan is None or plan_context is None:
        return None
    validated = await _validate_replanned_plan(
        user_text=user_text,
        state=state,
        plan=new_plan,
        brief=brief,
        plan_context=plan_context,
        seed_post_id=seed_post_id,
        spec=spec,
        model=model,
        api_key=api_key,
        transcript=transcript,
        trigger=trigger,
    )
    if validated is None:
        transcript.append("[replan] rejected by alignment — reactive fallback")
        return None
    transcript.append(
        f"[replan] goal={validated.goal} steps={len(validated.steps)} trigger={trigger}"
    )
    for index, replan_step in enumerate(validated.steps, start=1):
        purpose = f" — {replan_step.purpose}" if replan_step.purpose else ""
        transcript.append(
            f"[replan] {index}. {replan_step.tool}({replan_step.args}){purpose}"
        )
    return validated


async def _apply_plan_alignment_gate(
    *,
    user_text: str,
    state: AgentState,
    plan: RetrievalPlan | None,
    brief: RetrievalBrief,
    plan_context: L2PlanContext,
    transcript: list[str],
    hints: list[str],
    spec: ProviderSpec,
    model: str,
    api_key: str,
    seed_post_id: str | None,
    replans_used: int,
    max_steps: int,
    steps_used: int,
    dialog_context: str = "",
) -> tuple[RetrievalPlan | None, int]:
    """Validate plan against brief; replan once on misalignment."""
    if plan is None:
        return None, replans_used

    verdict = await _evaluate_alignment_verdict(
        user_text=user_text,
        state=state,
        brief=brief,
        plan=plan,
        plan_context=plan_context,
        seed_post_id=seed_post_id,
        spec=spec,
        model=model,
        api_key=api_key,
    )
    _record_alignment_verdict(state, verdict)
    if verdict.aligned:
        return plan, replans_used

    transcript.append(f"[plan_check] rejected: {verdict.reason}")
    if verdict.fix_hint:
        transcript.append(f"[plan_check] fix: {verdict.fix_hint}")
    state.decision_ledger.append(f"[ledger] plan rejected: {verdict.reason}")

    if replans_used >= MAX_PLAN_REPLANS or steps_used >= max_steps:
        transcript.append("[plan_check] replan budget exhausted — reactive fallback")
        return None, replans_used

    trigger = f"plan_alignment:{verdict.reason}"
    new_plan, _ = await _try_replan(
        user_text=user_text,
        state=state,
        transcript=transcript,
        hints=hints,
        spec=spec,
        model=model,
        api_key=api_key,
        max_steps=max_steps,
        steps_used=steps_used,
        plan_context=plan_context,
        trigger=trigger,
        seed_post_id=seed_post_id,
        alignment_feedback=verdict.fix_hint,
        brief=brief,
        dialog_context=dialog_context,
    )
    replans_used += 1
    if new_plan is None:
        transcript.append("[plan_check] replan failed — reactive fallback")
        return None, replans_used

    transcript.append(f"[replan] goal={new_plan.goal} steps={len(new_plan.steps)} trigger={trigger}")
    for index, replan_step in enumerate(new_plan.steps, start=1):
        purpose = f" — {replan_step.purpose}" if replan_step.purpose else ""
        transcript.append(
            f"[replan] {index}. {replan_step.tool}({replan_step.args}){purpose}"
        )
    state.decision_ledger.append(f"[ledger] replan after {verdict.reason}")

    recheck = await _evaluate_alignment_verdict(
        user_text=user_text,
        state=state,
        brief=brief,
        plan=new_plan,
        plan_context=plan_context,
        seed_post_id=seed_post_id,
        spec=spec,
        model=model,
        api_key=api_key,
    )
    _record_alignment_verdict(state, recheck)
    if recheck.aligned:
        return new_plan, replans_used

    transcript.append(f"[plan_check] replan still misaligned: {recheck.reason}")
    return None, replans_used


async def _try_replan(
    *,
    user_text: str,
    state: AgentState,
    transcript: list[str],
    hints: list[str],
    spec: ProviderSpec,
    model: str,
    api_key: str,
    max_steps: int,
    steps_used: int,
    plan_context: L2PlanContext | None,
    trigger: str,
    seed_post_id: str | None = None,
    alignment_feedback: str | None = None,
    brief: RetrievalBrief | None = None,
    dialog_context: str = "",
) -> tuple[RetrievalPlan | None, str]:
    remaining = max_steps - steps_used
    if remaining <= 0 or plan_context is None:
        return None, ""

    catalog_summary, target_resolution_summary = _planner_context_blocks(state)
    plan, plan_raw = await compose_retrieval_plan(
        user_text=user_text,
        l1_results=plan_context.l1_results,
        hints=hints,
        scope=state.scope,
        spec=spec,
        model=model,
        api_key=api_key,
        max_steps=remaining,
        tier_a=plan_context.tier_a,
        tier_b=plan_context.tier_b,
        transcript=transcript,
        replan_trigger=trigger,
        post_id=_chat_post_id(state, seed_post_id),
        alignment_feedback=alignment_feedback,
        brief=brief or state.retrieval_brief,
        dialog_context=dialog_context,
        catalog_summary=catalog_summary,
        target_resolution_summary=target_resolution_summary,
    )
    trace_step(
        "7. rag.L2.replan",
        format_plan_compose_trace_lines(
            raw=plan_raw,
            plan=plan,
            decision_reason=trigger,
            phase="replan",
        ),
    )
    return plan, plan_raw


async def _finalize_plan_phase(
    *,
    user_text: str,
    state: AgentState,
    transcript: list[str],
    stopped_reason: str,
) -> tuple[str, bool]:
    from app.services.ai.rag_stop_evaluator import evaluate_stop

    verdict = evaluate_stop(
        user_text,
        state,
        state.context_blocks,
        scope=state.scope,
    )
    if verdict.allowed:
        trace_step(
            "7. rag.L2.plan_exec",
            f"plan_done — stop accepted ({verdict.reason})",
        )
        return "plan_complete", True

    transcript.append(
        f"План выполнен, контекста недостаточно: {verdict.reason}. Продолжай."
    )
    trace_step(
        "7. rag.L2.plan_exec",
        f"plan_done — stop rejected ({verdict.reason}), reactive fallback",
    )
    return stopped_reason, False


async def run_agentic_loop(
    *,
    state: AgentState,
    user_text: str,
    seed_ref: str | None,
    seed_post_id: str | None = None,
    hints: list[str],
    spec: ProviderSpec,
    model: str,
    api_key: str,
    max_steps: int,
    plan_context: L2PlanContext | None = None,
    dialog_context: str = "",
) -> AgentResult:
    from app.services.ai.llm import complete_chat_completion

    transcript: list[str] = []
    steps_used = 0
    plan: RetrievalPlan | None = None
    plan_step_index = 0
    plan_phase_done = False
    replans_used = 0

    if seed_ref and seed_ref.startswith("note:"):
        note_id = seed_ref[len("note:") :].strip()
        post_id = (
            str(seed_post_id or "").strip()
            or str((state.base_post_data or {}).get("id") or "").strip()
            or None
        )
        outcome = await tool_open_note(state, note_id=note_id, post_id=post_id)
        transcript.append(f"[seed] OpenNote note_id={note_id}: {outcome.summary}")
        trace_step("7. rag.L2.step", f"[seed] OpenNote({note_id}): {outcome.summary}")
        if outcome.error:
            logger.warning("RAG L2 seed OpenNote failed: %s", outcome.error)

    if state.scope == "post":
        current_post_id = _chat_post_id(state, seed_post_id)
        if current_post_id and current_post_id not in state.opened_posts:
            outcome = await tool_open_post(state, post_id=current_post_id)
            transcript.append(f"[seed] OpenPost post_id={current_post_id}: {outcome.summary}")
            trace_step(
                "7. rag.L2.step",
                f"[seed] OpenPost({current_post_id}): {outcome.summary}",
            )
            if outcome.error:
                logger.warning("RAG L2 seed OpenPost failed: %s", outcome.error)
            else:
                state.resolved_target_post_id = current_post_id

    brief: RetrievalBrief | None = None
    tier_a_post_id = (
        str(plan_context.tier_a.escalate_post_id or "").strip()
        if plan_context and plan_context.tier_a and plan_context.tier_a.escalate_post_id
        else None
    ) or None

    if plan_context is not None:
        decision = decide_structured_plan(
            planning_mode=plan_context.planning_mode,
            user_text=user_text,
            scope=state.scope,
            hints=hints,
            tier_a=plan_context.tier_a,
            tier_b=plan_context.tier_b,
            l1_results=plan_context.l1_results,
        )
        trace_step(
            "7. rag.L2.planning",
            [
                f"mode={plan_context.planning_mode}",
                f"use_structured_plan={decision.use_plan}",
                f"reason={decision.reason}",
            ],
        )
        brief = _store_brief(
            state=state,
            user_text=user_text,
            plan_context=plan_context,
            seed_post_id=seed_post_id,
            dialog_context=dialog_context,
        )
        if brief.named_post_query and state.scope == "global":
            await _ensure_post_catalog(state, transcript)
            await _run_target_resolver(
                state=state,
                user_text=user_text,
                dialog_context=dialog_context,
                brief=brief,
                plan_context=plan_context,
                spec=spec,
                model=model,
                api_key=api_key,
            )
        if decision.use_plan:
            catalog_summary, target_resolution_summary = _planner_context_blocks(state)
            plan, plan_raw = await compose_retrieval_plan(
                user_text=user_text,
                l1_results=plan_context.l1_results,
                hints=hints,
                scope=state.scope,
                spec=spec,
                model=model,
                api_key=api_key,
                max_steps=max_steps,
                tier_a=plan_context.tier_a,
                tier_b=plan_context.tier_b,
                post_id=_chat_post_id(state, seed_post_id),
                brief=brief,
                dialog_context=dialog_context,
                catalog_summary=catalog_summary,
                target_resolution_summary=target_resolution_summary,
            )
            trace_step(
                "7. rag.L2.plan",
                format_plan_compose_trace_lines(
                    raw=plan_raw,
                    plan=plan,
                    decision_reason=decision.reason,
                    phase="initial",
                ),
            )
            if plan is not None:
                transcript.append(f"[plan] goal={plan.goal}")
                for index, step in enumerate(plan.steps, start=1):
                    purpose = f" — {step.purpose}" if step.purpose else ""
                    transcript.append(
                        f"[plan] {index}. {step.tool}({step.args}){purpose}"
                    )
                if brief is not None:
                    plan, replans_used = await _apply_plan_alignment_gate(
                        user_text=user_text,
                        state=state,
                        plan=plan,
                        brief=brief,
                        plan_context=plan_context,
                        transcript=transcript,
                        hints=hints,
                        spec=spec,
                        model=model,
                        api_key=api_key,
                        seed_post_id=seed_post_id,
                        replans_used=replans_used,
                        max_steps=max_steps,
                        steps_used=steps_used,
                        dialog_context=dialog_context,
                    )
            else:
                transcript.append("[plan] compose/parse failed — reactive fallback")

    stopped_reason = "budget_exhausted"
    while steps_used < max_steps:
        if plan is not None and plan_step_index < len(plan.steps):
            step = plan.steps[plan_step_index]
            plan_step_index += 1
            action = PlannerAction(tool=step.tool, args=dict(step.args))
            trace_lines = [
                f"step={plan_step_index}/{len(plan.steps)} budget={steps_used + 1}/{max_steps}",
                f"tool={action.tool}",
                f"args={action.args!r}",
            ]
            if step.purpose:
                trace_lines.append(f"purpose={step.purpose!r}")
            trace_step("7. rag.L2.plan_exec", trace_lines)

            if action.tool == "HydrateAttachment":
                hydrate_ref = str(action.args.get("ref") or "").strip()
                if not _is_valid_hydrate_ref(hydrate_ref):
                    skip_summary = (
                        f"{action.tool}({action.args}): skipped invalid ref {hydrate_ref!r}"
                    )
                    transcript.append(skip_summary)
                    trace_step("7. rag.L2.step", skip_summary)
                    outcome = ToolOutcome(summary=skip_summary, error="invalid_ref")
                    should_replan = replans_used < MAX_PLAN_REPLANS and steps_used < max_steps
                    if should_replan:
                        trigger = f"after_error:{outcome.error}"
                        new_plan, _ = await _try_replan(
                            user_text=user_text,
                            state=state,
                            transcript=transcript,
                            hints=hints,
                            spec=spec,
                            model=model,
                            api_key=api_key,
                            max_steps=max_steps,
                            steps_used=steps_used,
                            plan_context=plan_context,
                            trigger=trigger,
                            seed_post_id=seed_post_id,
                            brief=brief,
                            dialog_context=dialog_context,
                        )
                        replans_used += 1
                        plan = await _adopt_replanned_plan(
                            new_plan=new_plan,
                            trigger=trigger,
                            user_text=user_text,
                            state=state,
                            brief=brief,
                            plan_context=plan_context,
                            transcript=transcript,
                            spec=spec,
                            model=model,
                            api_key=api_key,
                            seed_post_id=seed_post_id,
                        )
                        if plan is not None:
                            plan_step_index = 0
                            continue
                        plan = None
                        plan_step_index = 0
                    continue

            blocked = _blocked_binding_action(
                state=state,
                action=action,
                plan_context=plan_context,
                seed_post_id=_chat_post_id(state, seed_post_id),
                tier_a_post_id=tier_a_post_id,
            )
            if blocked is not None:
                skip_summary = f"{action.tool}({action.args}): {blocked.summary}"
                transcript.append(skip_summary)
                trace_step(
                    "7. rag.L2.step",
                    skip_summary + (f" [error={blocked.error}]" if blocked.error else ""),
                )
                state.decision_ledger.append(f"[ledger] plan blocked: {blocked.summary}")
                steps_used += 1
                continue

            outcome = await _run_tool_step(
                state=state,
                action=action,
                transcript=transcript,
            )
            _update_entity_bindings(
                state=state,
                action=action,
                seed_post_id=_chat_post_id(state, seed_post_id),
                tier_a_post_id=tier_a_post_id,
                l1_results=_l1_results(plan_context),
            )
            _maybe_record_target_evidence_gap(state=state, action=action, outcome=outcome)
            steps_used += 1
            await _maybe_run_discovery_ladder(
                state=state,
                action=action,
                outcome=outcome,
                transcript=transcript,
            )

            attachment_replan = _needs_attachment_replan_after_list_notes(
                brief, action, outcome
            )
            should_replan = replans_used < MAX_PLAN_REPLANS and steps_used < max_steps and (
                action.tool in DISCOVERY_TOOLS
                or outcome.error is not None
                or attachment_replan
            )
            if should_replan:
                if attachment_replan:
                    trigger = "after_ListPostNotes_attachments"
                elif action.tool in DISCOVERY_TOOLS:
                    trigger = f"after_{action.tool}"
                else:
                    trigger = f"after_error:{outcome.error}"
                new_plan, _ = await _try_replan(
                    user_text=user_text,
                    state=state,
                    transcript=transcript,
                    hints=hints,
                    spec=spec,
                    model=model,
                    api_key=api_key,
                    max_steps=max_steps,
                    steps_used=steps_used,
                    plan_context=plan_context,
                    trigger=trigger,
                    seed_post_id=seed_post_id,
                    brief=brief,
                    dialog_context=dialog_context,
                )
                replans_used += 1
                plan = await _adopt_replanned_plan(
                    new_plan=new_plan,
                    trigger=trigger,
                    user_text=user_text,
                    state=state,
                    brief=brief,
                    plan_context=plan_context,
                    transcript=transcript,
                    spec=spec,
                    model=model,
                    api_key=api_key,
                    seed_post_id=seed_post_id,
                )
                if plan is not None:
                    plan_step_index = 0
                    continue
                if outcome.error is not None:
                    transcript.append("[replan] failed — reactive fallback")
                plan = None
                plan_step_index = 0
            continue

        if plan is not None and not plan_phase_done and plan_step_index >= len(plan.steps):
            plan_phase_done = True
            stopped_reason, should_break = await _finalize_plan_phase(
                user_text=user_text,
                state=state,
                transcript=transcript,
                stopped_reason=stopped_reason,
            )
            if should_break:
                break
            plan = None

        if steps_used >= max_steps:
            break

        messages = build_agent_messages(user_text, transcript, hints)
        try:
            raw = await complete_chat_completion(
                spec=spec,
                model=model,
                api_key=api_key,
                messages=messages,
            )
        except Exception as exc:
            logger.warning("RAG L2 planner call failed: %s", exc)
            trace_step(
                "7. rag.L2.planner",
                [
                    f"step={steps_used + 1}/{max_steps}",
                    f"call_failed: {exc}",
                ],
            )
            stopped_reason = "call_failed"
            break

        action = parse_planner_action(raw)
        trace_step(
            "7. rag.L2.planner",
            format_planner_trace_lines(
                step_index=steps_used + 1,
                max_steps=max_steps,
                raw=raw or "",
                action=action,
            ),
        )
        if action is None:
            logger.warning("RAG L2 planner parse failed: %r", (raw or "")[:200])
            stopped_reason = "parse_failed"
            break

        if action.tool not in _KNOWN_TOOLS:
            logger.warning("RAG L2 unknown tool: %s", action.tool)
            stopped_reason = "unknown_tool"
            break

        if action.tool == "Stop":
            accepted_reason, should_break = await _maybe_accept_stop(
                user_text=user_text,
                state=state,
                action=action,
                steps_used=steps_used,
                max_steps=max_steps,
                transcript=transcript,
                default_reason="sufficient",
            )
            if should_break:
                stopped_reason = accepted_reason or "sufficient"
                break
            steps_used += 1
            if steps_used >= max_steps:
                stopped_reason = "budget_exhausted"
                break
            continue

        blocked = _blocked_binding_action(
            state=state,
            action=action,
            plan_context=plan_context,
            seed_post_id=_chat_post_id(state, seed_post_id),
            tier_a_post_id=tier_a_post_id,
        )
        if blocked is not None:
            transcript.append(f"{action.tool}({action.args}): {blocked.summary}")
            trace_step(
                "7. rag.L2.step",
                f"{action.tool}({action.args}): {blocked.summary}"
                + (f" [error={blocked.error}]" if blocked.error else ""),
            )
            state.decision_ledger.append(f"[ledger] reactive blocked: {blocked.summary}")
            steps_used += 1
            if steps_used >= max_steps:
                stopped_reason = "budget_exhausted"
                break
            continue

        reactive_outcome = await _run_tool_step(state=state, action=action, transcript=transcript)
        _update_entity_bindings(
            state=state,
            action=action,
            seed_post_id=_chat_post_id(state, seed_post_id),
            tier_a_post_id=tier_a_post_id,
            l1_results=_l1_results(plan_context),
        )
        _maybe_record_target_evidence_gap(state=state, action=action, outcome=reactive_outcome)
        await _maybe_run_discovery_ladder(
            state=state,
            action=action,
            outcome=reactive_outcome,
            transcript=transcript,
        )
        steps_used += 1

    if (
        plan is not None
        and not plan_phase_done
        and plan_step_index >= len(plan.steps)
    ):
        plan_phase_done = True
        stopped_reason, _ = await _finalize_plan_phase(
            user_text=user_text,
            state=state,
            transcript=transcript,
            stopped_reason=stopped_reason,
        )

    if state.decision_ledger:
        trace_step("7. rag.L2.ledger", state.decision_ledger)

    gap_plain = format_target_evidence_gap(state)
    if gap_plain and state.resolved_target_post_id:
        target_id = state.resolved_target_post_id
        post_data = state.opened_posts.get(target_id, {})
        from app.services.ai.rag import _post_title_from_text

        text_value = str(post_data.get("text") or "").strip()
        title = _post_title_from_text(text_value) if text_value else target_id
        state.context_blocks.append(
            (
                NoteCite(path=f"/post/{target_id}/", title=title),
                gap_plain,
            )
        )

    rag_context, cites = render_agent_context(state.context_blocks)
    return AgentResult(rag_context=rag_context, cites=cites, stopped_reason=stopped_reason)
