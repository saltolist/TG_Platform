"""Strict phase-6 rollout gates, canary allocation, and rollback drills.

This module is deliberately independent from answer generation.  It evaluates
observable artifacts and configuration only; importing or calling it cannot
invoke a model or mutate a run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


ROLLOUT_SCHEMA = "workspace.unified-rollout/v1"
SELECTOR_SCHEMA_V2 = "workspace.context-selector/v2"
VERIFIED_PACK_SCHEMA_V2 = "workspace.evidence-pack/v2"
ROLLOUT_FLAG_ORDER = (
    "unified_catalog",
    "typed_requirements",
    "unified_selector",
    "verified_pack_boundary",
    "planner_policy",
    "default_on",
)
NON_PASSING_AVAILABILITY = {
    "unavailable",
    "missing",
    "inconclusive",
    "not_measured",
    "derived",
}


class GateRule(StrEnum):
    EQUAL = "equal"
    MAX = "max"
    MIN = "min"
    BELOW_BASELINE = "below_baseline"
    NOT_BELOW_BASELINE = "not_below_baseline"


@dataclass(frozen=True)
class GateSpec:
    name: str
    rule: GateRule
    threshold: float | None = None
    baseline: float | None = None


MANDATORY_GATE_SPECS = (
    GateSpec("fallback_select_all_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("required_source_forced_selection_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("fidelity_mismatch_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("structural_count_error_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("card_only_exact_quote_edit_mutation_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("complete_coverage", GateRule.NOT_BELOW_BASELINE),
    GateSpec("relevant_recall", GateRule.NOT_BELOW_BASELINE),
    GateSpec("irrelevant_selection_rate", GateRule.MAX, threshold=0.0),
    GateSpec("p95_latency_ms", GateRule.MAX),
    GateSpec(
        "semantic_selector_initial_calls_per_selector_run",
        GateRule.MAX,
        threshold=1.0,
    ),
    GateSpec("selector_p95_latency_ms", GateRule.MAX),
    GateSpec("selector_p95_prompt_tokens", GateRule.MAX),
    GateSpec("selector_full_request_measured", GateRule.EQUAL, threshold=1.0),
    GateSpec("selector_provider_token_usage_measured", GateRule.EQUAL, threshold=1.0),
    GateSpec("selector_relevant_p95_total_tokens", GateRule.MAX, threshold=2500.0),
    GateSpec("selector_complete_sync_p95_total_tokens", GateRule.MAX, threshold=10000.0),
    GateSpec(
        "selector_complete_boundary_p95_total_tokens", GateRule.MAX, threshold=22000.0
    ),
    GateSpec("selector_schema_retry_telemetry_measured", GateRule.EQUAL, threshold=1.0),
    GateSpec("selector_schema_reliability_within_budget", GateRule.EQUAL),
    GateSpec("selector_first_attempt_valid_rate", GateRule.MIN, threshold=0.95),
    GateSpec("selector_final_valid_rate", GateRule.EQUAL, threshold=1.0),
    GateSpec("selector_retry_rate", GateRule.MAX, threshold=0.05),
    GateSpec("selector_position_error_count", GateRule.EQUAL, threshold=0.0),
    GateSpec(
        "answer_model_calls_after_final_selector_failure",
        GateRule.EQUAL,
        threshold=0.0,
    ),
    GateSpec(
        "complete_classification_required_object_coverage",
        GateRule.EQUAL,
        threshold=1.0,
    ),
    GateSpec("required_critical_evidence_recall", GateRule.EQUAL, threshold=1.0),
    GateSpec("selector_summary_160_non_inferior_recall", GateRule.EQUAL, threshold=1.0),
    GateSpec("capped_canary_chat_count", GateRule.MAX, threshold=20.0),
    GateSpec("capped_canary_max_user_messages_per_chat", GateRule.MAX, threshold=4.0),
    GateSpec("selector_summary_backfill_coverage", GateRule.EQUAL, threshold=1.0),
    GateSpec("compact_decoder_completeness", GateRule.EQUAL, threshold=1.0),
    GateSpec("sync_rollout_ceiling_guard", GateRule.EQUAL, threshold=1.0),
    GateSpec("checkpoint_resume_pass_rate", GateRule.EQUAL, threshold=1.0),
    GateSpec("interrupted_cancelled_pass_rate", GateRule.EQUAL, threshold=1.0),
    GateSpec("tenant_status_security_guard_pass_rate", GateRule.EQUAL, threshold=1.0),
    GateSpec("shadow_answer_model_calls", GateRule.EQUAL, threshold=0.0),
    GateSpec("shadow_user_answer_change_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("planner_trace_coverage", GateRule.EQUAL, threshold=1.0),
    GateSpec("additive_search_trace_coverage", GateRule.EQUAL, threshold=1.0),
    GateSpec("registry_overflow_ready_rate", GateRule.EQUAL, threshold=0.0),
    GateSpec("rollback_drill_pass_rate", GateRule.EQUAL, threshold=1.0),
    GateSpec("staging_canary_rollback_drill_pass_rate", GateRule.EQUAL, threshold=1.0),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evaluate_gate(spec: GateSpec, measurement: Mapping[str, Any] | None) -> dict[str, Any]:
    """Evaluate one gate. Only factual ``measured`` telemetry can pass."""

    row = dict(measurement or {})
    availability = str(row.get("availability") or "missing")
    value = _number(row.get("value"))
    threshold = _number(row.get("threshold"))
    baseline = _number(row.get("baseline"))
    if threshold is None:
        threshold = spec.threshold
    if baseline is None:
        baseline = spec.baseline

    passed = False
    reason = "measurement_not_available"
    if availability == "measured" and value is not None:
        if spec.rule == GateRule.EQUAL and threshold is not None:
            passed = value == threshold
        elif spec.rule == GateRule.MAX and threshold is not None:
            passed = value <= threshold
        elif spec.rule == GateRule.MIN and threshold is not None:
            passed = value >= threshold
        elif spec.rule == GateRule.BELOW_BASELINE and baseline is not None:
            passed = value < baseline
        elif spec.rule == GateRule.NOT_BELOW_BASELINE and baseline is not None:
            passed = value >= baseline
        reason = "threshold_passed" if passed else "threshold_failed_or_missing"
    elif availability not in NON_PASSING_AVAILABILITY:
        reason = "availability_must_be_measured"

    return {
        "name": spec.name,
        "rule": spec.rule.value,
        "availability": availability,
        "value": value,
        "threshold": threshold,
        "baseline": baseline,
        "sample_size": row.get("sample_size"),
        "source": row.get("source"),
        "passed": passed,
        "reason": reason,
    }


_SELECTOR_RELIABILITY_CHILDREN = (
    "selector_first_attempt_valid_rate",
    "selector_final_valid_rate",
    "selector_retry_rate",
    "selector_position_error_count",
)


def _selector_reliability_composite(
    measurements: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the canary reliability composite from factual child telemetry."""

    children = [dict(measurements.get(name) or {}) for name in _SELECTOR_RELIABILITY_CHILDREN]
    sample_sizes = [
        int(row.get("sample_size") or 0)
        for row in children
        if not isinstance(row.get("sample_size"), bool)
    ]
    values_present = all(_number(row.get("value")) is not None for row in children)
    measured = all(row.get("availability") == "measured" for row in children)
    sample_size = min(sample_sizes) if len(sample_sizes) == len(children) else 0
    source = "derived from formal canary Selector validity, retry, and position telemetry"
    if not values_present:
        return {
            "availability": "unavailable",
            "value": None,
            "threshold": 1.0,
            "sample_size": sample_size,
            "source": source,
        }
    if not measured or sample_size < 20:
        return {
            "availability": "inconclusive",
            "value": None,
            "threshold": 1.0,
            "sample_size": sample_size,
            "source": source,
        }

    first_attempt, final, retry, position_errors = (
        _number(row.get("value")) for row in children
    )
    passed = (
        first_attempt is not None
        and first_attempt >= 0.95
        and final == 1.0
        and retry is not None
        and retry <= 0.05
        and position_errors == 0.0
    )
    return {
        "availability": "measured",
        "value": 1.0 if passed else 0.0,
        "threshold": 1.0,
        "sample_size": sample_size,
        "source": source,
    }


def build_quality_report(
    measurements: Mapping[str, Mapping[str, Any]],
    *,
    report_id: str,
    source_commit: str,
    owner: str,
    compatibility_remove_after: str,
) -> dict[str, Any]:
    effective_measurements = dict(measurements)
    effective_measurements["selector_schema_reliability_within_budget"] = (
        _selector_reliability_composite(effective_measurements)
    )
    gates = [
        evaluate_gate(spec, effective_measurements.get(spec.name))
        for spec in MANDATORY_GATE_SPECS
    ]
    blocking = [gate["name"] for gate in gates if not gate["passed"]]
    body = {
        "schema": "workspace.unified-quality-report/v1",
        "report_id": report_id,
        "source_commit": source_commit,
        "owner": owner,
        "compatibility_path": {
            "owner": owner,
            "remove_after": compatibility_remove_after,
            "status": "retained_for_rollback",
        },
        "gate_replacements": [
            {
                "original": "llm_calls_per_run",
                "replacement": "semantic_selector_initial_calls_per_selector_run",
                "reason": "measure the initial semantic Selector boundary; total provider calls remain diagnostic",
            },
            {
                "original": "selector_monetary_ceiling_configured",
                "replacement": "capped_canary_chat_count",
                "reason": "rollout-owner capped pilot risk control; price remains unavailable",
            },
            {
                "original": "selector_cost_p95_within_ceiling",
                "replacement": "capped_canary_max_user_messages_per_chat",
                "reason": "rollout-owner capped pilot risk control; cost remains unavailable",
            },
        ],
        "gates": gates,
        "all_mandatory_gates_passed": not blocking,
        "blocking_gates": blocking,
        "default_on_allowed": not blocking,
    }
    canonical = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        **body,
        "attestation": {
            "kind": "sha256",
            "signed_by": owner,
            "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        },
    }


def canary_bucket(run_key: str) -> float:
    digest = hashlib.sha256(run_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64) * 100.0


def selected_for_canary(run_key: str, percent: float) -> bool:
    bounded = max(0.0, min(100.0, float(percent)))
    return bounded > 0 and canary_bucket(run_key) < bounded


def build_canary_decision(
    *,
    run_key: str,
    predicate_kind: str,
    factual_percent: float,
    semantic_complete_percent: float,
    mandatory_gates_passed: bool,
) -> dict[str, Any]:
    """Allocate a canary only after the signed mandatory gate decision passes."""

    semantic = str(predicate_kind or "").strip().lower() in {"semantic", "mixed"}
    stage = "semantic_complete" if semantic else "factual"
    percent = semantic_complete_percent if semantic else factual_percent
    selected = mandatory_gates_passed and selected_for_canary(run_key, percent)
    return {
        "schema": "workspace.unified-canary-decision/v1",
        "stage": stage,
        "bucket": round(canary_bucket(run_key), 6),
        "percent": max(0.0, min(100.0, float(percent))),
        "mandatory_gates_passed": mandatory_gates_passed,
        "selected": selected,
        "reason": (
            "selected"
            if selected
            else "outside_cohort"
            if mandatory_gates_passed
            else "quality_gates_blocked"
        ),
    }


def validate_flag_sequence(flags: Mapping[str, Any]) -> list[str]:
    """Return deterministic dependency violations without mutating settings."""

    violations: list[str] = []
    enabled_prefix = True
    for name in ROLLOUT_FLAG_ORDER:
        enabled = bool(flags.get(name))
        if enabled and not enabled_prefix:
            violations.append(f"{name}:previous_stage_disabled")
        enabled_prefix = enabled_prefix and enabled
    return violations


def runtime_rollout_flags(
    settings: Any,
    *,
    contract_version: int,
    mandatory_gates_passed: bool = False,
) -> dict[str, bool]:
    """Resolve configured flags into the only safe runtime activation prefix."""

    requested = {
        "unified_catalog": bool(
            getattr(settings, "agent_unified_catalog_v1_enabled", False)
        ),
        "typed_requirements": bool(
            getattr(settings, "agent_typed_requirements_v1_enabled", False)
        ),
        "unified_selector": bool(
            getattr(settings, "agent_unified_selector_v1_enabled", False)
        ),
        "verified_pack_boundary": bool(
            getattr(settings, "agent_verified_pack_boundary_v1_enabled", False)
        ),
        "planner_policy": bool(
            getattr(settings, "agent_planner_policy_v1_enabled", False)
        ),
        "default_on": bool(getattr(settings, "agent_unified_default_on", False)),
    }
    effective: dict[str, bool] = {}
    effective["unified_catalog"] = requested["unified_catalog"]
    effective["typed_requirements"] = bool(
        requested["typed_requirements"] and effective["unified_catalog"]
    )
    effective["unified_selector"] = bool(
        requested["unified_selector"]
        and effective["typed_requirements"]
        and contract_version >= 3
    )
    effective["verified_pack_boundary"] = bool(
        requested["verified_pack_boundary"] and effective["unified_selector"]
    )
    effective["planner_policy"] = bool(
        requested["planner_policy"]
        and effective["verified_pack_boundary"]
        and planner_policy_active(
            {
                **effective,
                "planner_policy": requested["planner_policy"],
                "default_on": False,
            },
            selector_schema=SELECTOR_SCHEMA_V2,
            verified_pack_boundary=effective["verified_pack_boundary"],
        )
    )
    effective["default_on"] = bool(
        requested["default_on"]
        and mandatory_gates_passed
        and all(effective[name] for name in ROLLOUT_FLAG_ORDER[:-1])
    )
    return effective


def planner_policy_active(
    flags: Mapping[str, Any],
    *,
    selector_schema: str,
    verified_pack_boundary: bool,
) -> bool:
    """Planner policy requires the sole v2 Selector and verified pack boundary."""

    return bool(
        flags.get("planner_policy")
        and flags.get("unified_selector")
        and flags.get("verified_pack_boundary")
        and selector_schema == SELECTOR_SCHEMA_V2
        and verified_pack_boundary
        and not validate_flag_sequence(flags)
    )


def rollback_projection(
    flags: Mapping[str, Any],
    *,
    target: str,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Disable the target and all later stages while preserving durable state."""

    if target not in ROLLOUT_FLAG_ORDER:
        raise ValueError(f"unknown rollout flag: {target}")
    cutoff = ROLLOUT_FLAG_ORDER.index(target)
    projected = {
        name: bool(flags.get(name)) if index < cutoff else False
        for index, name in enumerate(ROLLOUT_FLAG_ORDER)
    }
    durable = dict(checkpoint or {})
    preserved = {
        key: durable.get(key)
        for key in (
            "user_message_id",
            "search_ledger",
            "known_context_refs",
            "evidence_records",
            "evidence_ids",
            "turn_contract",
        )
        if key in durable
    }
    return {
        "schema": "workspace.unified-rollback-projection/v1",
        "disabled_from": target,
        "flags": projected,
        "preserved": preserved,
        "sequence_valid": not validate_flag_sequence(projected),
    }


def run_rollback_drill(
    flags: Mapping[str, Any],
    scenarios: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    required = {
        "flag_sequence",
        "new_run",
        "resume_old_checkpoint",
        "selector_timeout",
        "catalog_schema_mismatch",
        "pack_budget_overflow",
        "summary_backfill_interrupted",
        "compact_decode_failure",
    }
    for scenario in scenarios:
        name = str(scenario.get("name") or "")
        checkpoint = scenario.get("checkpoint")
        projection = rollback_projection(
            flags,
            target=str(scenario.get("target") or "planner_policy"),
            checkpoint=checkpoint if isinstance(checkpoint, Mapping) else None,
        )
        expected = {
            key: (checkpoint or {}).get(key)
            for key in (
                "user_message_id",
                "search_ledger",
                "known_context_refs",
                "evidence_records",
                "evidence_ids",
                "turn_contract",
            )
            if isinstance(checkpoint, Mapping) and key in checkpoint
        }
        passed = projection["sequence_valid"] and projection["preserved"] == expected
        results.append({"name": name, "passed": passed, "projection": projection})
    present = {item["name"] for item in results}
    return {
        "schema": "workspace.unified-rollback-drill/v1",
        "results": results,
        "required_scenarios_present": required <= present,
        "passed": required <= present and all(item["passed"] for item in results),
    }


__all__ = [
    "MANDATORY_GATE_SPECS",
    "NON_PASSING_AVAILABILITY",
    "ROLLOUT_FLAG_ORDER",
    "SELECTOR_SCHEMA_V2",
    "VERIFIED_PACK_SCHEMA_V2",
    "build_quality_report",
    "build_canary_decision",
    "canary_bucket",
    "evaluate_gate",
    "planner_policy_active",
    "rollback_projection",
    "runtime_rollout_flags",
    "run_rollback_drill",
    "selected_for_canary",
    "validate_flag_sequence",
]
