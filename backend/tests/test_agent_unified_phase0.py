"""Unified integrity phase-0 baseline, fixtures, and safety freeze."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.services.agent.runtime.baseline import (
    UNIFIED_METRICS,
    UNIFIED_SNAPSHOT_FIELDS,
    build_unified_phase0_report,
    load_unified_phase0_fixture,
    validate_unified_phase0_fixture,
    verify_protected_fixtures,
)
from app.services.agent.runtime.graders import grade_unified_phase0_snapshot
from app.services.agent.runtime.replay import replay_snapshot_fixture
from scripts.agent_unified_phase0_report import build_report, check_report

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = BACKEND_ROOT / "tests/fixtures/agent_unified_phase0/v1/scenarios.json"
BASELINE_COMMIT = "128a96497416bc40d5d019ad3be97866ad094394"
FUTURE_FLAG_NAMES = (
    "agent_typed_requirements_v1_enabled",
    "agent_unified_selector_v1_enabled",
    "agent_verified_pack_boundary_v1_enabled",
    "agent_planner_policy_v1_enabled",
    "agent_unified_default_on",
)


@pytest.fixture(scope="module")
def fixture() -> dict:
    return load_unified_phase0_fixture(FIXTURE_PATH)


def _scenario(payload: dict, scenario_id: str) -> dict:
    return next(item for item in payload["scenarios"] if item["id"] == scenario_id)


def test_fixture_covers_required_golden_and_lifecycle_cases(fixture: dict) -> None:
    ids = {item["id"] for item in fixture["scenarios"]}
    assert {
        "note-with-two-images",
        "note-inside-post",
        "irrelevant-ambient-note",
        "external-note-unrelated-parent-hit",
        "invalid-selector-output",
        "catalog-nine-objects",
        "catalog-one-hundred-one-objects",
        "fast-flow",
        "exact-flow",
        "mutation-flow",
        "checkpoint-resume",
        "interrupted-run",
        "cancelled-run",
    } <= ids
    assert sum(item["split"] == "golden" for item in fixture["scenarios"]) == 10
    assert sum(item["split"] == "held_out" for item in fixture["scenarios"]) == 3


def test_every_scenario_freezes_all_required_snapshots(fixture: dict) -> None:
    for scenario in fixture["scenarios"]:
        assert set(UNIFIED_SNAPSHOT_FIELDS) <= set(scenario["snapshots"]), scenario["id"]
        assert not grade_unified_phase0_snapshot(scenario).failures, scenario["id"]


def test_catalog_fixtures_contain_full_synthetic_ground_truth(fixture: dict) -> None:
    nine = _scenario(fixture, "catalog-nine-objects")
    hundred_one = _scenario(fixture, "catalog-one-hundred-one-objects")
    assert len(nine["fixture_input"]["catalog_member_refs"]) == 9
    assert len(nine["snapshots"]["candidate_registry"]["refs"]) == 8
    assert len(hundred_one["fixture_input"]["catalog_member_refs"]) == 101
    assert len(hundred_one["snapshots"]["candidate_registry"]["refs"]) == 100
    assert hundred_one["snapshots"]["material_plan"]["omitted_ids"] == [
        "note:fixture-301"
    ]


def test_fixture_rejects_user_text_and_real_identifiers(fixture: dict) -> None:
    raw_text = copy.deepcopy(fixture)
    raw_text["scenarios"][0]["snapshots"]["trace"][0]["user_text"] = "private text"
    with pytest.raises(ValueError, match="user text field is forbidden"):
        validate_unified_phase0_fixture(raw_text)

    raw_uuid = copy.deepcopy(fixture)
    raw_uuid["scenarios"][0]["snapshots"]["checkpoint"]["run_ref"] = (
        "123e4567-e89b-12d3-a456-426614174000"
    )
    with pytest.raises(ValueError, match="raw UUID is forbidden"):
        validate_unified_phase0_fixture(raw_uuid)

    raw_url = copy.deepcopy(fixture)
    raw_url["scenarios"][0]["snapshots"]["final_pack"]["source"] = (
        "https://example.invalid/private"
    )
    with pytest.raises(ValueError, match="URL is forbidden"):
        validate_unified_phase0_fixture(raw_url)


def test_metric_availability_never_substitutes_missing_with_zero(fixture: dict) -> None:
    report = build_unified_phase0_report(fixture)
    assert set(report["metrics"]) == set(UNIFIED_METRICS)
    context_tokens = report["metrics"]["context_tokens"]
    assert context_tokens["available"] == 0
    assert context_tokens["missing"] == len(fixture["scenarios"])
    assert context_tokens["distribution"] == {
        "n": 0,
        "p50": None,
        "p95": None,
        "p99": None,
        "min": None,
        "max": None,
    }
    assert report["metrics"]["planner_calls"]["distribution"]["p50"] == 0


def test_replay_is_identical_twice(fixture: dict) -> None:
    first = replay_snapshot_fixture(fixture)
    second = replay_snapshot_fixture(fixture)
    assert first == second
    assert first["scenario_count"] == 13
    assert len(first["digest"]) == 64


def test_existing_fixture_expected_results_are_protected(fixture: dict) -> None:
    verified = verify_protected_fixtures(fixture, root=BACKEND_ROOT)
    assert verified == fixture["protected_fixtures"]


def test_control_flows_keep_zero_planner_calls(fixture: dict) -> None:
    for scenario_id in ("fast-flow", "exact-flow", "mutation-flow"):
        scenario = _scenario(fixture, scenario_id)
        assert scenario["metrics"]["planner_calls"] == {
            "availability": "derived",
            "value": 0,
        }
        assert scenario["expected"]["planner_calls"] == 0


def test_resume_interrupted_and_cancelled_checkpoints_are_frozen(fixture: dict) -> None:
    assert _scenario(fixture, "checkpoint-resume")["snapshots"]["checkpoint"] == {
        "schema": "workspace.checkpoint/baseline-v1",
        "status": "completed",
        "turn_revision": 2,
        "resumed_from_revision": 1,
        "material_plan_schema": "workspace.material-plan/v1",
    }
    assert _scenario(fixture, "interrupted-run")["snapshots"]["checkpoint"]["status"] == (
        "interrupted"
    )
    assert _scenario(fixture, "cancelled-run")["snapshots"]["checkpoint"]["status"] == (
        "cancelled"
    )


def test_rollout_flags_default_off_and_future_flags_have_no_runtime_consumers(
    fixture: dict,
) -> None:
    assert fixture["rollback"]["baseline_commit"] == BASELINE_COMMIT
    assert all(value is False for value in fixture["rollback"]["flags"].values())
    compose = (BACKEND_ROOT.parent / "docker-compose.yml").read_text(encoding="utf-8")
    root_env = (BACKEND_ROOT.parent / ".env.example").read_text(encoding="utf-8")
    backend_env = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    for env_name in fixture["rollback"]["flags"]:
        assert f"{env_name}: ${{{env_name}:-0}}" in compose
        assert f"{env_name}=0" in root_env
        assert f"{env_name}=0" in backend_env
    runtime_root = BACKEND_ROOT / "app/services/agent"
    for flag_name in FUTURE_FLAG_NAMES:
        consumers = [
            path
            for path in runtime_root.rglob("*.py")
            if flag_name in path.read_text(encoding="utf-8")
        ]
        assert consumers == [], f"reserved phase-0 flag is consumed: {flag_name}"


def test_combined_report_gate_passes_and_replays_twice() -> None:
    report = build_report(repeat=2)
    assert report["replay"]["runs"] == 2
    assert report["replay"]["stable"] is True
    assert report["trace_baseline"]["scenario_count"] == 32
    assert check_report(report) == []
