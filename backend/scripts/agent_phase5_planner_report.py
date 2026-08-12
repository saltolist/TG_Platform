"""Reproducible quality/work benchmark for phase 5 planner control flow."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/agent_planner_phase5/v1/scenarios.json"
)


def _latency(row: dict[str, Any], model: dict[str, Any]) -> float:
    return (
        int(row.get("planner_calls") or 0) * float(model["planner_call"])
        + int(row.get("tool_calls") or 0) * float(model["tool_call"])
    )


def _p95(values: list[float]) -> float:
    return sorted(values)[max(0, int(len(values) * 0.95) - 1)] if values else 0.0


def build_report(fixture: dict[str, Any]) -> dict[str, Any]:
    scenarios = list(fixture.get("scenarios") or ())
    model = dict(fixture.get("latency_model_ms") or {})
    baseline = [dict(item.get("baseline") or {}) for item in scenarios]
    phase5 = [dict(item.get("phase5") or {}) for item in scenarios]
    baseline_latency = [_latency(item, model) for item in baseline]
    phase5_latency = [_latency(item, model) for item in phase5]
    planner_calls = sum(int(item.get("planner_calls") or 0) for item in phase5)
    invalid = sum(int(item.get("invalid_outputs") or 0) for item in phase5)
    total_steps = sum(
        int(item.get("planner_calls") or 0) + int(item.get("tool_calls") or 0)
        for item in phase5
    )
    wasted = sum(int(item.get("wasted_steps") or 0) for item in phase5)
    baseline_tokens = int(model["baseline_planner_output_tokens"])
    phase5_tokens = int(model["phase5_planner_output_tokens"])
    return {
        "schema": fixture.get("schema"),
        "scenarios": len(scenarios),
        "thresholds": fixture.get("thresholds") or {},
        "baseline": {
            "planner_calls": sum(int(item.get("planner_calls") or 0) for item in baseline),
            "wasted_steps": sum(int(item.get("wasted_steps") or 0) for item in baseline),
            "estimated_latency_p50_ms": statistics.median(baseline_latency),
            "estimated_latency_p95_ms": _p95(baseline_latency),
            "planner_output_budget_tokens": baseline_tokens,
        },
        "phase5": {
            "planner_calls": planner_calls,
            "invalid_planner_rate": invalid / planner_calls if planner_calls else 0.0,
            "wasted_steps": wasted,
            "wasted_step_rate": wasted / total_steps if total_steps else 0.0,
            "quality_floor": min(float(item.get("quality") or 0.0) for item in scenarios),
            "mode_budget_violations": sum(
                int(item["phase5"].get("planner_calls") or 0) > int(item.get("planner_budget") or 0)
                for item in scenarios
            ),
            "duplicate_open_scenarios": sum(
                int(item["phase5"].get("duplicate_opens") or 0) > 0 for item in scenarios
            ),
            "finish_emissions": sum(int(item.get("finish_emissions") or 0) for item in phase5),
            "estimated_latency_p50_ms": statistics.median(phase5_latency),
            "estimated_latency_p95_ms": _p95(phase5_latency),
            "planner_output_budget_tokens": phase5_tokens,
        },
        "change": {
            "planner_call_reduction": 1 - planner_calls / sum(
                int(item.get("planner_calls") or 0) for item in baseline
            ),
            "estimated_latency_p95_reduction": 1 - _p95(phase5_latency) / _p95(baseline_latency),
            "planner_output_reduction": 1 - phase5_tokens / baseline_tokens,
        },
    }


def check_report(report: dict[str, Any]) -> list[str]:
    phase5 = report["phase5"]
    thresholds = report["thresholds"]
    issues: list[str] = []
    if phase5["invalid_planner_rate"] >= thresholds["invalid_planner_rate_max"]:
        issues.append("invalid planner output rate is not below threshold")
    if phase5["wasted_step_rate"] >= thresholds["wasted_step_rate_max"]:
        issues.append("wasted planner steps are not below threshold")
    if phase5["quality_floor"] < thresholds["quality_floor"]:
        issues.append("quality floor regressed")
    if phase5["mode_budget_violations"]:
        issues.append("planner mode budget violated")
    if phase5["duplicate_open_scenarios"] or phase5["finish_emissions"]:
        issues.append("duplicate open or finish loop remains")
    if report["change"]["planner_output_reduction"] < thresholds["planner_output_reduction_min"]:
        issues.append("planner output reduction below threshold")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(json.loads(args.fixture.read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    issues = check_report(report)
    if args.check and issues:
        raise SystemExit("; ".join(issues))


if __name__ == "__main__":
    main()
