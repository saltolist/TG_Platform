"""Execute agent runs with graph, events, and interrupt handling."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from langgraph.types import Command

from app.db.models import AgentRun, User
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.observability import (
    AGENT_DURATION,
    AGENT_INTERRUPTS,
    AGENT_RUNS,
)
from app.services.agent.runtime.workspace_graph import get_compiled_workspace_graph

logger = logging.getLogger(__name__)


def _interrupt_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if "__interrupt__" in value:
            return _interrupt_payload(value["__interrupt__"])
        for nested in value.values():
            found = _interrupt_payload(nested)
            if found is not None:
                return found
    if isinstance(value, (list, tuple)):
        for nested in value:
            found = _interrupt_payload(nested)
            if found is not None:
                return found
    interrupt_value = getattr(value, "value", None)
    return dict(interrupt_value) if isinstance(interrupt_value, dict) else None


async def emit_run_event(
    session,
    *,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    evt = await event_service.append_event(
        session,
        run_id=run_id,
        event_type=event_type,
        payload=payload,
    )
    return evt.sequence


async def execute_agent_run(
    session,
    *,
    run: AgentRun,
    user: User,
    user_text: str,
    runtime_context: RuntimeContext,
    configurable: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    await ensure_checkpointer_ready()
    graph = get_compiled_workspace_graph()
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
            **(configurable or {}),
        }
    }
    initial = {
        "run_id": str(run.id),
        "user_id": str(user.id),
        "user_text": user_text,
        "scope": run.scope,
        "post_id": run.post_id,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "repair_count": 0,
        "max_steps": runtime_context.settings.rag_agent_max_steps,
    }
    await emit_run_event(
        session,
        run_id=run.id,
        event_type="graph_started",
        payload={"user_text": user_text[:200]},
    )
    checkpoint = await graph.aget_state(cfg)
    checkpoint_values = dict(checkpoint.values or {})
    graph_input: dict[str, Any] | None = initial
    if checkpoint_values:
        if not checkpoint.next:
            recovered_status = str(checkpoint_values.get("status") or "completed")
            await event_service.update_run_status(
                session,
                run,
                status=recovered_status,
                snapshot=checkpoint_values,
                current_interrupt=None,
            )
            await session.commit()
            return checkpoint_values
        graph_input = None
    final_state: dict[str, Any] = checkpoint_values or initial
    try:
        async for mode, chunk in graph.astream(
            graph_input,
            cfg,
            stream_mode=["values", "updates"],
        ):
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="graph_state",
                    payload={
                        "status": chunk.get("status"),
                        "step_count": chunk.get("step_count"),
                        "stopped_reason": chunk.get("stopped_reason"),
                    },
                )
            elif mode == "updates" and isinstance(chunk, dict):
                interrupt_payload = _interrupt_payload(chunk)
                if interrupt_payload is not None:
                    run.current_interrupt = interrupt_payload
                    run.status = "interrupted"
                    AGENT_INTERRUPTS.labels(
                        str(interrupt_payload.get("type") or "unknown")
                    ).inc()
                    await emit_run_event(
                        session,
                        run_id=run.id,
                        event_type="interrupt",
                        payload=interrupt_payload,
                    )
        status = str(final_state.get("status") or "completed")
        if run.status == "interrupted":
            status = "interrupted"
        elif status not in {"failed", "cancelled"}:
            status = "completed"
        await event_service.update_run_status(
            session,
            run,
            status=status,
            snapshot=dict(final_state),
            current_interrupt=run.current_interrupt,
        )
        if final_state.get("answer_text"):
            await emit_run_event(
                session,
                run_id=run.id,
                event_type="answer",
                payload={
                    "text": final_state["answer_text"],
                    "claims": final_state.get("claims") or [],
                    "evidence_ids": final_state.get("evidence_ids") or [],
                },
            )
        await emit_run_event(
            session,
            run_id=run.id,
            event_type="run_interrupted" if status == "interrupted" else "run_completed",
            payload={"status": status},
        )
        await session.commit()
        AGENT_RUNS.labels(status).inc()
        AGENT_DURATION.observe(time.perf_counter() - started_at)
        return final_state
    except Exception as exc:
        logger.exception("Agent run %s failed", run.id)
        await event_service.update_run_status(
            session,
            run,
            status="failed",
            error=str(exc),
        )
        await emit_run_event(
            session,
            run_id=run.id,
            event_type="run_failed",
            payload={"error": str(exc)},
        )
        await session.commit()
        AGENT_RUNS.labels("failed").inc()
        AGENT_DURATION.observe(time.perf_counter() - started_at)
        raise


async def resume_agent_graph(
    session,
    *,
    run: AgentRun,
    resume_value: dict[str, Any],
    runtime_context: RuntimeContext | None = None,
) -> dict[str, Any]:
    from app.services.agent.runtime.runs import rebuild_runtime_context_for_run

    await ensure_checkpointer_ready()
    graph = get_compiled_workspace_graph()
    # Resume must carry runtime_context — nodes downstream of the interrupt
    # (research/answer) read it from configurable and would otherwise KeyError
    # (agent-runtime-sprints §1.5).
    if runtime_context is None:
        runtime_context = await rebuild_runtime_context_for_run(session, run)
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
        }
    }
    final_state: dict[str, Any] = {}
    pending_interrupt: dict[str, Any] | None = None
    async for mode, chunk in graph.astream(
        Command(resume=resume_value),
        cfg,
        stream_mode=["values", "updates"],
    ):
        if mode == "values" and isinstance(chunk, dict):
            final_state = chunk
        elif mode == "updates":
            payload = _interrupt_payload(chunk)
            if payload is not None:
                pending_interrupt = payload
    status = "interrupted" if pending_interrupt else str(
        final_state.get("status") or "completed"
    )
    if status not in {"interrupted", "failed", "cancelled"}:
        status = "completed"
    await event_service.update_run_status(
        session,
        run,
        status=status,
        snapshot=dict(final_state),
        current_interrupt=pending_interrupt,
    )
    if pending_interrupt is not None:
        await emit_run_event(
            session,
            run_id=run.id,
            event_type="interrupt",
            payload=pending_interrupt,
        )
    elif final_state.get("answer_text"):
        await emit_run_event(
            session,
            run_id=run.id,
            event_type="answer",
            payload={
                "text": final_state["answer_text"],
                "claims": final_state.get("claims") or [],
                "evidence_ids": final_state.get("evidence_ids") or [],
            },
        )
    await emit_run_event(
        session,
        run_id=run.id,
        event_type="graph_resumed",
        payload=resume_value,
    )
    await session.commit()
    return final_state
