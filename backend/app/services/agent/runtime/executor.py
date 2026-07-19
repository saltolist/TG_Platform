"""Execute agent runs with graph, events, and interrupt handling."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx
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
from app.services.ai.llm import _HTTP_TIMEOUT

logger = logging.getLogger(__name__)


def _planner_step_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the newest planner step from an "updates" event's data, if present.

    v2 "updates" events yield {"type": "updates", "data": {node_name: partial_state_update}}
    per node (agent-runtime-sprints §3.3). research_planner_node returns the full
    accumulated planner_steps list each time it runs, so the newest entry
    (the one this node call just appended) is always the last item.
    """
    planner_update = data.get("planner")
    if not isinstance(planner_update, dict):
        return None
    steps = planner_update.get("planner_steps")
    if not isinstance(steps, list) or not steps:
        return None
    latest = steps[-1]
    return dict(latest) if isinstance(latest, dict) else None


def _workspace_step_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the workspace classifier's decision from a "workspace_agent" update.

    workspace_agent_node classifies each turn into one of read/finish/
    post_proposal/media_proposal and stores it in `current_tool` (see
    workspace_graph.py). The research planner only emits planner_step events
    for the `read` branch, so without this the activity indicator has nothing
    to show for finish/post_proposal/media_proposal turns (and nothing during
    classification itself) — it just sits on the default label. Emitting the
    classifier decision as its own step gives the UI a real, per-turn phrase.
    """
    node_update = data.get("workspace_agent")
    if not isinstance(node_update, dict):
        return None
    tool = node_update.get("current_tool")
    if not isinstance(tool, str) or not tool:
        return None
    return {"tool": tool}


async def _emit_answer_partial(session, *, run_id: uuid.UUID, data: dict[str, Any]) -> None:
    """Emit a partial "answer" event from a custom stream tick, if it carries one.

    answer_node streams the decoded answer text as {"answer_partial": <text>}
    via the graph's custom stream writer (workspace_graph.py). We surface each
    tick as a normal "answer" event so the frontend — which already renders the
    latest answer event's text into the streaming reply — fills in progressively
    instead of receiving the whole answer at once at the end of the run. The
    terminal "answer" event (with claims) still follows and is the source of
    truth; these partials carry no claims (empty), which is fine mid-stream.
    """
    partial = data.get("answer_partial")
    if not isinstance(partial, str) or not partial:
        return
    await emit_run_event(
        session,
        run_id=run_id,
        event_type="answer",
        payload={"text": partial, "claims": [], "evidence_ids": [], "partial": True},
    )


def _tool_outcome_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the newest tool result from a "tool" node "updates" event's data.

    Mirrors _planner_step_payload: research_tool_node returns the full
    accumulated tool_outcomes list, so the last entry is the one this node
    call just appended (Спринт 5 — tool observability).
    """
    tool_update = data.get("tool")
    if not isinstance(tool_update, dict):
        return None
    outcomes = tool_update.get("tool_outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return None
    latest = outcomes[-1]
    return dict(latest) if isinstance(latest, dict) else None


def _extract_interrupt(interrupts: tuple[Any, ...]) -> dict[str, Any] | None:
    """Pull the interrupt payload out of a v2 "values" event's "interrupts" tuple.

    v2 keeps interrupts out of the state dict entirely (unlike v1, which mixes
    a raw non-JSON-serializable Interrupt object into the "values" chunk under
    "__interrupt__" — see agent-runtime-remaining.md bugfix pass). Only the
    latest interrupt matters; a node raises at most one per step.
    """
    if not interrupts:
        return None
    value = getattr(interrupts[-1], "value", None)
    return dict(value) if isinstance(value, dict) else None


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


def _llm_metrics_payload(runtime_context: RuntimeContext, *, duration_ms: float) -> dict[str, Any]:
    calls = [dict(item) for item in runtime_context.llm_metrics]
    return {
        "duration_ms": round(duration_ms, 1),
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in calls),
        "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in calls),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in calls),
        "token_method": "chars_div_4_estimate",
        "calls": calls,
    }


async def _emit_llm_metrics(session, *, run_id: uuid.UUID, runtime_context: RuntimeContext, started_at: float) -> None:
    await emit_run_event(
        session,
        run_id=run_id,
        event_type="run_metrics",
        payload=_llm_metrics_payload(
            runtime_context,
            duration_ms=(time.perf_counter() - started_at) * 1000,
        ),
    )


async def _persist_turn_memory(
    session,
    *,
    run: AgentRun,
    runtime_context: RuntimeContext,
    final_state: dict[str, Any],
) -> None:
    """Persist grounded entities and the full answer artifact once per run."""
    if not runtime_context.ledger_key:
        return
    from app.services.ai.rag_dialog_ledger import (
        append_turn,
        build_snapshot_from_evidence_records,
    )

    contract = dict(final_state.get("turn_contract") or runtime_context.turn_contract or {})
    output = dict(contract.get("output") or {})
    snapshot = build_snapshot_from_evidence_records(
        user_text=str(final_state.get("user_text") or ""),
        evidence_ids=[str(item) for item in (final_state.get("evidence_ids") or [])],
        records=dict(final_state.get("evidence_records") or {}),
        target_post_id=str(final_state.get("post_id") or run.post_id or "") or None,
        answer_text=str(final_state.get("answer_text") or ""),
        artifact_kind=str(output.get("kind") or "assistant_artifact"),
        turn_id=str(run.id),
        turn_contract=contract,
    )
    await append_turn(
        session,
        user_id=run.user_id,
        chat_key=runtime_context.ledger_key,
        snapshot=snapshot,
    )


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
    # Commit each event as it's produced so the /events/ SSE reader (a separate
    # session that only sees committed rows) streams live progress — the
    # activity indicator's step phrase, and the answer, appear as the graph
    # runs instead of all at once when the whole task finally commits. The
    # executor's session is dedicated to events + run status (graph nodes use
    # their own sessions from RuntimeContext.session_factory), so committing
    # mid-run never persists a partial graph state. Append is its own advisory-
    # locked sequence allocation, so per-event commits stay ordered.
    await session.commit()
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
    contract_budgets = runtime_context.turn_contract.get("budgets") or {}
    hard_deadline_s = min(
        runtime_context.settings.rag_agent_deadline_s,
        float(contract_budgets.get("hard_deadline_ms") or 0) / 1000
        if contract_budgets.get("hard_deadline_ms")
        else runtime_context.settings.rag_agent_deadline_s,
    )
    runtime_context.deadline_monotonic = time.monotonic() + hard_deadline_s
    runtime_context.soft_deadline_monotonic = time.monotonic() + (
        float(contract_budgets.get("soft_deadline_ms") or hard_deadline_s * 1000) / 1000
    )
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
            "dialog_context": runtime_context.dialog_context,
            "dialog_ledger": runtime_context.dialog_ledger,
            "turn_contract": runtime_context.turn_contract,
            **(configurable or {}),
        }
    }
    contract_max_steps = int(runtime_context.turn_contract.get("max_steps") or 0)
    max_steps = runtime_context.settings.rag_agent_max_steps
    if contract_max_steps > 0:
        max_steps = min(max_steps, contract_max_steps)
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
        "max_steps": max_steps,
        "no_progress_count": 0,
        "turn_contract": dict(runtime_context.turn_contract),
        "target_contract": dict(runtime_context.turn_contract.get("target_contract") or {}),
        "resolution_events": list(
            (runtime_context.turn_contract.get("target_contract") or {}).get("resolution_events") or []
        ),
        "search_ledger": [],
        "finish_retrieval_attempted": False,
        "validator_events": [],
        "phase5_enabled": bool(
            runtime_context.settings.agent_planner_phase5_enabled
            and runtime_context.turn_contract.get("version") == 2
        ),
        "planner_calls_used": 0,
        "search_calls_used": 0,
        "deep_reads_used": 0,
        "tool_calls_used": 0,
        "planner_invalid_count": 0,
        "sufficiency": {},
        "deadline_exhausted": False,
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
    # One shared httpx.AsyncClient for all LLM calls in this run — avoids
    # re-establishing TLS per call (was one AsyncClient per call before).
    # budget.py injects it via ctx.llm_client; llm.py won't close it because
    # owns_client=False when a client is passed in.
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as llm_client:
        runtime_context.llm_client = llm_client
        try:
            # version="v2" keeps interrupts in a dedicated "interrupts" field on
            # "values" events instead of mixing a raw, non-JSON-serializable
            # Interrupt object into the state dict (v1's "__interrupt__" key) —
            # see agent-runtime-remaining.md bugfix pass for the crash v1 caused.
            async for event in graph.astream(
                graph_input,
                cfg,
                stream_mode=["values", "updates", "custom"],
                version="v2",
            ):
                mode = event["type"]
                data = event["data"]
                if mode == "custom" and isinstance(data, dict):
                    await _emit_answer_partial(session, run_id=run.id, data=data)
                elif mode == "values" and isinstance(data, dict):
                    final_state = data
                    await emit_run_event(
                        session,
                        run_id=run.id,
                        event_type="graph_state",
                        payload={
                            "status": data.get("status"),
                            "step_count": data.get("step_count"),
                            "stopped_reason": data.get("stopped_reason"),
                        },
                    )
                    interrupt_payload = _extract_interrupt(event.get("interrupts") or ())
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
                elif mode == "updates" and isinstance(data, dict):
                    workspace_step = _workspace_step_payload(data)
                    if workspace_step is not None:
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="workspace_step",
                            payload=workspace_step,
                        )
                    planner_step = _planner_step_payload(data)
                    if planner_step is not None:
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="planner_step",
                            payload=planner_step,
                        )
                    tool_outcome = _tool_outcome_payload(data)
                    if tool_outcome is not None:
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="tool_result",
                            payload=tool_outcome,
                        )
            status = str(final_state.get("status") or "completed")
            if run.status == "interrupted":
                status = "interrupted"
            elif status not in {"failed", "cancelled"}:
                status = "completed"
            if status == "completed":
                await _persist_turn_memory(
                    session,
                    run=run,
                    runtime_context=runtime_context,
                    final_state=final_state,
                )
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
                        "output_schema": final_state.get("output_schema") or "",
                        "output_validation": final_state.get("output_validation") or {},
                    },
                )
            await _emit_llm_metrics(
                session,
                run_id=run.id,
                runtime_context=runtime_context,
                started_at=started_at,
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
            await _emit_llm_metrics(
                session,
                run_id=run.id,
                runtime_context=runtime_context,
                started_at=started_at,
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
            await _emit_llm_metrics(
                session,
                run_id=run.id,
                runtime_context=runtime_context,
                started_at=started_at,
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

    started_at = time.perf_counter()
    await ensure_checkpointer_ready()
    graph = get_compiled_workspace_graph()
    # Resume must carry runtime_context — nodes downstream of the interrupt
    # (research/answer) read it from configurable and would otherwise KeyError
    # (agent-runtime-sprints §1.5).
    if runtime_context is None:
        runtime_context = await rebuild_runtime_context_for_run(session, run)
    runtime_context.llm_metrics.clear()
    # Fresh wall-clock budget for the resumed leg (agent-runtime-sprints §6).
    contract_budgets = runtime_context.turn_contract.get("budgets") or {}
    hard_deadline_s = min(
        runtime_context.settings.rag_agent_deadline_s,
        float(contract_budgets.get("hard_deadline_ms") or 0) / 1000
        if contract_budgets.get("hard_deadline_ms")
        else runtime_context.settings.rag_agent_deadline_s,
    )
    runtime_context.deadline_monotonic = time.monotonic() + hard_deadline_s
    runtime_context.soft_deadline_monotonic = time.monotonic() + (
        float(contract_budgets.get("soft_deadline_ms") or hard_deadline_s * 1000) / 1000
    )
    cfg = {
        "configurable": {
            "thread_id": str(run.id),
            "runtime_context": runtime_context,
            "dialog_context": runtime_context.dialog_context,
            "dialog_ledger": runtime_context.dialog_ledger,
            "turn_contract": runtime_context.turn_contract,
        }
    }
    final_state: dict[str, Any] = {}
    pending_interrupt: dict[str, Any] | None = None
    async for event in graph.astream(
        Command(resume=resume_value),
        cfg,
        stream_mode=["values", "updates", "custom"],
        version="v2",
    ):
        mode = event["type"]
        data = event["data"]
        if mode == "custom" and isinstance(data, dict):
            await _emit_answer_partial(session, run_id=run.id, data=data)
        elif mode == "values" and isinstance(data, dict):
            final_state = data
            interrupt_payload = _extract_interrupt(event.get("interrupts") or ())
            if interrupt_payload is not None:
                pending_interrupt = interrupt_payload
        elif mode == "updates" and isinstance(data, dict):
            workspace_step = _workspace_step_payload(data)
            if workspace_step is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="workspace_step",
                    payload=workspace_step,
                )
            planner_step = _planner_step_payload(data)
            if planner_step is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="planner_step",
                    payload=planner_step,
                )
            tool_outcome = _tool_outcome_payload(data)
            if tool_outcome is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="tool_result",
                    payload=tool_outcome,
                )
    status = "interrupted" if pending_interrupt else str(
        final_state.get("status") or "completed"
    )
    if status not in {"interrupted", "failed", "cancelled"}:
        status = "completed"
    if status == "completed":
        await _persist_turn_memory(
            session,
            run=run,
            runtime_context=runtime_context,
            final_state=final_state,
        )
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
                "output_schema": final_state.get("output_schema") or "",
                "output_validation": final_state.get("output_validation") or {},
            },
        )
    await _emit_llm_metrics(
        session,
        run_id=run.id,
        runtime_context=runtime_context,
        started_at=started_at,
    )
    await emit_run_event(
        session,
        run_id=run.id,
        event_type="graph_resumed",
        payload=resume_value,
    )
    await session.commit()
    return final_state
