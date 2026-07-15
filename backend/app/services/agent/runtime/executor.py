"""Execute agent runs with graph, events, and interrupt handling."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from langgraph.types import Command

from app.db.models import AgentRun, User
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.budget import RunDeadlineExceeded
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.observability import (
    AGENT_DURATION,
    AGENT_EMPTY_PACK,
    AGENT_INTERRUPTS,
    AGENT_RUNS,
    AGENT_STEPS,
    AGENT_STOPPED_REASON,
)
from app.services.agent.runtime.trace import render_run_trace
from app.services.agent.runtime.workspace_graph import get_compiled_workspace_graph

logger = logging.getLogger(__name__)


def _planner_step_payload(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the newest planner step from an "updates" chunk, if present.

    The "updates" stream yields {node_name: partial_state_update} per node
    (agent-runtime-sprints §3.3). research_planner_node returns the full
    accumulated planner_steps list each time it runs, so the newest entry
    (the one this node call just appended) is always the last item.
    """
    planner_update = chunk.get("planner")
    if not isinstance(planner_update, dict):
        return None
    steps = planner_update.get("planner_steps")
    if not isinstance(steps, list) or not steps:
        return None
    latest = steps[-1]
    return dict(latest) if isinstance(latest, dict) else None


def _tool_outcome_payload(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the newest tool result from a "tool" node "updates" chunk.

    Mirrors _planner_step_payload: research_tool_node returns the full
    accumulated tool_outcomes list, so the last entry is the one this node
    call just appended (Спринт 5 — tool observability).
    """
    tool_update = chunk.get("tool")
    if not isinstance(tool_update, dict):
        return None
    outcomes = tool_update.get("tool_outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return None
    latest = outcomes[-1]
    return dict(latest) if isinstance(latest, dict) else None


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


async def _maybe_log_trace(session, *, run: AgentRun, settings) -> None:
    """When AI_CONTEXT_LOG=1, dump the run's decision timeline to the worker
    log — durable-first tracing (Спринт 5). Rendered from the persisted
    agent_events, not a process-local buffer, so it works from the Celery
    worker. Gated by the flag: the extra event re-query only runs when on."""
    if not getattr(settings, "ai_context_log", False):
        return
    try:
        events = await event_service.list_events(session, run_id=run.id)
        body = render_run_trace(events, run_id=str(run.id))
        if body:
            logger.info("\n%s", body)
    except Exception:  # tracing must never break a run
        logger.exception("Failed to render agent run trace for %s", run.id)


def _record_run_metrics(final_state: dict[str, Any]) -> None:
    """Run-level observability counters (Спринт 5): steps taken, empty-pack
    (grounding gap), and terminal stopped_reason. Read from the final state so
    a single call covers every successful terminal path."""
    AGENT_STEPS.observe(int(final_state.get("step_count") or 0))
    if not (final_state.get("evidence_ids") or []):
        AGENT_EMPTY_PACK.inc()
    AGENT_STOPPED_REASON.labels(str(final_state.get("stopped_reason") or "unknown")).inc()


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
    # Arm the run-level wall-clock budget (agent-runtime-sprints §6): every LLM
    # call downstream reads this off runtime_context and caps itself with it.
    runtime_context.deadline_monotonic = (
        time.monotonic() + runtime_context.settings.rag_agent_deadline_s
    )
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
            "dialog_context": runtime_context.dialog_context,
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
                planner_step = _planner_step_payload(chunk)
                if planner_step is not None:
                    await emit_run_event(
                        session,
                        run_id=run.id,
                        event_type="planner_step",
                        payload=planner_step,
                    )
                tool_outcome = _tool_outcome_payload(chunk)
                if tool_outcome is not None:
                    await emit_run_event(
                        session,
                        run_id=run.id,
                        event_type="tool_result",
                        payload=tool_outcome,
                    )
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
        _record_run_metrics(final_state)
        await _maybe_log_trace(session, run=run, settings=runtime_context.settings)
        return final_state
    except RunDeadlineExceeded as exc:
        # Wall-clock budget spent (agent-runtime-sprints §6). Distinct terminal
        # state from a generic crash: the run is "failed" but with an explicit
        # deadline_exceeded reason so ops/metrics can tell a timeout from a bug.
        logger.warning("Agent run %s hit wall-clock deadline: %s", run.id, exc)
        await event_service.update_run_status(
            session,
            run,
            status="failed",
            error="deadline_exceeded",
        )
        await emit_run_event(
            session,
            run_id=run.id,
            event_type="run_failed",
            payload={"error": "deadline_exceeded", "stopped_reason": "deadline_exceeded"},
        )
        await session.commit()
        AGENT_RUNS.labels("failed").inc()
        AGENT_DURATION.observe(time.perf_counter() - started_at)
        AGENT_STOPPED_REASON.labels("deadline_exceeded").inc()
        raise
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
        AGENT_STOPPED_REASON.labels("crash").inc()
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
    # Fresh wall-clock budget for the resumed leg (agent-runtime-sprints §6).
    runtime_context.deadline_monotonic = (
        time.monotonic() + runtime_context.settings.rag_agent_deadline_s
    )
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
            "dialog_context": runtime_context.dialog_context,
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
        elif mode == "updates" and isinstance(chunk, dict):
            planner_step = _planner_step_payload(chunk)
            if planner_step is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="planner_step",
                    payload=planner_step,
                )
            tool_outcome = _tool_outcome_payload(chunk)
            if tool_outcome is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="tool_result",
                    payload=tool_outcome,
                )
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
