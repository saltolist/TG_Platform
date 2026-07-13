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
        "ListNoteAttachments",
        "HydrateAttachment",
        "GetPostAnalytics",
    }
)

AGENT_SYSTEM = """Ты research-агент workspace. Собери факты read-tools и заверши через FinishRetrieval.

Доступные tools (JSON):
- SearchNodes {query, node_types?, k?}
- OpenPost {post_id}
- OpenNote {note_id, post_id?}
- ListPosts {query?, limit?}
- ListNoteAttachments {note_id, post_id?}
- HydrateAttachment {ref, mode?}
- GetPostAnalytics {post_id, period?}
- FinishRetrieval {status: ready|partial, evidence_ids: string[], unresolved?: string[]}

Правила:
- Только read; никаких мутаций.
- Завершай, когда собрано достаточно для ответа.
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
        return await tool_list_posts(
            state,
            status=str(args.get("status") or "") or None,
            query=str(args.get("query") or "") or None,
            limit=int(args.get("limit") or 8),
        )
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
    l1_summary = ""
    if l1_results:
        previews = [
            f"- {item.get('node_type')}:{item.get('note_id')} sim={item.get('similarity', 0):.2f}"
            for item in l1_results[:6]
        ]
        l1_summary = "L1 hits:\n" + "\n".join(previews)

    ledger_text = format_ledger_for_planner(dialog_ledger) if dialog_ledger else ""

    async def seed_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        transcript = list(state.get("research_transcript") or [])
        async with ctx.session_factory() as session:
            agent_state = ctx.bind_agent_state(session)
            if seed_ref and seed_ref.startswith("note:"):
                note_id = seed_ref[len("note:") :].strip()
                outcome = await tool_open_note(
                    agent_state,
                    note_id=note_id,
                    post_id=seed_post_id,
                )
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
                ledger=dialog_ledger,
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

    async def planner_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        from app.services.ai.llm import complete_chat_completion

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
            messages = _build_messages(
                user_text=user_text,
                transcript=list(state.get("research_transcript") or []),
                hints=list(state.get("research_hints") or []),
                dialog_context=dialog_context,
                ledger_text=ledger_text,
                l1_summary=l1_summary,
            )
            evidence_text, _ = build_evidence_pack(
                records=records,
                evidence_ids=list(records),
            )
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
        trace_step(
            "7. rag.L2.langgraph",
            [f"step={steps}/{max_steps}", f"tool={action.tool}"],
        )
        return {
            **state,
            "step_count": steps,
            "tool_action": {"tool": action.tool, "args": action.args},
        }

    async def tool_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
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

    async def verify_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        records = {
            key: EvidenceRecord.from_dict(value)
            for key, value in (state.get("evidence_records") or {}).items()
        }
        candidate = dict((state.get("tool_action") or {}).get("args") or {})
        if not candidate.get("evidence_ids"):
            candidate["evidence_ids"] = list(records)
        verdict = verify_evidence(
            finish=candidate,
            records=records,
            repair_count=int(state.get("repair_count") or 0),
        )
        if verdict.ok or not verdict.repair_allowed:
            return {
                **state,
                "finish_retrieval": candidate,
                "verification_ok": True,
            }
        return {
            **state,
            "repair_count": int(state.get("repair_count") or 0) + 1,
            "research_hints": [
                *(state.get("research_hints") or []),
                f"repair: {', '.join(verdict.errors)}",
            ],
            "verification_ok": False,
        }

    async def pack_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        records = {
            key: EvidenceRecord.from_dict(value)
            for key, value in (state.get("evidence_records") or {}).items()
        }
        finish = dict(state.get("finish_retrieval") or {})
        if not finish:
            finish = {
                "status": "partial" if records else "ready",
                "evidence_ids": list(records),
                "unresolved": [],
            }
        evidence_ids = [str(item) for item in finish.get("evidence_ids") or list(records)]
        unresolved_items = [str(item) for item in finish.get("unresolved") or []]
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

    def route_plan(state: AgentGraphState) -> Literal["planner", "tool", "verify", "pack"]:
        action = state.get("tool_action") or {}
        tool = str(action.get("tool") or "")
        if tool == "FinishRetrieval":
            return "verify"
        if int(state.get("step_count") or 0) >= max_steps:
            return "pack"
        return "tool" if tool in READ_TOOLS else "planner"

    def route_after_tool(state: AgentGraphState) -> Literal["planner", "pack"]:
        return "pack" if int(state.get("step_count") or 0) >= max_steps else "planner"

    def route_verify(state: AgentGraphState) -> Literal["planner", "pack"]:
        return "pack" if state.get("verification_ok") else "planner"

    graph = StateGraph(AgentGraphState)
    graph.add_node("seed", seed_node)
    graph.add_node("planner", planner_node)
    graph.add_node("tool", tool_node)
    graph.add_node("verify", verify_node)
    graph.add_node("pack", pack_node)
    graph.set_entry_point("seed")
    graph.add_edge("seed", "planner")
    graph.add_conditional_edges("planner", route_plan)
    graph.add_conditional_edges("tool", route_after_tool)
    graph.add_conditional_edges("verify", route_verify)
    graph.add_edge("pack", END)

    await ensure_checkpointer_ready()
    compiled = graph.compile(checkpointer=get_checkpointer())
    config = {
        "configurable": {
            "thread_id": str(ctx.user_id),
            "checkpoint_ns": f"research:{checkpoint_id or uuid.uuid4()}",
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
