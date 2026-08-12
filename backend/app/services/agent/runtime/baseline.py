"""Reproducible phase-0 baseline analysis over anonymized trace fixtures."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.agent.runtime.graders import grade_trace

SCHEMA_VERSION = "workspace-agent-scenario/v1"
UNIFIED_PHASE0_SCHEMA_VERSION = "workspace-agent-unified-phase0/v1"
PHASE_NAMES = ("startup", "bootstrap", "research", "answer")
UNIFIED_SNAPSHOT_FIELDS = (
    "turn_contract",
    "candidate_registry",
    "selector_input",
    "material_plan",
    "final_pack",
    "sufficiency",
    "search_ledger",
    "checkpoint",
    "trace",
)
UNIFIED_METRICS = (
    "latency_ms",
    "planner_calls",
    "tool_calls",
    "context_tokens",
    "selector_relevant_precision",
    "selector_relevant_recall",
    "irrelevant_selection_rate",
    "required_source_forced_selection_rate",
    "fallback_select_all_rate",
    "required_evidence_recall",
    "fidelity_mismatch_rate",
    "catalog_property_unknown_rate",
    "structural_count_error_rate",
    "final_pack_precision",
    "planner_noop_rate",
)
_RAW_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_URL_RE = re.compile(r"(?:https?://|tg://|t\.me/)", re.IGNORECASE)
_FORBIDDEN_TEXT_KEYS = {
    "user_text",
    "prompt",
    "query",
    "search_query",
    "text",
    "title",
    "body",
    "content",
    "answer_text",
    "claim",
    "claims",
    "summary",
    "reason",
    "reasoning",
    "observations",
    "gap",
    "repair_hint",
}


def load_scenario_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_scenario_fixture(payload)
    return payload


def validate_scenario_fixture(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported scenario schema: {payload.get('schema_version')!r}")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")
    seen: set[str] = set()
    required = {"id", "split", "provenance", "temperature", "trace", "expected", "metrics"}
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenarios[{index}] must be an object")
        missing = required - set(scenario)
        if missing:
            raise ValueError(f"scenarios[{index}] missing fields: {sorted(missing)}")
        scenario_id = str(scenario.get("id") or "")
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"duplicate/empty scenario id: {scenario_id!r}")
        seen.add(scenario_id)
        if scenario.get("split") not in {"golden", "held_out"}:
            raise ValueError(f"scenario {scenario_id}: invalid split")
        if scenario.get("temperature") not in {"cold", "warm", "unknown"}:
            raise ValueError(f"scenario {scenario_id}: invalid temperature")
        if not isinstance(scenario.get("trace"), list):
            raise ValueError(f"scenario {scenario_id}: trace must be a list")


def load_unified_phase0_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_unified_phase0_fixture(payload)
    return payload


def _validate_anonymized_value(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in _FORBIDDEN_TEXT_KEYS:
                raise ValueError(f"{path}.{key_text}: user text field is forbidden")
            _validate_anonymized_value(child, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_anonymized_value(child, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if _RAW_UUID_RE.search(value):
        raise ValueError(f"{path}: raw UUID is forbidden")
    if _EMAIL_RE.search(value):
        raise ValueError(f"{path}: email is forbidden")
    if _URL_RE.search(value):
        raise ValueError(f"{path}: URL is forbidden")


def validate_unified_phase0_fixture(payload: Mapping[str, Any]) -> None:
    """Validate the synthetic safety freeze without importing runtime schemas."""

    if payload.get("schema_version") != UNIFIED_PHASE0_SCHEMA_VERSION:
        raise ValueError(f"unsupported unified phase-0 schema: {payload.get('schema_version')!r}")
    rollback = payload.get("rollback")
    if not isinstance(rollback, Mapping) or not rollback.get("baseline_commit"):
        raise ValueError("rollback.baseline_commit is required")
    flags = rollback.get("flags")
    if (
        not isinstance(flags, Mapping)
        or not flags
        or any(value is not False for value in flags.values())
    ):
        raise ValueError("all reserved unified rollout flags must be false")
    floors = payload.get("quality_floors")
    if not isinstance(floors, Mapping) or set(UNIFIED_METRICS) - set(floors):
        raise ValueError("quality_floors must name every unified metric")
    metric_defaults = payload.get("metric_defaults")
    if not isinstance(metric_defaults, Mapping) or set(UNIFIED_METRICS) - set(metric_defaults):
        raise ValueError("metric_defaults must name every unified metric")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a non-empty list")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenarios[{index}] must be an object")
        scenario_id = str(scenario.get("id") or "")
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"duplicate/empty scenario id: {scenario_id!r}")
        seen.add(scenario_id)
        if scenario.get("split") not in {"golden", "held_out"}:
            raise ValueError(f"scenario {scenario_id}: invalid split")
        snapshots = scenario.get("snapshots")
        if not isinstance(snapshots, Mapping):
            raise ValueError(f"scenario {scenario_id}: snapshots must be an object")
        missing_snapshots = set(UNIFIED_SNAPSHOT_FIELDS) - set(snapshots)
        if missing_snapshots:
            raise ValueError(
                f"scenario {scenario_id}: missing snapshots {sorted(missing_snapshots)}"
            )
        metrics = scenario.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ValueError(f"scenario {scenario_id}: metrics must be an object")
        for metric_name in UNIFIED_METRICS:
            metric = metrics.get(metric_name, metric_defaults.get(metric_name))
            if not isinstance(metric, Mapping):
                raise ValueError(f"scenario {scenario_id}: missing metric {metric_name}")
            availability = metric.get("availability")
            if availability not in {"measured", "derived", "unavailable"}:
                raise ValueError(
                    f"scenario {scenario_id}: invalid availability for {metric_name}"
                )
            value = metric.get("value")
            if availability == "unavailable" and value is not None:
                raise ValueError(
                    f"scenario {scenario_id}: unavailable {metric_name} must be null"
                )
            if availability != "unavailable" and not isinstance(value, (int, float)):
                raise ValueError(
                    f"scenario {scenario_id}: available {metric_name} needs a number"
                )
    _validate_anonymized_value(payload)


def _metric_availability(
    scenarios: Sequence[Mapping[str, Any]],
    name: str,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [scenario["metrics"].get(name, defaults[name]) for scenario in scenarios]
    values = [row["value"] for row in rows if row["availability"] != "unavailable"]
    availability_counts = Counter(str(row["availability"]) for row in rows)
    return {
        "availability": dict(sorted(availability_counts.items())),
        "available": len(values),
        "missing": len(rows) - len(values),
        "distribution": _distribution(values),
    }


def build_unified_phase0_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_unified_phase0_fixture(payload)
    scenarios = list(payload["scenarios"])
    return {
        "schema_version": payload["schema_version"],
        "baseline_commit": payload["rollback"]["baseline_commit"],
        "scenario_count": len(scenarios),
        "scenario_ids": [str(item["id"]) for item in scenarios],
        "splits": dict(sorted(Counter(str(item["split"]) for item in scenarios).items())),
        "flow_counts": dict(
            sorted(Counter(str(item["flow"]) for item in scenarios).items())
        ),
        "status_counts": dict(
            sorted(Counter(str(item["status"]) for item in scenarios).items())
        ),
        "metrics": {
            name: _metric_availability(scenarios, name, payload["metric_defaults"])
            for name in UNIFIED_METRICS
        },
        "quality_floors": dict(payload["quality_floors"]),
        "rollback": dict(payload["rollback"]),
    }


def verify_protected_fixtures(
    payload: Mapping[str, Any], *, root: str | Path
) -> dict[str, str]:
    validate_unified_phase0_fixture(payload)
    expected = payload.get("protected_fixtures")
    if not isinstance(expected, Mapping) or not expected:
        raise ValueError("protected_fixtures must be a non-empty object")
    result: dict[str, str] = {}
    for relative_path, expected_digest in expected.items():
        path = Path(root) / str(relative_path)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(expected_digest):
            raise ValueError(f"protected fixture changed: {relative_path}")
        result[str(relative_path)] = actual
    return result


def percentile(values: Sequence[float | int], quantile: float) -> float | None:
    """Continuous percentile, matching PostgreSQL percentile_cont."""
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    position = (len(clean) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    fraction = position - lower
    return clean[lower] + (clean[upper] - clean[lower]) * fraction


def _distribution(values: Sequence[float | int]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if value is not None]
    return {
        "n": len(clean),
        "p50": percentile(clean, 0.50),
        "p95": percentile(clean, 0.95),
        "p99": percentile(clean, 0.99),
        "min": min(clean) if clean else None,
        "max": max(clean) if clean else None,
    }


def _cohort(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [scenario["metrics"].get("duration_ms") for scenario in scenarios]
    planner_calls = [scenario["metrics"].get("planner_calls") for scenario in scenarios]
    tool_calls = [scenario["metrics"].get("tool_calls") for scenario in scenarios]
    llm_calls = [scenario["metrics"].get("llm_calls_inferred") for scenario in scenarios]
    token_totals = [
        scenario["metrics"].get("tokens", {}).get("total")
        for scenario in scenarios
        if scenario["metrics"].get("tokens", {}).get("total") is not None
    ]
    phase_timings = {
        phase: _distribution(
            [
                scenario["metrics"].get("phase_ms", {}).get(phase)
                for scenario in scenarios
                if scenario["metrics"].get("phase_ms", {}).get(phase) is not None
            ]
        )
        for phase in PHASE_NAMES
    }
    return {
        "count": len(scenarios),
        "status_counts": dict(
            sorted(
                Counter(
                    str(scenario["expected"]["terminal_status"])
                    for scenario in scenarios
                ).items()
            )
        ),
        "duration_ms": _distribution(durations),
        "planner_calls": _distribution(planner_calls),
        "tool_calls": _distribution(tool_calls),
        "llm_calls_inferred": _distribution(llm_calls),
        "tokens": {
            "coverage": len(token_totals),
            "missing": len(scenarios) - len(token_totals),
            "total": _distribution(token_totals),
        },
        "phase_ms": phase_timings,
    }


def build_baseline_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_scenario_fixture(payload)
    scenarios = list(payload["scenarios"])
    grader_counts: Counter[str] = Counter()
    known_failures: Counter[str] = Counter()
    target_annotated = 0
    target_correct = 0
    for scenario in scenarios:
        report = grade_trace(scenario["trace"])
        for result in report.results:
            grader_counts[f"{result.name}:{'pass' if result.passed else 'fail'}"] += 1
        known_failures.update(str(item) for item in scenario.get("known_failures") or [])
        expected = scenario.get("expected") or {}
        if expected.get("target_annotation") == "production_review":
            target_annotated += 1
            expected_refs = {str(item) for item in expected.get("target_refs") or []}
            observed_refs: set[str] = set()
            for event in scenario.get("trace") or []:
                event_type = str(event.get("event_type") or "")
                event_payload = event.get("payload") or {}
                if event_type == "tool_result":
                    observed_refs.update(str(item) for item in event_payload.get("record_ids") or [])
            if expected_refs and expected_refs <= observed_refs:
                target_correct += 1

    cohorts: dict[str, Any] = {"all": _cohort(scenarios)}
    for temperature in ("cold", "warm", "unknown"):
        selected = [item for item in scenarios if item["temperature"] == temperature]
        cohorts[temperature] = _cohort(selected)
    for split in ("golden", "held_out"):
        selected = [item for item in scenarios if item["split"] == split]
        cohorts[split] = _cohort(selected)

    return {
        "schema_version": payload["schema_version"],
        "captured_at": payload.get("captured_at"),
        "scenario_count": len(scenarios),
        "cohorts": cohorts,
        "grader_counts": dict(sorted(grader_counts.items())),
        "known_failures": dict(sorted(known_failures.items())),
        "target_accuracy": {
            "annotated": target_annotated,
            "correct": target_correct,
            "accuracy": target_correct / target_annotated if target_annotated else None,
            "coverage": target_annotated / len(scenarios),
        },
    }
