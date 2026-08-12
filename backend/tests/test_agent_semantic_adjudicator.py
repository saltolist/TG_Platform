from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.agent.research.graph import (
    OBLIGATION_CLASSIFICATION_VERSION,
    POST_READ_LABEL_VERSION,
    _assemble_obligation_coverage_positions,
    _decode_obligation_classification,
    _decode_post_read_labels,
    _obligation_assignment_json_schema,
    _obligation_pair_scores,
    _run_precision_confirmation,
)
from app.services.agent.research.material_plan import empty_material_plan
from app.services.agent.research.planner_decision import ContextSelectorDecision
from app.services.agent.research.semantic_adjudicator import (
    AdjudicationGrade,
    AdjudicationResult,
    RowVerdict,
    adjudication_json_schema,
    build_adjudication_mapping,
    decode_adjudication_result,
    merge_adjudication_results,
)
from app.services.agent.research.selector_transport import encode_selector_transport
from app.services.ai.providers import ChatCompletionCapability


def _candidate(ref: str, summary: str) -> dict:
    return {
        "ref": ref,
        "kind": ref.split(":", 1)[0],
        "title": ref,
        "selector_summary": summary,
        "selector_summary_version": 2,
        "source_revision": 3,
        "source_requirement_id": "workspace-notes",
        "status": "active",
        "available_fidelity": ["card", "semantic_card", "full_text"],
    }


def _contract(
    *,
    maximum: int = 4,
    obligations: tuple[str, ...] = ("requested fact",),
    selection_mode: str = "composition",
) -> dict:
    return {
        "schema": "workspace.turn/v3",
        "version": 3,
        "semantic_adjudication": "parallel_v1",
        "task_profile": "workspace_synthesis",
        "selection_mode": selection_mode,
        "answer_obligations": [
            {"description": description} for description in obligations
        ],
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "evidence_obligation": "required",
                "selection_cardinality": {"min": 0, "max": maximum},
                "required_fidelity": "semantic_card",
            }
        ],
    }


def _decision(*, first_selected: bool = True) -> ContextSelectorDecision:
    return ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": "note:a",
                    "relevance": "direct" if first_selected else "irrelevant",
                    "role": "answer_evidence" if first_selected else "none",
                    "resolution": "card" if first_selected else "none",
                    "confidence": 0.9,
                    "reason_code": "exact_fact" if first_selected else "ambiguous",
                },
                {
                    "ref": "note:b",
                    "relevance": "irrelevant",
                    "role": "none",
                    "resolution": "none",
                    "confidence": 0.9,
                    "reason_code": "ambiguous",
                },
            ],
            "source_dispositions": [
                {
                    "source_id": "workspace-notes",
                    "status": "selected" if first_selected else "no_relevant_candidate",
                }
            ],
        }
    )


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="fixture-provider"),
        reasoner_model="fixture-model",
        reasoner_api_key="secret-not-logged",
        planner_llm=None,
        llm_metrics=[],
    )


def _lane_payload(mapping, *, selected_position: int) -> str:
    return json.dumps(
        {
            "v": 1,
            "n": len(mapping.candidates),
            "r": mapping.nonce,
            "rows": [
                {
                    "i": position,
                    "g": 2 if position == selected_position else 0,
                    "o": [0] if position == selected_position else [],
                }
                for position in range(len(mapping.candidates))
            ],
            "done": True,
        }
    )


def _opened_candidates() -> list[dict]:
    candidates = [
        _candidate("note:a", "Direct evidence for the requested fact."),
        _candidate("note:b", "Neighboring background."),
    ]
    for candidate in candidates:
        candidate["opened_evidence"] = {
            "text": candidate["selector_summary"],
            "digest": "1111111111111111",
            "citation_path": f"/{candidate['ref'].replace(':', '/')}/",
            "source_revision": candidate["source_revision"],
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    return candidates


def _obligation_payload(
    *,
    nonce: str,
    support: dict[str, list[dict[str, int]]],
) -> str:
    return json.dumps(
        {
            "v": OBLIGATION_CLASSIFICATION_VERSION,
            "n": len(support),
            "r": nonce,
            "support": support,
            "done": True,
        }
    )


def _obligation_assignment_payload(
    *, nonce: str, candidate_count: int, position: int, warrant_unit: int
) -> str:
    return json.dumps(
        {
            "v": OBLIGATION_CLASSIFICATION_VERSION,
            "n": candidate_count,
            "r": nonce,
            "support": {
                "0": {"position": position, "warrant_unit": warrant_unit}
            },
            "done": True,
        }
    )


def test_audit_schema_binds_warrant_range_to_selected_row() -> None:
    candidates = [
        _candidate("note:long", "Long row."),
        _candidate("post:short", "Short row."),
    ]
    transport = encode_selector_transport(
        question="Find the requested fact.",
        dialog_context="",
        contract=_contract(),
        candidates=candidates,
    )
    mapping = transport.mapping
    decision_obligations = (("answer:0",), ("answer:0",))
    unit_counts = (63, 9)
    schema = _obligation_assignment_json_schema(
        mapping,
        decision_obligations,
        unit_counts,
    )
    branches = schema["properties"]["support"]["properties"]["0"]["anyOf"]
    branch_by_position = {
        branch["properties"]["position"]["const"]: branch for branch in branches
    }

    assert branch_by_position[-1]["properties"]["warrant_unit"]["const"] == -1
    assert branch_by_position[0]["properties"]["warrant_unit"]["maximum"] == 62
    assert branch_by_position[1]["properties"]["warrant_unit"]["maximum"] == 8

    invalid_old_schema_payload = _obligation_assignment_payload(
        nonce=mapping.registry_nonce,
        candidate_count=2,
        position=1,
        warrant_unit=40,
    )
    positions, _gates, errors = _decode_obligation_classification(
        invalid_old_schema_payload,
        mapping=mapping,
        unit_counts=unit_counts,
        decision_obligations=decision_obligations,
    )
    assert positions is None


def test_post_read_label_v2_owns_membership_without_obligation_edges() -> None:
    candidates = _opened_candidates()
    transport = encode_selector_transport(
        question="Which records are the requested members?",
        dialog_context="",
        contract=_contract(selection_mode="member_inventory"),
        candidates=candidates,
    )
    raw = json.dumps(
        {
            "v": POST_READ_LABEL_VERSION,
            "n": 2,
            "r": transport.mapping.registry_nonce,
            "labels": {
                "0": {"keep": True, "reason": "essential", "warrant_unit": 0},
                "1": {"keep": False, "reason": "irrelevant", "warrant_unit": -1},
            },
            "done": True,
        }
    )
    positions, edges, _gates, errors = _decode_post_read_labels(
        raw,
        mapping=transport.mapping,
        unit_counts=(1, 1),
        decision_obligations=(("answer:0",), ("answer:0",)),
    )
    assert positions == (0,)
    assert edges == {}
    assert errors == ()


def test_mapping_is_immutable_and_schema_is_bounded() -> None:
    mapping = build_adjudication_mapping(
        question="How do A and B form one workflow?",
        obligations=("A", "B"),
        task_profile="workspace_synthesis",
        selection_mode="composition",
        source_requirements=(
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "query_goal": "Find A and B.",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "selection_cardinality": {"min": 0, "max": 4},
            },
        ),
        candidates=(
            _candidate("note:a", "Explicit evidence for A."),
            _candidate("note:b", "Explicit evidence for B."),
        ),
    )
    repeated = build_adjudication_mapping(
        question="How do A and B form one workflow?",
        obligations=("A", "B"),
        task_profile="workspace_synthesis",
        selection_mode="composition",
        source_requirements=(
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "query_goal": "Find A and B.",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "selection_cardinality": {"min": 0, "max": 4},
            },
        ),
        candidates=(
            _candidate("note:a", "Explicit evidence for A."),
            _candidate("note:b", "Explicit evidence for B."),
        ),
    )

    assert mapping.signature == repeated.signature
    assert mapping.nonce == repeated.nonce
    assert [item.ref for item in mapping.candidates] == ["note:a", "note:b"]
    assert mapping.payload["task"] == {
        "profile": "workspace_synthesis",
        "selection": "composition",
    }
    assert mapping.payload["sources"][0]["goal"] == "Find A and B."
    schema = adjudication_json_schema(mapping)
    assert schema["properties"]["rows"]["minItems"] == 2
    assert schema["properties"]["rows"]["maxItems"] == 2


def test_decoder_rejects_position_and_normalizes_redundant_exclusion_edges() -> None:
    mapping = build_adjudication_mapping(
        question="Find the evidence.",
        obligations=("the evidence",),
        candidates=(_candidate("note:a", "Evidence."),),
    )
    invalid_position = json.dumps(
        {
            "v": 1,
            "n": 1,
            "r": mapping.nonce,
            "rows": [{"i": 1, "g": 2, "o": [0]}],
            "done": True,
        }
    )
    invalid_exclusion = json.dumps(
        {
            "v": 1,
            "n": 1,
            "r": mapping.nonce,
            "rows": [{"i": 0, "g": 0, "o": [0]}],
            "done": True,
        }
    )

    assert decode_adjudication_result(
        invalid_position, mapping=mapping
    ).errors == ("invalid_position",)
    normalized = decode_adjudication_result(invalid_exclusion, mapping=mapping)
    assert normalized.valid
    assert normalized.verdicts == (
        RowVerdict(0, AdjudicationGrade.EXCLUDE, ()),
    )


def test_consensus_accepts_positive_rejects_negative_and_preserves_disagreement() -> None:
    left = AdjudicationResult(
        (
            RowVerdict(0, AdjudicationGrade.DIRECT, (0,)),
            RowVerdict(1, AdjudicationGrade.EXCLUDE, ()),
            RowVerdict(2, AdjudicationGrade.DIRECT, (1,)),
        )
    )
    right = AdjudicationResult(
        (
            RowVerdict(0, AdjudicationGrade.SUPPORTING, (0,)),
            RowVerdict(1, AdjudicationGrade.EXCLUDE, ()),
            RowVerdict(2, AdjudicationGrade.EXCLUDE, ()),
        )
    )

    merged = merge_adjudication_results(left, right)

    assert merged[0].grade == AdjudicationGrade.SUPPORTING
    assert merged[0].agreement == "consensus"
    assert merged[1].grade == AdjudicationGrade.EXCLUDE
    assert merged[2].grade is None
    assert merged[2].agreement == "unresolved"


def test_tie_breaker_resolves_only_disputed_rows() -> None:
    left = AdjudicationResult(
        (
            RowVerdict(0, AdjudicationGrade.DIRECT, (0,)),
            RowVerdict(1, AdjudicationGrade.EXCLUDE, ()),
        )
    )
    right = AdjudicationResult(
        (
            RowVerdict(0, AdjudicationGrade.EXCLUDE, ()),
            RowVerdict(1, AdjudicationGrade.EXCLUDE, ()),
        )
    )
    tie = AdjudicationResult(
        (
            RowVerdict(0, AdjudicationGrade.SUPPORTING, (0,)),
            RowVerdict(1, AdjudicationGrade.DIRECT, (0,)),
        )
    )

    merged = merge_adjudication_results(left, right, tie_breaker=tie)

    assert merged[0].grade == AdjudicationGrade.SUPPORTING
    assert merged[0].agreement == "tie_breaker"
    assert merged[1].grade == AdjudicationGrade.EXCLUDE
    assert merged[1].agreement == "consensus"


def test_tie_breaker_resolves_obligation_disagreement() -> None:
    left = AdjudicationResult(
        (RowVerdict(0, AdjudicationGrade.DIRECT, (0,)),)
    )
    right = AdjudicationResult(
        (RowVerdict(0, AdjudicationGrade.DIRECT, (1,)),)
    )
    tie = AdjudicationResult(
        (RowVerdict(0, AdjudicationGrade.DIRECT, (0, 1)),)
    )

    unresolved = merge_adjudication_results(left, right)
    resolved = merge_adjudication_results(left, right, tie_breaker=tie)

    assert unresolved[0].grade is None
    assert unresolved[0].agreement == "obligation_disagreement"
    assert resolved[0] == resolved[0].__class__(
        0, AdjudicationGrade.DIRECT, (0, 1), "tie_breaker"
    )


def test_invalid_lane_never_produces_partial_membership() -> None:
    valid = AdjudicationResult((RowVerdict(0, AdjudicationGrade.DIRECT, (0,)),))
    invalid = AdjudicationResult(errors=("provider_error",))

    assert merge_adjudication_results(valid, invalid) == ()


@pytest.mark.asyncio
async def test_parallel_protocol_recovers_consensus_row_and_finalizes_lane_metrics() -> None:
    candidates = [
        _candidate("note:a", "Neighboring topic."),
        _candidate("note:b", "Direct evidence for the requested fact."),
    ]
    contract = _contract(obligations=())
    mapping = build_adjudication_mapping(
        question="Which row answers the request?",
        obligations=(),
        candidates=candidates,
        task_profile=str(contract.get("task_profile") or ""),
        selection_mode=str(contract.get("selection_mode") or ""),
        source_requirements=contract["source_requirements"],
    )
    payload = _lane_payload(mapping, selected_position=1)
    ctx = _ctx()
    calls_by_role: dict[str, dict] = {}

    async def provider(runtime_context, **kwargs) -> str:
        calls_by_role[kwargs["telemetry"]["model_role"]] = kwargs
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Which row answers the request?",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    assert calls == 2
    assert deadline is False
    assert trace["precision_protocol"] == "parallel_semantic_adjudication_v1"
    assert trace["schema_result"] == "valid"
    assert trace["semantic_scope"] == "exact_user_request"
    assert trace["obligation_count"] == 1
    assert trace["contract_obligation_count"] == 0
    assert [item["model"] for item in trace["lane_bindings"]] == [
        "fixture-model",
        "fixture-model",
    ]
    assert "keys v,n,r,rows,done" in calls_by_role["lane_b"]["messages"][1]["content"]
    assert trace["confirmed_refs"] == ["note:b"]
    assert {item.ref for item in decision.assessments if item.relevance.value != "irrelevant"} == {
        "note:b"
    }
    assert [item["schema_result"] for item in ctx.llm_metrics] == ["valid", "valid"]


@pytest.mark.asyncio
async def test_parallel_protocol_sends_primary_disagreement_to_full_text_shortlist() -> None:
    candidates = [
        _candidate("note:a", "Potential direct evidence hidden by a lossy card."),
        _candidate("note:b", "Competing evidence for the same obligation."),
    ]
    contract = _contract()
    mapping = build_adjudication_mapping(
        question="Which row supplies the requested fact?",
        obligations=("requested fact",),
        candidates=candidates,
        task_profile=str(contract.get("task_profile") or ""),
        selection_mode=str(contract.get("selection_mode") or ""),
        source_requirements=contract["source_requirements"],
    )
    payloads = {
        "lane_a": _lane_payload(mapping, selected_position=0),
        "lane_b": _lane_payload(mapping, selected_position=1),
        "tie_breaker": _lane_payload(mapping, selected_position=1),
    }
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payloads[kwargs["telemetry"]["model_role"]]

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Which row supplies the requested fact?",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    assert calls == 3
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:b"}
    assert trace["membership_owner"] == "post_read"
    assert trace["demoted_refs"] == ["note:a"]
    assert trace["recall_protected_refs"] == ["note:b"]
    assembler = trace["deterministic_assembler"]
    assert assembler["selected_positions"] == [1]
    assert assembler["primary_disagreement_positions"] == []
    assert assembler["read_shortlist_positions"] == [1, 0]
    assert assembler["semantic_probe_positions"] == [0, 1]


@pytest.mark.asyncio
async def test_card_recall_positive_displaces_consensus_negative_primary() -> None:
    candidates = [
        _candidate("note:a", "Primary card with neighboring subject matter."),
        _candidate("note:b", "Card that supports the requested fact."),
    ]
    contract = _contract()
    mapping = build_adjudication_mapping(
        question="Which row supplies the requested fact?",
        obligations=("requested fact",),
        candidates=candidates,
        task_profile=str(contract.get("task_profile") or ""),
        selection_mode=str(contract.get("selection_mode") or ""),
        source_requirements=contract["source_requirements"],
    )
    payload = _lane_payload(mapping, selected_position=1)
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Which row supplies the requested fact?",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    assert calls == 2
    assert trace["recall_protected_refs"] == ["note:b"]
    assert trace["demoted_refs"] == ["note:a"]
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:b"}


def test_cross_record_comparison_assigns_distinct_premise_rows() -> None:
    candidates = [
        _candidate("note:broad", "Overview that repeats all three claims."),
        _candidate("note:second", "Independent source for the second claim."),
        _candidate("note:third", "Independent source for the third claim."),
    ]
    support = {
        0: {0: 0, 1: 1, 2: 2},
        1: {1: 0},
        2: {2: 0},
    }
    scores = {
        (0, 0): 0.9,
        (0, 1): 0.9,
        (0, 2): 0.9,
        (1, 1): 0.8,
        (2, 2): 0.8,
    }
    contract = _contract(
        obligations=("first claim", "second claim", "relationship"),
        selection_mode="cross_record_comparison",
    )

    selected, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
        obligation_count=3,
        support=support,
        pair_scores=scores,
    )

    assert selected == (0, 1, 2)
    assert len(set(trace["assignment_positions"].values())) == 3
    assert trace["distinct_premise_positions"] is True

    ordinary_selected, ordinary_trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract={
            **contract,
            "selection_mode": "composition",
            "task_profile": "topical_answer",
        },
        material_plan=empty_material_plan(),
        obligation_count=3,
        support=support,
        pair_scores=scores,
    )
    assert ordinary_selected == (0,)
    assert ordinary_trace["distinct_premise_positions"] is False


def test_composition_preserves_competitive_cross_cutting_premise() -> None:
    candidates = [
        _candidate("note:integrated", "Integrated account of the complete workflow."),
        _candidate("note:premise", "Cross-cutting premise for two workflow stages."),
        _candidate("note:incidental", "Incidental detail for only one stage."),
    ]
    support = {
        0: {0: 0, 1: 1, 2: 2},
        1: {0: 0, 1: 1},
        2: {2: 0},
    }
    scores = {
        (0, 0): 0.60,
        (0, 1): 0.62,
        (0, 2): 0.64,
        (1, 0): 0.43,
        (1, 1): 0.45,
        (2, 2): 0.61,
    }

    selected, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            obligations=("first stage", "second stage", "third stage"),
            selection_mode="composition",
        ),
        material_plan=empty_material_plan(),
        obligation_count=3,
        support=support,
        pair_scores=scores,
    )

    assert selected == (0, 1, 2)
    assert len(set(trace["assignment_positions"].values())) == 3
    assert trace["distinct_premise_positions"] is True


@pytest.mark.asyncio
async def test_pair_scoring_prefers_central_document_over_incidental_local_phrase() -> None:
    class Embeddings:
        model_key = "fixture-centrality"

        async def embed_passages(self, texts: list[str]) -> list[list[float]]:
            assert len(texts) == 4
            return [
                [1.0, 0.0],
                [0.0, 1.0],
                [0.8, 0.2],
                [1.0, 0.0],
            ]

        async def embed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    candidates = [
        _candidate("note:central", "Target topic as the document's main subject."),
        _candidate("note:incidental", "A different neighboring subject."),
    ]
    scores, trace = await _obligation_pair_scores(
        embedding_backend=Embeddings(),
        obligation_descriptions=("target topic",),
        candidates=candidates,
        unit_texts=(("Target topic details.",), ("Target topic exact phrase.",)),
        support={0: {0: 0}, 1: {0: 0}},
    )

    assert scores[(0, 0)] > scores[(1, 0)]
    assert trace["scoring_mode"] == "central_card_plus_local_warrant"


@pytest.mark.asyncio
async def test_parallel_protocol_rejects_unsafe_primary_on_provider_failure() -> None:
    candidates = [
        _candidate("note:a", "Potential evidence."),
        _candidate("note:b", "Other evidence."),
    ]
    contract = _contract(maximum=0)
    mapping = build_adjudication_mapping(
        question="Find evidence.",
        obligations=("requested fact",),
        candidates=candidates,
        task_profile=str(contract.get("task_profile") or ""),
        selection_mode=str(contract.get("selection_mode") or ""),
        source_requirements=contract["source_requirements"],
    )
    payload = _lane_payload(mapping, selected_position=0)
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        if kwargs["telemetry"]["model_role"] == "lane_a":
            raise RuntimeError("temporary upstream failure")
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Find evidence.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    assert calls == 2
    assert trace["schema_result"] == "provider_api_error"
    assert trace["fallback"] == "reject_unsafe_primary"
    assert trace["confirmed_refs"] == []
    assert all(item.relevance.value == "irrelevant" for item in decision.assessments)
    assert {item["schema_result"] for item in ctx.llm_metrics} == {
        "provider_api_error",
        "valid",
    }


@pytest.mark.asyncio
async def test_parallel_protocol_separates_invalid_transport_and_preserves_safe_primary() -> None:
    candidates = [
        _candidate("note:a", "Direct evidence."),
        _candidate("note:b", "Other material."),
    ]
    contract = _contract()
    mapping = build_adjudication_mapping(
        question="Find evidence.",
        obligations=("requested fact",),
        candidates=candidates,
        task_profile=str(contract.get("task_profile") or ""),
        selection_mode=str(contract.get("selection_mode") or ""),
        source_requirements=contract["source_requirements"],
    )
    valid_payload = _lane_payload(mapping, selected_position=0)
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return (
            "not-json"
            if kwargs["telemetry"]["model_role"] == "lane_a"
            else valid_payload
        )

    primary = _decision()
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, _calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="Find evidence.",
            transport_tier=ChatCompletionCapability.PLAIN,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    assert trace["schema_result"] == "invalid_transport"
    assert trace["fallback"] == "validated_primary_baseline"
    assert decision == primary
    assert {item["schema_result"] for item in ctx.llm_metrics} == {
        "invalid_transport",
        "valid",
    }


@pytest.mark.asyncio
async def test_record_mode_keeps_one_self_contained_row() -> None:
    candidates = [
        _candidate("note:a", "Defines both alternatives and their outcomes."),
        _candidate("note:b", "Generic background about one option."),
    ]
    contract = _contract(
        obligations=("alternative set", "outcomes", "background reason"),
        selection_mode="record",
    )
    transport = encode_selector_transport(
        question="Which of the two options should be used, and why not the other?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = json.dumps(
        {
            "v": OBLIGATION_CLASSIFICATION_VERSION,
            "n": 2,
            "r": transport.mapping.registry_nonce,
            "support": {
                "0": {"0": 0, "1": 0, "2": 0},
                "1": {"0": -1, "1": -1, "2": 0},
            },
            "done": True,
        }
    )
    ctx = _ctx()
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "card",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"}
            ],
        }
    )

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="Which of the two options should be used, and why not the other?",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    selected = {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    }
    assert calls == 1
    assert selected == {"note:a"}
    assert trace["precision_protocol"] == "obligation_classification_v4"
    assert trace["deterministic_assembler"]["selected_positions"] == [0]


@pytest.mark.asyncio
async def test_parallel_composition_uses_minimal_cross_source_obligation_cover() -> None:
    candidates = [
        _candidate("note:overview", "Overview of the workspace capabilities."),
        _candidate("post:mechanism", "Explains the concrete author workflow action."),
        _candidate("note:neighbor", "Neighboring product background."),
    ]
    candidates[1]["source_requirement_id"] = "workspace-posts"
    contract = _contract(
        maximum=4,
        obligations=("workflow action", "platform capabilities"),
    )
    contract["source_requirements"].append(
        {
            "source_id": "workspace-posts",
            "kind": "posts",
            "evidence_obligation": "required",
            "selection_cardinality": {"min": 0, "max": 4},
        }
    )
    mapping = build_adjudication_mapping(
        question="Explain the workflow and the capabilities enabling it.",
        obligations=("workflow action", "platform capabilities"),
        candidates=candidates,
        task_profile="workspace_synthesis",
        selection_mode="composition",
        source_requirements=contract["source_requirements"],
    )
    payload = json.dumps(
        {
            "v": 1,
            "n": 3,
            "r": mapping.nonce,
            "rows": [
                {"i": 0, "g": 2, "o": [1]},
                {"i": 1, "g": 2, "o": [0]},
                {"i": 2, "g": 1, "o": [1]},
            ],
            "done": True,
        }
    )
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "card",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="Explain the workflow and the capabilities enabling it.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    selected = {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    }
    assert calls == 2
    assert selected == {"note:overview", "post:mechanism", "note:neighbor"}
    assert trace["membership_owner"] == "post_read"
    assert trace["demoted_refs"] == []
    assert trace["deterministic_assembler"]["covered_obligation_indexes"] == [0, 1]


@pytest.mark.asyncio
async def test_recommendation_keeps_only_bounded_window_prefix_to_selected_draft() -> None:
    note = _candidate("note:plan", "Workspace topics for the next post.")
    candidates = [note]
    for position in range(1, 7):
        post = _candidate(
            f"post:{position}",
            f"Post observation at ordered position {position}.",
        )
        post.update(
            {
                "source_requirement_id": "workspace-posts",
                "status": "draft" if position == 5 else "published",
                "catalog_window_memberships": [
                    {
                        "source_requirement_id": "workspace-posts",
                        "position": position,
                        "window_size": 6,
                    }
                ],
            }
        )
        candidates.append(post)
    contract = _contract(
        maximum=8,
        obligations=("current unfinished posts", "workspace topics"),
    )
    contract.update({"task_profile": "recommendation", "selection_mode": "composition"})
    contract["source_requirements"][0]["evidence_obligation"] = "optional"
    contract["source_requirements"].append(
        {
            "source_id": "workspace-posts",
            "kind": "posts",
            "evidence_obligation": "required",
            "discovery_mode": "catalog_window",
            "selection_cardinality": {"min": 0, "max": 5},
            "scope": {"mode": "corpus"},
        }
    )
    mapping = build_adjudication_mapping(
        question="What should be written next without duplicating current work?",
        obligations=("current unfinished posts", "workspace topics"),
        candidates=candidates,
        task_profile="recommendation",
        selection_mode="composition",
        source_requirements=contract["source_requirements"],
    )
    payload = json.dumps(
        {
            "v": 1,
            "n": len(candidates),
            "r": mapping.nonce,
            "rows": [
                {
                    "i": position,
                    "g": 2 if position in {0, 5} else 0,
                    "o": [1] if position == 0 else [0] if position == 5 else [],
                }
                for position in range(len(candidates))
            ],
            "done": True,
        }
    )
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct"
                    if candidate["ref"] in {"note:plan", "post:5"}
                    else "irrelevant",
                    "role": "answer_evidence"
                    if candidate["ref"] in {"note:plan", "post:5"}
                    else "none",
                    "resolution": "card"
                    if candidate["ref"] in {"note:plan", "post:5"}
                    else "none",
                    "confidence": 0.9,
                    "reason_code": "exact_fact"
                    if candidate["ref"] in {"note:plan", "post:5"}
                    else "ambiguous",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, _calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="What should be written next without duplicating current work?",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
        )

    selected = {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    }
    assert selected == {
        "note:plan",
        "post:1",
        "post:2",
        "post:3",
        "post:4",
        "post:5",
    }
    assert trace["catalog_window_prefix_refs"] == [
        "post:1",
        "post:2",
        "post:3",
        "post:4",
    ]


@pytest.mark.asyncio
async def test_post_read_consensus_keeps_only_consensus_positive_edges() -> None:
    candidates = _opened_candidates()
    contract = _contract()
    transport = encode_selector_transport(
        question="Find the requested fact.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = _obligation_payload(
        nonce=transport.mapping.registry_nonce,
        support={
            "0": [{"obligation_index": 0, "warrant_unit": 0}],
            "1": [],
        },
    )
    ctx = _ctx()
    schemas_by_role: dict[str, dict] = {}

    async def provider(runtime_context, **kwargs) -> str:
        schemas_by_role[kwargs["telemetry"]["model_role"]] = kwargs[
            "output_json_schema"
        ]
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return (
            _obligation_assignment_payload(
                nonce=transport.mapping.registry_nonce,
                candidate_count=2,
                position=0,
                warrant_unit=0,
            )
            if kwargs["telemetry"]["model_role"] == "adversarial"
            else payload
        )

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert trace["post_read_lane_count"] == 2
    assert trace["post_read_disputed_edges"] == []
    assert trace["obligation_assignments"] == [
        {"obligation": "answer:0", "position": 0, "coordinate": "0:0"}
    ]
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:a"}
    assert [item["schema_result"] for item in ctx.llm_metrics] == ["valid", "valid"]
    primary_support = schemas_by_role["primary"]["properties"]["support"]
    assert primary_support["properties"]["0"]["maxItems"] == 1
    audit_support = schemas_by_role["adversarial"]["properties"]["support"]
    assert audit_support["required"] == ["0"]
    audit_branches = audit_support["properties"]["0"]["anyOf"]
    assert all(
        set(branch["properties"]) == {"position", "warrant_unit"}
        for branch in audit_branches
    )


@pytest.mark.asyncio
async def test_post_read_disagreement_preserves_recall_and_uses_deterministic_rank() -> None:
    candidates = _opened_candidates()
    contract = _contract()
    transport = encode_selector_transport(
        question="Find the requested fact.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payloads = {
        "primary": _obligation_payload(
            nonce=transport.mapping.registry_nonce,
            support={
                "0": [{"obligation_index": 0, "warrant_unit": 0}],
                "1": [],
            },
        ),
        "adversarial": _obligation_payload(
            nonce=transport.mapping.registry_nonce,
            support={"0": [], "1": []},
        ),
    }
    payloads["adversarial"] = _obligation_assignment_payload(
        nonce=transport.mapping.registry_nonce,
        candidate_count=2,
        position=1,
        warrant_unit=0,
    )
    ctx = _ctx()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        return payloads[kwargs["telemetry"]["model_role"]]

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_decision(),
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert trace["post_read_lane_count"] == 2
    assert trace["post_read_disputed_edges"] == [[0, 0], [1, 0]]
    assert trace["post_read_merge_mode"] == "primary_edges_gap_recovery"
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:a"}
    assert [item["schema_result"] for item in ctx.llm_metrics] == [
        "valid",
        "valid",
    ]


@pytest.mark.asyncio
async def test_post_read_lane_error_preserves_only_safe_baseline_without_secrets() -> None:
    candidates = _opened_candidates()
    contract = _contract()
    transport = encode_selector_transport(
        question="Find the requested fact.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = _obligation_payload(
        nonce=transport.mapping.registry_nonce,
        support={
            "0": [{"obligation_index": 0, "warrant_unit": 0}],
            "1": [],
        },
    )
    ctx = _ctx()
    primary = _decision()

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        if kwargs["telemetry"]["model_role"] == "adversarial":
            raise RuntimeError("temporary failure api_key=super-secret")
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert decision == primary
    assert trace["schema_result"] == "provider_api_error"
    assert trace["fallback"] == "validated_primary_baseline"
    assert trace["confirmed_refs"] == ["note:a"]
    assert "super-secret" not in json.dumps(trace)


@pytest.mark.asyncio
async def test_post_read_failure_does_not_label_empty_baseline_as_no_evidence() -> None:
    candidates = _opened_candidates()
    contract = _contract()
    transport = encode_selector_transport(
        question="Find the requested fact.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = _obligation_payload(
        nonce=transport.mapping.registry_nonce,
        support={"0": [], "1": []},
    )
    ctx = _ctx()
    primary = _decision(first_selected=False)

    async def provider(runtime_context, **kwargs) -> str:
        runtime_context.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        if kwargs["telemetry"]["model_role"] == "adversarial":
            raise TimeoutError("temporary audit timeout")
        return payload

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, _calls, trace, _deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": ctx}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=primary,
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert decision == primary
    assert trace["degraded"] is True
    assert trace["empty_baseline_unverified"] is True
    assert trace["schema_result"] == "timeout"
