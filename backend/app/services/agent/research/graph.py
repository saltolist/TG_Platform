"""Evidence-driven research subgraph (LangGraph + bounded ReAct)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.services.agent.research.evidence import EvidenceRecord, records_from_agent_state
from app.services.agent.research.pack import build_evidence_pack
from app.services.agent.research.result import ResearchResult
from app.services.agent.research.verifier import verify_evidence
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.state import AgentGraphState
from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_dialog_ledger import (
    TurnSnapshot,
    format_ledger_for_planner,
    seed_hydrated_attachments_from_ledger,
)
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_tools import (
    AgentState,
    ToolOutcome,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_note_attachments,
    tool_list_post_notes,
    tool_list_posts,
    tool_open_note,
    tool_open_post,
    tool_search_nodes,
)
from app.services.ai.reply_pipeline_log import trace_step

logger = logging.getLogger(__name__)

READ_TOOLS = frozenset(
    {
        "SearchNodes",
        "OpenPost",
        "OpenNote",
        "ListPosts",
        "ListPostNotes",
        "ListNoteAttachments",
        "HydrateAttachment",
        "GetPostAnalytics",
    }
)

AGENT_SYSTEM = """Ты research-агент workspace. Собери факты read-tools и заверши через FinishRetrieval.

Доступные tools (JSON):
- SearchNodes {query, node_types?, k?}
- OpenPost {post_id}
- OpenNote {note_id, post_id?} — прочитать содержимое конкретной заметки
- ListPosts {query?, limit?}
- ListPostNotes {post_id} — перечислить заметки поста (сначала OpenPost)
- ListNoteAttachments {note_id, post_id?}
- HydrateAttachment {ref, mode?}
- GetPostAnalytics {post_id, period?}
- FinishRetrieval {status: ready|partial, evidence_ids: string[], unresolved?: string[]}

Правила:
- Только read; никаких мутаций.
- Завершай, когда собрано достаточно для ответа.
- В `evidence_ids` перечисляй ТОЛЬКО те id, что показаны в блоке «Собранный context» как `[id: …]` — дословно. Не выдумывай id и не подставляй номера постов.
- Верни один JSON: {"tool": "...", "args": {...}}.
"""


@dataclass(frozen=True)
class ToolAction:
    tool: str
    args: dict[str, Any]


def parse_tool_action(raw: str) -> ToolAction | None:
    payload = extract_json_object(raw or "")
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if not tool:
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    return ToolAction(tool=tool, args=args)


def render_agent_context(state: AgentState) -> str:
    lines: list[str] = []
    for cite, plain in state.context_blocks[-12:]:
        title = getattr(cite, "title", "") or getattr(cite, "path", "")
        lines.append(f"### {title}\n{(plain or '')[:1200]}")
    return "\n\n".join(lines) if lines else "(контекст пуст)"


def _build_messages(
    *,
    user_text: str,
    transcript: list[str],
    hints: list[str],
    dialog_context: str,
    ledger_text: str,
    l1_summary: str,
) -> list[dict[str, str]]:
    parts = [f"Вопрос:\n{user_text.strip()}"]
    if dialog_context.strip():
        parts.append(f"Диалог:\n{dialog_context.strip()}")
    if ledger_text.strip():
        parts.append(ledger_text.strip())
    if l1_summary.strip():
        parts.append(l1_summary.strip())
    if hints:
        parts.append("Подсказки: " + "; ".join(hints))
    if transcript:
        parts.append("Ход агента:\n" + "\n".join(transcript[-12:]))
    parts.append("Текущий собранный контекст:\n" + "(см. transcript)")
    return [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


async def _execute_tool(state: AgentState, action: ToolAction) -> ToolOutcome:
    tool = action.tool
    args = action.args
    if tool == "SearchNodes":
        return await tool_search_nodes(
            state,
            query=str(args.get("query") or ""),
            node_types=args.get("node_types"),
            k=args.get("k"),
        )
    if tool == "OpenPost":
        return await tool_open_post(state, post_id=str(args.get("post_id") or ""))
    if tool == "OpenNote":
        return await tool_open_note(
            state,
            note_id=str(args.get("note_id") or ""),
            post_id=args.get("post_id"),
        )
    if tool == "ListPosts":
        # Expose only the documented query/limit surface — no hidden status arg
        # that the planner was never told about (agent-runtime-sprints §1.4).
        return await tool_list_posts(
            state,
            query=str(args.get("query") or "") or None,
            limit=int(args.get("limit") or 8),
        )
    if tool == "ListPostNotes":
        return tool_list_post_notes(state, post_id=str(args.get("post_id") or ""))
    if tool == "ListNoteAttachments":
        return await tool_list_note_attachments(
            state,
            note_id=str(args.get("note_id") or ""),
            post_id=args.get("post_id"),
        )
    if tool == "HydrateAttachment":
        return await tool_hydrate_attachment(
            state,
            ref=str(args.get("ref") or ""),
            mode=str(args.get("mode") or "text"),
        )
    if tool == "GetPostAnalytics":
        return await tool_get_post_analytics(
            state,
            post_id=str(args.get("post_id") or ""),
            period=str(args.get("period") or "7d"),
        )
    return ToolOutcome(summary=f"Неизвестный tool: {tool}", error="unknown_tool")


# ---------------------------------------------------------------------------
# Module-level research nodes (agent-runtime-sprints §1.0 single-graph).
#
# Lifted out of run_research_graph's closures so the SAME nodes power both the
# legacy run_research_graph entrypoint and the unified workspace graph. Each
# node reads the RuntimeContext + planner inputs from config["configurable"]
# instead of capturing them, so there is one graph, one checkpointer, one state.
# ---------------------------------------------------------------------------


def _planner_inputs(config: RunnableConfig) -> dict[str, Any]:
    conf = (config or {}).get("configurable", {}) if config else {}
    return {
        "dialog_context": str(conf.get("dialog_context") or ""),
        "dialog_ledger": tuple(conf.get("dialog_ledger") or ()),
        "l1_results": conf.get("l1_results"),
        "seed_ref": conf.get("seed_ref"),
        "seed_post_id": conf.get("seed_post_id"),
    }


def _format_evidence_for_planner(records: dict[str, EvidenceRecord]) -> str:
    """List collected evidence with its natural id so the planner cites real keys.

    FinishRetrieval.evidence_ids must reference these ids verbatim; surfacing
    them here is what closes the empty-pack loop (agent-runtime-sprints §1.2).
    """
    if not records:
        return "(контекст пуст)"
    blocks: list[str] = []
    for rec_id, rec in records.items():
        title = rec.citation_title or rec_id
        body = (rec.content or "").strip()[:1200] or "(пусто)"
        blocks.append(f"[id: {rec_id}] {title}\n{body}")
    return "\n\n".join(blocks)


def _l1_summary(l1_results: list[dict[str, Any]] | None) -> str:
    if not l1_results:
        return ""
    previews = [
        f"- {item.get('node_type')}:{item.get('note_id')} sim={item.get('similarity', 0):.2f}"
        for item in l1_results[:6]
    ]
    return "L1 hits:\n" + "\n".join(previews)


async def research_seed_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    inp = _planner_inputs(config)
    seed_ref = inp["seed_ref"]
    seed_post_id = inp["seed_post_id"]
    user_text = str(state.get("user_text") or "")
    transcript = list(state.get("research_transcript") or [])
    async with ctx.session_factory() as session:
        agent_state = ctx.bind_agent_state(session)
        if seed_ref and str(seed_ref).startswith("note:"):
            note_id = str(seed_ref)[len("note:") :].strip()
            outcome = await tool_open_note(agent_state, note_id=note_id, post_id=seed_post_id)
            transcript.append(f"[seed] OpenNote: {outcome.summary}")
        if ctx.scope == "post":
            post_id = (
                str(seed_post_id or "").strip()
                or str((ctx.post_data or {}).get("id") or "").strip()
            )
            if post_id:
                outcome = await tool_open_post(agent_state, post_id=post_id)
                transcript.append(f"[seed] OpenPost: {outcome.summary}")
                agent_state.resolved_target_post_id = post_id
        seeded = seed_hydrated_attachments_from_ledger(
            agent_state,
            user_text=user_text,
            ledger=inp["dialog_ledger"],
        )
        if seeded:
            transcript.append(f"[seed] ledger attachments: {', '.join(seeded)}")
        records = records_from_agent_state(agent_state)
        await session.commit()
    return {
        **state,
        "research_transcript": transcript,
        "evidence_records": {key: rec.to_dict() for key, rec in records.items()},
        "step_count": 0,
        "repair_count": 0,
        "status": "running",
    }


async def research_planner_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    from app.services.ai.llm import complete_chat_completion

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    inp = _planner_inputs(config)
    spec = ctx.reasoner_spec
    model = ctx.reasoner_model
    api_key = ctx.reasoner_api_key
    max_steps = int(state.get("max_steps") or 4)
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    if spec is None or not model or not api_key:
        action = ToolAction(
            tool="FinishRetrieval",
            args={
                "status": "partial" if records else "ready",
                "evidence_ids": list(records),
                "unresolved": ["no_reasoner_llm"],
            },
        )
    else:
        ledger_text = (
            format_ledger_for_planner(inp["dialog_ledger"]) if inp["dialog_ledger"] else ""
        )
        messages = _build_messages(
            user_text=str(state.get("user_text") or ""),
            transcript=list(state.get("research_transcript") or []),
            hints=list(state.get("research_hints") or []),
            dialog_context=inp["dialog_context"],
            ledger_text=ledger_text,
            l1_summary=_l1_summary(inp["l1_results"]),
        )
        evidence_text = _format_evidence_for_planner(records)
        messages[-1]["content"] += "\n\nСобранный context:\n" + evidence_text
        raw = await complete_chat_completion(
            messages=messages,
            spec=spec,
            model=model,
            api_key=api_key,
            temperature=0.1,
            max_tokens=700,
        )
        action = parse_tool_action(raw) or ToolAction(tool="Invalid", args={})
    steps = int(state.get("step_count") or 0) + 1
    trace_step("7. rag.L2.langgraph", [f"step={steps}/{max_steps}", f"tool={action.tool}"])
    return {
        **state,
        "step_count": steps,
        "tool_action": {"tool": action.tool, "args": action.args},
    }


async def research_tool_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    raw_action = state.get("tool_action") or {}
    action = ToolAction(
        tool=str(raw_action.get("tool") or ""),
        args=dict(raw_action.get("args") or {}),
    )
    transcript = list(state.get("research_transcript") or [])
    existing_records = dict(state.get("evidence_records") or {})
    async with ctx.session_factory() as session:
        agent_state = ctx.bind_agent_state(session)
        outcome = await _execute_tool(agent_state, action)
        records = records_from_agent_state(agent_state)
        await session.commit()
    transcript.append(f"step {state.get('step_count', 0)}: {action.tool} → {outcome.summary}")
    if outcome.error:
        transcript.append(f"  error={outcome.error}")
    return {
        **state,
        "research_transcript": transcript,
        "evidence_records": {
            **existing_records,
            **{key: rec.to_dict() for key, rec in records.items()},
        },
    }


async def research_verify_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    # Do NOT auto-fill evidence_ids with every record — an empty list is a
    # verification failure that triggers repair, not a licence to "cite
    # everything" (agent-runtime-sprints §1.3). The model must choose its cites.
    candidate = dict((state.get("tool_action") or {}).get("args") or {})
    verdict = verify_evidence(
        finish=candidate,
        records=records,
        repair_count=int(state.get("repair_count") or 0),
    )
    if verdict.ok or not verdict.repair_allowed:
        return {**state, "finish_retrieval": candidate, "verification_ok": True}
    return {
        **state,
        "repair_count": int(state.get("repair_count") or 0) + 1,
        "research_hints": [
            *(state.get("research_hints") or []),
            f"repair: {', '.join(verdict.errors)}",
        ],
        "verification_ok": False,
    }


async def research_pack_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (state.get("evidence_records") or {}).items()
    }
    # Honour the verified finish literally — no "cite everything" fallback.
    # An empty selection yields an empty pack, which the answer guard turns
    # into an honest refusal rather than ungrounded text (agent-runtime-sprints §1.3).
    finish = dict(state.get("finish_retrieval") or {})
    evidence_ids = [str(item) for item in (finish.get("evidence_ids") or [])]
    unresolved_items = [str(item) for item in (finish.get("unresolved") or [])]
    packed, _ = build_evidence_pack(
        records=records,
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
    )
    return {
        **state,
        "rag_context": packed,
        "evidence_ids": evidence_ids,
        "unresolved": unresolved_items,
        "stopped_reason": str(finish.get("status") or "ready"),
        "status": "completed",
    }


def route_research_plan(state: AgentGraphState) -> Literal["planner", "tool", "verify"]:
    action = state.get("tool_action") or {}
    tool = str(action.get("tool") or "")
    if tool == "FinishRetrieval":
        return "verify"
    # Hard-stop on step budget still routes through verify, never straight to
    # pack — the collected evidence must clear the gate before it can ground an
    # answer (agent-runtime-sprints §1.3).
    if int(state.get("step_count") or 0) >= int(state.get("max_steps") or 4):
        return "verify"
    return "tool" if tool in READ_TOOLS else "planner"


def route_research_after_tool(state: AgentGraphState) -> Literal["planner", "verify"]:
    return (
        "verify"
        if int(state.get("step_count") or 0) >= int(state.get("max_steps") or 4)
        else "planner"
    )


def route_research_verify(state: AgentGraphState) -> Literal["planner", "pack"]:
    return "pack" if state.get("verification_ok") else "planner"


def build_research_graph() -> StateGraph:
    """Assemble the research loop from the shared module-level nodes.

    Single source of truth: the same nodes power both this standalone graph
    (legacy run_research_graph / contract tests) and the unified workspace
    graph (agent-runtime-sprints §1.0), so behaviour cannot drift between the two paths.
    """
    graph = StateGraph(AgentGraphState)
    graph.add_node("seed", research_seed_node)
    graph.add_node("planner", research_planner_node)
    graph.add_node("tool", research_tool_node)
    graph.add_node("verify", research_verify_node)
    graph.add_node("pack", research_pack_node)
    graph.set_entry_point("seed")
    graph.add_edge("seed", "planner")
    graph.add_conditional_edges("planner", route_research_plan)
    graph.add_conditional_edges("tool", route_research_after_tool)
    graph.add_conditional_edges("verify", route_research_verify)
    graph.add_edge("pack", END)
    return graph


async def run_research_graph(
    ctx: RuntimeContext,
    *,
    user_text: str,
    seed_ref: str | None = None,
    seed_post_id: str | None = None,
    hints: list[str] | None = None,
    dialog_context: str = "",
    dialog_ledger: tuple[TurnSnapshot, ...] = (),
    l1_results: list[dict[str, Any]] | None = None,
    max_steps: int = 4,
    spec: ProviderSpec | None = None,
    model: str = "",
    api_key: str = "",
    checkpoint_id: str | None = None,
) -> ResearchResult:
    """Run the durable, bounded evidence research state machine."""
    from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready, get_checkpointer

    research_hints = list(hints or [])

    graph = build_research_graph()
    await ensure_checkpointer_ready()
    compiled = graph.compile(checkpointer=get_checkpointer())
    config = {
        "configurable": {
            "thread_id": str(ctx.user_id),
            "checkpoint_ns": f"research:{checkpoint_id or uuid.uuid4()}",
            "runtime_context": ctx,
            "dialog_context": dialog_context,
            "dialog_ledger": dialog_ledger,
            "l1_results": l1_results,
            "seed_ref": seed_ref,
            "seed_post_id": seed_post_id,
        }
    }
    initial: AgentGraphState = {
        "user_text": user_text,
        "scope": ctx.scope,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "repair_count": 0,
        "step_count": 0,
        "max_steps": max_steps,
        "research_transcript": [],
        "research_hints": research_hints,
    }
    final_state = initial
    async for value in compiled.astream(initial, config, stream_mode="values"):
        final_state = value
    records = {
        key: EvidenceRecord.from_dict(value)
        for key, value in (final_state.get("evidence_records") or {}).items()
    }
    evidence_ids = list(final_state.get("evidence_ids") or [])
    unresolved_items = list(final_state.get("unresolved") or [])
    rag_context, cites = build_evidence_pack(
        records=records,
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
    )
    return ResearchResult(
        rag_context=rag_context,
        cites=cites,
        stopped_reason=str(final_state.get("stopped_reason") or "ready"),
        evidence_ids=evidence_ids,
        unresolved=unresolved_items,
        step_count=int(final_state.get("step_count") or 0),
    )


def build_research_subgraph() -> StateGraph:
    """Build a serializable pack-only graph for isolated contract tests."""

    async def bootstrap(state: AgentGraphState) -> AgentGraphState:
        return {**state, "status": "running", "step_count": 0}

    async def pack_node(state: AgentGraphState) -> AgentGraphState:
        records = {
            k: EvidenceRecord.from_dict(v)
            for k, v in (state.get("evidence_records") or {}).items()
        }
        ids = state.get("evidence_ids") or list(records.keys())
        ctx, _cites = build_evidence_pack(records=records, evidence_ids=ids)
        return {**state, "rag_context": ctx, "status": "completed"}

    graph = StateGraph(AgentGraphState)
    graph.add_node("bootstrap", bootstrap)
    graph.add_node("pack", pack_node)
    graph.set_entry_point("bootstrap")
    graph.add_edge("bootstrap", "pack")
    graph.add_edge("pack", END)
    return graph
