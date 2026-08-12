"""Print the reproducible phase-0 trace baseline as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.agent.runtime.baseline import build_baseline_report, load_scenario_fixture

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/agent_baseline/v1/scenarios.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    report = build_baseline_report(load_scenario_fixture(args.fixture))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
