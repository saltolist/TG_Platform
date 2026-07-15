"""Compiled WorkspaceAgent graph with durable checkpointing."""

from __future__ import annotations

import logging
import asyncio
import uuid
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.db.models import AgentRun, User
from app.services.agent.actions.proposals import create_proposal
from app.services.agent.media.jobs import create_media_job, enqueue_media_job
from app.services.agent.media.registry import lookup_capability, resolve_profile_media_model
from app.services.agent.research.graph import (
    research_seed_node,
    research_planner_node,
    research_tool_node,
    research_verify_node,
    research_pack_node,
    route_research_plan,
    route_research_after_tool,
    route_research_verify,
)
from app.services.agent.research.trust import UNTRUSTED_SYSTEM_NOTE
from app.services.agent.runtime.budget import call_llm_with_deadline
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready, get_checkpointer
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.state import AgentGraphState

logger = logging.getLogger(__name__)
_compiled_graphs: dict[int, tuple[object, Any]] = {}

WORKSPACE_SYSTEM = """Ты единственный WorkspaceAgent платформы.
Верни один JSON tool call:
- {"type":"read"} — нужен поиск по workspace;
- {"type":"finish"} — ответ не требует данных workspace;
- {"type":"post_proposal","command":"create_post|edit_post|schedule_post|publish_post|cancel_schedule|delete_post|restore_post","payload":{...}};
- {"type":"media_proposal","kind":"image|video","prompt":"...","options":{},"cost_ceiling":number}.
Не выполняй мутации напрямую. Выбирай только тип вызова, без keyword routing.
При любой неоднозначности выбирай "read": если запрос ссылается на посты, заметки, метрики, охваты или любые факты workspace — это "read". "finish" — только для явно общих/не-фактических запросов (приветствие, объяснение возможностей, вопрос не про данные workspace).
Если передан блок "Диалог" — используй его, чтобы понять контекст запроса. Короткая правка твоего предыдущего ответа без новых фактических вопросов (перефразируй, покороче, на другом языке, другим тоном) — это "finish", даже если предыдущий ответ был по фактам workspace: факты уже собраны и лежат в диалоге, повторный поиск не нужен.
Если передан блок "Текущий пост" и пользователь просит изменить его текст (убрать/добавить/переформулировать что-то в посте) — это {"type":"post_proposal","command":"edit_post","payload":{"post_id":"<id из блока>","patch":{"text":"<полный новый текст поста>"}}}. В patch.text верни ПОЛНЫЙ текст поста с внесённой правкой, сохранив всё остальное без изменений — не фрагмент и не описание правки."""


async def bootstrap_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    return {
        **state,
        "status": "running",
        "step_count": 0,
        "repair_count": state.get("repair_count", 0),
    }


async def workspace_agent_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.services.ai.rag_json import extract_json_object

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    if not ctx.reasoner_spec or not ctx.reasoner_model or not ctx.reasoner_api_key:
        call: dict[str, Any] = {"type": "read"}
    else:
        # dialog_context lets the classifier route conversational follow-ups
        # ("покороче", "на английском?") to "finish" instead of a doomed
        # research pass with nothing new to retrieve (agent-runtime-sprints
        # §2.1 — canon requires both planner and answer to see history).
        dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
        user_text = str(state.get("user_text") or "")
        content_parts: list[str] = []
        if dialog_context.strip():
            content_parts.append(f"Диалог:\n{dialog_context.strip()}")
        # The classifier must see the post it's being asked to edit — without
        # this it cannot produce a correct edit_post payload and silently
        # falls back to "read"/"finish" (a plain text answer, no proposal).
        if ctx.scope == "post" and ctx.post_data:
            post_id = str(ctx.post_data.get("id") or "")
            post_text = str(ctx.post_data.get("text") or "")
            if post_id and post_text:
                content_parts.append(f"Текущий пост (id={post_id}):\n{post_text}")
        content_parts.append(f"Текущий запрос:\n{user_text}" if content_parts else user_text)
        user_content = "\n\n".join(content_parts)
        raw = await call_llm_with_deadline(
            ctx,
            messages=[
                {"role": "system", "content": WORKSPACE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            spec=ctx.reasoner_spec,
            model=ctx.reasoner_model,
            api_key=ctx.reasoner_api_key,
            temperature=0.0,
            max_tokens=600,
        )
        call = extract_json_object(raw) or {"type": "read"}
    call_type = str(call.get("type") or "read")
    if call_type not in {"read", "finish", "post_proposal", "media_proposal"}:
        call = {"type": "read"}
        call_type = "read"
    return {**state, "current_tool": call_type, "tool_call": call}


def route_workspace_call(
    state: AgentGraphState,
) -> Literal["seed", "answer", "build_action_proposal", "build_media_proposal"]:
    # "read" enters the research loop directly at its first node (seed). The
    # research nodes (seed/planner/tool/verify/pack) are first-class members of
    # this single graph — no nested subgraph, no separate checkpointer, and no
    # lossy repackaging of evidence_records (agent-runtime-sprints §1.0).
    call_type = str((state.get("tool_call") or {}).get("type") or "read")
    return {
        "read": "seed",
        "finish": "answer",
        "post_proposal": "build_action_proposal",
        "media_proposal": "build_media_proposal",
    }.get(call_type, "seed")  # type: ignore[return-value]


REFUSAL_TEXT = (
    "Не нашёл в workspace данных, чтобы ответить на это фактически. "
    "Уточните запрос или добавьте материалы, на которые можно опереться."
)


async def answer_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    from app.services.ai.rag_json import extract_json_object

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
    evidence_ids = state.get("evidence_ids") or []
    rag_context = str(state.get("rag_context") or "").strip()
    came_through_research = str((state.get("tool_call") or {}).get("type") or "") == "read"

    # Answer guard (code-gate, not prompt): if the request went through research
    # but produced no grounded evidence, refuse instead of letting the model
    # invent an answer on an empty pack (agent-runtime-sprints §1.1). Dialog
    # history never overrides this — it cannot substitute for missing facts.
    if came_through_research and (not evidence_ids or not rag_context):
        return {
            **state,
            "answer_text": REFUSAL_TEXT,
            "claims": [],
            "stopped_reason": "empty_evidence_refusal",
        }

    prompt_parts: list[str] = []
    if dialog_context.strip():
        prompt_parts.append(f"Диалог:\n{dialog_context.strip()}")
    prompt_parts.append(f"Вопрос:\n{state.get('user_text', '')}")
    if came_through_research:
        # Grounded path: cite only the retrieved evidence, same contract as before.
        prompt_parts.append(f"Evidence IDs: {evidence_ids}\nEvidence:\n{rag_context}")
        prompt_parts.append(
            'Верни JSON {"answer":"...","claims":[{"text":"...","evidence_ids":[...]}]}.'
        )
        system_text = (
            "Отвечай только по evidence. Не выдумывай отсутствующие факты.\n"
            + UNTRUSTED_SYSTEM_NOTE
        )
    else:
        # Conversational "finish" path (agent-runtime-sprints §2.1): a
        # follow-up like "покороче" or "на английском?" needs the prior turn
        # from dialog_context, not new evidence — there is none to fetch.
        prompt_parts.append('Верни JSON {"answer":"...","claims":[]}.')
        system_text = (
            "Отвечай на разговорный запрос, используя диалог выше как контекст "
            "(например, если это правка твоего предыдущего ответа). Не выдумывай "
            "факты о workspace, которых нет в диалоге."
        )
    prompt = "\n\n".join(prompt_parts)

    if not ctx.reasoner_spec or not ctx.reasoner_model or not ctx.reasoner_api_key:
        answer = rag_context or "Для ответа не требуется дополнительный контекст."
        return {**state, "answer_text": answer, "claims": []}

    raw = await call_llm_with_deadline(
        ctx,
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
        spec=ctx.reasoner_spec,
        model=ctx.reasoner_model,
        api_key=ctx.reasoner_api_key,
        temperature=0.1,
        max_tokens=1200,
    )
    parsed = extract_json_object(raw) or {}
    claims = parsed.get("claims") if isinstance(parsed.get("claims"), list) else []
    return {
        **state,
        "answer_text": str(parsed.get("answer") or raw),
        "claims": claims,
    }


async def build_action_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.session import async_session_factory

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    if not ctx.settings.agent_actions_enabled:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "agent_actions_disabled"],
            "answer_text": "Действия агента отключены feature flag.",
        }
    call = state.get("tool_call") or {}
    command = str(call.get("command") or "")
    payload = dict(call.get("payload") or {})
    async with async_session_factory() as session:
        run = await session.get(AgentRun, uuid.UUID(state["run_id"]))
        if run is None:
            raise RuntimeError("agent_run_not_found")
        proposal = await create_proposal(
            session,
            run=run,
            user_id=uuid.UUID(state["user_id"]),
            command=command,
            payload=payload,
            resource_version=str(call.get("resource_version") or "") or None,
            warnings=[str(item) for item in call.get("warnings") or []],
        )
        await session.commit()
    pending = {
        "type": "action_proposal",
        "proposal": {
            "id": str(proposal.id),
            "command": proposal.command,
            "payload_hash": proposal.payload_hash,
            "payload": proposal.payload,
            "warnings": proposal.warnings,
            "resource_version": proposal.resource_version,
        },
    }
    return {
        **state,
        "proposal_ids": [*(state.get("proposal_ids") or []), str(proposal.id)],
        "interrupt": pending,
    }


async def build_media_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    if not ctx.settings.agent_media_enabled:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "agent_media_disabled"],
            "answer_text": "Генерация медиа отключена feature flag.",
        }
    call = state.get("tool_call") or {}
    kind = str(call.get("kind") or "image")
    model = resolve_profile_media_model(ctx.ai_profile, kind=kind)  # type: ignore[arg-type]
    if model is None:
        return {
            **state,
            "errors": [*(state.get("errors") or []), f"no_active_{kind}_model"],
            "answer_text": f"В профиле не выбрана активная {kind}-модель.",
        }
    capability = lookup_capability(
        str(model.get("provider") or ""),
        str(model.get("model") or ""),
    )
    if capability is None or capability.kind != kind:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "unsupported_media_model"],
            "answer_text": "Выбранная media-модель пока не поддерживается runtime.",
        }
    pending = {
        "type": "media_cost",
        "proposal": {
            "kind": kind,
            "provider": model.get("provider"),
            "model": model.get("model"),
            "model_id": model.get("id"),
            "prompt": str(call.get("prompt") or ""),
            "options": dict(call.get("options") or {}),
            "cost_ceiling": call.get("cost_ceiling"),
        },
    }
    return {**state, "interrupt": pending}


def _action_result_text(decision: dict[str, Any]) -> str:
    """Report the real outcome of an approved action, not a hardcoded string.

    The resume payload carries `applied` — the execute_approved_proposal result
    (e.g. {"post_id": .., "status": "published"}). Reflecting it means a failed
    or unexpected execution no longer reads as a flat "выполнено"
    (agent-runtime-remaining.md Спринт 5)."""
    if decision.get("decision") != "approve":
        return "Предложенное действие отклонено."
    applied = decision.get("applied")
    if not isinstance(applied, dict) or not applied:
        # Approved but no execution result surfaced — be honest, don't claim done.
        return "Действие подтверждено (результат исполнения недоступен)."
    status = str(applied.get("status") or "").strip()
    post_id = str(applied.get("post_id") or "").strip()
    tail = f" (пост {post_id}, статус: {status})" if status else ""
    return f"Действие подтверждено и выполнено{tail}."


async def action_hitl_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt")
    if pending and pending.get("type") == "action_proposal":
        decision = interrupt(pending)
        return {
            **state,
            "interrupt": None,
            "status": "running",
            "answer_text": _action_result_text(decision),
        }
    return state


async def media_hitl_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt")
    if pending and pending.get("type") in {"media_cost", "media_attach"}:
        decision = interrupt(pending)
        return {
            **state,
            "interrupt": None,
            "status": "running",
            "media_decision": {
                **decision,
                "proposal": dict(pending.get("proposal") or {}),
            },
        }
    return state


def route_media_decision(state: AgentGraphState) -> Literal["submit_media", "complete"]:
    decision = state.get("media_decision") or {}
    return "submit_media" if decision.get("decision") == "approve" else "complete"


async def submit_media_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.session import async_session_factory

    proposal = dict((state.get("interrupt") or {}).get("proposal") or {})
    # On resume the interrupt payload was cleared; retain the original proposal
    # in the resume value when provided by the API.
    decision = state.get("media_decision") or {}
    proposal = dict(decision.get("proposal") or proposal)
    async with async_session_factory() as session:
        job = await create_media_job(
            session,
            user_id=uuid.UUID(state["user_id"]),
            run_id=uuid.UUID(state["run_id"]),
            job_type=str(proposal.get("kind") or "image"),
            provider=str(proposal.get("provider") or ""),
            model=str(proposal.get("model") or ""),
            brief={
                "prompt": str(proposal.get("prompt") or ""),
                "options": dict(proposal.get("options") or {}),
                "model_id": proposal.get("model_id"),
            },
            reserved_cost=proposal.get("cost_ceiling"),
        )
        await enqueue_media_job(session, job)
        await session.commit()
    return {
        **state,
        "job_ids": [*(state.get("job_ids") or []), str(job.id)],
        "interrupt": {"type": "awaiting_job", "job_id": str(job.id)},
    }


async def media_wait_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt") or {}
    result = interrupt(pending)
    return {
        **state,
        "interrupt": None,
        "media_result": result,
    }


async def build_media_attach_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.models import MediaAsset
    from app.db.session import async_session_factory
    from app.services.agent.media.storage import MediaStorage
    from app.core.config import get_settings

    result = state.get("media_result") or {}
    post_id = str(state.get("post_id") or "")
    asset_id = str(result.get("asset_id") or "")
    if not post_id or not asset_id:
        return state
    async with async_session_factory() as session:
        run = await session.get(AgentRun, uuid.UUID(state["run_id"]))
        asset = await session.get(MediaAsset, uuid.UUID(asset_id))
        if run is None or asset is None or asset.user_id != uuid.UUID(state["user_id"]):
            raise RuntimeError("media_attach_target_not_found")
        payload = {
            "post_id": post_id,
            "asset_id": asset_id,
            "mime_type": asset.mime_type,
            "name": "generated",
            "preview_url": MediaStorage(get_settings()).signed_preview_url(asset.object_key),
        }
        proposal = await create_proposal(
            session,
            run=run,
            user_id=uuid.UUID(state["user_id"]),
            command="attach_media",
            payload=payload,
            warnings=["Медиа будет прикреплено к посту только после подтверждения."],
        )
        await session.commit()
    pending = {
        "type": "action_proposal",
        "proposal": {
            "id": str(proposal.id),
            "command": proposal.command,
            "payload_hash": proposal.payload_hash,
            "payload": proposal.payload,
            "warnings": proposal.warnings,
        },
    }
    return {
        **state,
        "proposal_ids": [*(state.get("proposal_ids") or []), str(proposal.id)],
        "interrupt": pending,
    }


async def complete_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    return {**state, "status": "completed"}


def build_workspace_graph() -> StateGraph:
    graph = StateGraph(AgentGraphState)
    graph.add_node("bootstrap", bootstrap_node)
    graph.add_node("workspace_agent", workspace_agent_node)
    # Research nodes are first-class in the single graph (agent-runtime-sprints §1.0), not a
    # nested subgraph. One checkpointer, one state, no content="" repackaging.
    graph.add_node("seed", research_seed_node)
    graph.add_node("planner", research_planner_node)
    graph.add_node("tool", research_tool_node)
    graph.add_node("verify", research_verify_node)
    graph.add_node("pack", research_pack_node)
    graph.add_node("answer", answer_node)
    graph.add_node("build_action_proposal", build_action_proposal_node)
    graph.add_node("build_media_proposal", build_media_proposal_node)
    graph.add_node("action_hitl", action_hitl_node)
    graph.add_node("media_hitl", media_hitl_node)
    graph.add_node("submit_media", submit_media_node)
    graph.add_node("media_wait", media_wait_node)
    graph.add_node("build_media_attach_proposal", build_media_attach_proposal_node)
    graph.add_node("complete", complete_node)
    graph.set_entry_point("bootstrap")
    graph.add_edge("bootstrap", "workspace_agent")
    graph.add_conditional_edges("workspace_agent", route_workspace_call)
    # read → research loop (seed → planner ⇄ tool → verify → pack) → answer
    graph.add_edge("seed", "planner")
    graph.add_conditional_edges("planner", route_research_plan)
    graph.add_conditional_edges("tool", route_research_after_tool)
    graph.add_conditional_edges("verify", route_research_verify)
    graph.add_edge("pack", "answer")
    graph.add_edge("answer", "complete")
    graph.add_edge("build_action_proposal", "action_hitl")
    graph.add_edge("build_media_proposal", "media_hitl")
    graph.add_edge("action_hitl", "complete")
    graph.add_conditional_edges("media_hitl", route_media_decision)
    graph.add_edge("submit_media", "media_wait")
    graph.add_edge("media_wait", "build_media_attach_proposal")
    graph.add_edge("build_media_attach_proposal", "action_hitl")
    graph.add_edge("complete", END)
    return graph


def get_compiled_workspace_graph():
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        return build_workspace_graph().compile(checkpointer=get_checkpointer())
    saver = get_checkpointer()
    cached = _compiled_graphs.get(loop_key)
    if cached is None or cached[0] is not saver:
        compiled = build_workspace_graph().compile(checkpointer=saver)
        _compiled_graphs[loop_key] = (saver, compiled)
        return compiled
    return cached[1]


async def run_workspace_graph(
    *,
    run_id: uuid.UUID,
    user_text: str,
    runtime_context: RuntimeContext,
    configurable: dict[str, Any] | None = None,
) -> AgentGraphState:
    await ensure_checkpointer_ready()
    graph = get_compiled_workspace_graph()
    initial: AgentGraphState = {
        "run_id": str(run_id),
        "user_id": str(runtime_context.user_id),
        "user_text": user_text,
        "scope": runtime_context.scope,
        "post_id": str((runtime_context.post_data or {}).get("id") or "") or None,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "repair_count": 0,
        "max_steps": runtime_context.settings.rag_agent_max_steps,
    }
    cfg = {
        "configurable": {
            "thread_id": str(run_id),
            "runtime_context": runtime_context,
            **(configurable or {}),
        }
    }
    final_state: AgentGraphState = initial
    async for chunk in graph.astream(initial, cfg, stream_mode="values"):
        if isinstance(chunk, dict):
            final_state = chunk
    return final_state
