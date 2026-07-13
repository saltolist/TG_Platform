"""Golden scenario catalog — docs exist for every scenario id."""

from __future__ import annotations

from tests.golden_runner import EXAMPLES_DIR, implemented_scenario_ids, list_golden_scenarios


def test_golden_catalog_covers_01_through_19() -> None:
    scenarios = list_golden_scenarios()
    assert [item.scenario_id for item in scenarios] == [f"{number:02d}" for number in range(1, 20)]
    assert implemented_scenario_ids() == [f"{number:02d}" for number in range(1, 20)]
    for item in scenarios:
        assert item.path.exists(), f"missing golden doc: {item.path}"
        assert item.path.parent == EXAMPLES_DIR
