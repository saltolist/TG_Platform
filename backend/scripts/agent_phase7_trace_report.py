"""Reproducible phase-7 quality/latency report for consolidated tools."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def build_report(fixture_path: Path) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    scenarios = list(fixture.get("scenarios") or [])
    baseline_latency = [float(item.get("baseline_latency_ms") or 0) for item in scenarios]
    phase7_latency = [float(item.get("phase7_latency_ms") or 0) for item in scenarios]
    baseline_tools = [float(item.get("baseline_tool_calls") or 0) for item in scenarios]
    phase7_tools = [float(item.get("phase7_tool_calls") or 0) for item in scenarios]
    quality = min(float(item.get("quality") or 0) for item in scenarios) if scenarios else 0.0
    result = {
        "schema": "workspace.agent-phase7-report/v1",
        "scenario_count": len(scenarios),
        "quality_floor": quality,
        "targets_preserved_rate": sum(bool(item.get("targets_preserved")) for item in scenarios) / max(1, len(scenarios)),
        "evidence_preserved_rate": sum(bool(item.get("evidence_preserved")) for item in scenarios) / max(1, len(scenarios)),
        "new_tool_errors": sum(int(item.get("new_tool_errors") or 0) for item in scenarios),
        "baseline": {
            "latency_p50_ms": statistics.median(baseline_latency),
            "latency_p95_ms": _p95(baseline_latency),
            "tool_calls_p50": statistics.median(baseline_tools),
            "tool_calls_p95": _p95(baseline_tools),
        },
        "phase7": {
            "latency_p50_ms": statistics.median(phase7_latency),
            "latency_p95_ms": _p95(phase7_latency),
            "tool_calls_p50": statistics.median(phase7_tools),
            "tool_calls_p95": _p95(phase7_tools),
        },
    }
    result["latency_p50_reduction"] = 1 - result["phase7"]["latency_p50_ms"] / max(1, result["baseline"]["latency_p50_ms"])
    result["latency_p95_reduction"] = 1 - result["phase7"]["latency_p95_ms"] / max(1, result["baseline"]["latency_p95_ms"])
    result["tool_call_p50_reduction"] = 1 - result["phase7"]["tool_calls_p50"] / max(1, result["baseline"]["tool_calls_p50"])
    result["tool_call_p95_reduction"] = 1 - result["phase7"]["tool_calls_p95"] / max(1, result["baseline"]["tool_calls_p95"])
    return result


def check_report(report: dict[str, Any], fixture_path: Path) -> list[str]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    thresholds = fixture.get("thresholds") or {}
    issues: list[str] = []
    if report["quality_floor"] < float(thresholds.get("quality_floor") or 1.0):
        issues.append("quality floor regressed")
    if report["new_tool_errors"] > int(thresholds.get("max_new_tool_errors") or 0):
        issues.append("new typed tool errors appeared")
    if report["tool_call_p50_reduction"] < float(thresholds.get("min_tool_call_reduction") or 0):
        issues.append("tool-call reduction below threshold")
    if report["latency_p50_reduction"] < float(thresholds.get("min_latency_reduction") or 0):
        issues.append("latency reduction below threshold")
    if report["targets_preserved_rate"] < 1 or report["evidence_preserved_rate"] < 1:
        issues.append("target/evidence preservation regressed")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path(__file__).parents[1] / "tests/fixtures/agent_phase7/v1/scenarios.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(args.fixture)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.check:
        issues = check_report(report, args.fixture)
        if issues:
            print("phase7 report failed: " + "; ".join(issues))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
