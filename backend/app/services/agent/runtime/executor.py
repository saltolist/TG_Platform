"""Execute agent runs with graph, events, and interrupt handling."""

from __future__ import annotations

import logging
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from langgraph.types import Command
from sqlalchemy import select

from app.db.models import AgentEvent, AgentRun, User
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.budget import RunDeadlineExceeded
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.tool_contracts import typed_tool_error
from app.services.agent.runtime.observability import (
    AGENT_DURATION,
    AGENT_DURATION_BY_MODE,
    AGENT_EMPTY_PACK,
    AGENT_MESSAGE_CONTEXT_ITEMS,
    AGENT_PLAN_DECISIONS,
    AGENT_PLANNER_NOOPS,
    AGENT_REFERENT_CONFIDENCE,
    AGENT_ROUTES,
    AGENT_RETRIEVAL_SEARCHES,
    AGENT_REUSED_CONTEXT_REFS,
    AGENT_USED_CONTEXT_REFS,
    AGENT_SELECTOR_ASSESSMENT_COVERAGE,
    AGENT_SELECTOR_REGISTRY_SIZE,
    AGENT_UNIFIED_READY_BLOCKS,
    AGENT_UNIFIED_RUNS,
    AGENT_EVIDENCE_FIDELITY,
    AGENT_CLARIFICATIONS,
    AGENT_LEGACY_RESOLVER,
    AGENT_CONTEXT_MISMATCH,
    AGENT_INTERRUPTS,
    AGENT_RUNS,
    AGENT_STEPS,
    AGENT_STOPPED_REASON,
    AGENT_TOOL_CALLS,
    AGENT_DUPLICATE_SUPPRESSIONS,
    normalize_phase_timings,
    observe_run_phases,
)
from app.services.agent.runtime.replay import capture_unified_rollout_trace
from app.services.agent.runtime.rollout import runtime_rollout_flags
from app.services.agent.runtime.trace import render_run_trace
from app.services.agent.runtime.workspace_graph import get_compiled_workspace_graph
from app.services.ai.llm import _HTTP_TIMEOUT

logger = logging.getLogger(__name__)


def is_retryable_run_exception(exc: BaseException) -> bool:
    """Return whether Celery may transparently resume this run."""

    return isinstance(exc, httpx.TransportError)


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


def _sufficiency_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    update = data.get("verify")
    if not isinstance(update, dict):
        return None
    sufficiency = update.get("sufficiency")
    if not isinstance(sufficiency, dict) or not sufficiency:
        return None
    return {
        **sufficiency,
        "schema": "workspace.sufficiency-result/v1",
        "evidence_ids": [str(item) for item in update.get("evidence_ids") or []],
    }


def _evidence_lineage_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    update = data.get("pack")
    if not isinstance(update, dict):
        return None
    pack = update.get("evidence_pack")
    if not isinstance(pack, dict) or not pack:
        return None
    items = pack.get("items") or pack.get("evidence") or []
    return {
        "schema": pack.get("schema") or update.get("evidence_pack_schema"),
        "evidence_ids": [str(item) for item in update.get("evidence_ids") or []],
        "lineage": [
            {
                "evidence_id": item.get("evidence_id") or item.get("id"),
                "kind": item.get("kind"),
                "source_ref": item.get("source_ref"),
                "source_requirement_ids": item.get("source_requirement_ids") or [],
                "source_intent_ids": item.get("source_intent_ids") or [],
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


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


def _resume_state_ref(state: dict[str, Any]) -> dict[str, Any]:
    contract = dict(state.get("turn_contract") or {})
    target_contract = dict(state.get("target_contract") or contract.get("target_contract") or {})
    target_ids = sorted(
        str(item.get("id") or "")
        for item in target_contract.get("targets") or []
        if isinstance(item, dict) and item.get("id")
    )
    evidence_ids = sorted(str(item) for item in state.get("evidence_ids") or [])
    canonical = {
        "run_id": str(state.get("run_id") or ""),
        "contract_revision": contract.get("revision"),
        "target_ids": target_ids,
        "evidence_ids": evidence_ids,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:20]
    return {**canonical, "state_fingerprint": digest}


def _restore_resume_continuity(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Keep authoritative research state across an approval interruption."""

    restored = dict(after)
    for field in ("turn_contract", "target_contract", "resolution_events"):
        if before.get(field):
            restored[field] = before[field]
    previous_records = before.get("evidence_records")
    if isinstance(previous_records, dict):
        restored["evidence_records"] = {
            **previous_records,
            **dict(restored.get("evidence_records") or {}),
        }
    previous_ids = [str(item) for item in before.get("evidence_ids") or []]
    current_ids = [str(item) for item in restored.get("evidence_ids") or []]
    if previous_ids:
        restored["evidence_ids"] = list(dict.fromkeys([*previous_ids, *current_ids]))
    for field in ("evidence_pack", "evidence_pack_schema", "search_ledger", "sufficiency"):
        previous = before.get(field)
        current = restored.get(field)
        if previous and not current:
            restored[field] = previous
    return restored


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
    call_type = str((final_state.get("tool_call") or {}).get("type") or final_state.get("current_tool") or "unknown")
    AGENT_ROUTES.labels(call_type).inc()
    search_rows = list(final_state.get("search_ledger") or ())
    for row in search_rows:
        if isinstance(row, dict) and str(row.get("tool") or "") in {"SearchNodes", "SearchObjectChunks"}:
            AGENT_RETRIEVAL_SEARCHES.labels(str(row.get("tool"))).inc()
    for decision in final_state.get("plan_decisions") or ():
        if isinstance(decision, dict):
            AGENT_PLAN_DECISIONS.labels(
                str(decision.get("route") or "unknown"),
                str(decision.get("reason_code") or "unknown"),
            ).inc()
    for _ in range(int(final_state.get("planner_noop_count") or 0)):
        AGENT_PLANNER_NOOPS.inc()
    plan = final_state.get("material_plan") or {}
    assessments = [
        item for item in plan.get("assessments") or () if isinstance(item, dict)
    ]
    selector_steps = [
        item
        for item in final_state.get("planner_steps") or ()
        if isinstance(item, dict)
        and str(item.get("schema") or "") == "workspace.context-selector/v2"
    ]
    selector_step = selector_steps[-1] if selector_steps else {}
    selector_schema = "workspace.context-selector/v2" if selector_steps else "none"
    pack = final_state.get("evidence_pack") or {}
    pack_schema = str(pack.get("schema") or "none")
    coverage = str(pack.get("coverage") or plan.get("coverage") or "unknown")
    if (
        selector_steps
        or pack_schema == "workspace.evidence-pack/v2"
        or str(plan.get("schema") or "") == "workspace.material-plan/v2"
    ):
        AGENT_UNIFIED_RUNS.labels(selector_schema, pack_schema, coverage).inc()
    visible_refs = {
        str(item)
        for item in selector_step.get("visible_refs") or ()
        if str(item or "")
    }
    if not visible_refs and selector_steps:
        visible_refs = {
            str(item.get("ref") or "")
            for item in selector_step.get("assessments") or ()
            if isinstance(item, dict) and item.get("ref")
        }
    if visible_refs:
        AGENT_SELECTOR_REGISTRY_SIZE.observe(len(visible_refs))
        assessed_refs = {
            str(item.get("ref") or "") for item in assessments if item.get("ref")
        }
        AGENT_SELECTOR_ASSESSMENT_COVERAGE.observe(
            len(assessed_refs & visible_refs) / len(visible_refs)
        )
    for gap in final_state.get("evidence_gaps") or ():
        if isinstance(gap, dict) and gap.get("blocks_ready"):
            AGENT_UNIFIED_READY_BLOCKS.labels(str(gap.get("kind") or "unknown")).inc()
    AGENT_REUSED_CONTEXT_REFS.observe(len(final_state.get("known_context_refs") or ()))
    AGENT_USED_CONTEXT_REFS.observe(len(final_state.get("used_context_refs") or ()))
    for item in pack.get("items") or ():
        if isinstance(item, dict):
            AGENT_EVIDENCE_FIDELITY.labels(str(item.get("fidelity") or "unknown")).inc()
    if str(final_state.get("stopped_reason") or "") in {"referent_ambiguity", "clarification"}:
        AGENT_CLARIFICATIONS.inc()
    manifest = final_state.get("message_context_manifest") or {}
    for kind, field in (
        ("considered_evidence", "considered_context"),
        ("cited_evidence", "cited_evidence"),
        ("context_ref", "context_refs"),
    ):
        AGENT_MESSAGE_CONTEXT_ITEMS.labels(kind).observe(len(manifest.get(field) or ()))
    target_contract = final_state.get("target_contract") or {}
    targets = target_contract.get("targets") or ()
    AGENT_MESSAGE_CONTEXT_ITEMS.labels("target_set").observe(len(targets))
    resolution = target_contract.get("referent_resolution") or {}
    references = resolution.get("references") or ()
    selected = [item for ref in references if isinstance(ref, dict) for item in ref.get("target_ids") or ()]
    AGENT_MESSAGE_CONTEXT_ITEMS.labels("selected_target").observe(len(selected))
    AGENT_MESSAGE_CONTEXT_ITEMS.labels("unresolved_reference").observe(
        len(resolution.get("unresolved") or ())
    )
    for reference in references:
        if isinstance(reference, dict):
            AGENT_REFERENT_CONFIDENCE.observe(float(reference.get("confidence") or 0.0))
    if references:
        AGENT_LEGACY_RESOLVER.inc()
    manifest_refs = {
        str(item.get("ref") or "")
        for item in manifest.get("context_refs") or ()
        if isinstance(item, dict)
    }
    from app.services.agent.runtime.message_context import supplied_object_refs

    pack_refs = supplied_object_refs(final_state.get("evidence_pack") or {})
    if manifest_refs and not manifest_refs.issubset(pack_refs):
        AGENT_CONTEXT_MISMATCH.inc()


def _llm_metrics_payload(runtime_context: RuntimeContext, *, duration_ms: float) -> dict[str, Any]:
    calls = [dict(item) for item in runtime_context.llm_metrics]
    contract = dict(runtime_context.turn_contract or {})
    execution_mode = str(contract.get("execution_mode") or "unknown")
    phase_timings = normalize_phase_timings(getattr(runtime_context, "phase_timings", {}))
    try:
        from app.tasks.async_runtime import runtime_status

        worker_state = runtime_status()
    except Exception:  # pragma: no cover - optional outside Celery
        worker_state = {}
    worker_warm = bool(worker_state.get("ready"))
    return {
        "duration_ms": round(duration_ms, 1),
        "time_to_final_ms": round(
            duration_ms + float(phase_timings.get("queue_wait") or 0), 1
        ),
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in calls),
        "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in calls),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in calls),
        "token_method": "chars_div_4_estimate",
        "calls": calls,
        "schema": "workspace.run-metrics/v1",
        "execution_mode": execution_mode,
        "phase_timings_ms": phase_timings,
        "worker_warm": worker_warm,
        "worker_status": worker_state.get("status") or "unknown",
        "cold_start_ms": worker_state.get("worker_init_ms"),
        "embedding_init_ms": worker_state.get("embedding_init_ms"),
        "first_embed_ms": worker_state.get("first_embed_ms"),
        "checkpointer_init_ms": worker_state.get("checkpointer_init_ms"),
        "graph_compile_ms": worker_state.get("graph_compile_ms"),
        "db_timings_ms": {},
    }


def _runtime_rollout_state(runtime_context: RuntimeContext) -> dict[str, bool]:
    rollout_flags = runtime_rollout_flags(
        runtime_context.settings,
        contract_version=int(runtime_context.turn_contract.get("version") or 0),
    )
    phase5_enabled = bool(
        runtime_context.settings.agent_planner_phase5_enabled
        and int(runtime_context.turn_contract.get("version") or 0) >= 2
    )
    return {
        "adaptive_evidence_depth_enabled": bool(
            phase5_enabled
            and (
                getattr(
                    runtime_context.settings,
                    "agent_adaptive_evidence_depth_v1_enabled",
                    False,
                )
                or rollout_flags["unified_selector"]
            )
        ),
        "unified_selector_enabled": bool(
            phase5_enabled and rollout_flags["unified_selector"]
        ),
        "verified_pack_boundary_enabled": bool(
            phase5_enabled and rollout_flags["verified_pack_boundary"]
        ),
        "planner_policy_enabled": bool(
            phase5_enabled and rollout_flags["planner_policy"]
        ),
        "recall_verifier_enabled": bool(
            phase5_enabled
            and rollout_flags["unified_selector"]
            and getattr(
                runtime_context.settings,
                "agent_recall_verifier_v1_enabled",
                False,
            )
        ),
        "recall_verifier_shadow": bool(
            getattr(runtime_context.settings, "agent_recall_verifier_v1_shadow", True)
        ),
    }


def _merge_llm_metrics_payloads(
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge durable retry attempts with the terminal in-memory ledger."""

    if not payloads:
        return {}
    merged = dict(payloads[-1])
    calls = [
        dict(call)
        for payload in payloads
        for call in payload.get("calls") or ()
        if isinstance(call, dict)
    ]
    phase_timings: dict[str, float] = {}
    for payload in payloads:
        for phase, value in (payload.get("phase_timings_ms") or {}).items():
            try:
                phase_timings[str(phase)] = phase_timings.get(str(phase), 0.0) + float(
                    value
                )
            except (TypeError, ValueError):
                continue
    merged.update(
        {
            "duration_ms": round(
                sum(float(payload.get("duration_ms") or 0.0) for payload in payloads),
                1,
            ),
            "time_to_final_ms": round(
                sum(
                    float(
                        payload.get("time_to_final_ms")
                        or payload.get("duration_ms")
                        or 0.0
                    )
                    for payload in payloads
                ),
                1,
            ),
            "llm_calls": len(calls),
            "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in calls),
            "completion_tokens": sum(
                int(call.get("completion_tokens") or 0) for call in calls
            ),
            "total_tokens": sum(int(call.get("total_tokens") or 0) for call in calls),
            "calls": calls,
            "phase_timings_ms": {
                phase: round(value, 1) for phase, value in phase_timings.items()
            },
            "attempt_count": len(payloads),
        }
    )
    return merged


async def _emit_llm_metrics(
    session,
    *,
    run_id: uuid.UUID,
    runtime_context: RuntimeContext,
    started_at: float,
    final_state: dict[str, Any] | None = None,
) -> None:
    terminal_payload = _llm_metrics_payload(
        runtime_context,
        duration_ms=(time.perf_counter() - started_at) * 1000,
    )
    attempt_payloads = list(
        await session.scalars(
            select(AgentEvent.payload)
            .where(
                AgentEvent.run_id == run_id,
                AgentEvent.event_type == "run_attempt_metrics",
            )
            .order_by(AgentEvent.sequence)
        )
    )
    payload = _merge_llm_metrics_payloads(
        [
            *(
                dict(item)
                for item in attempt_payloads
                if isinstance(item, dict)
            ),
            terminal_payload,
        ]
    )
    await emit_run_event(
        session,
        run_id=run_id,
        event_type="run_metrics",
        payload=payload,
    )
    unified_observability_requested = any(
        bool(getattr(runtime_context.settings, name, False))
        for name in (
            "agent_unified_catalog_v1_enabled",
            "agent_typed_requirements_v1_enabled",
            "agent_unified_selector_v1_enabled",
            "agent_verified_pack_boundary_v1_enabled",
            "agent_planner_policy_v1_enabled",
        )
    )
    if final_state is not None and unified_observability_requested:
        await emit_run_event(
            session,
            run_id=run_id,
            event_type="unified_rollout_trace",
            payload=capture_unified_rollout_trace(final_state, run_metrics=payload),
        )


def _phase_for_node(node: str) -> str:
    return {
        "bootstrap": "bootstrap",
        "workspace_agent": "bootstrap",
        "seed": "discovery",
        "planner": "planner",
        "tool": "tool",
        "verify": "sufficiency",
        "pack": "sufficiency",
        "answer": "answer",
        "build_action_proposal": "action",
        "build_media_proposal": "action",
        "resolve_schedule_time": "action",
        "media_enqueue": "action",
        "media_wait": "action",
        "media_attach_proposal": "action",
    }.get(node, "other")


def _phase_for_update(data: dict[str, Any], node: str) -> str:
    if node != "tool":
        return _phase_for_node(node)
    outcome = _tool_outcome_payload(data) or {}
    tool = str(outcome.get("tool") or "")
    if tool.startswith("Search") or tool.startswith("List") or tool == "ResolveObjects":
        return "discovery"
    if tool.startswith("Open") or tool.startswith("Hydrate") or tool in {
        "GetPostAnalytics",
        "ReadAnalytics",
    }:
        return "deep_read"
    return "tool"


def _record_tool_observation(payload: dict[str, Any]) -> None:
    tool = str(payload.get("tool") or "unknown")
    raw_error = str(
        ((payload.get("typed_error") or {}).get("code") if isinstance(payload.get("typed_error"), dict) else "")
        or payload.get("error")
        or ""
    )
    error = typed_tool_error(raw_error, "") if raw_error else None
    error_code = error.code if error else "none"
    cache_hit = bool(payload.get("cache_hit") or payload.get("cached"))
    AGENT_TOOL_CALLS.labels(tool, error_code, "true" if cache_hit else "false").inc()
    if cache_hit:
        AGENT_DUPLICATE_SUPPRESSIONS.inc()


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


async def _persist_message_context(
    session,
    *,
    run: AgentRun,
    runtime_context: RuntimeContext,
    final_state: dict[str, Any],
) -> dict[str, Any]:
    """Build and persist the authoritative manifest before the final commit."""
    if not getattr(runtime_context.settings, "dialog_message_context_manifest_v1", True):
        return {}
    from app.services.agent.runtime.message_context import (
        build_message_context_manifest,
        persist_message_context,
    )

    contract = dict(final_state.get("turn_contract") or runtime_context.turn_contract or {})
    unresolved = {
        str(item)
        for item in (
            *tuple(final_state.get("unresolved") or ()),
            *tuple((final_state.get("evidence_pack") or {}).get("unresolved") or ()),
            *tuple((final_state.get("sufficiency") or {}).get("open_requirements") or ()),
        )
    }
    stale_refs: list[dict[str, Any]] = [
        dict(item)
        for item in final_state.get("stale_refs") or ()
        if isinstance(item, dict)
    ]
    for source in contract.get("source_requirements") or ():
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "")
        target_ids = [str(item) for item in (source.get("scope") or {}).get("target_ids") or ()]
        source_missing = source_id in unresolved or any(
            source_id and source_id in item for item in unresolved
        )
        if not source_missing:
            continue
        kind = "post" if source.get("kind") == "posts" else "note" if source.get("kind") == "notes" else "object"
        stale_refs.extend(
            {"ref": f"{kind}:{identifier}", "kind": kind, "reason": "missing_or_stale_source"}
            for identifier in target_ids
        )

    manifest = build_message_context_manifest(
        message_id=str(getattr(run, "assistant_message_id", "") or run.id),
        run_id=str(run.id),
        source_turn_id=str(run.id),
        evidence_pack=dict(final_state.get("evidence_pack") or {}),
        claims=[item for item in final_state.get("claims") or () if isinstance(item, dict)],
        used_context_refs=[str(item) for item in final_state.get("used_context_refs") or ()],
        target_contract=dict(
            final_state.get("target_contract")
            or (final_state.get("turn_contract") or {}).get("target_contract")
            or {}
        ),
        answer_text=str(final_state.get("answer_text") or ""),
        stale_refs=stale_refs,
    )
    await persist_message_context(
        session,
        user_id=run.user_id,
        ledger_key=runtime_context.ledger_key,
        manifest=manifest,
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    final_state["message_context_manifest"] = payload
    return payload


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
    defer_retryable_failures: bool = False,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    runtime_context.phase_timings.clear()
    runtime_context.phase_timings["queue_wait"] = max(
        0.0, (datetime.now(timezone.utc) - created_at).total_seconds() * 1000
    )
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
        "assistant_message_id": str(getattr(run, "assistant_message_id", "") or run.id),
        "user_id": str(user.id),
        "user_text": user_text,
        "scope": run.scope,
        "post_id": run.post_id,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "used_context_refs": [],
        "message_context_manifest": {},
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
            and int(runtime_context.turn_contract.get("version") or 0) >= 2
        ),
        "planner_calls_used": 0,
        "search_calls_used": 0,
        "deep_reads_used": 0,
        "tool_calls_used": 0,
        "planner_invalid_count": 0,
        "sufficiency": {},
        "evidence_gaps": [],
        "soft_deadline_reached": False,
        "deadline_exhausted": False,
    }
    await emit_run_event(
        session,
        run_id=run.id,
        event_type="graph_started",
        payload={
            "schema": "workspace.run-trace/v1",
            "user_text": user_text[:200],
            "execution_mode": runtime_context.turn_contract.get("execution_mode") or "unknown",
            "contract_revision": runtime_context.turn_contract.get("revision"),
            "target_resolution": [
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "resolved_by": item.get("resolved_by"),
                    "confidence": item.get("confidence"),
                }
                for item in (runtime_context.turn_contract.get("target_contract") or {}).get("targets") or []
                if isinstance(item, dict)
            ],
            "source_requirement_ids": [
                str(item.get("source_id") or "")
                for item in runtime_context.turn_contract.get("source_requirements") or []
                if isinstance(item, dict) and item.get("source_id")
            ],
        },
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
    last_graph_update_at = time.perf_counter()
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
                        interrupt_payload = {
                            **interrupt_payload,
                            "resume_state": _resume_state_ref(data),
                        }
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
                    now = time.perf_counter()
                    node_names = [str(key) for key, value in data.items() if isinstance(value, dict)]
                    if node_names:
                        phase = _phase_for_update(data, node_names[0])
                        runtime_context.phase_timings[phase] = (
                            runtime_context.phase_timings.get(phase, 0.0)
                            + (now - last_graph_update_at) * 1000
                        )
                        last_graph_update_at = now
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
                        _record_tool_observation(tool_outcome)
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="tool_result",
                            payload=tool_outcome,
                        )
                    sufficiency = _sufficiency_payload(data)
                    if sufficiency is not None:
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="sufficiency",
                            payload=sufficiency,
                        )
                    lineage = _evidence_lineage_payload(data)
                    if lineage is not None:
                        await emit_run_event(
                            session,
                            run_id=run.id,
                            event_type="evidence_lineage",
                            payload=lineage,
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
                await _persist_message_context(
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
                        "message_context_manifest": final_state.get("message_context_manifest") or {},
                    },
                )
            await _emit_llm_metrics(
                session,
                run_id=run.id,
                runtime_context=runtime_context,
                started_at=started_at,
                final_state=final_state,
            )
            await emit_run_event(
                session,
                run_id=run.id,
                event_type="run_interrupted" if status == "interrupted" else "run_completed",
                payload={"status": status},
            )
            await session.commit()
            AGENT_RUNS.labels(status).inc()
            total_seconds = time.perf_counter() - started_at
            AGENT_DURATION.observe(total_seconds)
            metrics_payload = _llm_metrics_payload(
                runtime_context, duration_ms=total_seconds * 1000
            )
            execution_mode = str(metrics_payload["execution_mode"])
            worker_warm = bool(metrics_payload["worker_warm"])
            AGENT_DURATION_BY_MODE.labels(
                execution_mode, "warm" if worker_warm else "cold"
            ).observe(total_seconds)
            observe_run_phases(
                runtime_context.phase_timings,
                execution_mode=execution_mode,
                worker_warm=worker_warm,
            )
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
                final_state=final_state,
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
            if defer_retryable_failures and is_retryable_run_exception(exc):
                logger.warning(
                    "Agent run %s hit a retryable transport failure; terminal status deferred",
                    run.id,
                )
                retry_run_id = run.id
                attempt_payload = _llm_metrics_payload(
                    runtime_context,
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
                attempt_payload["terminal_reason"] = "retryable_transport_failure"
                await session.rollback()
                await emit_run_event(
                    session,
                    run_id=retry_run_id,
                    event_type="run_attempt_metrics",
                    payload=attempt_payload,
                )
                await session.commit()
                raise
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
                final_state=final_state,
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
    runtime_context.phase_timings.clear()
    updated_at = run.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    runtime_context.phase_timings["approval_wait"] = max(
        0.0, (datetime.now(timezone.utc) - updated_at).total_seconds() * 1000
    )
    resume_state_before = _resume_state_ref(dict(run.snapshot or {}))
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
    resume_rollout_update = _runtime_rollout_state(runtime_context)
    final_state: dict[str, Any] = {}
    pending_interrupt: dict[str, Any] | None = None
    last_graph_update_at = time.perf_counter()
    async for event in graph.astream(
        Command(resume=resume_value, update=resume_rollout_update),
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
                pending_interrupt = {
                    **interrupt_payload,
                    "resume_state": _resume_state_ref(data),
                }
        elif mode == "updates" and isinstance(data, dict):
            now = time.perf_counter()
            node_names = [str(key) for key, value in data.items() if isinstance(value, dict)]
            if node_names:
                phase = _phase_for_update(data, node_names[0])
                runtime_context.phase_timings[phase] = (
                    runtime_context.phase_timings.get(phase, 0.0)
                    + (now - last_graph_update_at) * 1000
                )
                last_graph_update_at = now
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
                _record_tool_observation(tool_outcome)
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="tool_result",
                    payload=tool_outcome,
                )
            sufficiency = _sufficiency_payload(data)
            if sufficiency is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="sufficiency",
                    payload=sufficiency,
                )
            lineage = _evidence_lineage_payload(data)
            if lineage is not None:
                await emit_run_event(
                    session,
                    run_id=run.id,
                    event_type="evidence_lineage",
                    payload=lineage,
                )
    status = "interrupted" if pending_interrupt else str(
        final_state.get("status") or "completed"
    )
    final_state = _restore_resume_continuity(dict(run.snapshot or {}), final_state)
    if status not in {"interrupted", "failed", "cancelled"}:
        status = "completed"
    if status == "completed":
        await _persist_turn_memory(
            session,
            run=run,
            runtime_context=runtime_context,
            final_state=final_state,
        )
        await _persist_message_context(
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
                "message_context_manifest": final_state.get("message_context_manifest") or {},
            },
        )
    await _emit_llm_metrics(
        session,
        run_id=run.id,
        runtime_context=runtime_context,
        started_at=started_at,
        final_state=final_state,
    )
    await emit_run_event(
        session,
        run_id=run.id,
        event_type="graph_resumed",
        payload={
            "decision": resume_value.get("decision"),
            "proposal_id": resume_value.get("proposal_id"),
            "resume_state_before": resume_state_before,
            "resume_state_after": _resume_state_ref(final_state),
            "status": status,
        },
    )
    await session.commit()
    total_seconds = time.perf_counter() - started_at
    metrics_payload = _llm_metrics_payload(runtime_context, duration_ms=total_seconds * 1000)
    execution_mode = str(metrics_payload["execution_mode"])
    worker_warm = bool(metrics_payload["worker_warm"])
    AGENT_RUNS.labels(status).inc()
    AGENT_DURATION.observe(total_seconds)
    AGENT_DURATION_BY_MODE.labels(
        execution_mode, "warm" if worker_warm else "cold"
    ).observe(total_seconds)
    observe_run_phases(
        runtime_context.phase_timings,
        execution_mode=execution_mode,
        worker_warm=worker_warm,
    )
    return final_state
