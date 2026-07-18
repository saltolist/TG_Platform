"""Reproducible phase-0 baseline analysis over anonymized trace fixtures."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.agent.runtime.graders import grade_trace

SCHEMA_VERSION = "workspace-agent-scenario/v1"
PHASE_NAMES = ("startup", "bootstrap", "research", "answer")


def load_scenario_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_scenario_fixture(payload)
    return payload


def validate_scenario_fixture(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported scenario schema: {payload.get('schema_version')!r}")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")
    seen: set[str] = set()
    required = {"id", "split", "provenance", "temperature", "trace", "expected", "metrics"}
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenarios[{index}] must be an object")
        missing = required - set(scenario)
        if missing:
            raise ValueError(f"scenarios[{index}] missing fields: {sorted(missing)}")
        scenario_id = str(scenario.get("id") or "")
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"duplicate/empty scenario id: {scenario_id!r}")
        seen.add(scenario_id)
        if scenario.get("split") not in {"golden", "held_out"}:
            raise ValueError(f"scenario {scenario_id}: invalid split")
        if scenario.get("temperature") not in {"cold", "warm", "unknown"}:
            raise ValueError(f"scenario {scenario_id}: invalid temperature")
        if not isinstance(scenario.get("trace"), list):
            raise ValueError(f"scenario {scenario_id}: trace must be a list")


def percentile(values: Sequence[float | int], quantile: float) -> float | None:
    """Continuous percentile, matching PostgreSQL percentile_cont."""
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    position = (len(clean) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    fraction = position - lower
    return clean[lower] + (clean[upper] - clean[lower]) * fraction


def _distribution(values: Sequence[float | int]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if value is not None]
    return {
        "n": len(clean),
        "p50": percentile(clean, 0.50),
        "p95": percentile(clean, 0.95),
        "p99": percentile(clean, 0.99),
        "min": min(clean) if clean else None,
        "max": max(clean) if clean else None,
    }


def _cohort(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [scenario["metrics"].get("duration_ms") for scenario in scenarios]
    planner_calls = [scenario["metrics"].get("planner_calls") for scenario in scenarios]
    tool_calls = [scenario["metrics"].get("tool_calls") for scenario in scenarios]
    llm_calls = [scenario["metrics"].get("llm_calls_inferred") for scenario in scenarios]
    token_totals = [
        scenario["metrics"].get("tokens", {}).get("total")
        for scenario in scenarios
        if scenario["metrics"].get("tokens", {}).get("total") is not None
    ]
    phase_timings = {
        phase: _distribution(
            [
                scenario["metrics"].get("phase_ms", {}).get(phase)
                for scenario in scenarios
                if scenario["metrics"].get("phase_ms", {}).get(phase) is not None
            ]
        )
        for phase in PHASE_NAMES
    }
    return {
        "count": len(scenarios),
        "status_counts": dict(
            sorted(
                Counter(
                    str(scenario["expected"]["terminal_status"])
                    for scenario in scenarios
                ).items()
            )
        ),
        "duration_ms": _distribution(durations),
        "planner_calls": _distribution(planner_calls),
        "tool_calls": _distribution(tool_calls),
        "llm_calls_inferred": _distribution(llm_calls),
        "tokens": {
            "coverage": len(token_totals),
            "missing": len(scenarios) - len(token_totals),
            "total": _distribution(token_totals),
        },
        "phase_ms": phase_timings,
    }


def build_baseline_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_scenario_fixture(payload)
    scenarios = list(payload["scenarios"])
    grader_counts: Counter[str] = Counter()
    known_failures: Counter[str] = Counter()
    target_annotated = 0
    target_correct = 0
    for scenario in scenarios:
        report = grade_trace(scenario["trace"])
        for result in report.results:
            grader_counts[f"{result.name}:{'pass' if result.passed else 'fail'}"] += 1
        known_failures.update(str(item) for item in scenario.get("known_failures") or [])
        expected = scenario.get("expected") or {}
        if expected.get("target_annotation") == "production_review":
            target_annotated += 1
            expected_refs = {str(item) for item in expected.get("target_refs") or []}
            observed_refs: set[str] = set()
            for event in scenario.get("trace") or []:
                event_type = str(event.get("event_type") or "")
                event_payload = event.get("payload") or {}
                if event_type == "tool_result":
                    observed_refs.update(str(item) for item in event_payload.get("record_ids") or [])
            if expected_refs and expected_refs <= observed_refs:
                target_correct += 1

    cohorts: dict[str, Any] = {"all": _cohort(scenarios)}
    for temperature in ("cold", "warm", "unknown"):
        selected = [item for item in scenarios if item["temperature"] == temperature]
        cohorts[temperature] = _cohort(selected)
    for split in ("golden", "held_out"):
        selected = [item for item in scenarios if item["split"] == split]
        cohorts[split] = _cohort(selected)

    return {
        "schema_version": payload["schema_version"],
        "captured_at": payload.get("captured_at"),
        "scenario_count": len(scenarios),
        "cohorts": cohorts,
        "grader_counts": dict(sorted(grader_counts.items())),
        "known_failures": dict(sorted(known_failures.items())),
        "target_accuracy": {
            "annotated": target_annotated,
            "correct": target_correct,
            "accuracy": target_correct / target_annotated if target_annotated else None,
            "coverage": target_annotated / len(scenarios),
        },
    }
