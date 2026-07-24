"""Phase-6 replay, shadow, canary, gates and rollback tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.agent.research.material_plan import normalize_candidates
from app.services.agent.research.sufficiency import evaluate_sufficiency
from app.services.agent.runtime.executor import _runtime_rollout_state
from app.services.agent.runtime.replay import (
    capture_unified_rollout_trace,
    compare_unified_shadow,
)
from app.services.agent.runtime.rollout import (
    MANDATORY_GATE_SPECS,
    SELECTOR_SCHEMA_V2,
    build_canary_decision,
    build_quality_report,
    planner_policy_active,
    run_rollback_drill,
    runtime_rollout_flags,
    selected_for_canary,
    validate_flag_sequence,
)
from scripts.agent_unified_phase6_report import DEFAULT_FIXTURE, build_report, check_report


def _all_flags(*, default_on: bool = False) -> dict[str, bool]:
    return {
        "unified_catalog": True,
        "typed_requirements": True,
        "unified_selector": True,
        "verified_pack_boundary": True,
        "planner_policy": True,
        "default_on": default_on,
    }


def test_unavailable_missing_inconclusive_and_not_measured_never_pass() -> None:
    for availability in ("unavailable", "missing", "inconclusive", "not_measured"):
        report = build_quality_report(
            {
                spec.name: {"availability": availability, "value": None}
                for spec in MANDATORY_GATE_SPECS
            },
            report_id="fixture",
            source_commit="fixture",
            owner="workspace-agent",
            compatibility_remove_after="2026-10-24",
        )
        assert report["default_on_allowed"] is False
        assert len(report["blocking_gates"]) == len(MANDATORY_GATE_SPECS)


def test_phase6_quality_report_is_attested_and_keeps_default_off() -> None:
    report = build_report(repeats=2)

    assert check_report(report) == []
    assert report["quality"]["attestation"]["kind"] == "sha256"
    assert report["quality"]["default_on_allowed"] is False
    assert report["rollout"]["default_on"] is False
    assert set(report["quality"]["blocking_gates"]) == {
        "relevant_recall",
        "irrelevant_selection_rate",
        "p95_latency_ms",
        "llm_calls_per_run",
        "selector_p95_latency_ms",
        "selector_p95_prompt_tokens",
    }
    assert report["selector_boundary_benchmark"]["registry_size"] == 256
    assert report["selector_boundary_benchmark"]["provider_latency_availability"] == "unavailable"
    assert report["selector_boundary_benchmark"]["estimated_prompt_tokens_chars_div_4"] > 30000
    assert report["offline_replay"]["stable"] is True
    assert report["offline_replay"]["scenario_count"] == 13
    assert report["offline_replay"]["answer_model_calls"] == 0
    assert report["shadow_comparison"]["side_effect_boundary_passed"] is True
    assert report["shadow_comparison"]["planner_decisions"]["shadow_noop_count"] == 1
    assert report["shadow_comparison"]["additive_search"]["shadow"]


def test_feature_sequence_canary_and_planner_boundary_are_deterministic() -> None:
    flags = _all_flags()
    assert validate_flag_sequence(flags) == []
    assert validate_flag_sequence({**flags, "typed_requirements": False})
    assert selected_for_canary("run:stable", 17.5) == selected_for_canary("run:stable", 17.5)
    assert build_canary_decision(
        run_key="run:stable",
        predicate_kind="structural",
        factual_percent=100,
        semantic_complete_percent=100,
        mandatory_gates_passed=False,
    )["selected"] is False
    assert build_canary_decision(
        run_key="run:stable",
        predicate_kind="semantic",
        factual_percent=0,
        semantic_complete_percent=100,
        mandatory_gates_passed=True,
    )["selected"] is True
    assert planner_policy_active(
        flags,
        selector_schema=SELECTOR_SCHEMA_V2,
        verified_pack_boundary=True,
    )
    assert not planner_policy_active(
        flags,
        selector_schema="workspace.context-selector/v1",
        verified_pack_boundary=True,
    )
    assert not planner_policy_active(
        flags,
        selector_schema=SELECTOR_SCHEMA_V2,
        verified_pack_boundary=False,
    )
    settings = type(
        "Settings",
        (),
        {
            "agent_unified_catalog_v1_enabled": True,
            "agent_typed_requirements_v1_enabled": True,
            "agent_unified_selector_v1_enabled": True,
            "agent_verified_pack_boundary_v1_enabled": True,
            "agent_planner_policy_v1_enabled": True,
            "agent_unified_default_on": True,
        },
    )()
    effective = runtime_rollout_flags(settings, contract_version=3)
    assert effective["planner_policy"] is True
    assert effective["default_on"] is False
    settings.agent_verified_pack_boundary_v1_enabled = False
    assert runtime_rollout_flags(settings, contract_version=3)["planner_policy"] is False
    settings.agent_planner_phase5_enabled = True
    settings.agent_adaptive_evidence_depth_v1_enabled = False
    resumed = _runtime_rollout_state(
        SimpleNamespace(settings=settings, turn_contract={"version": 3})
    )
    assert resumed == {
        "adaptive_evidence_depth_enabled": True,
        "unified_selector_enabled": True,
        "verified_pack_boundary_enabled": False,
        "planner_policy_enabled": False,
    }


def test_rollback_drill_preserves_durable_user_ledger_refs_and_evidence() -> None:
    checkpoint = {
        "user_message_id": "message:fixture",
        "search_ledger": [{"intent_key": "fixture"}],
        "known_context_refs": ["note:fixture"],
        "evidence_records": {"evidence:fixture": {"kind": "note_chunk"}},
        "evidence_ids": ["evidence:fixture"],
    }
    names = (
        "new_run",
        "resume_old_checkpoint",
        "selector_timeout",
        "catalog_schema_mismatch",
        "pack_budget_overflow",
    )
    drill = run_rollback_drill(
        _all_flags(),
        [
            {"name": name, "target": "planner_policy", "checkpoint": checkpoint}
            for name in names
        ],
    )

    assert drill["passed"] is True
    assert all(item["projection"]["preserved"] == checkpoint for item in drill["results"])


def test_rollout_trace_contains_policy_additive_search_and_no_source_text() -> None:
    state = {
        "status": "completed",
        "turn_contract": {"version": 3},
        "candidate_envelopes": [
            {
                "ref": "note:fixture",
                "origin": "authoritative_catalog",
                "semantic_score": None,
                "source_requirement_ids": ["workspace-notes"],
                "card_text": "must not be persisted in rollout trace",
            }
        ],
        "planner_steps": [
            {
                "schema": SELECTOR_SCHEMA_V2,
                "assessments": [{"ref": "note:fixture", "relevance": "direct"}],
                "source_dispositions": [{"source_id": "workspace-notes", "status": "selected"}],
                "visible_refs": ["note:fixture"],
                "attempts": 1,
            }
        ],
        "plan_decisions": [{"route": "CALL_CONTEXT_SELECTOR", "evidence_delta": 1}],
        "planner_noop_count": 1,
        "search_ledger": [
            {
                "search_relation": "additive_to_authoritative_catalog",
                "discovery_ref_count_before": 1,
                "discovery_ref_count_after": 1,
            }
        ],
        "material_plan": {"schema": "workspace.material-plan/v2", "coverage": "complete"},
        "evidence_pack": {
            "schema": "workspace.evidence-pack/v2",
            "evidence_ids": ["evidence:fixture"],
            "items": [
                {
                    "id": "evidence:fixture",
                    "source_ref": "note:fixture",
                    "fidelity": "full_text",
                    "content": "must not be persisted",
                }
            ],
            "coverage": "complete",
        },
        "claims": [{"claim_id": "claim:fixture", "evidence_ids": ["evidence:fixture"], "text": "omit"}],
    }
    trace = capture_unified_rollout_trace(
        state,
        run_metrics={
            "calls": [{"phase": "research.selector.context"}],
            "llm_calls": 1,
            "prompt_tokens": 100,
        },
        mode="shadow",
    )

    serialized = json.dumps(trace, sort_keys=True)
    assert "must not be persisted" not in serialized
    assert trace["policy"]["planner_noop_count"] == 1
    assert trace["selector"]["visible_refs"] == ["note:fixture"]
    assert trace["additive_search"][0]["discovery_ref_count_after"] == 1
    assert trace["answer_usage"]["answer_model_calls"] == 0

    active = capture_unified_rollout_trace(
        state,
        run_metrics={"calls": [{"phase": "answer"}]},
        mode="active",
    )
    comparison = compare_unified_shadow(active, trace)
    assert comparison["side_effect_boundary_passed"] is True
    assert comparison["shadow_answer_model_calls"] == 0
    assert comparison["user_answer_changed"] is False
    assert comparison["selector"]["shadow"]["schema"] == SELECTOR_SCHEMA_V2
    assert comparison["material_plan"]["shadow"]["schema"] == "workspace.material-plan/v2"


def test_registry_over_256_remains_incomplete_and_blocks_ready() -> None:
    contract = {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "coverage": "complete",
                "predicate_kind": "semantic",
                "selection_cardinality": {"min": 0, "max": 8},
                "required_fidelity": "full_text",
                "evidence_obligation": "optional",
            }
        ],
    }
    authoritative_refs = [f"note:fixture-{index:03d}" for index in range(257)]
    bounded_registry = normalize_candidates(
        (
            {
                "ref": ref,
                "origin": "authoritative_catalog",
                "source_requirement_id": "workspace-notes",
                "title": ref,
                "preview": "fixture",
            }
            for ref in authoritative_refs
        )
    )
    assessments = [
        {
            "ref": item["ref"],
            "relevance": "irrelevant",
            "role": "none",
            "resolution": "none",
            "confidence": 1,
            "reason_code": "not_relevant",
        }
        for item in bounded_registry
    ]
    state = {
        "coverage_targets_by_source": {"workspace-notes": authoritative_refs},
        "candidate_envelopes": bounded_registry,
        "material_plan": {
            "schema": "workspace.material-plan/v2",
            "assessments": assessments,
            "context_selection_done": True,
        },
        "evidence_records": {},
        "search_ledger": [],
    }
    sufficiency = evaluate_sufficiency(state=state, contract=contract).to_dict()

    assert len(bounded_registry) == 256
    assert len(authoritative_refs) == 257
    assert sufficiency["status"] != "ready"
    assert sufficiency["gaps"] == [
        {
            "schema": "workspace.evidence-gap/v1",
            "kind": "incomplete_assessment",
            "source_id": "workspace-notes",
            "required": "workspace-notes:assessment_coverage",
            "evidence_present": "1_refs_unassessed",
            "allowed_actions": ["assess_candidates"],
            "blocks_ready": True,
        }
    ]


def test_measurement_fixture_names_every_mandatory_gate() -> None:
    fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    assert {spec.name for spec in MANDATORY_GATE_SPECS} == set(fixture["measurements"])
