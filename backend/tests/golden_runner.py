"""Golden scenario runner — evidence/citation assertions, not LLM wording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoldenScenario:
    scenario_id: str
    path: Path
    implemented: bool


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "docs" / "dev" / "rag-pipeline" / "examples"


def list_golden_scenarios() -> list[GoldenScenario]:
    scenarios: list[GoldenScenario] = []
    for number in range(1, 20):
        sid = f"{number:02d}"
        matches = list(EXAMPLES_DIR.glob(f"{sid}-*.md"))
        scenarios.append(
            GoldenScenario(
                scenario_id=sid,
                path=matches[0] if matches else EXAMPLES_DIR / f"{sid}-missing.md",
                implemented=bool(matches),
            )
        )
    return scenarios


def implemented_scenario_ids() -> list[str]:
    return [item.scenario_id for item in list_golden_scenarios() if item.implemented]
