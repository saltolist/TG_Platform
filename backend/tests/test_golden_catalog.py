"""Golden scenario catalog — docs exist for every id; 3 are executable
(agent-runtime-sprints §4). The other 16 are intentionally doc-only, not a
silently-dropped gap — see golden_runner.EXECUTABLE_SCENARIOS."""

from __future__ import annotations

from tests.golden_runner import (
    EXAMPLES_DIR,
    EXECUTABLE_SCENARIOS,
    documented_scenario_ids,
    implemented_scenario_ids,
    list_golden_scenarios,
)


def test_golden_catalog_covers_01_through_19() -> None:
    scenarios = list_golden_scenarios()
    all_ids = [f"{number:02d}" for number in range(1, 20)]
    assert [item.scenario_id for item in scenarios] == all_ids
    assert documented_scenario_ids() == all_ids
    for item in scenarios:
        assert item.path.exists(), f"missing golden doc: {item.path}"
        assert item.path.parent == EXAMPLES_DIR


def test_golden_catalog_executable_scenarios_are_the_intended_three() -> None:
    assert implemented_scenario_ids() == sorted(EXECUTABLE_SCENARIOS)
