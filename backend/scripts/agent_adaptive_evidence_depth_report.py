"""Candidate-quota and card-context sweep for adaptive evidence depth."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/agent_adaptive_evidence_depth/v1/scenarios.json"
)
QUOTAS = (6, 8, 10)
CARD_BUDGETS = (6_000, 8_000)


def _recall(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 1.0


def build_report(fixture: dict[str, Any]) -> dict[str, Any]:
    scenarios = list(fixture.get("scenarios") or ())
    quota_rows: dict[str, Any] = {}
    for quota in QUOTAS:
        by_source: dict[str, list[float]] = {"notes": [], "posts": []}
        for scenario in scenarios:
            for source in by_source:
                ranked = [
                    str(item)
                    for item in (scenario.get("ranked_by_source") or {}).get(source) or ()
                ]
                relevant = {
                    str(item)
                    for item in (scenario.get("relevant_by_source") or {}).get(source) or ()
                }
                by_source[source].append(_recall(ranked, relevant, quota))
        quota_rows[str(quota)] = {
            source: statistics.mean(values) if values else 1.0
            for source, values in by_source.items()
        }
        quota_rows[str(quota)]["macro_recall"] = statistics.mean(
            quota_rows[str(quota)][source] for source in ("notes", "posts")
        )

    best_recall = max(row["macro_recall"] for row in quota_rows.values())
    tolerance = float((fixture.get("thresholds") or {}).get("recall_tolerance") or 0.0)
    selected_quota = min(
        quota
        for quota in QUOTAS
        if quota_rows[str(quota)]["macro_recall"] >= best_recall - tolerance
    )

    card_chars = sorted(
        int(scenario.get("selected_card_chars") or 0) for scenario in scenarios
    )
    p95_index = max(0, min(len(card_chars) - 1, int(len(card_chars) * 0.95) - 1))
    observed_p95 = card_chars[p95_index] if card_chars else 0
    selected_card_budget = min(
        (budget for budget in CARD_BUDGETS if budget >= observed_p95),
        default=max(CARD_BUDGETS),
    )
    return {
        "schema": "workspace.adaptive-evidence-depth-report/v1",
        "scenarios": len(scenarios),
        "quota_sweep": quota_rows,
        "selected_candidate_quota_per_source": selected_quota,
        "card_context": {
            "observed_selected_chars_p95": observed_p95,
            "selected_budget_chars": selected_card_budget,
            "truncated_scenarios": sum(
                chars > selected_card_budget for chars in card_chars
            ),
        },
        "thresholds": dict(fixture.get("thresholds") or {}),
    }


def check_report(report: dict[str, Any]) -> list[str]:
    thresholds = report.get("thresholds") or {}
    selected = str(report["selected_candidate_quota_per_source"])
    row = report["quota_sweep"][selected]
    issues: list[str] = []
    recall_floor = float(thresholds.get("candidate_recall_floor") or 0.0)
    for source in ("notes", "posts"):
        if float(row[source]) < recall_floor:
            issues.append(f"{source}_candidate_recall_below_floor")
    if report["card_context"]["truncated_scenarios"]:
        issues.append("selected_card_context_budget_truncates_fixture")
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
