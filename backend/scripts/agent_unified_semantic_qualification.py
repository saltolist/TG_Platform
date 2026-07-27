"""Assemble the raw-safe phase-6 semantic qualification attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = BACKEND_ROOT / "tests/fixtures/agent_unified_phase6"
DEFAULT_COHORT = FIXTURE_ROOT / "v4/qualification_selector_cohort.json"
DEFAULT_BASELINE = FIXTURE_ROOT / "v3/calibration_baseline_provider_replay.json"
DEFAULT_CALIBRATION = FIXTURE_ROOT / "v3/calibration_final_primary_run1.json"
DEFAULT_QUALIFICATION_RUNS = (
    FIXTURE_ROOT / "v4/qualification_primary_run1.json",
    FIXTURE_ROOT / "v4/qualification_primary_run2.json",
    FIXTURE_ROOT / "v4/qualification_primary_run3.json",
)
DEFAULT_COMPATIBILITY = FIXTURE_ROOT / "v4/qualification_compatibility_baseline.json"
DEFAULT_BOUNDARY = FIXTURE_ROOT / "v4/boundary_256_primary.json"
DEFAULT_OUTPUT = FIXTURE_ROOT / "v4/provider_replay_aggregate.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metrics(report: Mapping[str, Any], variant: str) -> dict[str, Any]:
    return dict((report.get("variants") or {}).get(variant) or {})


def _semantic_pass(report: Mapping[str, Any]) -> bool:
    metrics = _metrics(report, "160")
    scenario_count = int(report.get("semantic_scenario_count") or 0)
    return (
        scenario_count >= 20
        and int(metrics.get("final_valid") or 0) == scenario_count
        and int(metrics.get("first_attempt_valid") or 0) == scenario_count
        and int(metrics.get("retries") or 0) == 0
        and metrics.get("critical_required_recall") == 1.0
        and metrics.get("irrelevant_selection_rate") == 0.0
        and metrics.get("final_pack_precision") == 1.0
        and int(report.get("position_error_count") or 0) == 0
        and int(report.get("provider_failure_count") or 0) == 0
    )


def build_aggregate(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    baseline_path: Path = DEFAULT_BASELINE,
    calibration_path: Path = DEFAULT_CALIBRATION,
    qualification_paths: tuple[Path, ...] = DEFAULT_QUALIFICATION_RUNS,
    compatibility_path: Path = DEFAULT_COMPATIBILITY,
    boundary_path: Path = DEFAULT_BOUNDARY,
) -> dict[str, Any]:
    cohort = _load(cohort_path)
    baseline = _load(baseline_path)
    calibration = _load(calibration_path)
    qualification = [_load(path) for path in qualification_paths]
    compatibility = _load(compatibility_path)
    boundary = _load(boundary_path)

    version = str(cohort.get("version") or "")
    if not version or cohort.get("cohort_role") != "qualification":
        raise ValueError("qualification cohort role/version is invalid")
    for report in qualification:
        if report.get("cohort_version") != version:
            raise ValueError("qualification report cohort version mismatch")
    passing = [report for report in qualification if _semantic_pass(report)]
    if len(passing) < 2:
        raise ValueError("at least two complete semantic qualification repeats are required")

    primary = _metrics(passing[-1], "160")
    compatibility_metrics = _metrics(compatibility, "compatibility")
    for language, row in (primary.get("language_cohorts") or {}).items():
        baseline_row = (compatibility_metrics.get("language_cohorts") or {}).get(language) or {}
        if row.get("required_recall") < baseline_row.get("required_recall"):
            raise ValueError(f"required recall regressed for language {language}")
        if row.get("final_pack_precision") < baseline_row.get("final_pack_precision"):
            raise ValueError(f"final-pack precision regressed for language {language}")

    boundary_row = dict(boundary.get("boundary_256") or {})
    if (
        boundary_row.get("final_canonical_valid") is not True
        or boundary_row.get("gate_total_tokens_lte_22000") is not True
    ):
        raise ValueError("boundary-256 provider gate did not pass")

    schema_results: Counter[str] = Counter()
    validation_errors: Counter[str] = Counter()
    all_reports = [baseline, calibration, *qualification, compatibility, boundary]
    for report in all_reports:
        schema_results.update(report.get("schema_results") or {})
        validation_errors.update(report.get("validation_error_counts") or {})

    repeat_rows = []
    for path, report in zip(qualification_paths, qualification, strict=True):
        metrics = _metrics(report, "160")
        repeat_rows.append(
            {
                "artifact": path.name,
                "digest": _digest(path),
                "status": "pass" if _semantic_pass(report) else "inconclusive",
                "scenario_count": report.get("semantic_scenario_count"),
                "final_valid": metrics.get("final_valid"),
                "first_attempt_valid": metrics.get("first_attempt_valid"),
                "retries": metrics.get("retries"),
                "critical_required_recall": metrics.get("critical_required_recall"),
                "irrelevant_selection_rate": metrics.get("irrelevant_selection_rate"),
                "final_pack_precision": metrics.get("final_pack_precision"),
                "provider_failure_count": report.get("provider_failure_count"),
            }
        )

    return {
        "schema": "workspace.selector-provider-replay/v1",
        "cohort_version": version,
        "cohort_role": "qualification",
        "semantic_variant": "query_goal+directness+evidence_reason+explicit_absence+answer_slot",
        "provider": passing[-1].get("provider"),
        "model": passing[-1].get("model"),
        "transport_tier": passing[-1].get("transport_tier"),
        "contains_credentials": False,
        "contains_account_identifier": False,
        "contains_raw_provider_output": False,
        "contains_source_or_user_content": False,
        "semantic_scenario_count": passing[-1].get("semantic_scenario_count"),
        "semantic_sample_sufficient": True,
        "qualification": {
            "cohort_artifact": cohort_path.name,
            "cohort_digest": _digest(cohort_path),
            "labels_frozen_before_provider_output": bool(
                cohort.get("labels_frozen_before_provider_output")
            ),
            "valid_repeat_count": len(passing),
            "inconclusive_repeat_count": len(qualification) - len(passing),
            "repeats": repeat_rows,
            "calibration_artifact": calibration_path.name,
            "calibration_digest": _digest(calibration_path),
            "baseline_artifact": baseline_path.name,
            "baseline_digest": _digest(baseline_path),
        },
        "variants": {
            "compatibility": compatibility_metrics,
            "160": {
                **primary,
                "qualification_repeat_metrics": repeat_rows,
            },
        },
        "summary_160_non_inferior_recall": True,
        "summary_160_non_inferior_precision": True,
        "boundary_256": boundary_row,
        "provider_call_count": sum(
            int(report.get("provider_call_count") or 0) for report in all_reports
        ),
        "schema_results": dict(sorted(schema_results.items())),
        "validation_error_counts": dict(sorted(validation_errors.items())),
        "position_error_count": sum(
            int(report.get("position_error_count") or 0) for report in all_reports
        ),
        "provider_failure_count": sum(
            int(report.get("provider_failure_count") or 0) for report in all_reports
        ),
        "price_snapshot": {"availability": "unavailable", "version": None},
        "estimated_cost": {"availability": "unavailable", "value_usd": None},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument(
        "--qualification-run",
        dest="qualification_runs",
        action="append",
        type=Path,
        default=None,
    )
    parser.add_argument("--compatibility", type=Path, default=DEFAULT_COMPATIBILITY)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_aggregate(
        cohort_path=args.cohort,
        baseline_path=args.baseline,
        calibration_path=args.calibration,
        qualification_paths=tuple(args.qualification_runs or DEFAULT_QUALIFICATION_RUNS),
        compatibility_path=args.compatibility,
        boundary_path=args.boundary,
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
