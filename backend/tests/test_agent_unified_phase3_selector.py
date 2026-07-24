"""Unified phase 3: one complete semantic Context Selector."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.graph import (
    _compact_planner_node,
    _semantic_selector_candidates,
    _unified_selector_decision_is_valid,
)
from app.services.agent.research.material_plan import (
    empty_material_plan,
    merge_material_plan,
    normalize_candidates,
)
from app.services.agent.research.planner_decision import (
    ContextSelectorDecision,
    parse_context_selector_decision,
)
from app.services.agent.research.sufficiency import evaluate_sufficiency


def _source(
    source_id: str,
    *,
    predicate_kind: str = "semantic",
    minimum: int = 0,
    maximum: int = 16,
    discovery: str = "required",
    evidence: str = "optional",
) -> dict:
    return {
        "source_id": source_id,
        "kind": "posts" if source_id.endswith("posts") else "notes",
        "discovery_obligation": discovery,
        "evidence_obligation": evidence,
        "selection_cardinality": {"min": minimum, "max": maximum},
        "coverage": "relevant",
        "predicate_kind": predicate_kind,
        "required_fidelity": "semantic_card",
        "evidence_requirements": [],
    }


def _contract(*sources: dict, planner_calls: int = 2) -> dict:
    return {
        "schema": "workspace.turn/v3",
        "version": 3,
        "source_requirements": list(sources),
        "budgets": {"planner_calls": planner_calls, "deep_reads": 3},
        "plan_decision": {"route": "typed_planner", "reason_code": "SEMANTIC_PREDICATE"},
    }


def _candidate(
    ref: str,
    *,
    source: str = "workspace-notes",
    origin: str = "semantic_search",
    score: float | None = 0.8,
    parent_post_id: str | None = None,
) -> dict:
    return {
        "ref": ref,
        "title": ref,
        "preview": f"Card for {ref}",
        "origin": origin,
        "semantic_score": score,
        "source_requirement_id": source,
        "parent_post_id": parent_post_id,
        "index_revision": 1,
        "source_revision": 1,
        "summary_version": 1,
        "summary_model": "llm:provider:model:v1",
        "status": "active",
    }


def _state(contract: dict, candidates: list[dict], *, material_plan: dict | None = None) -> dict:
    return {
        "user_text": "Что относится к теме?",
        "turn_contract": contract,
        "adaptive_evidence_depth_enabled": True,
        "unified_selector_enabled": True,
        "candidate_envelopes": candidates,
        "material_plan": material_plan or empty_material_plan(),
        "evidence_records": {},
        "search_ledger": [],
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="test"),
        reasoner_model="selector",
        reasoner_api_key="key",
        planner_llm=None,
    )


def test_selector_schema_requires_complete_typed_assessments() -> None:
    raw = {
        "assessments": [
            {
                "ref": "note:n1",
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 0.9,
                "reason_code": "unrelated_topic",
            }
        ],
        "source_dispositions": [
            {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
        ],
    }
    assert parse_context_selector_decision(json.dumps(raw)) is not None
    assert parse_context_selector_decision(
        json.dumps({**raw, "assessments": [*raw["assessments"], raw["assessments"][0]]})
    ) is None
    inconsistent = dict(raw["assessments"][0], relevance="direct")
    assert parse_context_selector_decision(
        json.dumps({**raw, "assessments": [inconsistent]})
    ) is None


def test_selector_completeness_unknown_refs_dispositions_and_truthful_negative() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes", minimum=1))
    negative = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": item["ref"],
                    "relevance": "irrelevant",
                    "role": "none",
                    "resolution": "none",
                    "confidence": 0.9,
                    "reason_code": "unrelated_topic",
                }
                for item in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
            ],
        }
    )
    assert _unified_selector_decision_is_valid(
        negative,
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
    )

    incomplete = negative.model_copy(update={"assessments": negative.assessments[:1]})
    assert not _unified_selector_decision_is_valid(
        incomplete,
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
    )
    unknown_source = negative.model_copy(
        update={
            "source_dispositions": (
                negative.source_dispositions[0].model_copy(update={"source_id": "unknown"}),
            )
        }
    )
    assert not _unified_selector_decision_is_valid(
        unknown_source,
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
    )


def test_candidate_envelope_separates_inclusion_score_sources_and_parent() -> None:
    candidates = normalize_candidates(
        [
            _candidate(
                "note:n1",
                source="workspace-notes",
                origin="ambient_current_post",
                score=1.0,
                parent_post_id="p1",
            ),
            _candidate("note:n1", source="secondary-notes", score=0.99),
        ]
    )
    assert len(candidates) == 1
    envelope = candidates[0]
    assert envelope["schema"] == "workspace.candidate-envelope/v1"
    assert envelope["origin"] == "ambient_current_post"
    assert envelope["inclusion_priority"] == 10
    assert envelope["semantic_score"] is None
    assert envelope["source_requirement_ids"] == ["workspace-notes", "secondary-notes"]
    assert envelope["parent"] == {"kind": "post", "ref": "post:p1"}
    assert "full_text" in envelope["available_fidelity"]


@pytest.mark.asyncio
async def test_ambient_and_parent_are_assessed_without_automatic_parent_selection() -> None:
    candidates = normalize_candidates(
        [
            _candidate(
                "note:relevant",
                origin="ambient_current_post",
                score=None,
                parent_post_id="owner",
            ),
            _candidate("note:irrelevant", origin="ambient_current_post", score=None),
        ]
    )
    contract = _contract(_source("workspace-notes"), planner_calls=1)
    output = {
        "assessments": [
            {"ref": "note:relevant", "relevance": "direct", "role": "answer_evidence", "resolution": "card", "confidence": 0.95, "reason_code": "topic_only"},
            {"ref": "note:irrelevant", "relevance": "irrelevant", "role": "none", "resolution": "none", "confidence": 0.96, "reason_code": "unrelated_topic"},
        ],
        "source_dispositions": [{"source_id": "workspace-notes", "status": "selected"}],
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=json.dumps(output),
    ) as selector:
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_args.kwargs["phase"] == "research.selector.context"
    assert result["material_plan"]["card_ids"] == ["note:relevant"]
    assert "post:owner" not in result["material_plan"]["card_ids"]
    assessment_by_ref = {
        item["ref"]: item for item in result["material_plan"]["assessments"]
    }
    assert assessment_by_ref["note:irrelevant"]["relevance"] == "irrelevant"
    assert result["material_plan"]["source_dispositions"] == [
        {"source_id": "workspace-notes", "status": "selected"}
    ]


@pytest.mark.asyncio
async def test_invalid_selector_retries_once_preserves_exact_target_and_returns_gap() -> None:
    exact, ambient = normalize_candidates(
        [
            _candidate("note:exact", source="target-note", origin="exact_target", score=None),
            _candidate("note:ambient", origin="ambient_current_post", score=None),
        ]
    )
    contract = _contract(
        _source("target-note", minimum=1, evidence="required"),
        _source("workspace-notes"),
        planner_calls=2,
    )
    exact_plan = merge_material_plan(
        None,
        candidates=[exact],
        assessments=[
            {
                "ref": "note:exact",
                "relevance": "direct",
                "resolution": "card",
                "confidence": 1.0,
                "reason_code": "topic_only",
                "selection_source": "exact_target",
            }
        ],
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=["not json", '{"assessments":[]}'],
    ) as selector:
        result = await _compact_planner_node(
            _state(contract, [exact, ambient], material_plan=exact_plan),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[1].kwargs["phase"] == "research.selector.context_schema_retry"
    assert result["material_plan"]["card_ids"] == ["note:exact"]
    assert result["material_plan"]["required_full_text_ids"] == []
    assert result["material_plan"]["optional_full_text_ids"] == []
    assert result["tool_action"]["requested_status"] == "partial"
    assert result["evidence_gaps"][-1]["kind"] == "selector_failed"
    assert result["evidence_gaps"][-1]["source_id"] == "workspace-notes"


@pytest.mark.asyncio
async def test_selector_timeout_retries_once_and_never_selects_all() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"), planner_calls=2)
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=[TimeoutError("provider timeout"), TimeoutError("provider timeout")],
    ) as selector:
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert result["material_plan"]["card_ids"] == []
    assert result["material_plan"]["pending_full_text_ids"] == []
    assert result["material_plan"]["selector_failure"]["visible_refs"] == [
        "note:n1",
        "note:n2",
    ]
    assert result["evidence_gaps"][-1]["kind"] == "selector_failed"


@pytest.mark.asyncio
async def test_required_discovery_min_zero_accepts_no_relevant_candidate_without_fallback() -> None:
    candidates = normalize_candidates([_candidate("note:weak")])
    contract = _contract(_source("workspace-notes", minimum=0), planner_calls=1)
    output = {
        "assessments": [
            {"ref": "note:weak", "relevance": "irrelevant", "role": "none", "resolution": "none", "confidence": 0.99, "reason_code": "unrelated_topic"}
        ],
        "source_dispositions": [
            {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
        ],
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=json.dumps(output),
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert result["material_plan"]["card_ids"] == []
    assert result["material_plan"]["pending_full_text_ids"] == []
    assert result["material_plan"]["source_dispositions"] == [
        {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
    ]
    assert result["tool_action"]["actions"] == []


@pytest.mark.asyncio
async def test_complete_semantic_registry_is_assessed_by_one_selector_call() -> None:
    candidates = normalize_candidates([_candidate(f"note:n{index}") for index in range(20)])
    source = _source("workspace-notes", maximum=20)
    source["coverage"] = "complete"
    contract = _contract(source, planner_calls=1)

    async def selector_output(*_args, **kwargs) -> str:
        content = kwargs["messages"][1]["content"]
        snapshot = json.loads(content[content.index("{"):])
        visible = snapshot["candidates"]
        return json.dumps(
            {
                "assessments": [
                    {"ref": item["ref"], "relevance": "direct", "role": "answer_evidence", "resolution": "card", "confidence": 0.9, "reason_code": "topic_only"}
                    for item in visible
                ],
                "source_dispositions": [
                    {"source_id": "workspace-notes", "status": "selected"}
                ],
            }
        )

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=selector_output,
    ) as selector:
        first = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert len(first["material_plan"]["assessments"]) == 20
    assert first["material_plan"]["context_selection_done"] is True


@pytest.mark.asyncio
async def test_structural_source_never_invokes_context_selector() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    source = _source("workspace-notes", predicate_kind="structural", maximum=0)
    contract = _contract(source, planner_calls=1)
    ctx = SimpleNamespace(
        reasoner_spec=None,
        reasoner_model="",
        reasoner_api_key="",
        planner_llm=None,
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as llm:
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )
    assert llm.await_count == 0
    assert result["material_plan"]["context_selection_done"] is True
    assert _semantic_selector_candidates(candidates, contract=contract) == []


def test_optional_no_relevant_source_does_not_block_ready() -> None:
    contract = _contract(
        _source(
            "workspace-notes",
            discovery="optional",
            evidence="optional",
        )
    )
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {},
            "material_plan": {
                "assessments": [{"ref": "note:n1", "relevance": "irrelevant"}],
                "source_dispositions": [
                    {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
                ],
            },
            "search_ledger": [],
        },
        contract=contract,
    )
    assert result.status == "ready"
    assert result.gaps == ()


def test_phase3_replay_fixture_is_schema_complete_and_parent_stays_metadata() -> None:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "agent_unified_phase3"
        / "v1"
        / "scenarios.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for scenario in fixture["scenarios"]:
        candidates = normalize_candidates(scenario["candidates"])
        source_ids = sorted(
            {
                source_id
                for item in candidates
                for source_id in item["source_requirement_ids"]
            }
        )
        contract = _contract(*[_source(source_id) for source_id in source_ids])
        decision = ContextSelectorDecision.model_validate(scenario["decision"])
        assert ContextSelectorDecision.model_validate(
            decision.model_dump(mode="json")
        ) == decision
        assert _unified_selector_decision_is_valid(
            decision,
            candidates=candidates,
            contract=contract,
            material_plan=empty_material_plan(),
        ), scenario["id"]
        selected = [
            item.ref for item in decision.assessments if item.relevance.value != "irrelevant"
        ]
        assert selected == scenario["selected_refs"]
        assert "post:owner" not in selected
