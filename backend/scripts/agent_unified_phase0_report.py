"""Build and check the unified phase-0 safety-freeze report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent.runtime.baseline import (
    build_baseline_report,
    build_unified_phase0_report,
    load_scenario_fixture,
    load_unified_phase0_fixture,
    verify_protected_fixtures,
)
from app.services.agent.runtime.graders import grade_unified_phase0_snapshot
from app.services.agent.runtime.replay import replay_snapshot_fixture

DEFAULT_UNIFIED_FIXTURE = (
    BACKEND_ROOT / "tests/fixtures/agent_unified_phase0/v1/scenarios.json"
)
DEFAULT_TRACE_FIXTURE = BACKEND_ROOT / "tests/fixtures/agent_baseline/v1/scenarios.json"


def build_report(
    unified_fixture: Path = DEFAULT_UNIFIED_FIXTURE,
    trace_fixture: Path = DEFAULT_TRACE_FIXTURE,
    *,
    repeat: int = 2,
) -> dict[str, Any]:
    if repeat < 2:
        raise ValueError("phase-0 replay must run at least twice")
    unified = load_unified_phase0_fixture(unified_fixture)
    trace = load_scenario_fixture(trace_fixture)
    replays = [replay_snapshot_fixture(unified) for _ in range(repeat)]
    grader_failures: dict[str, list[str]] = {}
    for scenario in unified["scenarios"]:
        failures = grade_unified_phase0_snapshot(scenario).failures
        if failures:
            grader_failures[str(scenario["id"])] = [result.name for result in failures]
    return {
        "schema": "workspace.unified-phase0-report/v1",
        "trace_baseline": build_baseline_report(trace),
        "safety_freeze": build_unified_phase0_report(unified),
        "replay": {
            "runs": repeat,
            "stable": len({item["digest"] for item in replays}) == 1,
            "digest": replays[0]["digest"],
        },
        "protected_fixtures": verify_protected_fixtures(unified, root=BACKEND_ROOT),
        "grader_failures": grader_failures,
    }


def check_report(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    freeze = report["safety_freeze"]
    if report["replay"]["runs"] < 2 or not report["replay"]["stable"]:
        issues.append("snapshot replay is not stable across two runs")
    if report["grader_failures"]:
        issues.append("frozen evidence or lifecycle checkpoint changed")
    if freeze["baseline_commit"] != "128a96497416bc40d5d019ad3be97866ad094394":
        issues.append("rollback baseline commit changed")
    if any(freeze["rollback"]["flags"].values()):
        issues.append("a reserved unified rollout flag is enabled")
    required_scenarios = {
        "note-with-two-images",
        "note-inside-post",
        "irrelevant-ambient-note",
        "external-note-unrelated-parent-hit",
        "invalid-selector-output",
        "catalog-nine-objects",
        "catalog-one-hundred-one-objects",
        "checkpoint-resume",
        "interrupted-run",
        "cancelled-run",
    }
    missing = required_scenarios - set(freeze["scenario_ids"])
    if missing:
        issues.append(f"missing required scenarios: {sorted(missing)}")
    for flow in ("fast", "exact", "mutation"):
        if freeze["flow_counts"].get(flow) != 1:
            issues.append(f"missing {flow} control flow")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unified-fixture", type=Path, default=DEFAULT_UNIFIED_FIXTURE)
    parser.add_argument("--trace-fixture", type=Path, default=DEFAULT_TRACE_FIXTURE)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(args.unified_fixture, args.trace_fixture, repeat=args.repeat)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    issues = check_report(report)
    if args.check and issues:
        raise SystemExit("; ".join(issues))


if __name__ == "__main__":
    main()
