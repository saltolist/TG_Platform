"""Phase-0 quality freeze over anonymized production traces."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.agent.runtime.baseline import build_baseline_report, load_scenario_fixture
from app.services.agent.runtime.graders import grade_trace

FIXTURE_PATH = Path(__file__).parent / "fixtures/agent_baseline/v1/scenarios.json"
PROBLEM_CHAT_ID = "b9a1ff2d-4fae-47f3-9217-b0b9423c60be"


@pytest.fixture(scope="module")
def scenario_fixture() -> dict:
    return load_scenario_fixture(FIXTURE_PATH)


def _scenario(payload: dict, scenario_id: str) -> dict:
    return next(item for item in payload["scenarios"] if item["id"] == scenario_id)


def _grader(scenario: dict, name: str):
    return next(result for result in grade_trace(scenario["trace"]).results if result.name == name)


def test_scenario_fixture_has_requested_coverage(scenario_fixture: dict) -> None:
    scenarios = scenario_fixture["scenarios"]
    assert len(scenarios) == 32
    assert sum(item["split"] == "golden" for item in scenarios) == 24
    assert sum(item["split"] == "held_out" for item in scenarios) == 8
    assert [item["id"] for item in scenarios[:3]] == [
        "b9a1ff2d-turn-1",
        "b9a1ff2d-turn-2",
        "b9a1ff2d-turn-3",
    ]


def test_fixture_contains_no_unapproved_raw_uuid(scenario_fixture: dict) -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    uuids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        raw,
    )
    assert set(uuids) == {PROBLEM_CHAT_ID}
    assert len(uuids) == 3


def test_current_grader_results_are_frozen(scenario_fixture: dict) -> None:
    for scenario in scenario_fixture["scenarios"]:
        actual = {result.name: result.passed for result in grade_trace(scenario["trace"]).results}
        assert actual == scenario["expected"]["current_grader_results"], scenario["id"]


def test_every_known_failure_has_an_expected_result(scenario_fixture: dict) -> None:
    for scenario in scenario_fixture["scenarios"]:
        known = set(scenario.get("known_failures") or [])
        expectations = scenario["expected"]["regression_expectations"]
        assert set(expectations) == known, scenario["id"]
        assert all(value == {"current": True, "desired": False} for value in expectations.values())


def test_quality_floor_passes_outside_annotated_regressions(scenario_fixture: dict) -> None:
    required = set(scenario_fixture["quality_floor"]["required_graders"])
    for scenario in scenario_fixture["scenarios"]:
        known = set(scenario.get("known_failures") or [])
        results = {result.name: result for result in grade_trace(scenario["trace"]).results}
        for grader_name in required - known:
            assert results[grader_name].passed, f"{scenario['id']}: {results[grader_name].reason}"
    report = build_baseline_report(scenario_fixture)
    for grader_name, minimum in scenario_fixture["quality_floor"]["minimum_pass_counts"].items():
        assert report["grader_counts"].get(f"{grader_name}:pass", 0) >= minimum
    assert (
        report["target_accuracy"]["accuracy"]
        >= scenario_fixture["quality_floor"]["minimum_annotated_target_accuracy"]
    )


def test_baseline_distribution_snapshot(scenario_fixture: dict) -> None:
    report = build_baseline_report(scenario_fixture)
    assert report["scenario_count"] == 32
    assert report["grader_counts"] == {
        "no_duplicate_tool_calls:fail": 2,
        "no_duplicate_tool_calls:pass": 30,
        "no_finish_loops:fail": 5,
        "no_finish_loops:pass": 27,
        "output_event_schema:pass": 32,
        "valid_finish_evidence_ids:fail": 1,
        "valid_finish_evidence_ids:pass": 31,
    }
    assert report["target_accuracy"] == {
        "annotated": 2,
        "correct": 2,
        "accuracy": 1.0,
        "coverage": 0.0625,
    }
    all_runs = report["cohorts"]["all"]
    assert all_runs["duration_ms"]["p50"] == pytest.approx(9022.5)
    assert all_runs["duration_ms"]["p95"] == pytest.approx(119061.25)
    assert all_runs["duration_ms"]["p99"] == pytest.approx(1339780.39)
    assert all_runs["phase_ms"]["startup"]["p95"] == pytest.approx(4768.7)
    assert all_runs["phase_ms"]["bootstrap"]["p95"] == pytest.approx(2680.3)
    assert all_runs["phase_ms"]["research"]["p95"] == pytest.approx(88257.2)
    assert all_runs["phase_ms"]["answer"]["p95"] == pytest.approx(5634.6)


def test_cold_warm_and_token_telemetry_are_explicit(scenario_fixture: dict) -> None:
    report = build_baseline_report(scenario_fixture)
    assert report["cohorts"]["cold"]["count"] == 1
    assert report["cohorts"]["cold"]["duration_ms"]["p50"] == 102667.0
    assert report["cohorts"]["warm"]["count"] == 2
    assert report["cohorts"]["warm"]["duration_ms"]["p50"] == 18914.0
    assert report["cohorts"]["all"]["tokens"] == {
        "coverage": 0,
        "missing": 32,
        "total": {"n": 0, "p50": None, "p95": None, "p99": None, "min": None, "max": None},
    }


@pytest.mark.xfail(strict=True, reason="phase 1+: repeated FinishRetrieval is a frozen regression")
def test_regression_b9_turn_1_finishes_once(scenario_fixture: dict) -> None:
    assert _grader(_scenario(scenario_fixture, "b9a1ff2d-turn-1"), "no_finish_loops").passed


@pytest.mark.xfail(strict=True, reason="phase 1+: duplicate OpenNote is a frozen regression")
def test_regression_b9_turn_3_does_not_reopen_note(scenario_fixture: dict) -> None:
    assert _grader(_scenario(scenario_fixture, "b9a1ff2d-turn-3"), "no_duplicate_tool_calls").passed


@pytest.mark.xfail(strict=True, reason="phase 1+: repeated FinishRetrieval is a frozen regression")
def test_regression_b9_turn_3_finishes_once(scenario_fixture: dict) -> None:
    assert _grader(_scenario(scenario_fixture, "b9a1ff2d-turn-3"), "no_finish_loops").passed
