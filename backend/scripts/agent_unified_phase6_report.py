"""Build the strict phase-6 replay/shadow/canary quality report."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent.research.graph import _compact_state_snapshot
from app.services.agent.research.material_plan import normalize_candidates
from app.services.agent.runtime.baseline import load_unified_phase0_fixture
from app.services.agent.runtime.replay import (
    capture_unified_rollout_trace,
    compare_unified_shadow,
    replay_snapshot_fixture,
)
from app.services.agent.runtime.rollout import (
    build_canary_decision,
    build_quality_report,
    run_rollback_drill,
)


DEFAULT_FIXTURE = BACKEND_ROOT / "tests/fixtures/agent_unified_phase6/v1/measurements.json"
DEFAULT_REPLAY_FIXTURE = BACKEND_ROOT / "tests/fixtures/agent_unified_phase0/v1/scenarios.json"


def selector_boundary_benchmark(*, repeats: int = 50) -> dict[str, Any]:
    """Measure local serialization only; provider latency remains unavailable."""

    contract = {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "coverage": "complete",
                "predicate_kind": "semantic",
                "selection_cardinality": {"min": 0, "max": 8},
                "required_fidelity": "full_text",
            }
        ],
    }
    candidates = normalize_candidates(
        [
            {
                "ref": f"note:fixture-{index:03d}",
                "kind": "note",
                "title": f"Fixture {index:03d}",
                "preview": "x" * 240,
                "origin": "authoritative_catalog",
                "source_requirement_id": "workspace-notes",
                "source_revision": 1,
                "status": "active",
            }
            for index in range(256)
        ]
    )
    state = {
        "user_text": "synthetic semantic fixture",
        "turn_contract": contract,
        "candidate_envelopes": candidates,
        "unified_selector_enabled": True,
    }
    timings: list[float] = []
    rendered = ""
    for _ in range(max(2, repeats)):
        started = time.perf_counter()
        rendered = _compact_state_snapshot(state=state, records={}, sufficiency={})
        timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return {
        "schema": "workspace.selector-boundary-benchmark/v1",
        "registry_size": len(candidates),
        "repeats": len(timings),
        "local_serialization_p50_ms": round(statistics.median(timings), 3),
        "local_serialization_p95_ms": round(ordered[p95_index], 3),
        "serialized_chars": len(rendered),
        "estimated_prompt_tokens_chars_div_4": (len(rendered) + 3) // 4,
        "max_output_tokens": 12000,
        "selector_calls_per_successful_pass": 1,
        "provider_latency_availability": "unavailable",
        "provider_token_usage_availability": "unavailable",
    }


def _rollback_scenarios() -> list[dict[str, Any]]:
    checkpoint = {
        "user_message_id": "message:fixture-001",
        "search_ledger": [{"intent_key": "fixture", "state": "satisfied"}],
        "known_context_refs": ["note:fixture-001"],
        "evidence_records": {"evidence:fixture-001": {"kind": "note_chunk"}},
        "evidence_ids": ["evidence:fixture-001"],
        "turn_contract": {"version": 2},
    }
    return [
        {"name": "new_run", "target": "planner_policy", "checkpoint": {}},
        {"name": "resume_old_checkpoint", "target": "typed_requirements", "checkpoint": checkpoint},
        {"name": "selector_timeout", "target": "unified_selector", "checkpoint": checkpoint},
        {"name": "catalog_schema_mismatch", "target": "unified_catalog", "checkpoint": checkpoint},
        {"name": "pack_budget_overflow", "target": "verified_pack_boundary", "checkpoint": checkpoint},
    ]


def _shadow_fixture_comparison() -> dict[str, Any]:
    base = {
        "status": "completed",
        "turn_contract": {"version": 2},
        "candidate_envelopes": [
            {
                "ref": "note:fixture-001",
                "origin": "semantic_search",
                "semantic_score": 0.8,
                "source_requirement_id": "workspace-notes",
            }
        ],
        "material_plan": {"schema": "workspace.material-plan/v1", "coverage": "complete"},
        "evidence_pack": {
            "schema": "workspace.evidence-pack/v1",
            "evidence_ids": ["evidence:fixture-001"],
            "coverage": "complete",
        },
    }
    shadow = {
        **base,
        "turn_contract": {"version": 3},
        "planner_steps": [
            {
                "schema": "workspace.context-selector/v2",
                "assessments": [
                    {
                        "ref": "note:fixture-001",
                        "relevance": "direct",
                        "role": "answer_evidence",
                        "resolution": "full_text",
                    }
                ],
                "source_dispositions": [
                    {"source_id": "workspace-notes", "status": "selected"}
                ],
                "visible_refs": ["note:fixture-001"],
                "attempts": 1,
            }
        ],
        "plan_decisions": [
            {"route": "CALL_CONTEXT_SELECTOR", "reason_code": "SEMANTIC_PREDICATE"}
        ],
        "planner_noop_count": 1,
        "search_ledger": [
            {
                "tool": "SearchNodes",
                "search_relation": "additive_to_authoritative_catalog",
                "discovery_ref_count_before": 1,
                "discovery_ref_count_after": 1,
                "ranked_authoritative_ref_count": 1,
                "related_candidate_count": 0,
            }
        ],
        "material_plan": {"schema": "workspace.material-plan/v2", "coverage": "complete"},
        "evidence_pack": {
            "schema": "workspace.evidence-pack/v2",
            "evidence_ids": ["evidence:fixture-001"],
            "coverage": "complete",
        },
    }
    active_trace = capture_unified_rollout_trace(
        base,
        run_metrics={"calls": [{"phase": "answer"}], "llm_calls": 1},
        mode="active",
    )
    shadow_trace = capture_unified_rollout_trace(
        shadow,
        run_metrics={"calls": [{"phase": "research.selector.context"}], "llm_calls": 1},
        mode="shadow",
    )
    return compare_unified_shadow(active_trace, shadow_trace)


def build_report(path: Path = DEFAULT_FIXTURE, *, repeats: int = 50) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("schema") != "workspace.unified-phase6-measurements/v1":
        raise ValueError("unsupported phase-6 measurement fixture")
    flags = {
        "unified_catalog": True,
        "typed_requirements": True,
        "unified_selector": True,
        "verified_pack_boundary": True,
        "planner_policy": True,
        "default_on": False,
    }
    benchmark = selector_boundary_benchmark(repeats=repeats)
    measurements = dict(fixture["measurements"])
    measurements["selector_p95_prompt_tokens"] = {
        **dict(measurements["selector_p95_prompt_tokens"]),
        "value": benchmark["estimated_prompt_tokens_chars_div_4"],
    }
    quality = build_quality_report(
        measurements,
        report_id="unified-phase6-2026-07-24",
        source_commit=str(fixture["source_commit"]),
        owner=str(fixture["owner"]),
        compatibility_remove_after=str(fixture["compatibility_remove_after"]),
    )
    replay_fixture = load_unified_phase0_fixture(DEFAULT_REPLAY_FIXTURE)
    replays = [replay_snapshot_fixture(replay_fixture) for _ in range(max(2, repeats))]
    replay = {
        "runs": len(replays),
        "stable": len({item["digest"] for item in replays}) == 1,
        "digest": replays[0]["digest"],
        "scenario_count": replays[0]["scenario_count"],
        "answer_model_calls": 0,
    }
    return {
        "schema": "workspace.unified-phase6-report/v1",
        "scenario_inventory": fixture["scenario_inventory"],
        "quality": quality,
        "offline_replay": replay,
        "shadow_comparison": _shadow_fixture_comparison(),
        "selector_boundary_benchmark": benchmark,
        "rollback_drill": run_rollback_drill(flags, _rollback_scenarios()),
        "canary_plan": {
            "status": "blocked_until_all_mandatory_gates_pass",
            "factual_percent": 1.0,
            "semantic_complete_percent": 0.1,
            "sample_allocation": {
                key: build_canary_decision(
                    run_key=key,
                    predicate_kind="structural" if key != "fixture-run-003" else "semantic",
                    factual_percent=1.0,
                    semantic_complete_percent=0.1,
                    mandatory_gates_passed=quality["all_mandatory_gates_passed"],
                )
                for key in ("fixture-run-001", "fixture-run-002", "fixture-run-003")
            },
        },
        "rollout": {
            "offline_replay": "complete",
            "shadow_artifacts": "complete",
            "factual_canary": "blocked",
            "semantic_complete_canary": "blocked",
            "default_on": False,
            "blocking_gates": quality["blocking_gates"],
        },
    }


def check_report(report: dict[str, Any], *, require_default_on: bool = False) -> list[str]:
    issues: list[str] = []
    if not report["rollback_drill"]["passed"]:
        issues.append("rollback drill failed")
    if not report["offline_replay"]["stable"] or report["offline_replay"]["runs"] < 2:
        issues.append("offline replay is not stable")
    if report["offline_replay"]["answer_model_calls"] != 0:
        issues.append("offline replay invoked Answer Model")
    if not report["shadow_comparison"]["side_effect_boundary_passed"]:
        issues.append("shadow comparison crossed Answer Model boundary")
    inventory = report["scenario_inventory"]
    if int(inventory.get("golden") or 0) < 10 or int(inventory.get("held_out") or 0) < 3:
        issues.append("golden/held-out inventory is incomplete")
    quality = report["quality"]
    if quality["default_on_allowed"] != quality["all_mandatory_gates_passed"]:
        issues.append("default-on decision disagrees with mandatory gates")
    if report["rollout"]["default_on"]:
        issues.append("default-on must remain disabled in this report")
    if require_default_on and not quality["default_on_allowed"]:
        issues.append(f"mandatory gates blocked: {quality['blocking_gates']}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--repeat", type=int, default=50)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-default-on", action="store_true")
    args = parser.parse_args()
    report = build_report(args.fixture, repeats=args.repeat)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    issues = check_report(report, require_default_on=args.require_default_on)
    if args.check and issues:
        raise SystemExit("; ".join(issues))


if __name__ == "__main__":
    main()
