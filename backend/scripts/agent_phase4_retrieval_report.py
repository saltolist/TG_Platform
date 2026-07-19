"""Reproducible quality/work benchmark for phase 4 candidate retrieval."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.services.agent.research.prefetch import merge_and_rerank

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/agent_retrieval_phase4/v1/scenarios.json"
)


def _rows(values: list[list[Any]], source: str) -> list[dict[str, Any]]:
    return [
        {
            "node_type": "note_summary",
            "note_id": str(object_id),
            "post_id": "",
            "file_id": "",
            "similarity": float(score),
            "source": source,
        }
        for object_id, score in values
    ]


def _recall(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 1.0


def _irrelevant_reads(ranked: list[str], relevant: set[str], k: int) -> int:
    return sum(1 for object_id in ranked[:k] if object_id not in relevant)


def build_report(fixture: dict[str, Any], *, iterations: int = 500) -> dict[str, Any]:
    scenarios = list(fixture.get("scenarios") or ())
    baseline_candidate: list[float] = []
    phase4_candidate: list[float] = []
    baseline_evidence: list[float] = []
    phase4_evidence: list[float] = []
    baseline_irrelevant = 0
    phase4_irrelevant = 0
    baseline_reads = 0
    phase4_reads = 0
    ranking_samples_ms: list[float] = []

    for scenario in scenarios:
        relevant = {str(item) for item in scenario.get("relevant_ids") or ()}
        baseline = [str(item) for item in scenario.get("baseline_ranked_ids") or ()]
        vector = _rows(list(scenario.get("vector") or ()), "vector")
        lexical = _rows(list(scenario.get("lexical") or ()), "fts")
        started = time.perf_counter()
        fused: list[dict[str, Any]] = []
        for _ in range(max(1, iterations)):
            fused = merge_and_rerank(
                vector_results=vector, fts_results=lexical, top_k=5
            )
        ranking_samples_ms.append(
            (time.perf_counter() - started) * 1000 / max(1, iterations)
        )
        phase4 = [str(item.get("note_id") or "") for item in fused]

        baseline_candidate.append(_recall(baseline, relevant, 5))
        phase4_candidate.append(_recall(phase4, relevant, 5))
        baseline_evidence.append(_recall(baseline, relevant, 3))
        phase4_evidence.append(_recall(phase4, relevant, 3))
        baseline_irrelevant += _irrelevant_reads(baseline, relevant, 5)
        phase4_irrelevant += _irrelevant_reads(phase4, relevant, 3)
        baseline_reads += min(5, len(baseline))
        phase4_reads += min(3, len(phase4))

    def reduction(before: int, after: int) -> float:
        return (before - after) / before if before else 0.0

    return {
        "schema": fixture.get("schema"),
        "scenarios": len(scenarios),
        "thresholds": fixture.get("thresholds") or {},
        "baseline": {
            "candidate_recall_at_5": statistics.mean(baseline_candidate),
            "evidence_recall_at_3": statistics.mean(baseline_evidence),
            "deep_reads": baseline_reads,
            "irrelevant_deep_reads": baseline_irrelevant,
        },
        "phase4": {
            "candidate_recall_at_5": statistics.mean(phase4_candidate),
            "evidence_recall_at_3": statistics.mean(phase4_evidence),
            "deep_reads": phase4_reads,
            "irrelevant_deep_reads": phase4_irrelevant,
            "ranking_cpu_p50_ms": statistics.median(ranking_samples_ms),
            "ranking_cpu_p95_ms": sorted(ranking_samples_ms)[
                max(0, int(len(ranking_samples_ms) * 0.95) - 1)
            ],
        },
        "change": {
            "deep_read_reduction": reduction(baseline_reads, phase4_reads),
            "irrelevant_deep_read_reduction": reduction(
                baseline_irrelevant, phase4_irrelevant
            ),
            "candidate_recall_delta": statistics.mean(phase4_candidate)
            - statistics.mean(baseline_candidate),
            "evidence_recall_delta": statistics.mean(phase4_evidence)
            - statistics.mean(baseline_evidence),
        },
    }


def check_report(report: dict[str, Any]) -> list[str]:
    thresholds = report["thresholds"]
    issues: list[str] = []
    if report["phase4"]["candidate_recall_at_5"] < thresholds["candidate_recall_at_5"]:
        issues.append("candidate_recall_at_5 below threshold")
    if report["phase4"]["evidence_recall_at_3"] < report["baseline"]["evidence_recall_at_3"]:
        issues.append("evidence recall regressed from baseline")
    if report["phase4"]["evidence_recall_at_3"] < thresholds["evidence_recall_at_3_floor"]:
        issues.append("evidence_recall_at_3 below quality floor")
    if report["change"]["irrelevant_deep_read_reduction"] < thresholds["irrelevant_read_reduction"]:
        issues.append("irrelevant read reduction below threshold")
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
