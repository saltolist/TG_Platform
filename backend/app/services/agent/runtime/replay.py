"""Deterministic trace replay summaries and old/new comparisons.

The replay layer intentionally consumes persisted event-shaped mappings, so a
production trace export and a fixture use the same code. It does not rerun an
LLM or retain hidden reasoning; it compares observable decisions, timings,
errors, and evidence coverage.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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


__all__ = ["compare_traces", "render_comparison_report", "summarize_trace"]
