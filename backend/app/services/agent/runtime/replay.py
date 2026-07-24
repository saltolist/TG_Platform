"""Deterministic trace replay summaries and old/new comparisons.

The replay layer intentionally consumes persisted event-shaped mappings, so a
production trace export and a fixture use the same code. It does not rerun an
LLM or retain hidden reasoning; it compares observable decisions, timings,
errors, and evidence coverage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.agent.runtime.rollout import SELECTOR_SCHEMA_V2


def _payload(event: Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        value = event.get("payload")
    else:
        value = getattr(event, "payload", None)
    return value if isinstance(value, Mapping) else {}


def _event_type(event: Any) -> str:
    if isinstance(event, Mapping):
        return str(event.get("event_type") or "")
    return str(getattr(event, "event_type", "") or "")


def summarize_trace(events: Sequence[Any]) -> dict[str, Any]:
    """Extract stable operational facts from an agent event chain."""

    tool_calls = 0
    cached_tools = 0
    tool_errors = 0
    planner_steps = 0
    evidence_ids: set[str] = set()
    phase_timings: dict[str, float] = {}
    metrics: Mapping[str, Any] = {}
    status = "unknown"
    execution_mode = "unknown"
    worker_warm = False
    for event in events:
        event_type = _event_type(event)
        payload = _payload(event)
        if event_type == "tool_result":
            tool_calls += 1
            if payload.get("cache_hit") or payload.get("cached"):
                cached_tools += 1
            if payload.get("error") or (payload.get("typed_error") or {}).get("code"):
                tool_errors += 1
            evidence_ids.update(str(item) for item in payload.get("record_ids") or [])
        elif event_type == "planner_step":
            planner_steps += 1
        elif event_type == "answer":
            evidence_ids.update(str(item) for item in payload.get("evidence_ids") or [])
        elif event_type == "run_metrics":
            metrics = payload
            status = str(payload.get("status") or status)
            execution_mode = str(payload.get("execution_mode") or execution_mode)
            worker_warm = bool(payload.get("worker_warm"))
            phase_timings = {
                str(key): float(value)
                for key, value in (payload.get("phase_timings_ms") or {}).items()
                if isinstance(value, (int, float))
            }
        elif event_type in {"run_completed", "run_interrupted", "run_failed"}:
            status = str(payload.get("status") or event_type.removeprefix("run_"))
    duration_ms = float(metrics.get("duration_ms") or sum(phase_timings.values()) or 0)
    return {
        "status": status,
        "execution_mode": execution_mode,
        "worker_warm": worker_warm,
        "duration_ms": round(duration_ms, 1),
        "phase_timings_ms": phase_timings,
        "tool_calls": tool_calls,
        "cached_tools": cached_tools,
        "tool_errors": tool_errors,
        "planner_steps": planner_steps,
        "evidence_count": len(evidence_ids),
        "evidence_ids": sorted(evidence_ids),
        "schema": "workspace.trace-summary/v1",
    }


def compare_traces(old_events: Sequence[Any], new_events: Sequence[Any]) -> dict[str, Any]:
    """Compare old/new observable trajectories without comparing model prose."""

    old = summarize_trace(old_events)
    new = summarize_trace(new_events)

    def reduction(key: str) -> float:
        before = float(old.get(key) or 0)
        after = float(new.get(key) or 0)
        return round(1 - after / before, 4) if before else 0.0

    return {
        "schema": "workspace.trace-comparison/v1",
        "old": old,
        "new": new,
        "delta": {
            "duration_ms": round(float(new["duration_ms"]) - float(old["duration_ms"]), 1),
            "tool_calls": int(new["tool_calls"]) - int(old["tool_calls"]),
            "planner_steps": int(new["planner_steps"]) - int(old["planner_steps"]),
            "evidence_count": int(new["evidence_count"]) - int(old["evidence_count"]),
            "duration_reduction": reduction("duration_ms"),
            "tool_call_reduction": reduction("tool_calls"),
            "planner_step_reduction": reduction("planner_steps"),
            "quality_preserved": (
                int(new["evidence_count"]) >= int(old["evidence_count"])
                and int(new["tool_errors"]) <= int(old["tool_errors"])
            ),
        },
    }


def render_comparison_report(comparison: Mapping[str, Any]) -> str:
    old = comparison.get("old") or {}
    new = comparison.get("new") or {}
    delta = comparison.get("delta") or {}
    return "\n".join(
        [
            "Workspace Agent trace comparison",
            f"old: {old.get('duration_ms', 0)} ms, {old.get('tool_calls', 0)} tools, {old.get('planner_steps', 0)} planner steps",
            f"new: {new.get('duration_ms', 0)} ms, {new.get('tool_calls', 0)} tools, {new.get('planner_steps', 0)} planner steps",
            f"delta: duration {delta.get('duration_ms', 0)} ms, tool calls {delta.get('tool_calls', 0)}, planner steps {delta.get('planner_steps', 0)}",
            f"quality_preserved={bool(delta.get('quality_preserved'))} evidence {old.get('evidence_count', 0)} -> {new.get('evidence_count', 0)}",
        ]
    )


def replay_snapshot_fixture(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable digest of observable fixture snapshots.

    Timing telemetry remains in the baseline report; the replay digest freezes
    decisions and evidence while deliberately excluding wall-clock noise.
    """

    rows: list[dict[str, Any]] = []
    for scenario in payload.get("scenarios") or ():
        if not isinstance(scenario, Mapping):
            continue
        snapshots = scenario.get("snapshots")
        if not isinstance(snapshots, Mapping):
            continue
        canonical = json.dumps(
            snapshots, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        rows.append(
            {
                "id": str(scenario.get("id") or ""),
                "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "terminal_status": str(scenario.get("status") or "unknown"),
                "final_evidence_refs": sorted(
                    str(item)
                    for item in (snapshots.get("final_pack") or {}).get("evidence_refs") or ()
                ),
            }
        )
    aggregate = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "workspace.unified-phase0-replay/v1",
        "scenario_count": len(rows),
        "scenarios": rows,
        "digest": hashlib.sha256(aggregate.encode("utf-8")).hexdigest(),
    }


def capture_unified_rollout_trace(
    state: Mapping[str, Any],
    *,
    run_metrics: Mapping[str, Any] | None = None,
    mode: str = "active",
) -> dict[str, Any]:
    """Capture the phase-6 observable boundary without answer prose."""

    planner_steps = [
        dict(item)
        for item in state.get("planner_steps") or ()
        if isinstance(item, Mapping)
    ]
    selector_steps = [
        item for item in planner_steps if str(item.get("schema") or "") == SELECTOR_SCHEMA_V2
    ]
    selector = selector_steps[-1] if selector_steps else {}
    search_rows = [
        dict(item)
        for item in state.get("search_ledger") or ()
        if isinstance(item, Mapping)
    ]
    additive_rows = [
        item
        for item in search_rows
        if item.get("search_relation") == "additive_to_authoritative_catalog"
    ]
    metrics = dict(run_metrics or {})
    calls = [dict(item) for item in metrics.get("calls") or () if isinstance(item, Mapping)]
    answer_calls = [
        item
        for item in calls
        if "answer" in str(item.get("phase") or item.get("call_kind") or "").casefold()
    ]
    pack = dict(state.get("evidence_pack") or {})
    raw_plan = dict(state.get("material_plan") or {})
    material_plan = {
        key: raw_plan.get(key)
        for key in (
            "schema",
            "assessments",
            "source_dispositions",
            "materialization_queue",
            "runtime_trace",
            "omitted_ids",
            "gaps",
            "coverage",
            "budget",
            "budget_usage",
            "selector_failure",
        )
        if key in raw_plan
    }
    return {
        "schema": "workspace.unified-rollout-trace/v1",
        "mode": mode,
        "turn_contract": dict(state.get("turn_contract") or {}),
        "candidate_registry": [
            {
                key: item.get(key)
                for key in (
                    "ref",
                    "kind",
                    "origin",
                    "semantic_score",
                    "semantic_rank_score",
                    "parent",
                    "source_requirement_ids",
                    "source_requirement_id",
                    "available_fidelity",
                    "source_revision",
                )
                if key in item
            }
            for item in state.get("candidate_envelopes") or ()
            if isinstance(item, Mapping)
        ],
        "selector": {
            "schema": selector.get("schema"),
            "visible_refs": list(selector.get("visible_refs") or ()),
            "assessments": list(selector.get("assessments") or material_plan.get("assessments") or ()),
            "source_dispositions": list(
                selector.get("source_dispositions")
                or material_plan.get("source_dispositions")
                or ()
            ),
            "attempts": selector.get("attempts"),
        },
        "policy": {
            "decisions": [
                dict(item)
                for item in state.get("plan_decisions") or ()
                if isinstance(item, Mapping)
            ],
            "planner_noop_count": int(state.get("planner_noop_count") or 0),
        },
        "additive_search": additive_rows,
        "material_plan": material_plan,
        "final_pack": {
            "schema": pack.get("schema"),
            "evidence_ids": list(pack.get("evidence_ids") or ()),
            "items": [
                {
                    key: item.get(key)
                    for key in ("id", "source_ref", "fidelity", "provenance")
                    if key in item
                }
                for item in pack.get("items") or ()
                if isinstance(item, Mapping)
            ],
            "coverage": pack.get("coverage"),
            "coverage_by_source": dict(pack.get("coverage_by_source") or {}),
            "omissions": list(pack.get("omissions") or ()),
            "unresolved": list(pack.get("unresolved") or ()),
            "truncation": dict(pack.get("truncation") or {}),
        },
        "answer_usage": {
            "claims": [
                {
                    key: item.get(key)
                    for key in ("id", "claim_id", "evidence_ids", "source_refs")
                    if key in item
                }
                for item in state.get("claims") or ()
                if isinstance(item, Mapping)
            ],
            "used_context_refs": list(state.get("used_context_refs") or ()),
            "answer_model_calls": len(answer_calls),
        },
        "metrics": {
            "duration_ms": metrics.get("duration_ms"),
            "llm_calls": metrics.get("llm_calls"),
            "prompt_tokens": metrics.get("prompt_tokens"),
            "total_tokens": metrics.get("total_tokens"),
        },
        "lifecycle": {
            "status": state.get("status"),
            "stopped_reason": state.get("stopped_reason"),
            "checkpoint_schema": (state.get("checkpoint") or {}).get("schema")
            if isinstance(state.get("checkpoint"), Mapping)
            else None,
        },
    }


def compare_unified_shadow(
    active: Mapping[str, Any],
    shadow: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare read-only rollout traces and enforce the shadow side-effect boundary."""

    active_pack = active.get("final_pack") or {}
    shadow_pack = shadow.get("final_pack") or {}
    active_ids = {str(item) for item in active_pack.get("evidence_ids") or ()}
    shadow_ids = {str(item) for item in shadow_pack.get("evidence_ids") or ()}
    active_refs = {
        str(item.get("ref") or "")
        for item in active.get("candidate_registry") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    shadow_refs = {
        str(item.get("ref") or "")
        for item in shadow.get("candidate_registry") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    shadow_answer_calls = int((shadow.get("answer_usage") or {}).get("answer_model_calls") or 0)
    return {
        "schema": "workspace.unified-shadow-comparison/v1",
        "contract_changed": active.get("turn_contract") != shadow.get("turn_contract"),
        "contract": {
            "active": dict(active.get("turn_contract") or {}),
            "shadow": dict(shadow.get("turn_contract") or {}),
        },
        "candidate_registry": {
            "active_count": len(active_refs),
            "shadow_count": len(shadow_refs),
            "added": sorted(shadow_refs - active_refs),
            "removed": sorted(active_refs - shadow_refs),
            "preserved": sorted(active_refs & shadow_refs),
        },
        "selector": {
            "active": dict(active.get("selector") or {}),
            "shadow": dict(shadow.get("selector") or {}),
        },
        "material_plan": {
            "active": dict(active.get("material_plan") or {}),
            "shadow": dict(shadow.get("material_plan") or {}),
        },
        "pack_membership": {
            "added": sorted(shadow_ids - active_ids),
            "removed": sorted(active_ids - shadow_ids),
            "preserved": sorted(active_ids & shadow_ids),
        },
        "planner_decisions": {
            "active": list((active.get("policy") or {}).get("decisions") or ()),
            "shadow": list((shadow.get("policy") or {}).get("decisions") or ()),
            "active_noop_count": int(
                (active.get("policy") or {}).get("planner_noop_count") or 0
            ),
            "shadow_noop_count": int(
                (shadow.get("policy") or {}).get("planner_noop_count") or 0
            ),
        },
        "additive_search": {
            "active": list(active.get("additive_search") or ()),
            "shadow": list(shadow.get("additive_search") or ()),
        },
        "metrics": {
            "active": dict(active.get("metrics") or {}),
            "shadow": dict(shadow.get("metrics") or {}),
        },
        "shadow_answer_model_calls": shadow_answer_calls,
        "user_answer_changed": False,
        "side_effect_boundary_passed": shadow_answer_calls == 0,
    }


__all__ = [
    "capture_unified_rollout_trace",
    "compare_traces",
    "compare_unified_shadow",
    "render_comparison_report",
    "replay_snapshot_fixture",
    "summarize_trace",
]
