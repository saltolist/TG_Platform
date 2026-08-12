"""Unified integrity phase-5 planner policy, additive search and fast-path tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.catalog import build_catalog_snapshot
from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.evidence_pack import build_verified_evidence_pack
from app.services.agent.research.graph import (
    _compact_planner_node,
    _selector_candidate_limit,
    _semantic_selector_candidates,
    _structural_prefilter_candidates,
)
from app.services.agent.research.material_plan import (
    MATERIAL_PLAN_SCHEMA_V2,
    normalize_candidates,
)
from app.services.agent.research.planner_decision import (
    PlanDecisionRoute,
    decide_plan_route,
    planner_state_signature,
)
from app.services.agent.research.search_ledger import annotate_additive_search
from app.services.agent.research.sufficiency import evaluate_sufficiency
from app.services.agent.runtime.turn_contract import build_turn_contract
from app.services.agent.runtime.graders import grade_finish_ready_has_no_blockers


def _typed_contract(question: str) -> dict:
    return build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        typed_requirements_enabled=True,
    )


def _planner_context() -> SimpleNamespace:
    return SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="test"),
        reasoner_model="test-model",
        reasoner_api_key="key",
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )


def test_structural_contract_selects_traceable_fast_path() -> None:
    contract = _typed_contract("Сколько заметок с изображениями?")
    sufficiency = {
        "status": "ready",
        "open_requirements": [],
        "gaps": [],
        "allowed_next_intent_ids": [],
    }

    decision = decide_plan_route(contract=contract, state={}, sufficiency=sufficiency)

    assert decision.route == PlanDecisionRoute.USE_FAST_PATH
    assert decision.reason_code == "STRUCTURAL_PREDICATE"
    assert decision.blocks_ready is False


def test_planner_noop_is_deterministic_without_authoritative_delta() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    sufficiency = {
        "status": "follow_up_allowed",
        "open_requirements": ["workspace-notes:discovery"],
        "gaps": [
            {
                "kind": "missing_discovery",
                "source_id": "workspace-notes",
                "required": "workspace-notes:discovery",
            }
        ],
        "allowed_next_intent_ids": [],
    }
    signature = planner_state_signature({}, sufficiency)

    decision = decide_plan_route(
        contract=contract,
        state={"planner_input_signatures": [signature]},
        sufficiency=sufficiency,
    )

    assert decision.route == PlanDecisionRoute.PLANNER_NOOP
    assert decision.reason_code == "NO_AUTHORITATIVE_STATE_DELTA"
    assert decision.blocks_ready is True


def test_authoritative_discovery_state_delta_allows_one_new_planner_call() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    sufficiency = {
        "status": "follow_up_allowed",
        "open_requirements": ["workspace-notes:discovery"],
        "gaps": [
            {
                "kind": "missing_discovery",
                "source_id": "workspace-notes",
                "required": "workspace-notes:discovery",
            }
        ],
        "allowed_next_intent_ids": [],
    }
    old_signature = planner_state_signature({}, sufficiency)
    changed_state = {
        "planner_input_signatures": [old_signature],
        "search_ledger": [
            {
                "intent_key": "workspace-notes:search",
                "state": "exhausted",
                "exhausted_reason": "empty_result",
            }
        ],
    }

    decision = decide_plan_route(
        contract=contract,
        state=changed_state,
        sufficiency=sufficiency,
    )

    assert decision.route == PlanDecisionRoute.CALL_ACTION_PLANNER
    assert decision.state_signature != old_signature


def test_additive_search_trace_never_shrinks_authoritative_coverage() -> None:
    ledger = [
        {
            "tool": "SearchNodes",
            "source_requirement_id": "workspace-notes",
            "state": "satisfied",
        }
    ]
    traced = annotate_additive_search(
        ledger,
        source_requirement_id="workspace-notes",
        authoritative_refs=["note:a", "note:b", "note:c"],
        hits=[{"ref": "note:c"}, {"ref": "note:related"}],
    )

    assert traced[0]["search_relation"] == "additive_to_authoritative_catalog"
    assert traced[0]["discovery_ref_count_before"] == 3
    assert traced[0]["discovery_ref_count_after"] == 3
    assert traced[0]["ranked_authoritative_ref_count"] == 1
    assert traced[0]["related_candidate_count"] == 1


def test_semantic_ranking_enriches_catalog_without_replacing_members() -> None:
    catalog = [
        {
            "ref": f"note:{name}",
            "title": name,
            "preview": name,
            "origin": "authoritative_catalog",
            "source_requirement_id": "workspace-notes",
        }
        for name in ("a", "b", "c")
    ]
    search = [
        {
            "ref": "note:c",
            "title": "c",
            "preview": "ranked fragment",
            "origin": "semantic_search",
            "semantic_score": 0.99,
            "source_requirement_id": "workspace-notes",
        }
    ]

    merged = normalize_candidates([*catalog, *search])

    assert {item["ref"] for item in merged} == {"note:a", "note:b", "note:c"}
    ranked = next(item for item in merged if item["ref"] == "note:c")
    assert ranked["origin"] == "authoritative_catalog"
    assert ranked["semantic_score"] is None
    assert ranked["semantic_rank_score"] == pytest.approx(0.99)
    assert ranked["search_enriched"] is True


def test_complete_semantic_registry_over_one_hundred_stays_in_one_selector_input() -> None:
    contract = {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "coverage": "complete",
                "predicate_kind": "semantic",
            }
        ],
    }
    candidates = normalize_candidates(
        [
            {
                "ref": f"note:n-{index:03d}",
                "title": f"N {index}",
                "preview": f"Card {index}",
                "origin": "authoritative_catalog",
                "source_requirement_id": "workspace-notes",
            }
            for index in range(101)
        ]
    )

    selector_input = _semantic_selector_candidates(candidates, contract=contract)

    assert len(candidates) == 101
    assert len(selector_input) == 101
    assert _selector_candidate_limit(contract) == 256


def test_mixed_flow_structural_prefilter_runs_before_selector_and_preserves_unknown() -> None:
    contract = {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "predicate_kind": "mixed",
                "evidence_requirements": [
                    {
                        "subject": "notes",
                        "property": "has_images",
                        "operator": "filter",
                    }
                ],
            }
        ],
    }
    candidates = [
        {"ref": "note:yes", "source_requirement_id": "workspace-notes", "has_images": True},
        {"ref": "note:no", "source_requirement_id": "workspace-notes", "has_images": False},
        {"ref": "note:unknown", "source_requirement_id": "workspace-notes", "has_images": None},
    ]

    filtered, trace = _structural_prefilter_candidates(candidates, contract=contract)

    assert [item["ref"] for item in filtered] == ["note:yes"]
    assert trace["rejected_refs"] == ["note:no"]
    assert trace["unknown_refs"] == ["note:unknown"]
    assert trace["unknown_is_false"] is False


def test_post_image_result_sets_separate_direct_nested_and_union_without_double_count() -> None:
    snapshot = build_catalog_snapshot(
        [
            {
                "id": "both",
                "status": "draft",
                "text": "Both",
                "media": [{"id": "direct", "type": "image/png"}],
                "notes": [
                    {
                        "id": "nested",
                        "files": [{"id": "nested-image", "type": "image/jpeg"}],
                    }
                ],
            },
            {
                "id": "nested-only",
                "status": "draft",
                "text": "Nested",
                "media": [],
                "notes": [
                    {
                        "id": "nested-2",
                        "files": [{"id": "nested-image-2", "type": "image/webp"}],
                    }
                ],
            },
        ],
        kind="posts",
        source_requirement_id="workspace-posts",
    )

    assert snapshot["aggregates"]["direct_image_count"] == 1
    assert snapshot["aggregates"]["note_image_files_total"] == 2
    assert snapshot["aggregates"]["posts_with_any_images"] == 2
    assert snapshot["result_sets"]["posts_with_direct_images"] == ["post:both"]
    assert snapshot["result_sets"]["posts_with_images_in_notes"] == [
        "post:both",
        "post:nested-only",
    ]
    assert snapshot["result_sets"]["posts_with_any_images"] == [
        "post:both",
        "post:nested-only",
    ]


@pytest.mark.asyncio
async def test_finish_ready_with_typed_gap_is_rejected_deterministically() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    state = {
        "user_text": "Какие заметки про запуск?",
        "turn_contract": contract,
        "evidence_records": {},
        "prefetch_hits": [],
        "candidate_envelopes": [],
        "search_ledger": [],
        "material_plan": {"schema": MATERIAL_PLAN_SCHEMA_V2},
        "phase5_enabled": True,
        "adaptive_evidence_depth_enabled": True,
        "unified_selector_enabled": True,
        "planner_policy_enabled": True,
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "planner_input_signatures": [],
        "step_count": 0,
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=json.dumps(
            {
                "decision_code": "FINISH_READY",
                "actions": [],
                "state_updates": {},
                "confidence": 1.0,
            }
        ),
    ) as llm:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _planner_context(), "turn_contract": contract}},
        )

    assert llm.await_count == 1
    assert result["tool_action"]["requested_status"] != "ready"
    assert result["planner_steps"][-1]["decision_code"] != "FINISH_READY"


@pytest.mark.asyncio
async def test_repeated_planner_input_is_noop_and_makes_no_llm_call() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    state = {
        "user_text": "Какие заметки про запуск?",
        "turn_contract": contract,
        "evidence_records": {},
        "prefetch_hits": [],
        "candidate_envelopes": [],
        "search_ledger": [],
        "material_plan": {"schema": MATERIAL_PLAN_SCHEMA_V2},
        "phase5_enabled": True,
        "adaptive_evidence_depth_enabled": True,
        "unified_selector_enabled": True,
        "planner_policy_enabled": True,
        "planner_calls_used": 1,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }
    sufficiency = evaluate_sufficiency(state=state, contract=contract).to_dict()
    state["planner_input_signatures"] = [planner_state_signature(state, sufficiency)]
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as llm:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _planner_context(), "turn_contract": contract}},
        )

    assert llm.await_count == 0
    assert result["tool_action"]["decision_code"] == "PLANNER_NOOP"
    assert result["planner_noop_count"] == 1


@pytest.mark.asyncio
async def test_structural_fast_path_finishes_without_llm_even_when_catalog_is_paged() -> None:
    contract = _typed_contract("Сколько заметок с изображениями?")
    source_id = next(
        source["source_id"]
        for source in contract["source_requirements"]
        if source["kind"] == "notes"
    )
    snapshot = build_catalog_snapshot(
        [
            {
                "id": f"n-{index:03d}",
                "title": f"N {index}",
                "files": ([{"id": f"i-{index}", "type": "image/png"}] if index % 2 else []),
            }
            for index in range(101)
        ],
        kind="notes",
        source_requirement_id=source_id,
    )
    record = EvidenceRecord(
        id="/notes/",
        kind="catalog",
        source_ref="/notes/",
        content="catalog",
        citation_path="/notes/",
        citation_title="Notes",
        metadata={"catalog_snapshot": snapshot},
    )
    state = {
        "user_text": "Сколько заметок с изображениями?",
        "turn_contract": contract,
        "evidence_records": {record.id: record.to_dict()},
        "catalog_snapshots": {record.id: snapshot},
        "coverage_targets_by_source": {},
        "search_ledger": [],
        "material_plan": {"schema": MATERIAL_PLAN_SCHEMA_V2},
        "phase5_enabled": True,
        "adaptive_evidence_depth_enabled": True,
        "unified_selector_enabled": True,
        "planner_policy_enabled": True,
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as llm:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _planner_context(), "turn_contract": contract}},
        )

    assert snapshot["members_complete"] is False
    assert snapshot["aggregates"]["notes_with_images"] == 50
    assert len(snapshot["result_sets"]["notes_with_images"]) == 50
    assert llm.await_count == 0
    assert result["tool_action"]["requested_status"] == "ready"
    assert result["tool_action"]["decision_code"] == "USE_FAST_PATH"


def test_verified_structural_pack_exposes_backend_projection() -> None:
    snapshot = build_catalog_snapshot(
        [{"id": "n1", "title": "N1", "files": [{"id": "i1", "type": "image/png"}]}],
        kind="notes",
        source_requirement_id="workspace-notes",
    )
    record = EvidenceRecord(
        id="/notes/",
        kind="catalog",
        source_ref="/notes/",
        content="catalog",
        citation_path="/notes/",
        citation_title="Notes",
        metadata={"catalog_snapshot": snapshot},
    )
    contract = {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "predicate_kind": "structural",
                "coverage": "complete",
                "evidence_requirements": [
                    {"subject": "notes", "property": "has_images"},
                    {"subject": "notes", "property": "image_count"},
                ],
            }
        ],
    }
    pack = build_verified_evidence_pack(
        records={record.id: record},
        evidence_ids=[record.id],
        material_plan={"schema": MATERIAL_PLAN_SCHEMA_V2, "materialization_queue": [], "candidates": []},
        contract=contract,
        item_annotations={record.id: {"source_requirement_id": "workspace-notes"}},
    )

    assert len(pack.items) == 1
    projection = json.loads(pack.items[0].content.split("Backend structural result:\n", 1)[1])
    assert projection["aggregates"]["notes_with_images"] == 1
    assert projection["aggregates"]["image_files_total"] == 1
    assert projection["result_sets"]["notes_with_images"] == ["note:n1"]


def test_ready_grader_rejects_open_typed_gap() -> None:
    result = grade_finish_ready_has_no_blockers(
        {
            "turn_contract": {"version": 3},
            "planner_policy_enabled": True,
            "stopped_reason": "ready",
            "sufficiency": {
                "status": "follow_up_allowed",
                "open_requirements": ["notes.has_images"],
                "allowed_next_intent_ids": [],
                "gaps": [
                    {
                        "kind": "missing_property",
                        "required": "notes.has_images",
                        "blocks_ready": True,
                    }
                ],
            },
        }
    )

    assert result.passed is False
