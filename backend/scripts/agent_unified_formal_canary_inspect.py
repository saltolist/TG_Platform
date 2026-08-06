"""Inspect one formal live canary decision without emitting source or user content."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import AgentEvent, AgentRun
from app.db.session import async_session_factory
from app.services.ai.semantic_summary import (
    SELECTOR_SEMANTIC_FLAGS_VERSION,
    SELECTOR_SUMMARY_VERSION,
)


DEFAULT_MANIFEST = (
    BACKEND_ROOT / "tests/fixtures/agent_unified_phase6/v6/formal_canary_manifest.json"
)
POSITION_ERRORS = {
    "wrong_cardinality",
    "unknown_position",
    "duplicate_position",
    "missing_position",
    "out_of_range_position",
}


def _agent_classifier_execution_is_valid(
    calls: list[Mapping[str, Any]],
) -> bool:
    """Require one successful agent classification on every user turn."""

    classifier_calls = [
        item for item in calls if item.get("phase") == "bootstrap.classifier"
    ]
    return len(classifier_calls) == 1 and classifier_calls[0].get("success") is True


def _selector_execution_is_valid(
    *,
    expected_retrieval: bool,
    selector_attempts: Any,
    primary_provider: list[Mapping[str, Any]],
    reassessment_required: bool,
    reassessment_provider: list[Mapping[str, Any]],
    precision: Mapping[str, Any],
    precision_provider: list[Mapping[str, Any]],
) -> bool:
    """Validate either an intentional direct finish or one clean selector pass."""

    direct_finish = (
        selector_attempts in {None, 0}
        and not primary_provider
        and not reassessment_required
        and not reassessment_provider
        and not precision.get("called")
        and not precision_provider
    )
    if direct_finish:
        return not expected_retrieval
    return (
        selector_attempts == 1
        and len(primary_provider) == 1
        and all(
            item.get("schema_result") == "valid" and not item.get("retry")
            for item in primary_provider
        )
        and (
            (not reassessment_required and not reassessment_provider)
            or (
                reassessment_required
                and len(reassessment_provider) == 1
                and reassessment_provider[0].get("schema_result") == "valid"
                and not reassessment_provider[0].get("retry")
            )
        )
        and (
            not precision.get("called")
            or (
                precision.get("schema_result") == "valid"
                and len(precision_provider) == 1
                and precision_provider[0].get("schema_result") == "valid"
                and not precision_provider[0].get("retry")
            )
        )
    )


def _reasoner_model_usage_is_valid(
    *, expected_retrieval: bool, research_models: set[str]
) -> bool:
    """Allow no selector model only for a direct non-retrieval finish."""

    return len(research_models) == 1 or (
        not expected_retrieval and not research_models
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def _materialized_candidate_refs(
    items: list[Mapping[str, Any]], candidates: list[Mapping[str, Any]]
) -> set[str]:
    refs: set[str] = set()
    ref_by_path = {
        str(candidate.get("citation_path") or ""): str(candidate.get("ref") or "")
        for candidate in candidates
        if candidate.get("citation_path") and candidate.get("ref")
    }
    for item in items:
        provenance = item.get("provenance") or {}
        selection = provenance.get("selection") or {}
        source_ref = str(item.get("source_ref") or provenance.get("source_ref") or "")
        if source_ref in ref_by_path:
            refs.add(ref_by_path[source_ref])
        for parent in (selection.get("parent"), provenance.get("parent")):
            if isinstance(parent, Mapping) and parent.get("ref"):
                refs.add(str(parent["ref"]))
    return refs


async def inspect(
    sequence: int,
    manifest_path: Path,
    *,
    run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sequence < 1 or sequence > len(manifest.get("scenarios") or ()):
        raise ValueError(
            f"sequence must be between 1 and {len(manifest.get('scenarios') or ())}"
        )
    scenario = manifest["scenarios"][sequence - 1]
    expected_retrieval = bool(scenario.get("expected_retrieval", True))
    async with async_session_factory() as session:
        runs = (
            await session.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(200))
        ).scalars().all()
        run = (
            next(item for item in runs if item.id == run_id)
            if run_id is not None
            else next(
                item
                for item in runs
                if _digest((item.snapshot or {}).get("user_text"))
                == scenario["query_digest"]
            )
        )
        events = (
            await session.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id)
                .order_by(AgentEvent.sequence)
            )
        ).scalars().all()

    trace = next(
        item.payload for item in reversed(events) if item.event_type == "unified_rollout_trace"
    )
    selector = trace.get("selector") or {}
    assessments = selector.get("assessments") or []
    selected = {
        str(item.get("ref") or "")
        for item in assessments
        if item.get("relevance") != "irrelevant"
    }
    expected = set(scenario.get("expected_refs") or [])
    supporting = set(scenario.get("allowed_supporting_refs") or [])
    critical = set(scenario.get("critical_refs") or [])
    frozen_irrelevant = set(scenario.get("irrelevant_refs") or [])
    final_items = (trace.get("final_pack") or {}).get("items") or []
    candidates = (run.snapshot or {}).get("candidate_envelopes") or []
    materialized = _materialized_candidate_refs(final_items, candidates)
    provider = selector.get("provider_observability") or []
    run_metrics = next(
        (
            event.payload
            for event in reversed(events)
            if event.event_type == "run_metrics"
        ),
        {},
    )
    runtime_calls = [
        item
        for item in run_metrics.get("calls") or []
        if isinstance(item, Mapping)
    ]
    primary_provider = [
        item
        for item in provider
        if item.get("phase")
        in {"research.selector.context", "research.selector.context_schema_retry"}
    ]
    precision_provider = [
        item
        for item in provider
        if str(item.get("phase") or "").startswith(
            "research.selector.context_precision_confirmation"
        )
    ]
    reassessment_provider = [
        item
        for item in provider
        if item.get("phase")
        in {
            "research.selector.context_evidence_reassessment",
            "research.selector.context_evidence_reassessment_schema_retry",
        }
    ]
    reassessment_required = any(
        (event.payload.get("evidence_escalation") or {}).get("reassessment") is True
        for event in events
        if event.event_type == "planner_step"
    )
    precision = selector.get("precision_confirmation") or {}
    selected_baseline = selector.get("selected_evidence_baseline") or {}
    baseline_refs = selected_baseline.get("selected_refs") or []
    baseline_evidence = selected_baseline.get("evidence") or []
    baseline_provenance_verified = (
        isinstance(baseline_refs, list)
        and len(set(baseline_refs)) == len(baseline_refs)
        and len(baseline_evidence) == len(baseline_refs)
        and all(
            isinstance(item, Mapping)
            and len(str(item.get("digest") or "")) == 16
            and int(item.get("chars") or 0) > 0
            for item in baseline_evidence
        )
    )
    material_plan = trace.get("material_plan") or {}
    source_requirements = {
        str(item.get("source_id") or "")
        for item in (trace.get("turn_contract") or {}).get("source_requirements") or []
        if isinstance(item, Mapping) and item.get("source_id")
    }
    source_dispositions = {
        str(item.get("source_id") or ""): str(item.get("status") or "")
        for item in material_plan.get("source_dispositions") or []
        if isinstance(item, Mapping) and item.get("source_id")
    }
    discharges = [
        dict(item)
        for item in material_plan.get("runtime_trace") or []
        if isinstance(item, Mapping)
        and item.get("kind") == "baseline_discharged_source_obligation"
    ]
    discharged_source_ids = {
        str(source_id)
        for item in discharges
        for source_id in item.get("source_ids") or []
        if str(source_id)
    }
    discharge_provenance_verified = all(
        source_id in source_requirements
        and source_dispositions.get(source_id) == "no_relevant_candidate"
        for source_id in discharged_source_ids
    )
    research_models = {
        str(item.get("model") or "")
        for item in provider
        if str(item.get("phase") or "").startswith("research.selector.")
        and item.get("model")
    }
    validation_errors = [
        str(code)
        for event in events
        if event.event_type == "planner_step"
        for code in event.payload.get("validation_error_codes") or []
    ]
    owner_verified = all(
        (item.get("provenance") or {}).get("owner_verified") is True for item in final_items
    )
    status_verified = all(
        (item.get("provenance") or {}).get("status_verified") is True for item in final_items
    )
    checks = {
        "completed": (
            run.status == "completed"
            and (trace.get("lifecycle") or {}).get("status") == "completed"
        ),
        "agent_classifier_called": _agent_classifier_execution_is_valid(
            runtime_calls
        ),
        "critical_recall": critical <= selected,
        "no_unexpected_selection": not (selected - expected - supporting),
        "no_frozen_irrelevant": not (selected & frozen_irrelevant),
        "no_unwanted_materialization": expected_retrieval or not materialized,
        "critical_materialized": critical <= materialized,
        "first_attempt_valid": _selector_execution_is_valid(
            expected_retrieval=expected_retrieval,
            selector_attempts=selector.get("attempts"),
            primary_provider=primary_provider,
            reassessment_required=reassessment_required,
            reassessment_provider=reassessment_provider,
            precision=precision,
            precision_provider=precision_provider,
        ),
        "no_validation_errors": not validation_errors,
        "no_position_errors": not (set(validation_errors) & POSITION_ERRORS),
        "cards_llm_current_fresh": all(
            item.get("card_origin") == "llm"
            and item.get("selector_summary_version") == SELECTOR_SUMMARY_VERSION
            and (item.get("selector_semantic_flags") or {}).get("v")
            == SELECTOR_SEMANTIC_FLAGS_VERSION
            and item.get("selector_summary_fresh") is True
            for item in candidates
        ),
        "provenance_verified": owner_verified and status_verified,
        "baseline_provenance_verified": baseline_provenance_verified,
        "source_obligation_discharge_provenance_verified": discharge_provenance_verified,
        "no_extra_opened_evidence_arbiter": not any(
            item.get("phase")
            == "research.selector.context_opened_recall_confirmation"
            for item in provider
        ),
        "single_reasoner_model": _reasoner_model_usage_is_valid(
            expected_retrieval=expected_retrieval,
            research_models=research_models,
        ),
    }
    observability = primary_provider[0] if primary_provider else {}
    return {
        "sequence": sequence,
        "scenario_id": scenario["scenario_id"],
        "expected_retrieval": expected_retrieval,
        "run_digest": _digest(run.id)[:16],
        "created_at": run.created_at.isoformat(),
        "candidate_count": len(candidates),
        "selected_refs": sorted(selected),
        "materialized_candidate_refs": sorted(materialized),
        "unexpected_refs": sorted(selected - expected - supporting),
        "missed_critical_refs": sorted(critical - selected),
        "selected_irrelevant_refs": sorted(selected & frozen_irrelevant),
        "selector_attempts": selector.get("attempts"),
        "precision_confirmation": {
            "called": bool(precision.get("called")),
            "schema_result": precision.get("schema_result"),
            "confirmed_refs": list(precision.get("confirmed_refs") or ()),
            "demoted_refs": list(precision.get("demoted_refs") or ()),
        },
        "schema_result": observability.get("schema_result"),
        "evidence_reassessment": {
            "required": reassessment_required,
            "provider_calls": len(reassessment_provider),
            "schema_results": [
                item.get("schema_result") for item in reassessment_provider
            ],
        },
        "selected_evidence_baseline": {
            "schema": selected_baseline.get("schema"),
            "selected_refs": list(baseline_refs),
            "provider_calls": int(selected_baseline.get("provider_calls") or 0),
        },
        "source_obligation_discharges": sorted(discharged_source_ids),
        "provider_total_tokens": observability.get("total_tokens"),
        "provider_duration_ms": observability.get("duration_ms"),
        "validation_error_codes": validation_errors,
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-id", type=uuid.UUID)
    args = parser.parse_args()
    result = asyncio.run(inspect(args.sequence, args.manifest, run_id=args.run_id))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
