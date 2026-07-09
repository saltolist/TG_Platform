"""L2 agentic RAG planner loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_json import extract_json_object
from app.services.ai.reply_pipeline_log import trace_step
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
) -> tuple[RetrievalPlan | None, str]:
    remaining = max_steps - steps_used
    if remaining <= 0 or plan_context is None:
        return None, ""

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
        if decision.use_plan:
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
            outcome = await _run_tool_step(
                state=state,
                action=action,
                transcript=transcript,
            )
            steps_used += 1

            should_replan = replans_used < MAX_PLAN_REPLANS and steps_used < max_steps and (
                action.tool in DISCOVERY_TOOLS
                or outcome.error is not None
            )
            if should_replan:
                trigger = (
                    f"after_{action.tool}"
                    if action.tool in DISCOVERY_TOOLS
                    else f"after_error:{outcome.error}"
                )
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
                )
                replans_used += 1
                if new_plan is not None:
                    plan = new_plan
                    plan_step_index = 0
                    transcript.append(
                        f"[replan] goal={plan.goal} steps={len(plan.steps)} trigger={trigger}"
                    )
                    for index, replan_step in enumerate(plan.steps, start=1):
                        purpose = f" — {replan_step.purpose}" if replan_step.purpose else ""
                        transcript.append(
                            f"[replan] {index}. {replan_step.tool}({replan_step.args}){purpose}"
                        )
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

        await _run_tool_step(state=state, action=action, transcript=transcript)
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

    rag_context, cites = render_agent_context(state.context_blocks)
    return AgentResult(rag_context=rag_context, cites=cites, stopped_reason=stopped_reason)
