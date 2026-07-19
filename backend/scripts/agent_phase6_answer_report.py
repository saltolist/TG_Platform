"""Quality/latency report for the phase-6 answer contract fixture."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_FIXTURE = Path(__file__).parents[1] / "tests/fixtures/agent_answer_phase6/v1/scenarios.json"


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]


def build_report(fixture: dict[str, Any]) -> dict[str, Any]:
    scenarios = list(fixture.get("scenarios") or [])
    baseline_tokens = [float(item.get("baseline_answer_input_tokens") or 0) for item in scenarios]
    phase6_tokens = [float(item.get("phase6_answer_input_tokens") or 0) for item in scenarios]
    baseline_latency = [float(item.get("baseline_answer_latency_ms") or 0) for item in scenarios]
    phase6_latency = [float(item.get("phase6_answer_latency_ms") or 0) for item in scenarios]
    claims_valid = sum(bool(item.get("claims_valid")) for item in scenarios)
    schema_valid = sum(bool(item.get("schema_valid")) for item in scenarios)
    answer_path = sum(bool(item.get("answer_model_on_path")) for item in scenarios)
    count = max(1, len(scenarios))
    return {
        "fixture_schema": fixture.get("schema"),
        "measurement": fixture.get("measurement"),
        "scenarios": len(scenarios),
        "baseline": {
            "answer_input_tokens_median": median(baseline_tokens),
            "answer_input_tokens_p95": _p95(baseline_tokens),
            "answer_latency_ms_p95": _p95(baseline_latency),
        },
        "phase6": {
            "answer_input_tokens_median": median(phase6_tokens),
            "answer_input_tokens_p95": _p95(phase6_tokens),
            "answer_latency_ms_p95": _p95(phase6_latency),
            "grounded_claim_rate": claims_valid / count,
            "output_schema_compliance": schema_valid / count,
            "answer_model_path_rate": answer_path / count,
        },
        "change": {
            "answer_input_tokens_median_reduction": 1 - median(phase6_tokens) / max(1, median(baseline_tokens)),
            "answer_input_tokens_p95_reduction": 1 - _p95(phase6_tokens) / max(1, _p95(baseline_tokens)),
            "answer_latency_p95_reduction": 1 - _p95(phase6_latency) / max(1, _p95(baseline_latency)),
        },
    }


def check_report(report: dict[str, Any]) -> list[str]:
    phase6 = report["phase6"]
    issues: list[str] = []
    if phase6["answer_model_path_rate"] < 1.0:
        issues.append("answer model is not on the answer path for every scenario")
    if phase6["grounded_claim_rate"] < 1.0:
        issues.append("factual claims are not fully grounded")
    if phase6["output_schema_compliance"] < 0.99:
        issues.append("output schema compliance is below 99%")
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
