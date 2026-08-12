"""Inspect one formal live canary decision without emitting source or user content."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
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
    BACKEND_ROOT / "tests/fixtures/agent_unified_phase6/v174/formal_canary_manifest.json"
)
POSITION_ERRORS = {
    "wrong_cardinality",
    "unknown_position",
    "duplicate_position",
    "missing_position",
    "out_of_range_position",
}
MAX_UNEXPECTED_REFS = 2

_NUMBER_WORDS = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
}


def _answer_numbers(value: Any) -> set[int]:
    text = str(value or "").lower()
    result = {
        int(match)
        for match in re.findall(r"(?<![\w.,])\d+(?![\w.,])", text)
    }
    result.update(
        number
        for word, number in _NUMBER_WORDS.items()
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text)
    )
    return result


def _sparse_nonsemantic_candidate(candidate: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "card_text", "preview", "selector_summary")
    ).strip()
    return len(text) <= 32 or sum(char.isalnum() for char in text) < 4


def _agent_classifier_execution_is_valid(
    calls: list[Mapping[str, Any]],
) -> bool:
    """Require one terminal success, allowing only failed retry attempts before it."""

    classifier_calls = [
        item for item in calls if item.get("phase") == "bootstrap.classifier"
    ]
    return bool(classifier_calls) and (
        classifier_calls[-1].get("success") is True
        and all(item.get("success") is False for item in classifier_calls[:-1])
    )


def _selector_execution_is_valid(
    *,
    expected_retrieval: bool,
    selector_attempts: Any,
    primary_provider: list[Mapping[str, Any]],
    reassessment_required: bool,
    reassessment_provider: list[Mapping[str, Any]],
    precision: Mapping[str, Any],
    precision_provider: list[Mapping[str, Any]],
    selected_refs: set[str] | None = None,
    materialized_refs: set[str] | None = None,
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
    if (
        not expected_retrieval
        and not (selected_refs or set())
        and not (materialized_refs or set())
        and selector_attempts in {None, 0, 1}
    ):
        # Recall-first execution may legitimately probe cards and opened text
        # before concluding that no workspace material is evidence for the
        # answer. Treat that as a clean no-evidence result, provided every
        # provider call used a valid non-retry transport contract.
        primary_clean = all(
            item.get("schema_result") == "valid" and not item.get("retry")
            for item in primary_provider
        )
        reassessment_clean = all(
            item.get("schema_result") == "valid" and not item.get("retry")
            for item in reassessment_provider
        )
        precision_clean = bool(precision.get("called")) and (
            precision.get("schema_result") == "valid"
            and bool(precision_provider)
            and all(
                item.get("schema_result") == "valid" and not item.get("retry")
                for item in precision_provider
            )
        )
        if primary_clean and reassessment_clean and precision_clean:
            return True
    primary_valid = (
        len(primary_provider) == 1
        and all(
            item.get("schema_result") == "valid" and not item.get("retry")
            for item in primary_provider
        )
    )
    precision_protocol = str(precision.get("precision_protocol") or "")
    final_precision_provider = [
        item
        for item in precision_provider
        if item.get("phase") == "research.selector.context_precision_confirmation"
    ]
    recall_lane_provider = [
        item
        for item in precision_provider
        if str(item.get("phase") or "").startswith(
            "research.selector.context_precision_confirmation."
        )
    ]
    suffix_phases = [str(item.get("phase") or "") for item in recall_lane_provider]
    legacy_obligation_lane_topology = (
        len(final_precision_provider) == 1
        and suffix_phases.count(
            "research.selector.context_precision_confirmation.lane_a"
        )
        == 1
        and suffix_phases.count(
            "research.selector.context_precision_confirmation.lane_b"
        )
        == 1
        and suffix_phases.count(
            "research.selector.context_precision_confirmation.adversarial"
        )
        == 1
        and suffix_phases.count(
            "research.selector.context_precision_confirmation.tie_breaker"
        )
        in {0, 1}
        and len(suffix_phases)
        == 3
        + suffix_phases.count(
            "research.selector.context_precision_confirmation.tie_breaker"
        )
    )
    single_owner_obligation_topology = (
        len(final_precision_provider) == 1
        and not suffix_phases
    )
    post_read_shard_phases = [
        phase
        for phase in suffix_phases
        if phase.startswith(
            "research.selector.context_precision_confirmation.row_shard_"
        )
    ]
    post_read_shard_topology = (
        precision_protocol == "post_read_assessment_v5"
        and len(final_precision_provider) == 1
        and len(post_read_shard_phases) == len(suffix_phases)
        and len(post_read_shard_phases) >= 1
    )
    obligation_shard_phases = [
        phase
        for phase in suffix_phases
        if phase.startswith(
            "research.selector.context_precision_confirmation.obligation_shard_"
        )
    ]
    missing_obligation_audit_phase = (
        "research.selector.context_precision_confirmation"
        ".missing_obligation_audit"
    )
    missing_obligation_audit_count = suffix_phases.count(
        missing_obligation_audit_phase
    )
    disjoint_obligation_shard_topology = (
        precision_protocol == "post_read_assessment_v5"
        and len(final_precision_provider) == 1
        and len(obligation_shard_phases) >= 1
        and missing_obligation_audit_count in {0, 1}
        and len(suffix_phases)
        == len(obligation_shard_phases) + missing_obligation_audit_count
    )
    post_read_audit_topology = (
        precision_protocol == "post_read_assessment_v5"
        and len(final_precision_provider) == 1
        and suffix_phases
        == [missing_obligation_audit_phase]
    )
    obligation_lane_topology = (
        single_owner_obligation_topology
        or legacy_obligation_lane_topology
        or post_read_shard_topology
        or disjoint_obligation_shard_topology
        or post_read_audit_topology
    )
    member_lane_topology = (
        len(final_precision_provider) == 1
        and len(recall_lane_provider) in {0, 2, 3}
    )
    post_read_single_owner = (
        reassessment_required
        and selector_attempts in {None, 0}
        and (primary_valid or not primary_provider)
        and not reassessment_provider
        and precision.get("called") is True
        and precision.get("schema_result") == "valid"
        and precision_protocol
        in {
            "member_classification_v1",
            "obligation_classification_v4",
            "post_read_label_v1",
            "post_read_label_v2",
            "post_read_assessment_v5",
        }
        and precision.get("membership_owner")
        in {None, "post_read", "deterministic_assembler"}
        and (
            obligation_lane_topology
            if precision_protocol
            in {
                "obligation_classification_v4",
                "post_read_label_v1",
                "post_read_label_v2",
                "post_read_assessment_v5",
            }
            else member_lane_topology
        )
        and len(precision_provider)
        == len(final_precision_provider) + len(recall_lane_provider)
        and all(
            item.get("schema_result") == "valid" and not item.get("retry")
            for item in precision_provider
        )
    )
    if post_read_single_owner:
        return True
    return (
        selector_attempts == 1
        and primary_valid
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
                and len(precision_provider)
                in (
                    {2, 3, 4, 5, 6}
                    if precision.get("precision_protocol")
                    == "parallel_semantic_adjudication_v1"
                    else ({1, 2} if reassessment_required else {1})
                )
                and all(
                    item.get("schema_result") == "valid"
                    and not item.get("retry")
                    for item in precision_provider
                )
            )
        )
    )


def _reasoner_model_usage_is_valid(
    *,
    expected_retrieval: bool,
    research_models: set[str],
    precision_protocol: str = "",
) -> bool:
    """Allow two independent semantic lanes, or no model for direct finish."""

    expected_models = {2} if precision_protocol == "parallel_semantic_adjudication_v1" else {1}
    return len(research_models) in expected_models or (
        not expected_retrieval and not research_models
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def _materialized_candidate_refs(
    items: list[Mapping[str, Any]], candidates: list[Mapping[str, Any]]
) -> set[str]:
    def canonical_source_ref(value: str) -> str:
        raw = str(value or "").strip()
        if raw.startswith(("note:", "post:", "attachment:", "image:")):
            return raw
        parts = [part for part in raw.strip("/").split("/") if part]
        if len(parts) >= 3 and parts[0] == "note" and parts[1] in {
            "global",
            "post",
        }:
            return f"note:{parts[2]}"
        if len(parts) >= 2 and parts[0] == "post":
            return f"post:{parts[1]}"
        return ""

    refs: set[str] = set()
    ref_by_path = {
        str(candidate.get("citation_path") or ""): str(candidate.get("ref") or "")
        for candidate in candidates
        if candidate.get("citation_path") and candidate.get("ref")
    }
    candidate_refs = {
        str(candidate.get("ref") or "")
        for candidate in candidates
        if candidate.get("ref")
    }
    for item in items:
        provenance = item.get("provenance") or {}
        selection = provenance.get("selection") or {}
        source_ref = str(item.get("source_ref") or provenance.get("source_ref") or "")
        canonical_ref = canonical_source_ref(source_ref)
        if canonical_ref:
            refs.add(canonical_ref)
        if source_ref in candidate_refs:
            refs.add(source_ref)
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
    expected_retrieval_value = scenario.get("expected_retrieval")
    # ``null`` in the manifest means the normal retrieval path. Only an
    # explicit false declares a no-workspace-evidence scenario.
    expected_retrieval = (
        True
        if expected_retrieval_value is None
        else bool(expected_retrieval_value)
    )
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
    answer_payload = next(
        (
            event.payload
            for event in reversed(events)
            if event.event_type == "answer"
            and not bool((event.payload or {}).get("partial"))
        ),
        {},
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
    turn_contract = trace.get("turn_contract") or {}
    query_ir_owner = str(turn_contract.get("query_ir_owner") or "")
    semantic_fallbacks = [
        str(item) for item in turn_contract.get("semantic_fallbacks") or ()
    ]
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
        (
            (item.get("provenance") or {}).get("owner_verified") is True
            or (
                item.get("fidelity") == "catalog"
                and (item.get("provenance") or {}).get("producer") == "rag_tools"
                and str(item.get("source_ref") or "") in {"/notes/", "/posts/"}
            )
        )
        for item in final_items
    )
    status_verified = all(
        (
            (item.get("provenance") or {}).get("status_verified") is True
            or (
                item.get("fidelity") == "catalog"
                and (item.get("provenance") or {}).get("producer") == "rag_tools"
                and str(item.get("source_ref") or "") in {"/notes/", "/posts/"}
            )
        )
        for item in final_items
    )
    cards_current_fresh = all(
        _sparse_nonsemantic_candidate(item)
        or (
            item.get("card_origin") == "llm"
            and item.get("selector_summary_version") == SELECTOR_SUMMARY_VERSION
            and (item.get("selector_semantic_flags") or {}).get("v")
            == SELECTOR_SEMANTIC_FLAGS_VERSION
            and item.get("selector_summary_fresh") is True
        )
        for item in candidates
    )
    full_read_membership_verified = bool(
        precision.get("called")
        and precision.get("schema_result") == "valid"
        and precision.get("precision_protocol")
        in {
            "member_classification_v1",
            "post_read_label_v1",
            "post_read_label_v2",
            "post_read_assessment_v5",
        }
        and precision.get("membership_owner")
        in {"post_read", "deterministic_assembler"}
        and selected
        == {
            str(ref)
            for ref in precision.get("confirmed_refs") or ()
            if str(ref)
        }
    )
    unexpected_refs = selected - expected - supporting
    selected_irrelevant_refs = selected & frozen_irrelevant
    allowed_material_kinds = {
        str(item).strip().lower()
        for item in scenario.get("allowed_material_kinds") or ()
        if str(item).strip()
    }
    selected_material_kinds = {
        ref.split(":", 1)[0]
        for ref in selected | materialized
        if ":" in ref
    }
    expected_answer_numbers = {
        int(item) for item in scenario.get("expected_answer_numbers") or ()
    }
    actual_answer_numbers = _answer_numbers(answer_payload.get("text"))
    require_workspace_search = bool(scenario.get("require_workspace_search"))
    workspace_search_observed = bool(
        candidates
        or trace.get("additive_search")
        or precision.get("called")
        or primary_provider
        or reassessment_provider
    )
    deterministic_catalog_route = bool(final_items) and all(
        item.get("fidelity") == "catalog" for item in final_items
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
        "bounded_unexpected_selection": (
            len(unexpected_refs) <= MAX_UNEXPECTED_REFS
        ),
        "no_unwanted_materialization": expected_retrieval or not materialized,
        "critical_materialized": critical <= materialized,
        "first_attempt_valid": deterministic_catalog_route
        or _selector_execution_is_valid(
            expected_retrieval=expected_retrieval,
            selector_attempts=selector.get("attempts"),
            primary_provider=primary_provider,
            reassessment_required=reassessment_required,
            reassessment_provider=reassessment_provider,
            precision=precision,
            precision_provider=precision_provider,
            selected_refs=selected,
            materialized_refs=materialized,
        ),
        "no_validation_errors": not validation_errors,
        "no_position_errors": not (set(validation_errors) & POSITION_ERRORS),
        "card_inputs_safe": cards_current_fresh or full_read_membership_verified,
        "provenance_verified": owner_verified and status_verified,
        "baseline_provenance_verified": baseline_provenance_verified,
        "source_obligation_discharge_provenance_verified": discharge_provenance_verified,
        "no_extra_opened_evidence_arbiter": not any(
            item.get("phase")
            == "research.selector.context_opened_recall_confirmation"
            for item in provider
        ),
        "single_reasoner_model": deterministic_catalog_route
        or _reasoner_model_usage_is_valid(
            expected_retrieval=expected_retrieval,
            research_models=research_models,
            precision_protocol=str(precision.get("precision_protocol") or ""),
        ),
        "expected_answer_numbers_present": (
            not expected_answer_numbers
            or expected_answer_numbers <= actual_answer_numbers
        ),
        "workspace_search_observed": (
            not require_workspace_search or workspace_search_observed
        ),
        "planner_owned_query_ir": (
            query_ir_owner == "bootstrap_planner" and not semantic_fallbacks
        ),
    }
    retrieval_outcome = (
        "evidence_selected"
        if selected or materialized
        else "searched_no_evidence"
        if precision.get("called") or primary_provider or reassessment_provider
        else "direct_finish"
    )
    observability = primary_provider[0] if primary_provider else {}
    return {
        "sequence": sequence,
        "scenario_id": scenario["scenario_id"],
        "expected_retrieval": expected_retrieval,
        "retrieval_outcome": retrieval_outcome,
        "run_digest": _digest(run.id)[:16],
        "created_at": run.created_at.isoformat(),
        "candidate_count": len(candidates),
        "selected_refs": sorted(selected),
        "materialized_candidate_refs": sorted(materialized),
        "unexpected_refs": sorted(unexpected_refs),
        "selected_material_kinds": sorted(selected_material_kinds),
        "expected_answer_numbers": sorted(expected_answer_numbers),
        "actual_answer_numbers": sorted(actual_answer_numbers),
        "workspace_search_observed": workspace_search_observed,
        "query_ir_owner": query_ir_owner,
        "semantic_fallbacks": semantic_fallbacks,
        "unexpected_count": len(unexpected_refs),
        "unexpected_budget": MAX_UNEXPECTED_REFS,
        "missed_critical_refs": sorted(critical - selected),
        "selected_irrelevant_refs": sorted(selected_irrelevant_refs),
        "selector_attempts": selector.get("attempts"),
        "precision_confirmation": {
            "called": bool(precision.get("called")),
            "schema_result": precision.get("schema_result"),
            "precision_protocol": precision.get("precision_protocol"),
            "membership_owner": precision.get("membership_owner"),
            "decision_obligations": list(precision.get("decision_obligations") or ()),
            "obligation_assignments": list(
                precision.get("obligation_assignments") or ()
            ),
            "registry_refs": list(precision.get("registry_refs") or ()),
            "deterministic_assembler": dict(
                precision.get("deterministic_assembler") or {}
            ),
            "confirmed_refs": list(precision.get("confirmed_refs") or ()),
            "demoted_refs": list(precision.get("demoted_refs") or ()),
            "post_read_lane_count": precision.get("post_read_lane_count"),
            "post_read_lanes": list(precision.get("post_read_lanes") or ()),
            "post_read_lane_errors": list(
                precision.get("post_read_lane_errors") or ()
            ),
            "post_read_disputed_edges": list(
                precision.get("post_read_disputed_edges") or ()
            ),
            "post_read_primary_edges": list(
                precision.get("post_read_primary_edges") or ()
            ),
            "post_read_audit_edges": list(
                precision.get("post_read_audit_edges") or ()
            ),
            "post_read_merge_mode": precision.get("post_read_merge_mode"),
            "post_read_assessment_call_count": precision.get(
                "post_read_assessment_call_count"
            ),
            "post_read_assessment_mode": precision.get(
                "post_read_assessment_mode"
            ),
            "post_read_shards": list(precision.get("post_read_shards") or ()),
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
