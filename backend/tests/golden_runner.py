"""Golden scenario catalog — tracks executable coverage, not just doc presence.

agent-runtime-sprints §4: `implemented` used to mean "a .md file with this id
exists" — every scenario counted as done the moment its doc was written, even
the "TBD" stubs. It now means "has an executable scripted test in
test_agent_golden.py that runs the real execute_agent_run graph and grades
the outcome with grade_run" (the deterministic `pytest -m golden` gate). The
16 scenarios without an entry in EXECUTABLE_SCENARIOS remain doc-only by
design — see agent-runtime-remaining.md for the explicit tail.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "docs" / "dev" / "rag-pipeline" / "examples"

# scenario_id -> name of the pytest.mark.golden test in test_agent_golden.py
# that exercises it end-to-end. Only these 3 are executable; the remaining 16
# catalog ids are doc-only (agent-runtime-sprints §4 tail, not a silent gap).
EXECUTABLE_SCENARIOS: dict[str, str] = {
    "06": "test_golden_notes_with_content",
    "11": "test_golden_empty_pack_reaches_final_answer",
    "13": "test_golden_multi_turn_deixis",
}


@dataclass(frozen=True)
class GoldenScenario:
    scenario_id: str
    path: Path
    has_doc: bool
    implemented: bool
    executable_test: str | None


def list_golden_scenarios() -> list[GoldenScenario]:
    scenarios: list[GoldenScenario] = []
    for number in range(1, 20):
        sid = f"{number:02d}"
        matches = list(EXAMPLES_DIR.glob(f"{sid}-*.md"))
        test_name = EXECUTABLE_SCENARIOS.get(sid)
        scenarios.append(
            GoldenScenario(
                scenario_id=sid,
                path=matches[0] if matches else EXAMPLES_DIR / f"{sid}-missing.md",
                has_doc=bool(matches),
                implemented=test_name is not None,
                executable_test=test_name,
            )
        )
    return scenarios


def implemented_scenario_ids() -> list[str]:
    return [item.scenario_id for item in list_golden_scenarios() if item.implemented]


def documented_scenario_ids() -> list[str]:
    return [item.scenario_id for item in list_golden_scenarios() if item.has_doc]
