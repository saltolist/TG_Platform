"""Unified phase 3: one complete semantic Context Selector."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.graph import (
    CONTEXT_SELECTOR_SYSTEM,
    OPENED_EVIDENCE_REASSESSMENT_SYSTEM,
    PRECISION_CONFIRMATION_SYSTEM,
    PRECISION_CONFIRMATION_VERSION,
    _attach_matched_selector_evidence,
    _catalog_member_candidates,
    _close_opened_catalog_window_prefix,
    _compact_planner_node,
    _decode_precision_confirmation,
    _decision_answer_obligation_registry,
    _decision_obligation_registry,
    _decision_precision_obligations,
    _decision_registry_structurally_incomplete_positions,
    _is_inventory_answer_shape,
    _materialize_full_read_actions,
    _precision_confirmation_json_schema,
    _precision_evidence_units,
    _reassessment_selector_candidates,
    _render_precision_confirmation_registry,
    _semantic_selector_candidates,
    _unified_selector_decision_is_valid,
    _uses_decision_input_precision,
    _uses_member_classification_precision,
    _uses_finite_note_catalog_recall,
)
from app.services.agent.research.material_plan import (
    compile_material_plan,
    empty_material_plan,
    merge_material_plan,
    next_evidence_escalation_batch,
    normalize_candidates,
    record_full_read_results,
    schedule_evidence_escalation,
    schedule_matched_evidence_recall_probes,
    schedule_selected_evidence_reassessment,
)
from app.services.agent.research.planner_decision import (
    ContextSelectorDecision,
    parse_context_selector_decision,
)
from app.services.agent.research.selector_transport import (
    apply_selector_question_scope_guard,
    decode_selector_transport_result,
    encode_selector_transport,
    render_selector_transport_cardinality_correction,
    render_selector_transport_output_requirements,
)
from app.services.agent.research.sufficiency import evaluate_sufficiency
from app.services.ai.semantic_summary import (
    DISCOVERY_SUMMARY_VERSION,
    SELECTOR_SUMMARY_VERSION,
)


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
        "budgets": {
            "planner_calls": planner_calls,
            "selector_verification_calls": 4,
            "deep_reads": 3,
        },
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
        "summary_version": DISCOVERY_SUMMARY_VERSION,
        "summary_model": f"llm:provider:model:v{DISCOVERY_SUMMARY_VERSION}",
        "selector_summary": f"Selector summary for {ref}",
        "selector_summary_version": SELECTOR_SUMMARY_VERSION,
        "status": "active",
    }


def test_precision_category_entailment_is_semantic_but_source_grounded() -> None:
    assert "semantic, not exact-string matching" in PRECISION_CONFIRMATION_SYSTEM
    assert "same evidence explicitly states the property" in PRECISION_CONFIRMATION_SYSTEM
    assert "Never manufacture the requested taxonomy" in PRECISION_CONFIRMATION_SYSTEM
    assert "first establish one explicit alternative set" in PRECISION_CONFIRMATION_SYSTEM
    assert "generic description of one possible option" in PRECISION_CONFIRMATION_SYSTEM


def test_primary_selector_requires_one_coherent_set_for_implicit_comparison() -> None:
    assert "first establish one explicit alternative set" in CONTEXT_SELECTOR_SYSTEM
    assert "Do not invent the referenced alternatives" in CONTEXT_SELECTOR_SYSTEM
    assert "combining unrelated single-option" in CONTEXT_SELECTOR_SYSTEM


def test_precision_inventory_prompt_uses_source_local_member_units() -> None:
    assert "repeat that unit coordinate once per member" in PRECISION_CONFIRMATION_SYSTEM
    assert "runtime validates only local coordinates, cardinality" in PRECISION_CONFIRMATION_SYSTEM
    assert "exact verbatim quote" not in PRECISION_CONFIRMATION_SYSTEM
    assert "smallest sufficient proof span" in PRECISION_CONFIRMATION_SYSTEM
    assert "document length, detail" in PRECISION_CONFIRMATION_SYSTEM


def test_selector_prompts_do_not_turn_observed_examples_into_normative_advice() -> None:
    for prompt in (
        CONTEXT_SELECTOR_SYSTEM,
        OPENED_EVIDENCE_REASSESSMENT_SYSTEM,
        PRECISION_CONFIRMATION_SYSTEM,
    ):
        assert "file extension" in prompt
        assert "norm" in prompt
        assert "asks for an inference" in prompt or "asks to infer" in prompt


def test_opened_window_recovery_does_not_force_rejected_rows_into_final_context() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:older", source="workspace-posts"),
        ]
    )
    positions = {"post:recent": 1, "post:older": 2}
    for candidate in candidates[1:]:
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": positions[str(candidate["ref"])],
                "window_size": 2,
            }
        ]
        candidate["opened_evidence"] = {
            "text": "Verified observation.",
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": "note:plan",
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                },
                {
                    "ref": "post:recent",
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                },
                {
                    "ref": "post:older",
                    "relevance": "irrelevant",
                    "role": "none",
                    "resolution": "none",
                    "confidence": 0.9,
                    "reason_code": "topic_only",
                },
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )

    closed, promoted = _close_opened_catalog_window_prefix(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan={"finite_source_recovery_refs": ["post:older"]},
    )

    assert promoted == ()
    assert [
        item.ref
        for item in closed.assessments
        if item.relevance.value != "irrelevant"
    ] == ["note:plan", "post:recent"]


def test_opened_window_closes_incomplete_anchor_through_completed_run() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:draft", source="workspace-posts"),
            _candidate("post:published-one", source="workspace-posts"),
            _candidate("post:published-two", source="workspace-posts"),
            _candidate("post:older-draft", source="workspace-posts"),
        ]
    )
    lifecycle = {
        "post:draft": (1, "draft"),
        "post:published-one": (2, "published"),
        "post:published-two": (3, "published"),
        "post:older-draft": (4, "draft"),
    }
    for candidate in candidates:
        if candidate["ref"] == "note:plan":
            continue
        position, status = lifecycle[str(candidate["ref"])]
        candidate["status"] = status
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 4,
            }
        ]
        candidate["opened_evidence"] = {
            "text": "Verified ordered observation.",
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": str(candidate["ref"]),
                    "relevance": (
                        "direct"
                        if candidate["ref"] in {"note:plan", "post:draft"}
                        else "irrelevant"
                    ),
                    "role": (
                        "answer_evidence"
                        if candidate["ref"] in {"note:plan", "post:draft"}
                        else "none"
                    ),
                    "resolution": (
                        "full_text"
                        if candidate["ref"] in {"note:plan", "post:draft"}
                        else "none"
                    ),
                    "confidence": 0.9,
                    "reason_code": (
                        "exact_fact"
                        if candidate["ref"] in {"note:plan", "post:draft"}
                        else "topic_only"
                    ),
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )

    closed, promoted = _close_opened_catalog_window_prefix(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan={},
    )

    assert promoted == ("post:published-one", "post:published-two")
    assert {
        item.ref
        for item in closed.assessments
        if item.relevance.value != "irrelevant"
    } == {
        "note:plan",
        "post:draft",
        "post:published-one",
        "post:published-two",
    }


def test_window_fills_nearest_published_context_without_exceeding_source_max() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:new-draft", source="workspace-posts"),
            _candidate("post:published-one", source="workspace-posts"),
            _candidate("post:published-two", source="workspace-posts"),
            _candidate("post:published-three", source="workspace-posts"),
            _candidate("post:older-draft", source="workspace-posts"),
            _candidate("post:older-context", source="workspace-posts"),
        ]
    )
    lifecycle = {
        "post:new-draft": (1, "draft"),
        "post:published-one": (2, "published"),
        "post:published-two": (3, "published"),
        "post:published-three": (4, "published"),
        "post:older-draft": (5, "draft"),
        "post:older-context": (6, "published"),
    }
    selected = {
        "note:plan",
        "post:new-draft",
        "post:older-draft",
        "post:older-context",
    }
    for candidate in candidates:
        ref = str(candidate["ref"])
        if ref == "note:plan":
            continue
        position, status = lifecycle[ref]
        candidate["status"] = status
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 6,
            }
        ]
        if ref in selected:
            candidate["opened_evidence"] = {
                "text": "Verified selected evidence.",
                "digest": "1111111111111111",
                "citation_path": candidate["citation_path"],
                "source_revision": 1,
                "owner_verified": True,
                "status_verified": True,
                "truncated": False,
            }
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", maximum=5, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": str(candidate["ref"]),
                    "relevance": "direct" if candidate["ref"] in selected else "irrelevant",
                    "role": "answer_evidence" if candidate["ref"] in selected else "none",
                    "resolution": "full_text" if candidate["ref"] in selected else "none",
                    "confidence": 0.9,
                    "reason_code": "exact_fact" if candidate["ref"] in selected else "topic_only",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )

    closed, promoted = _close_opened_catalog_window_prefix(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan={},
    )

    assert promoted == ("post:published-one", "post:published-two")
    assert {
        item.ref
        for item in closed.assessments
        if item.relevance.value != "irrelevant"
        and item.ref.startswith("post:")
    } == {
        "post:new-draft",
        "post:published-one",
        "post:published-two",
        "post:older-draft",
        "post:older-context",
    }


@pytest.mark.asyncio
async def test_initial_decision_materializes_incomplete_anchor_published_prefix() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:draft", source="workspace-posts"),
            _candidate("post:published-one", source="workspace-posts"),
            _candidate("post:published-two", source="workspace-posts"),
            _candidate("post:older-draft", source="workspace-posts"),
        ]
    )
    lifecycle = {
        "post:draft": (1, "draft"),
        "post:published-one": (2, "published"),
        "post:published-two": (3, "published"),
        "post:older-draft": (4, "draft"),
    }
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["ref"] == "note:plan":
            continue
        position, status = lifecycle[str(candidate["ref"])]
        candidate["status"] = status
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 4,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    note_source["budget"] = {"deep_reads": 2}
    post_source = _source("workspace-posts", maximum=4, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    post_source["budget"] = {"deep_reads": 4}
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 4
    primary = _wire_output(
        candidates,
        {
            str(candidate["ref"]): (
                ("d", "a", "c", 0.9, "e")
                if candidate["ref"] in {"note:plan", "post:draft"}
                else ("i", "n", "n", 0.9, "t")
            )
            for candidate in candidates
        },
        contract=contract,
        source_status="s",
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=primary,
    ) as selector:
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {
        "note:plan",
        "post:draft",
        "post:published-one",
        "post:published-two",
    }
    assert {
        action["args"].get("note_id") or action["args"].get("post_id")
        for action in result["tool_action"]["actions"]
    } == {"plan", "draft", "published-one", "published-two"}


def test_window_fill_uses_full_plan_when_reassessment_registry_is_reduced() -> None:
    full_candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:new-draft", source="workspace-posts"),
            _candidate("post:published-one", source="workspace-posts"),
            _candidate("post:published-two", source="workspace-posts"),
            _candidate("post:published-three", source="workspace-posts"),
            _candidate("post:older-draft", source="workspace-posts"),
            _candidate("post:older-published", source="workspace-posts"),
        ]
    )
    lifecycle = {
        "post:new-draft": (1, "draft"),
        "post:published-one": (2, "published"),
        "post:published-two": (3, "published"),
        "post:published-three": (4, "published"),
        "post:older-draft": (5, "draft"),
        "post:older-published": (6, "published"),
    }
    selected = {
        "note:plan",
        "post:new-draft",
        "post:older-draft",
        "post:older-published",
    }
    for candidate in full_candidates:
        ref = str(candidate["ref"])
        if ref == "note:plan":
            continue
        position, status = lifecycle[ref]
        candidate["status"] = status
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 6,
            }
        ]
    reassessment_candidates = [
        candidate for candidate in full_candidates if candidate["ref"] in selected
    ]
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", maximum=5, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": str(candidate["ref"]),
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                }
                for candidate in reassessment_candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )

    closed, promoted = _close_opened_catalog_window_prefix(
        decision,
        candidates=reassessment_candidates,
        contract=contract,
        material_plan={"candidates": full_candidates},
    )

    assert promoted == ("post:published-one", "post:published-two")
    assert {
        item.ref
        for item in closed.assessments
        if item.relevance.value != "irrelevant" and item.ref.startswith("post:")
    } == {
        "post:new-draft",
        "post:published-one",
        "post:published-two",
        "post:older-draft",
        "post:older-published",
    }


def test_opened_window_lifecycle_closure_requires_catalog_decision_input() -> None:
    candidates = normalize_candidates(
        [
            _candidate("post:draft", source="workspace-posts"),
            _candidate("post:published", source="workspace-posts"),
        ]
    )
    for position, candidate in enumerate(candidates, start=1):
        candidate["status"] = "draft" if position == 1 else "published"
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 2,
            }
        ]
        candidate["opened_evidence"] = {
            "text": "Verified ordered observation.",
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "semantic_relevance"
    contract = _contract(post_source)
    contract["task_profile"] = "topical_answer"
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": "post:draft",
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                },
                {
                    "ref": "post:published",
                    "relevance": "irrelevant",
                    "role": "none",
                    "resolution": "none",
                    "confidence": 0.9,
                    "reason_code": "topic_only",
                },
            ],
            "source_dispositions": [
                {"source_id": "workspace-posts", "status": "selected"}
            ],
        }
    )

    closed, promoted = _close_opened_catalog_window_prefix(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan={},
    )

    assert promoted == ()
    assert [
        item.ref
        for item in closed.assessments
        if item.relevance.value != "irrelevant"
    ] == ["post:draft"]


def test_selector_transport_cardinality_retry_explains_typed_source_limits() -> None:
    note_source = _source("workspace-notes", maximum=2)
    post_source = _source("workspace-posts", maximum=3)
    transport = encode_selector_transport(
        question="q",
        dialog_context="",
        contract=_contract(note_source, post_source),
        candidates=[
            _candidate("note:n1"),
            _candidate("post:p1", source="workspace-posts"),
        ],
    )

    requirements = render_selector_transport_output_requirements(transport.mapping)
    correction = render_selector_transport_cardinality_correction(
        transport.mapping,
        ("de9", "se8"),
    )

    assert "maximum count of positive d/s rows" in requirements
    assert "count d/s independently for every source" in requirements
    assert "catalog-window membership or recency alone never makes a row positive" in requirements
    assert "min never justifies selecting irrelevant material" in requirements
    assert "For source_cardinality_exceeded only" in correction
    assert "source index 0 (workspace-notes) max 2 positive rows" in correction
    assert "source index 1 (workspace-posts) max 3 positive rows" in correction
    assert "candidate positions are [0]" in correction
    assert "Your prior assessment vector was ['de9', 'se8']" in correction
    assert "your prior vector selected 1 at positions [0], overflow 0" in correction


@pytest.mark.asyncio
async def test_initial_selector_overflow_is_deferred_to_opened_reassessment() -> None:
    candidates = normalize_candidates(
        [_candidate("note:n1"), _candidate("note:n2"), _candidate("note:n3")]
    )
    contract = _contract(_source("workspace-notes", minimum=1, maximum=2))
    transport = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    invalid = (
        f"CS2|n=3|r={transport.mapping.registry_nonce}|"
        "a=de9,de9,de9|done"
    )
    strict = decode_selector_transport_result(
        invalid,
        mapping=transport.mapping,
        plain_frame=True,
    )
    exploratory = decode_selector_transport_result(
        invalid,
        mapping=transport.mapping,
        plain_frame=True,
        allow_source_overflow=True,
    )
    assert strict.decision is None
    assert strict.error_codes == ("source_cardinality_exceeded",)
    assert exploratory.decision is not None

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[invalid],
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n1", "note:n2", "note:n3"]


def test_opened_reassessment_cardinality_ignores_exploratory_prior_selection() -> None:
    candidates = normalize_candidates(
        [_candidate("note:n1"), _candidate("note:n2"), _candidate("note:n3")]
    )
    contract = _contract(_source("workspace-notes", minimum=1, maximum=2))
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct" if index == 0 else "irrelevant",
                    "role": "answer_evidence" if index == 0 else "none",
                    "resolution": "full_text" if index == 0 else "none",
                    "confidence": 1.0,
                    "reason_code": "exact_fact" if index == 0 else "topic_only",
                }
                for index, candidate in enumerate(candidates)
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"}
            ],
        }
    )
    prior_plan = {
        **empty_material_plan(),
        "candidates": candidates,
        "required_full_text_ids": [candidate["ref"] for candidate in candidates],
    }

    assert not _unified_selector_decision_is_valid(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan=prior_plan,
    )
    assert _unified_selector_decision_is_valid(
        decision,
        candidates=candidates,
        contract=contract,
        material_plan=prior_plan,
        include_prior_selected_in_cardinality=False,
    )


def test_workspace_synthesis_record_without_ordered_input_uses_factual_precision() -> None:
    contract = {
        **_contract(_source("workspace-notes"), _source("workspace-posts")),
        "task_profile": "workspace_synthesis",
        "answer_shape": {"kind": "record", "expected_member_count": None},
    }

    assert _uses_decision_input_precision(contract) is False


def test_workspace_synthesis_freeform_uses_composite_precision() -> None:
    contract = {
        **_contract(_source("workspace-notes"), _source("workspace-posts")),
        "task_profile": "workspace_synthesis",
        "answer_shape": {"kind": "freeform", "expected_member_count": None},
    }

    assert _uses_decision_input_precision(contract) is True


def test_multi_obligation_topical_answer_widens_only_small_note_card_discovery() -> None:
    note_source = _source("workspace-notes", evidence="optional")
    note_source.update(
        {
            "discovery_mode": "semantic_relevance",
            "scope": {"mode": "corpus", "statuses": []},
        }
    )
    post_source = _source("workspace-posts", evidence="required")
    post_source["evidence_requirements"] = [
        {
            "requirement_id": "workspace-posts:first-alternative",
            "operator": "exists",
            "property": "first alternative outcome",
        },
        {
            "requirement_id": "workspace-posts:second-alternative",
            "operator": "exists",
            "property": "second alternative outcome",
        },
    ]
    contract = {
        **_contract(note_source, post_source),
        "task_profile": "topical_answer",
        "answer_shape": {"kind": "freeform", "expected_member_count": None},
    }

    assert _uses_finite_note_catalog_recall(contract, note_source) is True

    post_source["evidence_requirements"] = post_source["evidence_requirements"][:1]
    assert _uses_finite_note_catalog_recall(contract, note_source) is False


def test_decision_obligations_use_atomic_requirements_and_confirmed_windows_only() -> None:
    note_source = _source("workspace-notes", evidence="required")
    note_source["evidence_requirements"] = [
        {"requirement_id": "workspace-notes:workflow_steps"},
        {"requirement_id": "workspace-notes:enabling_capabilities"},
    ]
    post_source = _source("workspace-posts", evidence="required")
    post_source["evidence_requirements"] = [
        {"requirement_id": "workspace-posts:workflow_example"}
    ]
    post_source["discovery_mode"] = "semantic_relevance"
    candidates = normalize_candidates(
        [
            _candidate("note:workflow"),
            _candidate("post:workflow", source="workspace-posts"),
        ]
    )
    candidates[1]["catalog_window_memberships"] = [
        {
            "source_requirement_id": "workspace-posts",
            "position": 1,
            "window_size": 2,
        }
    ]
    contract = _contract(note_source, post_source)

    obligations = _decision_precision_obligations(candidates, contract)

    assert obligations == (
        (
            "answer:0",
            "answer:1",
            "answer:2",
        ),
        (
            "answer:0",
            "answer:1",
            "answer:2",
        ),
    )

    contract["source_requirements"][1]["discovery_mode"] = "catalog_window"
    assert _decision_precision_obligations(candidates, contract)[1] == (
        "workspace-posts:window_position:1",
    )


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


def _wire_output(
    candidates: list[dict],
    assessments: dict[str, tuple[str, str, str, float, str]],
    *,
    contract: dict,
    source_status: str,
) -> str:
    del source_status
    transport = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    codes = [
        value[0] + value[4] + str(round(value[3] * 9))
        for candidate in candidates
        for value in [assessments[str(candidate["ref"])]]
    ]
    return f"CS2|n={len(codes)}|r={transport.mapping.registry_nonce}|a={','.join(codes)}|done"


def _precision_output(
    candidates: list[dict],
    keep_refs: list[str],
    *,
    contract: dict,
    complete_ref: str | None = None,
    source_texts: dict[str, str] | None = None,
    question: str = "Что относится к теме?",
) -> str:
    transport = encode_selector_transport(
        question=question,
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    positions = [
        index
        for index, candidate in enumerate(candidates)
        if str(candidate["ref"]) in keep_refs
    ]
    complete_position = (
        next(
            index
            for index, candidate in enumerate(candidates)
            if str(candidate["ref"]) == (complete_ref or keep_refs[0])
        )
        if len(positions) == 1
        else -1
    )
    decision_input_mode = _uses_decision_input_precision(contract)
    decision_obligations = _decision_precision_obligations(candidates, contract)
    obligation_registry = _decision_obligation_registry(decision_obligations)
    answer_shape = contract.get("answer_shape") or {}
    answer_obligation_count = len(_decision_answer_obligation_registry(contract))
    obligation_assignment_mode = bool(
        decision_input_mode
        or (
            str(answer_shape.get("kind") or "") != "inventory"
            and answer_obligation_count > 1
        )
    )
    assigned_positions: dict[str, int] = {}
    if obligation_assignment_mode and positions:
        position_cursor = 0
        for obligation in obligation_registry:
            allowed_positions = [
                position
                for position in positions
                if obligation in decision_obligations[position]
            ]
            if not allowed_positions:
                continue
            assigned_positions[obligation] = allowed_positions[
                position_cursor % len(allowed_positions)
            ]
            position_cursor += 1
    obligation_registry = _decision_obligation_registry(
        decision_obligations if obligation_assignment_mode else None
    )
    obligation_assignments = {
        str(index): {
            "obligation": obligation,
            "coordinate": (
                f"{assigned_positions[obligation]}:0"
                if obligation in assigned_positions
                else "-1:-1"
            ),
        }
        for index, obligation in enumerate(obligation_registry)
    }

    def member_warrant(position: int) -> list[dict[str, object]]:
        candidate = candidates[position]
        ref = str(candidate["ref"])
        text = str(
            (source_texts or {}).get(ref)
            or ((candidate.get("opened_evidence") or {}).get("text"))
            or ((candidate.get("matched_evidence") or {}).get("text"))
            or candidate.get("selector_summary")
            or ""
        )
        units = _precision_evidence_units(text)
        quote = units[0]["text"] if units else text.strip()
        if decision_input_mode:
            return []
        return [{"unit": 0, "quote": quote}]

    gates = {
        str(position): (
            {
                "subject": True,
                "relation": True,
                "complete": True,
                "relation_warrant": 0,
                "value_warrants": [0],
                "member_warrants": member_warrant(position),
            }
            if position == complete_position
            else {
                "subject": True,
                "relation": True,
                "complete": False,
                "relation_warrant": 0,
                "value_warrants": [0],
                "member_warrants": member_warrant(position),
            }
            if position in positions
            else {
                "subject": False,
                "relation": False,
                "complete": False,
                "relation_warrant": -1,
                "value_warrants": [],
                "member_warrants": [],
            }
        )
        for position in range(len(candidates))
    }
    return json.dumps(
        {
            "v": PRECISION_CONFIRMATION_VERSION,
            "n": len(candidates),
            "r": transport.mapping.registry_nonce,
            "g": gates,
            "o": obligation_assignments,
            "b": complete_position,
            "k": positions,
            "done": True,
        }
    )


def _opened_reassessment_fixture(
    candidates: list[dict],
    contents: dict[str, str],
) -> tuple[dict, dict[str, dict]]:
    plan = merge_material_plan(
        empty_material_plan(), candidates=candidates, assessments=[]
    )
    plan.update(
        {
            "evidence_escalation_reassess_refs": [
                str(candidate["ref"]) for candidate in candidates
            ],
            "needs_evidence_reassessment": True,
        }
    )
    records = {
        candidate["citation_path"]: EvidenceRecord(
            id=candidate["citation_path"],
            kind=(
                "note_summary"
                if str(candidate["ref"]).startswith("note:")
                else "post_summary"
            ),
            source_ref=candidate["ref"],
            content=contents[str(candidate["ref"])],
            citation_path=candidate["citation_path"],
            citation_title=candidate["title"],
            metadata={
                "source_revision": 1,
                "owner_verified": True,
                "status_verified": True,
            },
        ).to_dict()
        for candidate in candidates
    }
    return plan, records


def test_precision_subset_contract_rejects_noncanonical_positions() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    transport = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    mapping = transport.mapping
    _, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    schema = _precision_confirmation_json_schema(mapping, unit_counts)
    assert schema["properties"]["k"]["items"]["enum"] == [0, 1]
    gate_schema = schema["properties"]["g"]["properties"]["0"]["properties"]
    assert gate_schema["relation_warrant"]["enum"] == [-1, 0]
    assert gate_schema["value_warrants"]["items"]["enum"] == [0]
    assert gate_schema["member_warrants"]["items"]["required"] == ["unit"]
    decision_schema = _precision_confirmation_json_schema(
        mapping,
        unit_counts,
        decision_input_mode=True,
        decision_obligations=_decision_precision_obligations(candidates, contract),
    )
    assert decision_schema["properties"]["g"]["properties"]["0"]["properties"][
        "member_warrants"
    ]["items"]["required"] == []
    assert decision_schema["properties"]["g"]["properties"]["0"]["properties"][
        "member_warrants"
    ]["maxItems"] == 0
    assignment_schema = decision_schema["properties"]["o"]["properties"]["0"]
    assert assignment_schema["required"] == ["obligation", "coordinate"]
    assert assignment_schema["properties"]["coordinate"] == {"type": "string"}
    unequal_decision_schema = _precision_confirmation_json_schema(
        mapping,
        (1, 3),
        decision_input_mode=True,
        decision_obligations=_decision_precision_obligations(candidates, contract),
    )
    assert unequal_decision_schema["properties"]["o"]["properties"]["0"][
        "properties"
    ]["coordinate"] == {"type": "string"}
    assert "proof_shape" not in gate_schema
    unequal_schema = _precision_confirmation_json_schema(mapping, (1, 3))
    unequal_gates = unequal_schema["properties"]["g"]["properties"]
    assert unequal_gates["0"]["properties"]["relation_warrant"]["enum"] == [-1, 0]
    assert unequal_gates["1"]["properties"]["relation_warrant"]["enum"] == [
        -1,
        0,
        1,
        2,
    ]
    composite_schema = _precision_confirmation_json_schema(
        mapping,
        unit_counts,
        structurally_incomplete_positions=(0, 1),
    )
    composite_gates = composite_schema["properties"]["g"]["properties"]
    assert composite_gates["0"]["properties"]["complete"]["const"] is False
    assert composite_gates["1"]["properties"]["complete"]["const"] is False
    assert composite_schema["properties"]["b"]["enum"] == [-1]
    assert "a" not in schema["properties"]
    assert "uniqueItems" not in schema["properties"]["k"]
    assert "minimum" not in schema["properties"]["k"]["items"]
    valid = _precision_output(candidates, ["note:n1"], contract=contract)
    positions, errors = _decode_precision_confirmation(
        valid,
        mapping=mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
        unit_texts=unit_texts,
    )
    assert positions == (0,)
    assert errors == ()

    contradictory = json.loads(valid)
    contradictory["g"]["1"] = {
        "subject": True,
        "relation": True,
        "complete": True,
        "relation_warrant": 0,
        "value_warrants": [0],
        "member_warrants": [],
    }
    contradictory["b"] = -1
    contradictory["k"] = [0, 1]
    assert _decode_precision_confirmation(
        json.dumps(contradictory),
        mapping=mapping,
        unit_counts=unit_counts,
    ) == (None, ("inconsistent_composite_subset",))

    payload = json.loads(valid)
    payload["g"]["0"]["relation_warrant"] = 1
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (None, ("invalid_relation_warrant",))

    payload = json.loads(valid)
    payload["g"]["0"]["value_warrants"] = [1]
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (None, ("invalid_value_warrants",))

    payload = json.loads(valid)
    payload["k"] = [1, 0]
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (
        None,
        ("invalid_positions",),
    )
    payload["k"] = [0]
    payload["r"] = "0" * 16
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (
        None,
        ("registry_mismatch",),
    )
    assert _decode_precision_confirmation(
        valid + "\nexplanation", mapping=mapping, unit_counts=unit_counts
    ) == (None, ("missing_frame",))
    payload = json.loads(valid)
    payload["g"]["0"].update({"relation": False, "relation_warrant": -1})
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (None, ("inconsistent_value_warrants",))
    payload = json.loads(valid)
    payload["g"] = {
        "0": {"subject": True, "relation": True, "complete": True, "relation_warrant": 0, "value_warrants": [0], "member_warrants": [{"unit": 0, "quote": "Selector summary for note:n1"}]},
        "1": {"subject": True, "relation": True, "complete": False, "relation_warrant": 0, "value_warrants": [0], "member_warrants": [{"unit": 0, "quote": "Selector summary for note:n2"}]},
    }
    payload["b"] = -1
    payload["k"] = [0, 1]
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (
        None,
        ("inconsistent_composite_subset",),
    )


    payload = json.loads(valid)
    payload.update({"b": 1, "k": [1]})
    payload["g"] = {
        "0": {"subject": True, "relation": True, "complete": True, "relation_warrant": 0, "value_warrants": [0], "member_warrants": [{"unit": 0, "quote": "Selector summary for note:n1"}]},
        "1": {"subject": True, "relation": True, "complete": True, "relation_warrant": 0, "value_warrants": [0], "member_warrants": [{"unit": 0, "quote": "Selector summary for note:n2"}]},
    }
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (
        (0,),
        (),
    )
    payload.update({"b": -1, "k": [0]})
    payload["g"] = {
        "0": {"subject": True, "relation": True, "complete": False, "relation_warrant": 0, "value_warrants": [0], "member_warrants": [{"unit": 0, "quote": "Selector summary for note:n1"}]},
        "1": {"subject": False, "relation": False, "complete": False, "relation_warrant": -1, "value_warrants": [], "member_warrants": []},
    }
    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=mapping, unit_counts=unit_counts
    ) == (
        None,
        ("inconsistent_composite_subset",),
    )


def test_precision_non_inventory_does_not_require_member_level_provenance() -> None:
    candidates = normalize_candidates([_candidate("note:record"), _candidate("note:other")])
    contract = _contract(_source("workspace-notes"))
    transport = encode_selector_transport(
        question="Compare the two delivery variants.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = json.loads(_precision_output(candidates, ["note:record"], contract=contract))
    payload["r"] = transport.mapping.registry_nonce
    selected_position = payload["b"]
    payload["g"][str(selected_position)]["member_warrants"] = []

    assert _decode_precision_confirmation(
        json.dumps(payload), mapping=transport.mapping, unit_counts=(1, 1)
    ) == ((selected_position,), ())


def test_factual_precision_binds_every_atomic_obligation_to_complete_row() -> None:
    candidates = normalize_candidates([_candidate("note:complete"), _candidate("note:partial")])
    source = _source("workspace-notes")
    source["evidence_requirements"] = [
        {
            "requirement_id": "workspace-notes:requested_value",
            "operator": "exists",
            "property": "requested value",
        },
        {
            "requirement_id": "workspace-notes:requested_reason",
            "operator": "exists",
            "property": "requested reason",
        },
    ]
    contract = _contract(source)
    transport = encode_selector_transport(
        question="Which option applies, and why?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    obligations = _decision_precision_obligations(candidates, contract)
    payload = json.loads(
        _precision_output(
            candidates,
            ["note:complete"],
            contract=contract,
            question="Which option applies, and why?",
        )
    )
    decode_kwargs = {
        "mapping": transport.mapping,
        "unit_counts": (1, 1),
        "decision_obligations": obligations,
    }

    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )

    payload["o"]["1"]["coordinate"] = "1:0"
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0, 1),
        (),
    )

    payload["g"]["1"].update({"subject": True, "relation": True, "relation_warrant": 0})
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0, 1),
        (),
    )


def test_factual_precision_preserves_split_assignments_even_when_rows_look_complete() -> None:
    candidates = normalize_candidates(
        [_candidate("note:broad"), _candidate("note:focused")]
    )
    source = _source("workspace-notes")
    source["evidence_requirements"] = [
        {"requirement_id": "workspace-notes:choice"},
        {"requirement_id": "workspace-notes:reason"},
    ]
    contract = _contract(source)
    transport = encode_selector_transport(
        question="Which option applies, and why not the other?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    obligations = _decision_precision_obligations(candidates, contract)
    payload = json.loads(
        _precision_output(
            candidates,
            ["note:broad", "note:focused"],
            contract=contract,
            question="Which option applies, and why not the other?",
        )
    )
    payload["g"] = {
        "0": {
            "subject": True,
            "relation": True,
            "complete": True,
            "relation_warrant": 0,
            "value_warrants": [0, 4],
            "member_warrants": [],
        },
        "1": {
            "subject": True,
            "relation": True,
            "complete": True,
            "relation_warrant": 1,
            "value_warrants": [1, 2],
            "member_warrants": [],
        },
    }
    payload["o"]["0"]["coordinate"] = "0:0"
    payload["o"]["1"]["coordinate"] = "1:2"

    assert _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=(5, 3),
        decision_obligations=obligations,
    ) == ((0, 1), ())


def test_precision_inventory_cardinality_uses_member_unit_coordinates() -> None:
    candidates = normalize_candidates([_candidate("note:five"), _candidate("note:six")])
    contract = {
        **_contract(_source("workspace-notes")),
        "answer_shape": {"kind": "inventory", "expected_member_count": 6},
    }
    transport = encode_selector_transport(
        question="List all six functional zones.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    candidates[0]["opened_evidence"] = {
        "text": "Functional zones: Alpha, Beta, Gamma, Delta, Epsilon."
    }
    candidates[1]["opened_evidence"] = {
        "text": "Functional zones: Alpha, Beta, Gamma, Delta, Epsilon, **Zeta\u00a0Zone**."
    }
    _, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )

    def gate(member_count: int, *, complete: bool) -> dict:
        return {
            "subject": True,
            "relation": True,
            "complete": complete,
            "relation_warrant": 0,
            "value_warrants": [0],
            "member_warrants": [{"unit": 0} for _ in range(member_count)],
        }

    payload = {
        "v": PRECISION_CONFIRMATION_VERSION,
        "n": 2,
        "r": transport.mapping.registry_nonce,
        "g": {
            "0": gate(5, complete=True),
            "1": gate(6, complete=False),
        },
        "o": {},
        "b": 0,
        "k": [0],
        "done": True,
    }
    decode_kwargs = {
        "mapping": transport.mapping,
        "unit_counts": unit_counts,
        "unit_sections": unit_sections,
        "unit_texts": unit_texts,
        "inventory_shape": True,
        "expected_member_count": 6,
    }

    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("wrong_member_cardinality",),
    )

    payload.update({"b": 1, "k": [1]})
    payload["g"] = {
        "0": gate(5, complete=False),
        "1": gate(6, complete=True),
    }
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == ((1,), ())

    payload["g"]["1"]["member_warrants"][-1]["unit"] = 1
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("invalid_member_warrants",),
    )


def test_precision_chooses_compact_proof_among_reasoner_complete_rows() -> None:
    candidates = normalize_candidates([_candidate("note:direct"), _candidate("note:broad")])
    contract = {
        **_contract(_source("workspace-notes")),
        "answer_shape": {"kind": "inventory", "expected_member_count": 5},
    }
    mapping = encode_selector_transport(
        question="List the five planned functions.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping

    def gate(units: list[int]) -> dict:
        return {
            "subject": True,
            "relation": True,
            "complete": True,
            "relation_warrant": units[0],
            "value_warrants": sorted(set(units)),
            "member_warrants": [{"unit": unit} for unit in units],
        }

    payload = {
        "v": PRECISION_CONFIRMATION_VERSION,
        "n": 2,
        "r": mapping.registry_nonce,
        "g": {
            "0": gate([1, 2, 3, 4, 5]),
            "1": gate([0, 5, 10, 15, 22]),
        },
        "o": {},
        "b": 1,
        "k": [1],
        "done": True,
    }

    assert _decode_precision_confirmation(
        json.dumps(payload),
        mapping=mapping,
        unit_counts=(6, 63),
        inventory_shape=True,
        expected_member_count=5,
    ) == ((0,), ())


def test_precision_registry_excludes_discovery_ranking_metadata() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    candidates[0]["semantic_score"] = 0.99
    candidates[0]["origin"] = "semantic_search"
    transport = encode_selector_transport(
        question="What is the complete answer?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )

    rendered, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    payload = json.loads(rendered)

    assert [row["row"] for row in payload["rows"]] == [0, 1]
    assert payload["rows"][0]["evidence_units"] == [
        {
            "unit": 0,
            "kind": "paragraph",
            "section_path": "root",
            "text": "Selector summary for note:n1",
        }
    ]
    assert payload["rows"][0]["query_focus_units"] == []
    assert unit_counts == (1, 1)
    assert unit_sections == (("root",), ("root",))
    assert unit_texts == (("Selector summary for note:n1",), ("Selector summary for note:n2",))
    assert "semantic_search" not in json.dumps(payload)


def test_precision_registry_aligns_evidence_by_transport_ref_not_input_order() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    transport = encode_selector_transport(
        question="Which source contains the answer?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    candidates[0]["opened_evidence"] = {"text": "Evidence belonging to n1."}
    candidates[1]["opened_evidence"] = {"text": "Evidence belonging to n2."}

    rendered, _, _, unit_texts = _render_precision_confirmation_registry(
        transport, list(reversed(candidates))
    )
    rows = json.loads(rendered)["rows"]

    assert transport.mapping.candidate_refs == ("note:n1", "note:n2")
    assert [row["evidence_units"][0]["text"] for row in rows] == [
        "Evidence belonging to n1.",
        "Evidence belonging to n2.",
    ]
    assert unit_texts == (
        ("Evidence belonging to n1.",),
        ("Evidence belonging to n2.",),
    )


def test_precision_registry_indexes_matched_units_without_replacing_full_text() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    candidates[0]["opened_evidence"] = {
        "text": """## Background

Unrelated introduction.

## Product areas

The workspace consists of linked areas, each with its own role.

Feed - current work.

Notes - retained knowledge.

## Appendix

Unrelated closing material.
""",
        "digest": "1111111111111111",
        "citation_path": "/note/global/n1/",
        "source_revision": 1,
        "owner_verified": True,
        "status_verified": True,
        "truncated": False,
    }
    candidates[0]["matched_evidence"] = {
        "text": """The workspace consists of linked areas, each with its own role.

Feed - current work.

Notes - retained knowledge.""",
        "digest": "2222222222222222",
        "node_type": "note_chunk",
        "source_revision": 1,
        "rank": 1,
        "truncated": False,
    }
    transport = encode_selector_transport(
        question="List every functional area.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )

    rendered, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    row = json.loads(rendered)["rows"][0]

    assert [unit["text"] for unit in row["query_focus_units"]] == [
        "The workspace consists of linked areas, each with its own role.",
        "Feed - current work.",
        "Notes - retained knowledge.",
    ]
    assert [unit["unit"] for unit in row["query_focus_units"]] == [3, 4, 5]
    assert [unit["text"] for unit in row["evidence_units"]] == [
        "Background",
        "Unrelated introduction.",
        "Product areas",
        "The workspace consists of linked areas, each with its own role.",
        "Feed - current work.",
        "Notes - retained knowledge.",
        "Appendix",
        "Unrelated closing material.",
    ]
    assert unit_counts == (8, 1)
    assert unit_sections[0][3:6] == ("Product areas",) * 3
    assert unit_texts[0][3:6] == tuple(
        unit["text"] for unit in row["query_focus_units"]
    )


def test_precision_registry_indexes_multiple_scoped_chunks_from_one_source() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    transport = encode_selector_transport(
        question="Find all relevant sections.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    candidates[0]["opened_evidence"] = {
        "text": "First relevant section.\n\nUnrelated middle.\n\nSecond relevant section."
    }
    candidates[0]["matched_evidence_units"] = [
        {"text": "First relevant section."},
        {"text": "Second relevant section."},
    ]
    rendered, _, _, _ = _render_precision_confirmation_registry(transport, candidates)
    focus = json.loads(rendered)["rows"][0]["query_focus_units"]

    assert [(item["unit"], item["text"]) for item in focus] == [
        (0, "First relevant section."),
        (2, "Second relevant section."),
    ]


def test_precision_units_preserve_sections_and_keep_fenced_blocks_atomic() -> None:
    units = _precision_evidence_units(
        """## Architecture

The system has two roots.

```text
root one
  child
root two
```

## Interface

The interface consists of linked zones.

- Feed
- Notes
"""
    )

    assert [unit["kind"] for unit in units] == [
        "heading",
        "paragraph",
        "code_block",
        "heading",
        "paragraph",
        "list_item",
        "list_item",
    ]
    assert units[2]["text"] == "root one\n  child\nroot two"
    assert units[2]["section_path"] == "Architecture"
    assert {unit["section_path"] for unit in units[3:]} == {"Interface"}


def test_precision_decoder_accepts_relation_unit_as_one_of_scoped_value_warrants() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"))
    transport = encode_selector_transport(
        question="List the members.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = json.loads(
        _precision_output(candidates, ["note:n1"], contract=contract)
    )
    payload["r"] = transport.mapping.registry_nonce
    payload["g"]["0"].update(
        {
            "relation_warrant": 0,
            "value_warrants": [1],
            "member_warrants": [{"unit": 1, "quote": "member one"}],
        }
    )
    unit_counts = (3, 1)
    unit_sections = (("section-a", "section-a", "section-b"), ("root",))

    assert _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
    ) == ((0,), ())

    payload["g"]["0"]["value_warrants"] = [0, 1]
    payload["g"]["0"]["member_warrants"] = [
        {"unit": 0, "quote": "scope"},
        {"unit": 1, "quote": "member one"},
    ]
    assert _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
    ) == ((0,), ())

    payload["g"]["0"]["value_warrants"] = [0, 2]
    payload["g"]["0"]["member_warrants"] = [
        {"unit": 0, "quote": "scope"},
        {"unit": 2, "quote": "member two"},
    ]
    assert _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
    ) == (None, ("cross_section_value_warrants",))


def test_precision_grouped_inventory_uses_distinct_member_units_as_provenance() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = {
        **_contract(_source("workspace-notes")),
        "answer_shape": {"kind": "inventory", "expected_member_count": 2},
    }
    transport = encode_selector_transport(
        question="List both areas.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = json.loads(_precision_output(candidates, ["note:n1"], contract=contract))
    payload["r"] = transport.mapping.registry_nonce
    payload["g"]["0"].update(
        {
            "relation_warrant": 0,
            "value_warrants": [1, 2],
            "member_warrants": [
                {"unit": 1},
                {"unit": 2},
            ],
        }
    )
    decode_kwargs = {
        "mapping": transport.mapping,
        "unit_counts": (3, 1),
        "unit_sections": (("areas", "areas", "areas"), ("root",)),
        "unit_texts": (("Areas", "First area", "Second area"), ("Other",)),
        "inventory_shape": True,
        "expected_member_count": 2,
    }

    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )

    payload["g"]["0"]["member_warrants"][0]["unit"] = 3
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("invalid_member_warrants",),
    )
    payload["g"]["0"]["member_warrants"][0]["unit"] = 1

    payload["g"]["0"].update(
        {
            "relation_warrant": 1,
            "value_warrants": [1, 2],
            "member_warrants": [
                {"unit": 1},
                {"unit": 2},
            ],
        }
    )
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )

    cross_section_kwargs = {
        **decode_kwargs,
        "unit_sections": (("areas", "areas", "appendix"), ("root",)),
    }
    assert _decode_precision_confirmation(
        json.dumps(payload), **cross_section_kwargs
    ) == (None, ("cross_section_value_warrants",))

    payload["g"]["0"]["value_warrants"] = [0, 1, 2]
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )

    payload["g"]["0"]["value_warrants"] = [2, 1, 2]
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )

    payload["g"]["0"]["member_warrants"][1]["unit"] = 1
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
    )


def test_precision_inventory_allows_grouped_members_to_share_a_unit() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = {
        **_contract(_source("workspace-notes")),
        "answer_shape": {"kind": "inventory", "expected_member_count": 2},
    }
    transport = encode_selector_transport(
        question="List both areas.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    payload = json.loads(_precision_output(candidates, ["note:n1"], contract=contract))
    payload["r"] = transport.mapping.registry_nonce
    payload["g"]["0"].update(
        {
            "relation_warrant": 0,
            "value_warrants": [1],
            "member_warrants": [
                {"unit": 1},
                {"unit": 1},
            ],
        }
    )
    decode_kwargs = {
        "mapping": transport.mapping,
        "unit_counts": (3, 1),
        "unit_sections": (("areas", "areas", "areas"), ("root",)),
        "unit_texts": (("Areas", "First area", "Second area"), ("Other",)),
        "inventory_shape": True,
        "expected_member_count": 2,
    }

    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        (0,),
        (),
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
async def test_catalog_window_candidates_preserve_source_local_member_positions() -> None:
    members = [
        {"id": "newest", "revision": 1},
        {"id": "older", "revision": 1},
    ]
    cards = [
        _candidate("post:older", source="recent-posts", origin="catalog_member", score=None),
        _candidate("post:newest", source="recent-posts", origin="catalog_member", score=None),
    ]
    with (
        patch(
            "app.services.agent.research.graph.resolve_current_source_revisions",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.agent.research.graph.load_discovery_cards_for_objects",
            new_callable=AsyncMock,
            return_value=cards,
        ),
    ):
        candidates, fresh_count = await _catalog_member_candidates(
            AsyncMock(),
            user_id="user",
            tenant_key=None,
            kind="posts",
            members=members,
            source_id="recent-posts",
            typed_catalog=True,
            catalog_window={"discovery_mode": "catalog_window"},
        )

    assert fresh_count == 2
    memberships = {
        item["ref"]: item["catalog_window_memberships"][0] for item in candidates
    }
    assert memberships == {
        "post:newest": {
            "source_requirement_id": "recent-posts",
            "position": 1,
            "window_size": 2,
        },
        "post:older": {
            "source_requirement_id": "recent-posts",
            "position": 2,
            "window_size": 2,
        },
    }


def test_catalog_window_order_survives_candidate_merge_and_selector_transport() -> None:
    source = {
        **_source("recent-posts", evidence="required", maximum=4),
        "query_goal": "Observe recent output history before choosing the next artifact.",
        "discovery_mode": "catalog_window",
        "order_by": "created_at",
        "order_direction": "desc",
        "budget": {"candidate_limit": 4},
    }
    window_candidate = {
        **_candidate("post:p1", source="recent-posts", origin="catalog_member", score=None),
        "catalog_window_memberships": [
            {
                "source_requirement_id": "recent-posts",
                "position": 1,
                "window_size": 4,
            }
        ],
    }
    candidates = normalize_candidates(
        [window_candidate, _candidate("post:p1", source="semantic-posts")]
    )

    assert candidates[0]["catalog_window_memberships"] == [
        {
            "source_requirement_id": "recent-posts",
            "position": 1,
            "window_size": 4,
        }
    ]
    transport = encode_selector_transport(
        question="What should the next artifact be?",
        dialog_context="",
        contract=_contract(source, _source("semantic-posts")),
        candidates=candidates,
    )
    source_row = dict(zip(transport.payload["sc"], transport.payload["s"][0]))
    candidate_row = dict(zip(transport.payload["cc"], transport.payload["c"][0]))

    assert source_row | {} == {
        "i": 0,
        "k": "p",
        "e": "r",
        "min": 0,
        "max": 4,
        "f": "s",
        "g": "Observe recent output history before choosing the next artifact.",
        "dm": "w",
        "by": "created_at",
        "dir": "desc",
        "lim": 4,
    }
    assert candidate_row["w"] == [[0, 1, 4]]


def test_semantic_source_transport_has_no_catalog_window_membership_signal() -> None:
    candidates = normalize_candidates([_candidate("post:p1", source="semantic-posts")])
    transport = encode_selector_transport(
        question="Which post states the requested fact?",
        dialog_context="",
        contract=_contract(_source("semantic-posts")),
        candidates=candidates,
    )

    assert "w" not in transport.payload["cc"]
    source_row = dict(zip(transport.payload["sc"], transport.payload["s"][0]))
    assert source_row["dm"] == "s"


def test_bounded_catalog_transport_exposes_both_existing_semantic_projections() -> None:
    candidate = _candidate(
        "note:n1",
        origin="authoritative_catalog",
        score=None,
    )
    candidate["preview"] = "Two delivery variants differ in intended use."
    candidate["selector_summary"] = "The product is self-hosted."
    transport = encode_selector_transport(
        question="Which recorded alternative fits?",
        dialog_context="",
        contract=_contract(_source("workspace-notes")),
        candidates=normalize_candidates([candidate]),
    )
    candidate_row = dict(zip(transport.payload["cc"], transport.payload["c"][0]))

    assert "The product is self-hosted." in candidate_row["data"]
    assert (
        "<discovery_summary>Two delivery variants differ in intended use."
        "</discovery_summary>" in candidate_row["data"]
    )


def test_workspace_synthesis_unknown_count_inventory_uses_member_proof() -> None:
    contract = {
        **_contract(_source("recent-posts")),
        "task_profile": "workspace_synthesis",
        "answer_shape": {"kind": "inventory", "expected_member_count": None},
    }

    assert _is_inventory_answer_shape(contract) is True
    assert _uses_decision_input_precision(contract) is False


def test_finite_inventory_uses_factual_precision_even_with_synthesis_profile() -> None:
    contract = {
        **_contract(_source("workspace-notes")),
        "task_profile": "workspace_synthesis",
        "answer_shape": {"kind": "inventory", "expected_member_count": 6},
    }

    assert _is_inventory_answer_shape(contract) is True
    assert _uses_decision_input_precision(contract) is False


def test_unique_semantic_candidate_preserves_query_evidence_provenance() -> None:
    envelope = normalize_candidates([_candidate("note:n1")])[0]

    assert envelope["search_enriched"] is True
    assert envelope["semantic_rank_score"] == 0.8


@pytest.mark.asyncio
async def test_first_pass_matched_evidence_uses_unique_semantic_candidate() -> None:
    class SessionContext:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *_args):
            return None

    candidates = normalize_candidates([_candidate("note:n1")])
    ctx = SimpleNamespace(
        session_factory=SessionContext,
        user_id="user",
        scope="global",
        embedding_backend=AsyncMock(),
        tenant_key=None,
        post_data=None,
        min_similarity=0.38,
        scope_bias=0.0,
    )
    with patch(
        "app.services.agent.research.graph.retrieve_for_discovery",
        new_callable=AsyncMock,
        return_value=[
            {
                "node_type": "note_chunk",
                "note_id": "n1",
                "chunk_text": "Two delivery contours: demo and full product.",
                "index_revision": 1,
            }
        ],
    ) as retrieve:
        augmented, telemetry = await _attach_matched_selector_evidence(
            ctx=ctx,
            question="How do the contours differ?",
            candidates=candidates,
        )

    assert augmented[0]["matched_evidence"]["text"].startswith("Two delivery contours")
    assert telemetry[0]["ref"] == "note:n1"
    assert retrieve.await_args.kwargs["min_similarity"] == 0.38


@pytest.mark.asyncio
async def test_matched_evidence_retains_bounded_ranked_chunks_per_object() -> None:
    class SessionContext:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *_args):
            return None

    candidates = normalize_candidates([_candidate("note:n1")])
    ctx = SimpleNamespace(
        session_factory=SessionContext,
        user_id="user",
        scope="global",
        embedding_backend=AsyncMock(),
        tenant_key=None,
        post_data=None,
        min_similarity=0.38,
        scope_bias=0.0,
    )
    hits = [
        {
            "node_type": "note_chunk",
            "note_id": "n1",
            "chunk_text": f"Relevant chunk {index}",
            "index_revision": 1,
        }
        for index in range(4)
    ]
    with patch(
        "app.services.agent.research.graph.retrieve_for_discovery",
        new_callable=AsyncMock,
        return_value=hits,
    ):
        augmented, telemetry = await _attach_matched_selector_evidence(
            ctx=ctx,
            question="Find the relevant detail.",
            candidates=candidates,
        )

    assert [item["text"] for item in augmented[0]["matched_evidence_units"]] == [
        "Relevant chunk 0",
        "Relevant chunk 1",
        "Relevant chunk 2",
    ]
    assert augmented[0]["matched_evidence"]["text"] == "Relevant chunk 0"
    assert telemetry[0]["focus_chunk_count"] == 3
    assert telemetry[0]["focus_chunk_ranks"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_matched_evidence_enriches_unranked_authoritative_catalog_candidate() -> None:
    class SessionContext:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *_args):
            return None

    candidate = normalize_candidates([_candidate("note:n1")])[0]
    candidate.update(
        {
            "origin": "authoritative_catalog",
            "search_enriched": False,
            "semantic_score": None,
            "semantic_rank_score": None,
        }
    )
    ctx = SimpleNamespace(
        session_factory=SessionContext,
        user_id="user",
        scope="global",
        embedding_backend=AsyncMock(),
        tenant_key=None,
        post_data=None,
        min_similarity=0.38,
        scope_bias=0.0,
    )
    with patch(
        "app.services.agent.research.graph.retrieve_for_discovery",
        new_callable=AsyncMock,
        return_value=[
            {
                "node_type": "note_chunk",
                "note_id": "n1",
                "chunk_text": "The interface has six functional zones.",
                "index_revision": 1,
            }
        ],
    ) as retrieve:
        augmented, telemetry = await _attach_matched_selector_evidence(
            ctx=ctx,
            question="Name all six functional zones.",
            candidates=[candidate],
        )

    assert augmented[0]["matched_evidence"]["text"].startswith("The interface has six")
    assert telemetry[0]["ref"] == "note:n1"
    assert retrieve.await_args.kwargs["selected_object_ids"] == frozenset({"n1"})
    assert retrieve.await_args.kwargs["min_similarity"] == 0.0


@pytest.mark.asyncio
async def test_selector_semantic_decision_is_not_overridden_by_lexical_subject_spelling() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    candidates[0].update(
        {
            "title": "Пространственная система платформы",
            "selector_summary": "Система имеет два корневых объекта: заметку и пост.",
        }
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=1,
    )
    question = "Какие два корневых объекта есть в модели TG Platform?"
    transport = encode_selector_transport(
        question=question,
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    output = f"CS2|n=1|r={transport.mapping.registry_nonce}|a=de9|done"
    state = {
        **_state(contract, candidates),
        "user_text": question,
        "verified_pack_boundary_enabled": True,
    }

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=output,
        ),
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assessment = result["material_plan"]["assessments"][0]
    assert assessment["ref"] == "note:n1"
    assert assessment["relevance"] == "direct"
    assert result["planner_steps"][-1]["scope_guard_demoted_refs"] == []


@pytest.mark.asyncio
async def test_search_more_opens_candidate_then_reassesses_with_verified_evidence() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    candidates[0]["selector_semantic_flags"] = {
        "v": 2,
        "explicit_absence": True,
        "observational_value": False,
        "record_roles": [],
    }
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    first_output = _wire_output(
        candidates,
        {"note:n1": ("i", "n", "n", 0.9, "s")},
        contract=contract,
        source_status="m",
    )
    first_state = {
        **_state(contract, candidates),
        "verified_pack_boundary_enabled": True,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=first_output,
        ),
    ):
        first = await _compact_planner_node(
            first_state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert first["tool_action"]["actions"] == [
        {
            "tool": "OpenNote",
            "args": {
                "source_requirement_id": "workspace-notes",
                "note_id": "n1",
            },
            "intent_id": None,
        }
    ]
    assert first["material_plan"]["discovery_actions"] == []

    path = candidates[0]["citation_path"]
    record = EvidenceRecord(
        id=path,
        kind="note_chunk",
        source_ref="note:n1",
        content="Two delivery contours: demo and full product. Docker is full stack.",
        citation_path=path,
        citation_title="n1",
        metadata={
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
        },
    )
    opened_plan = record_full_read_results(
        first["material_plan"],
        opened=["note:n1"],
        batch=["note:n1"],
    )
    second_output = _wire_output(
        candidates,
        {"note:n1": ("d", "a", "f", 0.9, "e")},
        contract=contract,
        source_status="s",
    )
    audit_transport = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    final_evidence = json.dumps(
        {
            "v": 1,
            "r": audit_transport.mapping.registry_nonce,
            "a": [
                {
                    "p": 0,
                    "e": ["Two delivery contours: demo and full product."],
                }
            ],
            "done": True,
        }
    )
    second_state = {
        **first,
        "material_plan": opened_plan,
        "evidence_records": {path: record.to_dict()},
        "deep_reads_used": 1,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[second_output, final_evidence],
        ) as selector,
    ):
        second = await _compact_planner_node(
            second_state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    selector_input = selector.await_args_list[0].kwargs["messages"][1]["content"]
    selector_system = selector.await_args_list[0].kwargs["messages"][0]["content"]
    assert (
        selector.await_args_list[0].kwargs["phase"]
        == "research.selector.context_evidence_reassessment"
    )
    assert "opened_evidence as the primary source" in selector_system
    assert "opened_evidence" in selector_input
    assert "Two delivery contours: demo and full product" in selector_input
    assessment = second["material_plan"]["assessments"][0]
    assert assessment["ref"] == "note:n1"
    assert assessment["relevance"] == "direct"
    assert second["planner_steps"][-1]["scope_guard_demoted_refs"] == []
    assert second["material_plan"]["evidence_escalation_reassess_refs"] == []
    assert second["material_plan"]["needs_evidence_reassessment"] is False


@pytest.mark.asyncio
async def test_verified_opened_set_uses_reassessment_without_an_extra_call() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    candidates[0]["selector_summary"] = "A broad summary that omits the requested list."
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    plan = merge_material_plan(
        empty_material_plan(), candidates=candidates, assessments=[]
    )
    plan.update(
        {
            "evidence_escalation_reassess_refs": ["note:n1"],
            "needs_evidence_reassessment": True,
        }
    )
    path = candidates[0]["citation_path"]
    record = EvidenceRecord(
        id=path,
        kind="note_summary",
        source_ref="note:n1",
        content="The six zones are Feed, Post, Notes, Chats, Analytics, and Settings.",
        citation_path=path,
        citation_title="n1",
        metadata={
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
        },
    )
    confirmed = _wire_output(
        candidates,
        {"note:n1": ("d", "a", "f", 0.9, "e")},
        contract=contract,
        source_status="n",
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "selector_verification_calls_used": 0,
        "evidence_records": {path: record.to_dict()},
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=confirmed,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert selector.await_args_list[0].kwargs["phase"] == (
        "research.selector.context_evidence_reassessment"
    )
    selector_input = selector.await_args_list[0].kwargs["messages"][1]["content"]
    assert "The six zones are Feed, Post, Notes, Chats, Analytics, and Settings." in selector_input
    assert selector.await_args_list[0].kwargs["model"] == "selector"
    assert selector.await_args_list[0].kwargs["telemetry"]["model_role"] == "selector"
    assert result["selector_verification_calls_used"] == 0
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n1"]


@pytest.mark.asyncio
async def test_opened_reassessment_runs_independent_precision_for_multiple_selections() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:n1"),
            _candidate("post:p1", source="workspace-posts"),
            _candidate("note:n2"),
        ]
    )
    candidates[0]["title"] = "Пространственная система тг платформы"
    candidates[1]["title"] = "TG Platform"
    candidates[0]["selector_summary"] = (
        "Система имеет два корневых объекта: глобальная заметка и пост с вложениями."
    )
    candidates[0]["selector_semantic_flags"] = {
        "v": 2,
        "explicit_absence": False,
        "observational_value": True,
        "record_roles": [],
    }
    candidates[1]["selector_semantic_flags"] = {
        "v": 2,
        "explicit_absence": False,
        "observational_value": False,
        "record_roles": [],
    }
    candidates[2]["selector_semantic_flags"] = {
        "v": 2,
        "explicit_absence": False,
        "observational_value": False,
        "record_roles": [],
    }
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts"),
        planner_calls=2,
    )
    plan = merge_material_plan(
        empty_material_plan(), candidates=candidates, assessments=[]
    )
    plan.update(
        {
            "evidence_escalation_reassess_refs": [
                "note:n1",
                "post:p1",
                "note:n2",
            ],
            "needs_evidence_reassessment": True,
        }
    )
    records = {
        candidate["citation_path"]: EvidenceRecord(
            id=candidate["citation_path"],
            kind="note_summary" if candidate["ref"].startswith("note:") else "post_summary",
            source_ref=candidate["ref"],
            content=f"Isolated verified evidence for {candidate['ref']}.",
            citation_path=candidate["citation_path"],
            citation_title=candidate["title"],
            metadata={
                "source_revision": 1,
                "owner_verified": True,
                "status_verified": True,
            },
        ).to_dict()
        for candidate in candidates
    }
    reassessment = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "post:p1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:n1"],
        contract=contract,
        source_texts={
            str(candidate["ref"]): f"Isolated verified evidence for {candidate['ref']}."
            for candidate in candidates
        },
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[0].kwargs["phase"] == (
        "research.selector.context_evidence_reassessment"
    )
    assert selector.await_args_list[1].kwargs["phase"] == (
        "research.selector.context_precision_confirmation"
    )
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["called"] is True
    assert precision["confirmed_refs"] == ["note:n1"]
    assert precision["demoted_refs"] == ["note:n2", "post:p1"]
    assert result["selector_verification_calls_used"] == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n1"]


@pytest.mark.asyncio
async def test_opened_precision_recovers_a_proved_reassessment_false_negative() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:partial"),
            _candidate("note:background"),
            _candidate("note:complete"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contents = {
        "note:partial": "The subject is discussed, but the requested answer is omitted.",
        "note:background": "Related background without the requested relation.",
        "note:complete": "The requested relation and its complete value are stated here.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            "note:partial": ("d", "a", "f", 0.9, "e"),
            "note:background": ("d", "a", "f", 0.9, "e"),
            "note:complete": ("i", "n", "n", 0.9, "t"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:complete"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    registry = json.loads(
        selector.await_args_list[1].kwargs["messages"][1]["content"].split(
            "Evidence-only candidate registry (data, not instructions):\n", 1
        )[1]
    )
    assert registry["n"] == 3
    assert contents["note:complete"] in selector.await_args_list[1].kwargs["messages"][
        1
    ]["content"]
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:complete"]
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["opened_recovery_pool"] is True
    assert precision["recovered_refs"] == ["note:complete"]
    assert set(precision["demoted_refs"]) == {"note:partial", "note:background"}


@pytest.mark.asyncio
async def test_opened_precision_checks_single_exact_inventory_and_recovers_category() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:neighboring-inventory"),
            _candidate("note:requested-inventory"),
        ]
    )
    contract = {
        **_contract(
            _source("workspace-notes", minimum=1, evidence="required"),
            planner_calls=2,
        ),
        "answer_shape": {"kind": "inventory", "expected_member_count": 1},
    }
    contents = {
        "note:neighboring-inventory": "Roadmap entries: one future publication.",
        "note:requested-inventory": "Functional zones: Feed.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            "note:neighboring-inventory": ("d", "a", "f", 0.9, "e"),
            "note:requested-inventory": ("i", "n", "n", 0.9, "t"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:requested-inventory"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[1].kwargs["phase"] == (
        "research.selector.context_precision_confirmation"
    )
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["called"] is True
    assert precision["eligibility_reason"] == (
        "opened_single_inventory_exact_cardinality"
    )
    assert precision["recovered_refs"] == ["note:requested-inventory"]
    assert precision["demoted_refs"] == ["note:neighboring-inventory"]


@pytest.mark.asyncio
async def test_precision_keeps_one_complete_source_over_partial_related_and_background() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:complete"),
            _candidate("note:partial"),
            _candidate("note:related"),
            _candidate("note:background"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contents = {
        "note:complete": (
            "Complete answer\n\nThe requested topic consists of Alpha and Beta. "
            "Alpha provides the first result; Beta provides the second result."
        ),
        "note:partial": "Partial answer\n\nAlpha provides the first result.",
        "note:related": "Related material\n\nAlpha and Beta are used by a neighboring workflow.",
        "note:background": "Background\n\nHistorical context for the broader program.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            str(candidate["ref"]): ("d", "a", "f", 0.9, "e")
            for candidate in candidates
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates, ["note:complete"], contract=contract, source_texts=contents
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    precision_call = selector.await_args_list[1].kwargs
    assert "counterfactual deletion test" in precision_call["messages"][0]["content"]
    assert "Never manufacture the requested taxonomy" in precision_call["messages"][0][
        "content"
    ]
    assert all(
        content.splitlines()[-1] in precision_call["messages"][1]["content"]
        for content in contents.values()
    )
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:complete"]
    assert result["planner_steps"][-1]["precision_confirmation"]["demoted_refs"] == [
        "note:background",
        "note:partial",
        "note:related",
    ]
    complete_position = next(
        index
        for index, candidate in enumerate(candidates)
        if candidate["ref"] == "note:complete"
    )
    assessment_codes = result["planner_steps"][-1]["precision_confirmation"][
        "assessment_codes"
    ]
    assert assessment_codes[complete_position] == "f"
    assert assessment_codes.count("f") == 1
    assert assessment_codes.count("x") == len(candidates) - 1
    assert result["planner_steps"][-1]["precision_confirmation"][
        "best_self_contained_position"
    ] == complete_position


@pytest.mark.asyncio
async def test_precision_keeps_indispensable_plan_and_completed_history_premises() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:planned-sequence"),
            _candidate("post:completed-alpha", source="workspace-posts"),
            _candidate("post:completed-beta", source="workspace-posts"),
            _candidate("note:independent-constraint"),
            _candidate("note:related-background"),
            _candidate("post:unrelated-history", source="workspace-posts"),
        ]
    )
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    note_source["evidence_requirements"] = [
        {"requirement_id": "planned-sequence"},
        {"requirement_id": "independent-constraint"},
    ]
    for source in (note_source, post_source):
        source["discovery_mode"] = "catalog_window"
    source_positions: dict[str, int] = {}
    for candidate in candidates:
        source_id = str(candidate["source_requirement_id"])
        source_positions[source_id] = source_positions.get(source_id, 0) + 1
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": source_id,
                "position": source_positions[source_id],
                "window_size": sum(
                    item["source_requirement_id"] == source_id for item in candidates
                ),
            }
        ]
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contents = {
        "note:planned-sequence": (
            "Planned sequence\n\nThe backlog orders Alpha before Beta and Gamma."
        ),
        "post:completed-alpha": (
            "Published result\n\nAlpha from the planned sequence has already been published."
        ),
        "post:completed-beta": (
            "Published result\n\nBeta from the planned sequence has already been published."
        ),
        "note:independent-constraint": (
            "Editorial constraint\n\nGamma must precede Delta because Delta assumes Gamma."
        ),
        "note:related-background": (
            "Related background\n\nAlpha, Beta, and Gamma belong to the same broad program."
        ),
        "post:unrelated-history": (
            "Published result\n\nA separate campaign used a neighboring broad topic."
        ),
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    indispensable = {
        "note:planned-sequence",
        "post:completed-alpha",
        "post:completed-beta",
        "note:independent-constraint",
    }
    reassessment = _wire_output(
        candidates,
        {
            str(candidate["ref"]): (
                ("d", "a", "f", 0.9, "e")
                if candidate["ref"] in indispensable
                else ("i", "n", "n", 0.9, "x")
            )
            for candidate in candidates
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        sorted(indispensable),
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {
        "note:planned-sequence",
        "post:completed-alpha",
        "post:completed-beta",
        "note:independent-constraint",
    }
    assert selector.await_count == 2
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["called"] is True
    assert set(precision["confirmed_refs"]) == {
        "note:planned-sequence",
        "post:completed-alpha",
        "post:completed-beta",
        "note:independent-constraint",
    }
    assert precision["demoted_refs"] == []


@pytest.mark.asyncio
async def test_decision_precision_keeps_exact_workflow_and_capability_premises_only() -> None:
    candidates = normalize_candidates(
        [
            _candidate("post:workflow", source="workspace-posts"),
            _candidate("note:capabilities"),
            _candidate("note:architecture"),
            _candidate("note:delivery"),
            _candidate("post:historical-example", source="workspace-posts"),
        ]
    )
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contents = {
        "post:workflow": (
            "Author workflow\n\nDraft the publication, preview it, schedule it, and publish it "
            "from the same workspace."
        ),
        "note:capabilities": (
            "Workspace capabilities\n\nThe editor, media attachments, preview, scheduling, and "
            "publication controls provide the requested end-to-end workflow."
        ),
        "note:architecture": (
            "Architecture\n\nThe platform uses an application layer and a worker layer."
        ),
        "note:delivery": (
            "Delivery\n\nThe product supports demonstration and production deployment modes."
        ),
        "post:historical-example": (
            "Older example\n\nA previous publication used one part of the editor."
        ),
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            str(candidate["ref"]): ("d", "a", "f", 0.9, "e")
            for candidate in candidates
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["post:workflow", "note:capabilities"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    precision_prompt = selector.await_args_list[1].kwargs["messages"][0]["content"]
    assert selector.await_args_list[1].kwargs["max_tokens"] >= 1_400
    assert "exact question" in precision_prompt
    assert "atomic answer obligations" in precision_prompt
    assert "obligation_assignments" in precision_prompt
    assert "typed obligation" in precision_prompt
    assert "Source goals scope discovery" in precision_prompt
    assert "Optional elaboration" in precision_prompt
    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {"post:workflow", "note:capabilities"}
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["confirmed_refs"] == ["note:capabilities", "post:workflow"]
    assert precision["demoted_refs"] == [
        "note:architecture",
        "note:delivery",
        "post:historical-example",
    ]


def test_decision_precision_rejects_redundant_obligation_coverage() -> None:
    question = (
        "Build the author workflow: how to prepare and publish a post without switching "
        "services, and which platform capabilities enable that?"
    )
    candidates = normalize_candidates(
        [
            _candidate("post:workflow", source="workspace-posts"),
            _candidate("note:capabilities"),
            _candidate("note:background"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", evidence="required"),
        _source("workspace-posts", evidence="required"),
    )
    contract["task_profile"] = "recommendation"
    for candidate in candidates:
        candidate["opened_evidence"] = {
            "text": f"Verified evidence for {candidate['ref']}.",
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    transport = encode_selector_transport(
        question=question,
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    _, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    payload = json.loads(
        _precision_output(
            candidates,
            ["post:workflow", "note:capabilities", "note:background"],
            contract=contract,
            question=question,
        )
    )
    decision_obligations = _decision_precision_obligations(candidates, contract)
    positions_by_ref = {
        str(candidate["ref"]): position for position, candidate in enumerate(candidates)
    }
    workflow_position = positions_by_ref["post:workflow"]
    capability_position = positions_by_ref["note:capabilities"]
    background_position = positions_by_ref["note:background"]
    capability_obligation = decision_obligations[capability_position][0]
    capability_assignment = next(
        assignment
        for assignment in payload["o"].values()
        if assignment["obligation"] == capability_obligation
    )
    decode_kwargs = {
        "mapping": transport.mapping,
        "unit_counts": unit_counts,
        "unit_sections": unit_sections,
        "unit_texts": unit_texts,
        "decision_input_mode": True,
        "selector_question": question,
        "decision_obligations": decision_obligations,
    }

    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        tuple(sorted([workflow_position, background_position])),
        (),
    )

    capability_assignment["coordinate"] = f"{capability_position}:0"
    payload["k"] = sorted([workflow_position, capability_position])
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        tuple(sorted([workflow_position, capability_position])),
        (),
    )

    capability_assignment["coordinate"] = f"{capability_position}:1"
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("invalid_decision_obligation_assignment",),
    )

    capability_assignment["coordinate"] = f"0{capability_position}:0"
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("invalid_decision_obligation_assignment",),
    )

    capability_assignment["coordinate"] = f"{capability_position}:0"
    capability_assignment["obligation"] = "unknown:obligation"
    assert _decode_precision_confirmation(json.dumps(payload), **decode_kwargs) == (
        None,
        ("invalid_decision_obligation_assignment",),
    )


@pytest.mark.asyncio
async def test_decision_input_precision_waits_for_opened_reassessment() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent", source="workspace-posts"),
        ]
    )
    candidates[1]["catalog_window_memberships"] = [
        {
            "source_requirement_id": "workspace-posts",
            "position": 1,
            "window_size": 1,
        }
    ]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    primary = _wire_output(
        candidates,
        {
            "note:plan": ("d", "a", "c", 0.9, "e"),
            "post:recent": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["called"] is False
    assert precision["reason"] == (
        "deferred_until_opened_decision_input_reassessment"
    )
    assert result["material_plan"]["required_full_text_ids"] == [
        "post:recent",
        "note:plan",
    ]


@pytest.mark.asyncio
async def test_opened_decision_input_uses_precision_then_closes_recent_prefix() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:history", source="workspace-posts"),
        ]
    )
    position_by_ref = {"post:recent": 1, "post:history": 2}
    for candidate in candidates[1:]:
        position = position_by_ref[str(candidate["ref"])]
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 2,
            }
        ]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    note_source["discovery_mode"] = "semantic_relevance"
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contents = {
        "note:plan": "Planned sequence\n\nGamma follows Alpha.",
        "post:recent": "A sparse recent observation.",
        "post:history": "Published history\n\nAlpha has already been published.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    for candidate in candidates:
        candidate["opened_evidence"] = {
            "text": contents[str(candidate["ref"])],
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    reassessment = _wire_output(
        candidates,
        {
            "note:plan": ("d", "a", "f", 0.9, "e"),
            "post:recent": ("i", "n", "n", 0.9, "x"),
            "post:history": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:plan", "post:history"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {"note:plan", "post:history", "post:recent"}
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["schema_result"] == "valid"
    assert precision["called"] is True
    assert precision["confirmed_refs"] == [
        "note:plan",
        "post:history",
        "post:recent",
    ]
    assert precision["catalog_window_prefix_refs"] == ["post:recent"]
    assert precision["post_precision_prefix_refs"] == ["post:recent"]
    assert result["selector_verification_calls_used"] == 1
    reassessment_system = selector.await_args_list[0].kwargs["messages"][0]["content"]
    assert "plans, themes, interests, responses, constraints" in reassessment_system
    assert "useful relation exists between rows" in reassessment_system
    assert "newest member as the temporal anchor" in reassessment_system
    assert "smallest consecutive recent prefix" in reassessment_system


def test_opened_decision_recovery_sources_force_composite_precision_schema() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("note:secondary"),
            _candidate("post:recent", source="workspace-posts"),
        ]
    )
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    incomplete = _decision_registry_structurally_incomplete_positions(
        contract,
        candidates,
    )
    assert incomplete == (0, 1, 2)
    mapping = encode_selector_transport(
        question="Choose the next result.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping
    precision_schema = _precision_confirmation_json_schema(
        mapping,
        (1, 1, 1),
        structurally_incomplete_positions=incomplete,
    )
    gate_schemas = precision_schema["properties"]["g"]["properties"]
    assert all(
        gate_schemas[str(position)]["properties"]["complete"]["const"] is False
        for position in range(3)
    )
    assert precision_schema["properties"]["b"]["enum"] == [-1]


def test_semantic_sources_do_not_force_composite_precision_schema() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:answer"),
            _candidate("post:neighbor", source="workspace-posts"),
        ]
    )
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["evidence_requirements"] = [
        {"requirement_id": "workspace-posts:requested_decision"}
    ]
    contract = _contract(note_source, post_source)
    contract.update(
        {
            "task_profile": "workspace_synthesis",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
        }
    )

    obligations = _decision_precision_obligations(candidates, contract)

    assert obligations == (
        ("answer:0",),
        ("answer:0",),
    )
    assert _decision_registry_structurally_incomplete_positions(
        contract,
        candidates,
    ) == ()

    mapping = encode_selector_transport(
        question="Which option is suitable and why?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping
    payload = _precision_output(
        candidates,
        ["note:answer"],
        contract=contract,
        source_texts={
            "note:answer": "The requested option and rationale are stated here.",
            "post:neighbor": "Neighboring material.",
        },
        question="Which option is suitable and why?",
    )

    assert _decode_precision_confirmation(
        payload,
        mapping=mapping,
        unit_counts=(1, 1),
        unit_sections=(("root",), ("root",)),
        unit_texts=(
            ("The requested option and rationale are stated here.",),
            ("Neighboring material.",),
        ),
        decision_input_mode=True,
        selector_question="Which option is suitable and why?",
        decision_obligations=obligations,
    ) == ((0,), ())


@pytest.mark.asyncio
async def test_opened_catalog_recovery_extends_selected_recent_prefix() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:older", source="workspace-posts"),
        ]
    )
    position_by_ref = {"post:recent": 1, "post:older": 2}
    for candidate in candidates[1:]:
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position_by_ref[str(candidate["ref"])],
                "window_size": 2,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contents = {
        "note:plan": "Planned sequence.",
        "post:recent": "Current completed observation.",
        "post:older": "Earlier opened observation.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    plan["finite_source_recovery_refs"] = ["post:older"]
    for candidate in candidates:
        candidate["opened_evidence"] = {
            "text": contents[str(candidate["ref"])],
            "digest": "1111111111111111",
            "citation_path": candidate["citation_path"],
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    reassessment = _wire_output(
        candidates,
        {
            "note:plan": ("d", "a", "f", 0.9, "e"),
            "post:recent": ("d", "a", "f", 0.9, "e"),
            "post:older": ("i", "n", "n", 0.9, "x"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:plan", "post:older"],
        contract=contract,
        source_texts=contents,
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ),
    ):
        result = await _compact_planner_node(
            {
                **_state(contract, candidates, material_plan=plan),
                "planner_calls_used": 1,
                "evidence_records": records,
            },
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {"note:plan", "post:recent", "post:older"}
    assert precision["catalog_window_prefix_refs"] == ["post:recent"]
    assert precision["post_precision_prefix_refs"] == ["post:recent"]


@pytest.mark.asyncio
async def test_opened_catalog_window_zero_selection_stays_empty() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:background"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:older", source="workspace-posts"),
        ]
    )
    for position, candidate in enumerate(candidates[1:], start=1):
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 2,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    plan, records = _opened_reassessment_fixture(
        candidates,
        {
            "note:background": "Unrelated background.",
            "post:recent": "Unrelated recent observation.",
            "post:older": "Unrelated older observation.",
        },
    )
    reassessment = _wire_output(
        candidates,
        {str(candidate["ref"]): ("i", "n", "n", 0.9, "x") for candidate in candidates},
        contract=contract,
        source_status="n",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=reassessment,
        ),
    ):
        result = await _compact_planner_node(
            {
                **_state(contract, candidates, material_plan=plan),
                "planner_calls_used": 1,
                "evidence_records": records,
            },
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert not [
        item
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ]
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["confirmed_refs"] == []
    assert precision["catalog_window_prefix_refs"] == []


@pytest.mark.asyncio
async def test_opened_decision_input_consumes_one_precision_call() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:history", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=0, evidence="required"),
        _source("workspace-posts", minimum=0, evidence="required"),
        planner_calls=2,
    )
    contract["task_profile"] = "recommendation"
    contents = {
        "note:plan": "Planned sequence\n\nGamma follows Alpha.",
        "post:history": "Published history\n\nAlpha has already been published.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            str(candidate["ref"]): ("d", "a", "f", 0.9, "e")
            for candidate in candidates
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["note:plan", "post:history"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {"note:plan", "post:history"}
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["called"] is True
    assert precision["confirmed_refs"] == ["note:plan", "post:history"]
    assert result["selector_verification_calls_used"] == 1


@pytest.mark.asyncio
async def test_opened_decision_input_does_not_force_an_absent_source() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:background"),
            _candidate("post:history-one", source="workspace-posts"),
            _candidate("post:history-two", source="workspace-posts"),
        ]
    )
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    post_candidates = [
        candidate
        for candidate in candidates
        if candidate["source_requirement_id"] == "workspace-posts"
    ]
    for position, candidate in enumerate(post_candidates, start=1):
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": len(post_candidates),
            }
        ]
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contents = {
        "note:background": "Background\n\nA neighboring topic with no planning premise.",
        "post:history-one": "Published history\n\nAlpha has already been published.",
        "post:history-two": "Published history\n\nBeta has already been published.",
    }
    plan, records = _opened_reassessment_fixture(candidates, contents)
    reassessment = _wire_output(
        candidates,
        {
            "note:background": ("i", "n", "n", 0.9, "x"),
            "post:history-one": ("d", "a", "f", 0.9, "e"),
            "post:history-two": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(
        candidates,
        ["post:history-one", "post:history-two"],
        contract=contract,
        source_texts=contents,
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[reassessment, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert {
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    } == {"post:history-one", "post:history-two"}
    assert selector.await_count == 2
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["schema_result"] == "valid"
    assert precision["called"] is True
    assert "note:background" not in precision["confirmed_refs"]


@pytest.mark.asyncio
async def test_opened_evidence_reassessment_keeps_its_own_decision() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    plan = merge_material_plan(empty_material_plan(), candidates=candidates, assessments=[])
    plan.update(
        {
            "evidence_escalation_reassess_refs": ["note:n1", "note:n2"],
            "needs_evidence_reassessment": True,
        }
    )
    records = {}
    for candidate in candidates:
        text = (
            "Support belonging only to note n1."
            if candidate["ref"] == "note:n1"
            else "Support belonging only to note n2."
        )
        records[candidate["citation_path"]] = EvidenceRecord(
            id=candidate["citation_path"],
            kind="note_summary",
            source_ref=candidate["ref"],
            content=text,
            citation_path=candidate["citation_path"],
            citation_title=candidate["title"],
            metadata={
                "source_revision": 1,
                "owner_verified": True,
                "status_verified": True,
            },
        ).to_dict()
    reassessment = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("i", "n", "n", 0.9, "x"),
        },
        contract=contract,
        source_status="s",
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=reassessment,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n1"]


@pytest.mark.asyncio
async def test_opened_evidence_reassessment_receives_prior_verified_selection_as_baseline() -> None:
    current = normalize_candidates([_candidate("note:current")])
    baseline = normalize_candidates([_candidate("note:baseline")])[0]
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=[baseline, *current],
        assessments=[
            {
                "ref": "note:baseline",
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 1.0,
                "reason_code": "exact_fact",
            }
        ],
    )
    plan.update(
        {
            "evidence_escalation_reassess_refs": ["note:current"],
            "needs_evidence_reassessment": True,
        }
    )
    records = {}
    for candidate, text in (
        (baseline, "Already selected complete answer."),
        (current[0], "Related but redundant current evidence."),
    ):
        records[candidate["citation_path"]] = EvidenceRecord(
            id=candidate["citation_path"],
            kind="note_summary",
            source_ref=(
                candidate["citation_path"]
                if candidate["ref"] == "note:baseline"
                else candidate["ref"]
            ),
            content=text,
            citation_path=candidate["citation_path"],
            citation_title=candidate["title"],
            metadata={
                "source_revision": 1,
                "owner_verified": True,
                "status_verified": True,
            },
        ).to_dict()
    reassessment = _wire_output(
        current,
        {"note:current": ("i", "n", "n", 0.9, "x")},
        contract=contract,
        source_status="n",
    )
    state = {
        **_state(contract, current, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": records,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(current, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=reassessment,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    baseline = result["planner_steps"][-1]["selected_evidence_baseline"]
    assert baseline["selected_refs"] == ["note:baseline"]
    assert baseline["provider_calls"] == 0
    assert "Already selected complete answer." in selector.await_args_list[0].kwargs[
        "messages"
    ][1]["content"]
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:baseline"]


@pytest.mark.asyncio
async def test_opened_evidence_reassessment_has_no_follow_up_provider_failure_path() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    plan = merge_material_plan(empty_material_plan(), candidates=candidates, assessments=[])
    plan.update(
        {
            "evidence_escalation_reassess_refs": ["note:n1"],
            "needs_evidence_reassessment": True,
        }
    )
    candidate = candidates[0]
    record = EvidenceRecord(
        id=candidate["citation_path"],
        kind="note_summary",
        source_ref="note:n1",
        content="Verified full text.",
        citation_path=candidate["citation_path"],
        citation_title=candidate["title"],
        metadata={
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
        },
    )
    reassessment = _wire_output(
        candidates,
        {"note:n1": ("i", "n", "n", 0.9, "x")},
        contract=contract,
        source_status="n",
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": {candidate["citation_path"]: record.to_dict()},
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=reassessment,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == []


@pytest.mark.asyncio
async def test_opened_evidence_reassessment_does_not_consume_verification_budget() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contract["budgets"]["selector_verification_calls"] = 0
    plan = merge_material_plan(
        empty_material_plan(), candidates=candidates, assessments=[]
    )
    plan.update(
        {
            "evidence_escalation_reassess_refs": ["note:n1"],
            "needs_evidence_reassessment": True,
        }
    )
    path = candidates[0]["citation_path"]
    record = EvidenceRecord(
        id=path,
        kind="note_summary",
        source_ref="note:n1",
        content="Verified evidence that must not be admitted without an audit verdict.",
        citation_path=path,
        citation_title="n1",
        metadata={
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
        },
    )
    negative = _wire_output(
        candidates,
        {"note:n1": ("i", "n", "n", 0.9, "x")},
        contract=contract,
        source_status="n",
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": {path: record.to_dict()},
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=negative,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["selector_verification_calls_used"] == 0
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == []


@pytest.mark.asyncio
async def test_required_source_negative_opens_candidate_before_accepting_absence() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    output = _wire_output(
        candidates,
        {"note:n1": ("i", "n", "n", 0.5, "x")},
        contract=contract,
        source_status="n",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=output,
        ),
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert result["material_plan"]["source_dispositions"] == [
        {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
    ]
    assert result["material_plan"]["evidence_escalation_pending_refs"] == ["note:n1"]
    assert result["tool_action"]["actions"] == [
        {
            "tool": "OpenNote",
            "args": {
                "source_requirement_id": "workspace-notes",
                "note_id": "n1",
            },
            "intent_id": None,
        }
    ]


def test_decision_input_opens_reasoner_requested_rows_per_source_in_one_batch() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("note:background"),
            _candidate("post:recent-one", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:topic-only", source="workspace-posts"),
        ]
    )
    positions = {
        "note:plan": 2,
        "note:background": 1,
        "post:recent-one": 1,
        "post:recent-two": 2,
        "post:topic-only": 3,
    }
    for candidate in candidates:
        source_id = str(candidate["source_requirement_id"])
        if source_id == "workspace-posts":
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": source_id,
                    "position": positions[str(candidate["ref"])],
                    "window_size": 3,
                }
            ]
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    note_source["discovery_mode"] = "semantic_relevance"
    note_source["budget"] = {"deep_reads": 2}
    post_source["discovery_mode"] = "catalog_window"
    post_source["budget"] = {"deep_reads": 2}
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": (
                    "topic_only"
                    if candidate["ref"] in {"note:background", "post:topic-only"}
                    else "search_more"
                ),
            }
            for candidate in candidates
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "search_more"},
        {"source_id": "workspace-posts", "status": "search_more"},
    ]

    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=4,
        planner_calls_remaining=1,
    )

    assert refs == [
        "note:plan",
        "post:recent-one",
        "post:recent-two",
    ]
    assert next_evidence_escalation_batch(result) == refs
    assert "note:background" not in refs
    assert "post:topic-only" not in refs
    assert result["runtime_trace"][-1]["strategy"] == (
        "reasoner_requested_decision_input_evidence"
    )


def test_decision_input_joins_selected_reads_with_unresolved_required_source() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:spare-probe"),
            *[
                _candidate(f"post:state-{position}", source="workspace-posts")
                for position in range(1, 6)
            ],
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["ref"] == "note:spare-probe":
            candidate["matched_evidence_rank"] = 1
        if candidate["source_requirement_id"] == "workspace-posts":
            position = int(str(candidate["ref"]).rsplit("-", 1)[-1])
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": position,
                    "window_size": 5,
                }
            ]
    note_source = _source("workspace-notes", evidence="required")
    note_source["budget"] = {"deep_reads": 3}
    post_source = _source("workspace-posts", evidence="required")
    post_source["coverage"] = "complete"
    post_source["budget"] = {"deep_reads": 5}
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 8
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] == "note:selected" else "irrelevant"
                ),
                "role": (
                    "answer_evidence"
                    if candidate["ref"] == "note:selected"
                    else "none"
                ),
                "resolution": (
                    "full_text" if candidate["ref"] == "note:selected" else "none"
                ),
                "confidence": 0.9,
                "reason_code": (
                    "exact_fact"
                    if candidate["ref"] == "note:selected"
                    else "search_more"
                ),
            }
            for candidate in candidates
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "search_more"},
        ],
        contract=contract,
    )

    plan = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=8,
    )
    assert plan.get("matched_evidence_recall_refs", []) == []
    assert plan["pending_full_text_ids"] == ["note:selected"]

    plan, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=8,
        planner_calls_remaining=1,
    )

    assert refs == [
        "note:selected",
        *(f"post:state-{position}" for position in range(1, 6)),
    ]
    batch = next_evidence_escalation_batch(plan)
    assert batch == refs
    assert "note:spare-probe" not in batch

    plan = record_full_read_results(plan, opened=batch, batch=batch)
    result = schedule_selected_evidence_reassessment(
        plan,
        contract=contract,
        opened=batch,
    )
    assert set(result["evidence_escalation_reassess_refs"]) == set(batch)


def test_decision_input_opens_selected_cards_before_bounded_negative_recovery() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:series-plan"),
            _candidate("note:product-context"),
            *[
                _candidate(f"post:state-{position}", source="workspace-posts")
                for position in range(1, 6)
            ],
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["source_requirement_id"] == "workspace-posts":
            position = int(str(candidate["ref"]).rsplit("-", 1)[-1])
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": position,
                    "window_size": 5,
                }
            ]
    note_source = _source("workspace-notes", evidence="required")
    note_source["budget"] = {"deep_reads": 3}
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    post_source["budget"] = {"deep_reads": 5}
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 6
    selected_notes = {"note:series-plan", "note:product-context"}
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] in selected_notes else "irrelevant"
                ),
                "role": (
                    "answer_evidence" if candidate["ref"] in selected_notes else "none"
                ),
                "resolution": "card" if candidate["ref"] in selected_notes else "none",
                "confidence": 0.9,
                "reason_code": (
                    "exact_fact" if candidate["ref"] in selected_notes else "topic_only"
                ),
            }
            for candidate in candidates
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "no_relevant_candidate"},
        ],
        contract=contract,
    )

    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=6,
        planner_calls_remaining=1,
    )

    assert set(refs[:2]) == selected_notes
    assert refs[2:] == [
        "post:state-1",
        "post:state-2",
        "post:state-3",
        "post:state-4",
    ]
    assert result["evidence_escalation_pending_refs"] == refs
    assert set(result["runtime_trace"][-1]["selected_input_refs"]) == selected_notes
    assert next_evidence_escalation_batch(result) == refs


def test_decision_input_opens_selected_cards_when_all_sources_are_selected() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:current", source="workspace-posts"),
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
    note_source = _source("workspace-notes", evidence="required")
    note_source["budget"] = {"deep_reads": 1}
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    post_source["budget"] = {"deep_reads": 1}
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
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
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=2,
        planner_calls_remaining=1,
    )

    assert set(refs) == {"note:plan", "post:current"}
    assert result["evidence_escalation_pending_refs"] == refs
    assert result["runtime_trace"][-1]["strategy"] == (
        "selected_decision_input_evidence"
    )


def test_finite_inventory_finishes_selected_read_before_source_probe() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("post:probe", source="workspace-posts"),
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "workspace_synthesis"
    contract["answer_shape"] = {"kind": "inventory", "expected_member_count": 6}
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": "note:selected",
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 1.0,
                "reason_code": "exact_fact",
            },
            {
                "ref": "post:probe",
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": "search_more",
            },
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "search_more"},
        ],
        contract=contract,
    )

    plan = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=2,
    )
    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=2,
        planner_calls_remaining=1,
    )

    assert plan["pending_full_text_ids"] == ["note:selected"]
    assert refs == []
    assert result.get("evidence_escalation_pending_refs", []) == []


def test_selected_source_without_positive_candidate_is_unresolved() -> None:
    candidates = normalize_candidates(
        [_candidate("note:unread", source="workspace-notes")]
    )
    candidates[0]["available_fidelity"] = ["semantic_card", "full_text"]
    source = _source("workspace-notes", evidence="required")
    source["budget"] = {"deep_reads": 1}
    contract = _contract(source, planner_calls=2)
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": "note:unread",
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": "topic_only",
            }
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "selected"}
    ]

    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=1,
        planner_calls_remaining=1,
    )

    assert refs == ["note:unread"]
    assert result["evidence_escalation_pending_refs"] == ["note:unread"]


def test_reassessment_registry_joins_current_reads_with_positive_baseline() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("note:background"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:draft", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", evidence="required"),
        _source("workspace-posts", evidence="required"),
    )
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": "note:plan",
                "relevance": "direct",
                "resolution": "full_text",
                "confidence": 1.0,
                "reason_code": "exact_fact",
            },
            {
                "ref": "note:background",
                "relevance": "irrelevant",
                "resolution": "card",
                "confidence": 1.0,
                "reason_code": "topic_only",
            },
        ],
    )
    plan["evidence_escalation_reassess_refs"] = ["post:recent", "post:draft"]

    registry = _reassessment_selector_candidates(
        candidates,
        material_plan=plan,
        contract=contract,
    )

    assert [candidate["ref"] for candidate in registry] == [
        "post:recent",
        "post:draft",
        "note:plan",
    ]


def test_reassessment_registry_includes_bounded_published_prefix_before_llm() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:new-draft", source="workspace-posts"),
            _candidate("post:published-one", source="workspace-posts"),
            _candidate("post:published-two", source="workspace-posts"),
            _candidate("post:published-three", source="workspace-posts"),
            _candidate("post:older-draft", source="workspace-posts"),
            _candidate("post:older-published", source="workspace-posts"),
        ]
    )
    lifecycle = {
        "post:new-draft": (1, "draft"),
        "post:published-one": (2, "published"),
        "post:published-two": (3, "published"),
        "post:published-three": (4, "published"),
        "post:older-draft": (5, "draft"),
        "post:older-published": (6, "published"),
    }
    for candidate in candidates:
        ref = str(candidate["ref"])
        if ref == "note:plan":
            continue
        position, status = lifecycle[ref]
        candidate["status"] = status
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 6,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    post_source = _source("workspace-posts", maximum=5, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    selected = {
        "note:plan",
        "post:new-draft",
        "post:older-draft",
        "post:older-published",
    }
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": ref,
                "relevance": "direct",
                "resolution": "full_text",
                "confidence": 1.0,
                "reason_code": "exact_fact",
            }
            for ref in selected
        ],
    )
    plan["evidence_escalation_reassess_refs"] = sorted(selected)

    registry = _reassessment_selector_candidates(
        candidates,
        material_plan=plan,
        contract=contract,
    )

    assert {candidate["ref"] for candidate in registry} == {
        *selected,
        "post:published-one",
        "post:published-two",
    }
    assert "post:published-three" not in {
        candidate["ref"] for candidate in registry
    }


def test_catalog_window_observations_precede_semantic_context_in_read_queue() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan-one"),
            _candidate("note:plan-two"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:recent-one", source="workspace-posts"),
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["ref"].startswith("post:"):
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": 1 if candidate["ref"] == "post:recent-one" else 2,
                    "window_size": 2,
                }
            ]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": "direct",
            "role": "answer_evidence",
            "resolution": "full_text",
            "confidence": 1.0,
            "reason_code": "exact_fact",
        }
        for candidate in candidates
    ]

    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
        max_objects=3,
    )

    assert plan["required_full_text_ids"] == [
        "post:recent-one",
        "post:recent-two",
        "note:plan-one",
    ]
    assert plan["materialization_queue"][0]["ordered_observation_priority"] is True
    assert "note:plan-two" in plan["omitted_ids"]


def test_source_deep_read_budgets_preserve_selected_context_across_sources() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan-one"),
            _candidate("note:plan-two"),
            _candidate("note:noise"),
            _candidate("post:recent-four", source="workspace-posts"),
            _candidate("post:recent-three", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:recent-one", source="workspace-posts"),
        ]
    )
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["ref"].startswith("post:"):
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": {
                        "post:recent-one": 1,
                        "post:recent-two": 2,
                        "post:recent-three": 3,
                        "post:recent-four": 4,
                    }[candidate["ref"]],
                    "window_size": 4,
                }
            ]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    note_source["budget"] = {"deep_reads": 2}
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["budget"] = {"deep_reads": 2}
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    irrelevant_refs = {"note:noise", "post:recent-one"}
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": (
                "irrelevant" if candidate["ref"] in irrelevant_refs else "direct"
            ),
            "role": (
                "none" if candidate["ref"] in irrelevant_refs else "answer_evidence"
            ),
            "resolution": (
                "none" if candidate["ref"] in irrelevant_refs else "full_text"
            ),
            "confidence": 1.0,
            "reason_code": (
                "unrelated_topic"
                if candidate["ref"] in irrelevant_refs
                else "exact_fact"
            ),
        }
        for candidate in candidates
    ]

    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
        max_objects=4,
    )

    assert plan["required_full_text_ids"] == [
        "post:recent-two",
        "post:recent-three",
        "note:plan-one",
        "note:plan-two",
    ]
    assert [
        item["read_budget_source_id"] for item in plan["materialization_queue"]
    ] == [
        "workspace-posts",
        "workspace-posts",
        "workspace-notes",
        "workspace-notes",
    ]
    assert irrelevant_refs.isdisjoint(
        {item["ref"] for item in plan["materialization_queue"]}
    )
    assert {
        item["ref"]
        for item in plan["runtime_trace"]
        if item.get("reason") == "source_deep_read_budget"
    } == {"post:recent-four"}


def test_materializes_the_entire_bounded_full_read_batch() -> None:
    refs = ["note:n1", "note:n2", "post:p1", "post:p2"]
    candidates = normalize_candidates(
        [
            _candidate("note:n1"),
            _candidate("note:n2"),
            _candidate("post:p1", source="workspace-posts"),
            _candidate("post:p2", source="workspace-posts"),
        ]
    )

    actions = _materialize_full_read_actions(refs, candidates)

    assert [action["args"].get("note_id") for action in actions] == [
        "n1",
        "n2",
        None,
        None,
    ]
    assert [action["args"].get("post_id") for action in actions] == [
        None,
        None,
        "p1",
        "p2",
    ]


@pytest.mark.asyncio
async def test_partial_evidence_escalation_batch_continues_before_reassessment() -> None:
    refs = [
        "note:n1",
        "note:n2",
        "note:n3",
        "post:p1",
        "post:p2",
        "post:p3",
    ]
    candidates = normalize_candidates(
        [
            _candidate("note:n1"),
            _candidate("note:n2"),
            _candidate("note:n3"),
            _candidate("post:p1", source="workspace-posts"),
            _candidate("post:p2", source="workspace-posts"),
            _candidate("post:p3", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contract["task_profile"] = "workspace_synthesis"
    contract["budgets"]["deep_reads"] = 6
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": ref,
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": "topic_only",
            }
            for ref in refs
        ],
    )
    plan.update(
        {
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "no_relevant_candidate"},
                {"source_id": "workspace-posts", "status": "no_relevant_candidate"},
            ],
            "evidence_escalation_pending_refs": refs[3:],
            "evidence_escalation_reassess_refs": refs[:3],
            "evidence_escalation_opened_refs": refs[:3],
            "opened_full_text_ids": refs[:3],
            "needs_evidence_reassessment": True,
        }
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "deep_reads_used": 3,
    }

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as selector:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    selector.assert_not_awaited()
    assert result["planner_calls_used"] == 1
    assert result["planner_steps"][-1]["decision_code"] == (
        "CONTINUE_EVIDENCE_ESCALATION"
    )
    assert [
        action["args"].get("post_id")
        for action in result["tool_action"]["actions"]
    ] == ["p1", "p2", "p3"]
    assert result["material_plan"]["needs_evidence_reassessment"] is True


def test_decision_input_all_negative_cards_probe_each_required_source() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:matched"),
            _candidate("note:other"),
            _candidate("post:recent", source="workspace-posts"),
            _candidate("post:older", source="workspace-posts"),
        ]
    )
    ranks = {
        "note:matched": 1,
        "note:other": 2,
        "post:recent": 1,
        "post:older": 2,
    }
    for candidate in candidates:
        rank = ranks[str(candidate["ref"])]
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        candidate["matched_evidence_rank"] = rank
        if candidate["source_requirement_id"] == "workspace-posts":
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": rank,
                    "window_size": 2,
                }
            ]
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    note_source["discovery_mode"] = "semantic_relevance"
    note_source["budget"] = {"deep_reads": 2}
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["discovery_mode"] = "catalog_window"
    post_source["budget"] = {"deep_reads": 2}
    contract = _contract(note_source, post_source, planner_calls=2)
    contract["task_profile"] = "workspace_synthesis"
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": "topic_only",
            }
            for candidate in candidates
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "no_relevant_candidate"},
        {"source_id": "workspace-posts", "status": "no_relevant_candidate"},
    ]

    result, refs = schedule_evidence_escalation(
        plan,
        contract=contract,
        deep_reads_remaining=4,
        planner_calls_remaining=1,
    )

    assert refs == [
        "note:matched",
        "note:other",
        "post:recent",
        "post:older",
    ]
    assert result["runtime_trace"][-1]["strategy"] == (
        "bounded_per_source_decision_input_evidence"
    )


@pytest.mark.asyncio
async def test_selected_full_text_opens_before_negative_source_probe() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("post:probe", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contract["task_profile"] = "workspace_synthesis"
    contract["answer_shape"] = {
        "kind": "freeform",
        "expected_member_count": None,
    }
    output = _wire_output(
        candidates,
        {
            "note:selected": ("d", "a", "f", 0.9, "e"),
            "post:probe": ("i", "n", "n", 0.9, "x"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=output,
        ),
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert result["material_plan"]["pending_full_text_ids"] == ["note:selected"]
    assert result["material_plan"]["evidence_escalation_pending_refs"] == []
    assert result["tool_action"]["actions"] == [
        {
            "tool": "OpenNote",
            "args": {
                "source_requirement_id": "workspace-notes",
                "note_id": "selected",
            },
            "intent_id": None,
        }
    ]


def test_completed_selected_reads_schedule_reassessment_without_a_negative_source() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:n1"),
            _candidate("post:p1", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
    )
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 0.9,
                "reason_code": "exact_fact",
            }
            for candidate in candidates
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "selected"},
        {"source_id": "workspace-posts", "status": "selected"},
    ]
    refs = [str(candidate["ref"]) for candidate in candidates]
    plan = record_full_read_results(plan, opened=refs, batch=refs)

    result = schedule_selected_evidence_reassessment(
        plan,
        contract=contract,
        opened=refs,
    )

    assert result["needs_evidence_reassessment"] is True
    assert result["evidence_escalation_reassess_refs"] == sorted(refs)
    assert result["runtime_trace"][-1]["reason"] == "minimal_verified_opened_set"


def test_matched_evidence_probes_fill_spare_budget_and_join_one_reassessment() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:selected-two"),
            _candidate("note:rank-one"),
            _candidate("note:rank-three"),
            _candidate("note:rank-four"),
            _candidate("note:rank-five"),
        ]
    )
    ranks = {
        "note:selected": 2,
        "note:selected-two": 6,
        "note:rank-one": 1,
        "note:rank-three": 3,
        "note:rank-four": 4,
        "note:rank-five": 5,
    }
    for candidate in candidates:
        candidate["matched_evidence_rank"] = ranks[str(candidate["ref"])]
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["required_fidelity"] = "full_text"
    contract = _contract(source)
    contract["budgets"]["deep_reads"] = 5
    assessments = [
        {
            "ref": str(candidate["ref"]),
            "relevance": (
                "direct"
                if candidate["ref"] in {"note:selected", "note:selected-two"}
                else "irrelevant"
            ),
            "role": (
                "answer_evidence"
                if candidate["ref"] in {"note:selected", "note:selected-two"}
                else "none"
            ),
            "resolution": (
                "full_text"
                if candidate["ref"] in {"note:selected", "note:selected-two"}
                else "none"
            ),
            "confidence": 0.9,
            "reason_code": (
                "exact_fact"
                if candidate["ref"] in {"note:selected", "note:selected-two"}
                else "topic_only"
            ),
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"}
        ],
        contract=contract,
    )

    plan = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=5,
    )

    assert plan["matched_evidence_recall_refs"] == [
        "note:rank-one",
        "note:rank-three",
        "note:rank-four",
    ]
    assert plan["pending_full_text_ids"] == [
        "note:selected",
        "note:selected-two",
        "note:rank-one",
        "note:rank-three",
        "note:rank-four",
    ]
    assert "note:rank-five" not in plan["pending_full_text_ids"]

    opened = list(plan["pending_full_text_ids"])
    plan = record_full_read_results(plan, opened=opened, batch=opened)
    result = schedule_selected_evidence_reassessment(
        plan,
        contract=contract,
        opened=opened,
    )

    assert result["evidence_escalation_reassess_refs"] == opened
    assert result["runtime_trace"][-1]["probe_refs"] == [
        "note:rank-one",
        "note:rank-three",
        "note:rank-four",
    ]


def test_finite_complete_decision_source_uses_spare_read_for_rejected_card() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:noise-one"),
            _candidate("note:noise-two"),
            _candidate("post:recent-one", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:recent-three", source="workspace-posts"),
            _candidate("post:rejected", source="workspace-posts"),
        ]
    )
    for candidate in candidates:
        if candidate["source_requirement_id"] == "workspace-posts":
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": {
                        "post:recent-one": 1,
                        "post:recent-two": 2,
                        "post:recent-three": 3,
                        "post:rejected": 4,
                    }[candidate["ref"]],
                    "window_size": 4,
                }
            ]
    note_source = _source("workspace-notes", evidence="required")
    note_source["coverage"] = "complete"
    note_source["budget"] = {"deep_reads": 2}
    post_source = _source("workspace-posts", evidence="required")
    post_source["coverage"] = "complete"
    post_source["budget"] = {"deep_reads": 5}
    post_source["discovery_mode"] = "catalog_window"
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 5
    selected_refs = {
        "note:selected",
        "post:recent-one",
        "post:recent-two",
        "post:recent-three",
    }
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": "direct" if candidate["ref"] in selected_refs else "irrelevant",
            "role": "answer_evidence" if candidate["ref"] in selected_refs else "none",
            "resolution": "full_text" if candidate["ref"] in selected_refs else "none",
            "confidence": 0.9,
            "reason_code": "exact_fact" if candidate["ref"] in selected_refs else "topic_only",
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=5,
    )

    assert recovered["finite_source_recovery_refs"] == ["post:rejected"]
    assert recovered["matched_evidence_recall_refs"] == []
    assert recovered["pending_full_text_ids"][-1] == "post:rejected"
    assert "note:noise-one" not in recovered["pending_full_text_ids"]
    assert "note:noise-two" not in recovered["pending_full_text_ids"]

    opened = list(recovered["pending_full_text_ids"])
    recovered = record_full_read_results(recovered, opened=opened, batch=opened)
    reassessment = schedule_selected_evidence_reassessment(
        recovered,
        contract=contract,
        opened=opened,
    )
    assert "post:rejected" in reassessment["evidence_escalation_reassess_refs"]

    nonfinite_contract = {
        **contract,
        "source_requirements": [
            note_source,
            {
                **post_source,
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
            },
        ],
    }
    not_recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=nonfinite_contract,
        deep_reads_remaining=5,
    )
    assert not not_recovered["finite_source_recovery_refs"]
    assert "post:rejected" not in not_recovered["pending_full_text_ids"]

    bounded_contract = {
        **contract,
        "source_requirements": [
            note_source,
            {**post_source, "coverage": "relevant"},
        ],
    }
    bounded_recovery = schedule_matched_evidence_recall_probes(
        plan,
        contract=bounded_contract,
        deep_reads_remaining=5,
    )
    assert bounded_recovery["finite_source_recovery_refs"] == ["post:rejected"]


def test_selected_bounded_history_reassesses_all_rejected_window_members() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent-one", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:recent-three", source="workspace-posts"),
            _candidate("post:recent-four", source="workspace-posts"),
        ]
    )
    for position, candidate in enumerate(candidates[1:], start=1):
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 4,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    note_source.update({"coverage": "complete", "budget": {"deep_reads": 3}})
    post_source = _source("workspace-posts", evidence="required")
    post_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "catalog_window",
            "budget": {"deep_reads": 4},
        }
    )
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 7
    selected_refs = {"note:plan", "post:recent-one"}
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": "direct" if candidate["ref"] in selected_refs else "irrelevant",
            "role": "answer_evidence" if candidate["ref"] in selected_refs else "none",
            "resolution": "full_text" if candidate["ref"] in selected_refs else "none",
            "confidence": 0.9,
            "reason_code": "exact_fact" if candidate["ref"] in selected_refs else "topic_only",
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=7,
    )

    assert recovered["finite_source_recovery_refs"] == [
        "post:recent-four",
        "post:recent-three",
        "post:recent-two",
    ]
    opened = list(recovered["pending_full_text_ids"])
    recovered = record_full_read_results(recovered, opened=opened, batch=opened)
    reassessment = schedule_selected_evidence_reassessment(
        recovered,
        contract=contract,
        opened=opened,
    )
    assert set(reassessment["evidence_escalation_reassess_refs"]) == set(opened)
    assert len(reassessment["evidence_escalation_reassess_refs"]) == len(opened)


def test_semantic_search_more_opens_only_the_strongest_rejected_card() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:rank-two"),
            _candidate("note:rank-three"),
            _candidate("note:rank-four"),
            _candidate("note:rank-five"),
        ]
    )
    ranks = {
        "note:selected": 1,
        "note:rank-two": 2,
        "note:rank-three": 3,
        "note:rank-four": 4,
        "note:rank-five": 5,
    }
    for candidate in candidates:
        candidate["matched_evidence_rank"] = ranks[str(candidate["ref"])]
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
    note_source = _source("workspace-notes", evidence="required")
    note_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "semantic_relevance",
            "budget": {"deep_reads": 3},
        }
    )
    contract = _contract(note_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 3
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": (
                "direct" if candidate["ref"] == "note:selected" else "irrelevant"
            ),
            "role": (
                "answer_evidence"
                if candidate["ref"] == "note:selected"
                else "none"
            ),
            "resolution": (
                "full_text" if candidate["ref"] == "note:selected" else "none"
            ),
            "confidence": 0.9,
            "reason_code": (
                "exact_fact"
                if candidate["ref"] == "note:selected"
                else "search_more"
            ),
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"}
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=3,
    )

    assert recovered["finite_source_recovery_refs"] == ["note:rank-two"]
    assert recovered["pending_full_text_ids"] == [
        "note:selected",
        "note:rank-two",
    ]
    assert "note:rank-three" not in recovered["pending_full_text_ids"]
    assert "note:rank-four" not in recovered["pending_full_text_ids"]


def test_spare_read_opens_one_strongest_rejected_semantic_card_for_same_reassessment() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected-one"),
            _candidate("note:selected-two"),
            _candidate("note:selected-three"),
            _candidate("post:selected", source="workspace-posts"),
            _candidate("post:matched", source="workspace-posts"),
            _candidate("note:recovery"),
            _candidate("note:noise"),
        ]
    )
    semantic_scores = {
        "note:selected-one": 0.60,
        "note:selected-two": 0.55,
        "note:selected-three": 0.52,
        "post:selected": 0.50,
        "post:matched": 0.45,
        "note:recovery": 0.44,
        "note:noise": 0.30,
    }
    for candidate in candidates:
        candidate["semantic_rank_score"] = semantic_scores[str(candidate["ref"])]
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["ref"] == "post:matched":
            candidate["matched_evidence_rank"] = 1

    note_source = _source("workspace-notes", evidence="optional")
    note_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "semantic_relevance",
            "budget": {"deep_reads": 3},
        }
    )
    post_source = _source("workspace-posts", evidence="required")
    post_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "semantic_relevance",
            "budget": {"deep_reads": 3},
        }
    )
    contract = _contract(note_source, post_source)
    contract["budgets"]["deep_reads"] = 6
    selected_refs = {
        "note:selected-one",
        "note:selected-two",
        "note:selected-three",
        "post:selected",
    }
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] in selected_refs else "irrelevant"
                ),
                "role": (
                    "answer_evidence" if candidate["ref"] in selected_refs else "none"
                ),
                "resolution": (
                    "full_text" if candidate["ref"] in selected_refs else "none"
                ),
                "confidence": 0.9,
                "reason_code": (
                    "exact_fact" if candidate["ref"] in selected_refs else "topic_only"
                ),
            }
            for candidate in candidates
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=6,
    )

    assert recovered["matched_evidence_recall_refs"] == ["post:matched"]
    assert recovered["semantic_card_recovery_refs"] == ["note:recovery"]
    assert "note:noise" not in recovered["pending_full_text_ids"]

    opened = list(recovered["pending_full_text_ids"])
    recovered = record_full_read_results(recovered, opened=opened, batch=opened)
    reassessment = schedule_selected_evidence_reassessment(
        recovered,
        contract=contract,
        opened=opened,
    )

    assert set(reassessment["evidence_escalation_reassess_refs"]) == set(opened)
    assert "note:recovery" in reassessment["evidence_escalation_reassess_refs"]


def test_semantic_recovery_can_cross_a_misclassified_source_type() -> None:
    candidates = normalize_candidates(
        [
            _candidate("post:selected", source="workspace-posts"),
            _candidate("post:selected-two", source="workspace-posts"),
            _candidate("note:matched", source="workspace-notes"),
            _candidate("note:slower", source="workspace-notes"),
        ]
    )
    for candidate, rank in zip(candidates, (1, 2, 3, 5), strict=True):
        candidate["semantic_rank_score"] = 0.70 - rank / 100
        candidate["matched_evidence_rank"] = rank
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
    post_source = _source("workspace-posts", evidence="required")
    post_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "semantic_relevance",
            "budget": {"deep_reads": 4},
        }
    )
    contract = _contract(post_source)
    contract["task_profile"] = "workspace_synthesis"
    contract["answer_shape"] = {"kind": "freeform"}
    contract["budgets"]["deep_reads"] = 4
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": "direct" if candidate["ref"].startswith("post:selected") else "irrelevant",
                "role": "answer_evidence" if candidate["ref"].startswith("post:selected") else "none",
                "resolution": "full_text" if candidate["ref"].startswith("post:selected") else "none",
                "confidence": 0.9,
                "reason_code": "exact_fact" if candidate["ref"].startswith("post:selected") else "topic_only",
            }
            for candidate in candidates
        ],
        source_dispositions=[{"source_id": "workspace-posts", "status": "selected"}],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=4,
    )

    assert recovered["semantic_card_recovery_refs"] == ["note:matched"]


def test_normative_guard_rejects_observational_card_even_when_source_is_misclassified() -> None:
    candidate = _candidate("note:image", source="workspace-notes")
    candidate["selector_semantic_flags"] = {
        "v": 3,
        "normative_value": False,
        "observational_value": True,
    }
    decision = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": "note:image",
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "exact_fact",
                }
            ],
            "source_dispositions": [],
        }
    )
    guarded = apply_selector_question_scope_guard(
        decision,
        question="Какой формат изображений использовать для постов?",
        candidates=[candidate],
        mapping=encode_selector_transport(
            question="Какой формат изображений использовать для постов?",
            dialog_context="",
            contract={
                "source_requirements": [
                    {
                        "source_id": "workspace-posts",
                        "claim_modality": "normative",
                    }
                ]
            },
            candidates=[candidate],
        ).mapping,
        contract={
            "source_requirements": [
                {
                    "source_id": "workspace-posts",
                    "claim_modality": "normative",
                }
            ]
        },
    )

    assert tuple(guarded.demoted_refs) == ("note:image",)


def test_finite_topical_comparison_spends_only_spare_reads_on_search_more_cards() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected-one"),
            _candidate("note:selected-two"),
            _candidate("post:selected", source="workspace-posts"),
            _candidate(
                "note:probe-one",
                origin="authoritative_catalog",
                score=None,
            ),
            _candidate(
                "note:probe-two",
                origin="authoritative_catalog",
                score=None,
            ),
            _candidate(
                "note:probe-three",
                origin="authoritative_catalog",
                score=None,
            ),
        ]
    )
    for candidate in candidates:
        if candidate["ref"] in {"note:probe-one", "note:probe-two"}:
            candidate["matched_evidence_rank"] = (
                1 if candidate["ref"] == "note:probe-one" else 2
            )
    selected_refs = {"note:selected-one", "note:selected-two", "post:selected"}
    note_source = _source("workspace-notes", evidence="optional")
    post_source = _source("workspace-posts", evidence="required")
    post_source["evidence_requirements"] = [
        {
            "requirement_id": "workspace-posts:first-side",
            "property": "first side",
            "operator": "exists",
        },
        {
            "requirement_id": "workspace-posts:second-side",
            "property": "second side",
            "operator": "exists",
        },
    ]
    contract = {
        **_contract(note_source, post_source),
        "task_profile": "topical_answer",
        "answer_shape": {"kind": "freeform", "expected_member_count": None},
    }
    contract["budgets"]["deep_reads"] = 5
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] in selected_refs else "irrelevant"
                ),
                "role": (
                    "answer_evidence" if candidate["ref"] in selected_refs else "none"
                ),
                "resolution": (
                    "full_text" if candidate["ref"] in selected_refs else "none"
                ),
                "confidence": 0.9 if candidate["ref"] in selected_refs else 0.3,
                "reason_code": (
                    "exact_fact" if candidate["ref"] in selected_refs else "search_more"
                ),
            }
            for candidate in candidates
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "search_more"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=5,
    )

    assert recovered["finite_topical_recall_refs"] == [
        "note:probe-one",
        "note:probe-two",
    ]
    assert "note:probe-three" not in recovered["pending_full_text_ids"]


def test_decision_recovery_preserves_semantic_probe_and_ordered_window() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:plan-detail"),
            _candidate("note:noise"),
            _candidate("post:recent-one", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:recent-three", source="workspace-posts"),
            _candidate("post:recent-four", source="workspace-posts"),
        ]
    )
    ranks = {
        "note:selected": 1,
        "note:plan-detail": 2,
        "note:noise": 3,
    }
    for candidate in candidates:
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        if candidate["source_requirement_id"] == "workspace-notes":
            candidate["matched_evidence_rank"] = ranks[str(candidate["ref"])]
        else:
            position = {
                "post:recent-one": 1,
                "post:recent-two": 2,
                "post:recent-three": 3,
                "post:recent-four": 4,
            }[str(candidate["ref"])]
            candidate["catalog_window_memberships"] = [
                {
                    "source_requirement_id": "workspace-posts",
                    "position": position,
                    "window_size": 4,
                }
            ]
    note_source = _source("workspace-notes", evidence="required")
    note_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "semantic_relevance",
            "budget": {"deep_reads": 3},
        }
    )
    post_source = _source("workspace-posts", evidence="required")
    post_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "catalog_window",
            "budget": {"deep_reads": 5},
        }
    )
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 6
    selected_refs = {"note:selected", "post:recent-one"}
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": (
                "direct" if candidate["ref"] in selected_refs else "irrelevant"
            ),
            "role": (
                "answer_evidence" if candidate["ref"] in selected_refs else "none"
            ),
            "resolution": (
                "full_text" if candidate["ref"] in selected_refs else "none"
            ),
            "confidence": 0.9,
            "reason_code": (
                "exact_fact" if candidate["ref"] in selected_refs else "search_more"
            ),
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "selected"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=6,
    )

    assert recovered["finite_source_recovery_refs"] == [
        "note:plan-detail",
        "post:recent-two",
        "post:recent-three",
        "post:recent-four",
    ]
    assert "note:noise" not in recovered["pending_full_text_ids"]


def test_catalog_window_search_more_uses_spare_cross_source_reads() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:plan"),
            _candidate("post:recent-one", source="workspace-posts"),
            _candidate("post:recent-two", source="workspace-posts"),
            _candidate("post:topic-only", source="workspace-posts"),
        ]
    )
    for position, candidate in enumerate(candidates[1:], start=1):
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 3,
            }
        ]
    note_source = _source("workspace-notes", evidence="required")
    note_source["coverage"] = "complete"
    note_source["budget"] = {"deep_reads": 2}
    post_source = _source("workspace-posts", evidence="required")
    post_source.update(
        {
            "coverage": "relevant",
            "discovery_mode": "catalog_window",
            "budget": {"deep_reads": 3},
        }
    )
    contract = _contract(note_source, post_source)
    contract["task_profile"] = "recommendation"
    contract["budgets"]["deep_reads"] = 4
    assessments = [
        {
            "ref": candidate["ref"],
            "relevance": "direct" if candidate["ref"] == "note:plan" else "irrelevant",
            "role": "answer_evidence" if candidate["ref"] == "note:plan" else "none",
            "resolution": "full_text" if candidate["ref"] == "note:plan" else "none",
            "confidence": 0.9,
            "reason_code": (
                "exact_fact"
                if candidate["ref"] == "note:plan"
                else "topic_only"
                if candidate["ref"] == "post:topic-only"
                else "search_more"
            ),
        }
        for candidate in candidates
    ]
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=assessments,
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "search_more"},
        ],
        contract=contract,
    )

    recovered = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=4,
    )

    assert recovered["finite_source_recovery_refs"] == [
        "post:recent-one",
        "post:recent-two",
    ]
    assert recovered["pending_full_text_ids"] == [
        "note:plan",
        "post:recent-one",
        "post:recent-two",
    ]
    assert "post:topic-only" not in recovered["pending_full_text_ids"]


def test_matched_evidence_probes_do_not_expand_a_single_selected_source() -> None:
    by_ref = {
        str(candidate["ref"]): candidate
        for candidate in normalize_candidates(
            [_candidate("note:selected"), _candidate("note:probe")]
        )
    }
    selected = by_ref["note:selected"]
    probe = by_ref["note:probe"]
    probe["matched_evidence_rank"] = 1
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["required_fidelity"] = "full_text"
    contract = _contract(source)
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=[selected, probe],
        assessments=[
            {
                "ref": selected["ref"],
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 0.9,
                "reason_code": "exact_fact",
            },
            {
                "ref": probe["ref"],
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 0.9,
                "reason_code": "topic_only",
            },
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"}
        ],
        contract=contract,
    )

    result = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=3,
    )

    assert "matched_evidence_recall_refs" not in result
    assert result.get("semantic_card_recovery_refs", []) == []
    assert result["pending_full_text_ids"] == ["note:selected"]


def test_finite_inventory_single_selection_opens_only_query_matched_probes() -> None:
    by_ref = {
        str(candidate["ref"]): candidate
        for candidate in normalize_candidates(
            [
                _candidate("note:selected"),
                _candidate("note:matched"),
                _candidate("note:unmatched"),
            ]
        )
    }
    by_ref["note:matched"]["matched_evidence_rank"] = 1
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["required_fidelity"] = "full_text"
    contract = _contract(source)
    contract["answer_shape"] = {"kind": "inventory", "expected_member_count": 6}
    contract["budgets"]["deep_reads"] = 3
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=list(by_ref.values()),
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] == "note:selected" else "irrelevant"
                ),
                "role": (
                    "answer_evidence" if candidate["ref"] == "note:selected" else "none"
                ),
                "resolution": (
                    "full_text" if candidate["ref"] == "note:selected" else "none"
                ),
                "confidence": 0.9,
                "reason_code": (
                    "exact_fact" if candidate["ref"] == "note:selected" else "topic_only"
                ),
            }
            for candidate in by_ref.values()
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"}
        ],
        contract=contract,
    )

    result = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=3,
    )

    assert result["matched_evidence_recall_refs"] == ["note:matched"]
    assert result["pending_full_text_ids"] == ["note:selected", "note:matched"]
    assert "note:unmatched" not in result["pending_full_text_ids"]


def test_finite_inventory_probes_selected_source_when_another_source_is_unresolved() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:matched"),
            _candidate("post:unresolved", source="workspace-posts"),
        ]
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["available_fidelity"] = ["semantic_card", "full_text"]
        candidate["matched_evidence_rank"] = rank
    note_source = _source("workspace-notes", minimum=1, evidence="required")
    note_source["required_fidelity"] = "full_text"
    post_source = _source("workspace-posts", minimum=1, evidence="required")
    post_source["required_fidelity"] = "full_text"
    contract = _contract(note_source, post_source)
    contract["answer_shape"] = {"kind": "inventory", "expected_member_count": 6}
    contract["budgets"]["deep_reads"] = 3
    plan = compile_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": (
                    "direct" if candidate["ref"] == "note:selected" else "irrelevant"
                ),
                "role": (
                    "answer_evidence" if candidate["ref"] == "note:selected" else "none"
                ),
                "resolution": (
                    "full_text" if candidate["ref"] == "note:selected" else "none"
                ),
                "confidence": 0.9,
                "reason_code": (
                    "exact_fact" if candidate["ref"] == "note:selected" else "topic_only"
                ),
            }
            for candidate in candidates
        ],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "selected"},
            {"source_id": "workspace-posts", "status": "no_relevant_candidate"},
        ],
        contract=contract,
    )

    result = schedule_matched_evidence_recall_probes(
        plan,
        contract=contract,
        deep_reads_remaining=3,
    )

    assert result["matched_evidence_recall_refs"] == ["note:matched"]
    assert result["pending_full_text_ids"] == ["note:selected", "note:matched"]
    assert "post:unresolved" not in result["pending_full_text_ids"]


@pytest.mark.asyncio
async def test_selector_schedules_ranked_recall_probes_without_an_extra_llm_call() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("note:selected-two"),
            _candidate("note:rank-one"),
            _candidate("note:rank-three"),
            _candidate("note:rank-four"),
        ]
    )
    ranks = {
        "note:selected": 2,
        "note:selected-two": 5,
        "note:rank-one": 1,
        "note:rank-three": 3,
        "note:rank-four": 4,
    }
    for candidate in candidates:
        rank = ranks[str(candidate["ref"])]
        candidate["matched_evidence_rank"] = rank
        candidate["matched_evidence"] = {
            "text": f"Matched evidence for {candidate['ref']}",
            "rank": rank,
            "node_type": "note_chunk",
            "source_revision": 1,
            "digest": f"{rank:016x}",
            "truncated": False,
        }
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["required_fidelity"] = "full_text"
    contract = _contract(source)
    contract["budgets"]["deep_reads"] = 5
    primary = _wire_output(
        candidates,
        {
            "note:selected": ("d", "a", "f", 0.9, "e"),
            "note:selected-two": ("d", "a", "f", 0.9, "e"),
            "note:rank-one": ("i", "n", "n", 0.9, "t"),
            "note:rank-three": ("i", "n", "n", 0.9, "t"),
            "note:rank-four": ("i", "n", "n", 0.9, "t"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            {
                **_state(contract, candidates),
                "verified_pack_boundary_enabled": True,
            },
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["material_plan"]["matched_evidence_recall_refs"] == [
        "note:rank-one",
        "note:rank-three",
        "note:rank-four",
    ]
    assert [
        action["args"]["note_id"] for action in result["tool_action"]["actions"]
    ] == ["selected", "selected-two", "rank-one"]


def test_failed_required_read_is_demoted_before_opened_set_reassessment() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:n1"),
            _candidate("post:p1", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
    )
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": candidate["ref"],
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 0.9,
                "reason_code": "exact_fact",
            }
            for candidate in candidates
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "selected"},
        {"source_id": "workspace-posts", "status": "selected"},
    ]
    plan = record_full_read_results(
        plan,
        opened=["note:n1"],
        failed=["post:p1"],
        batch=["note:n1", "post:p1"],
    )

    result = schedule_selected_evidence_reassessment(
        plan,
        contract=contract,
        opened=["note:n1"],
    )

    assessment_by_ref = {item["ref"]: item for item in result["assessments"]}
    assert assessment_by_ref["post:p1"]["relevance"] == "irrelevant"
    assert result["evidence_escalation_reassess_refs"] == ["note:n1"]
    assert result["source_dispositions"] == [
        {"source_id": "workspace-notes", "status": "selected"},
        {"source_id": "workspace-posts", "status": "search_more"},
    ]
    assert result["runtime_trace"][-2]["kind"] == "failed_selected_full_text_demoted"


@pytest.mark.asyncio
async def test_normal_selector_pass_discharges_redundant_negative_corpus() -> None:
    candidates = normalize_candidates(
        [
            _candidate("note:selected"),
            _candidate("post:probe", source="workspace-posts"),
        ]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
        planner_calls=2,
    )
    for source in contract["source_requirements"]:
        source["scope"] = {"mode": "corpus", "corpus": "workspace"}
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": "note:selected",
                "relevance": "direct",
                "role": "answer_evidence",
                "resolution": "full_text",
                "confidence": 0.9,
                "reason_code": "exact_fact",
            },
            {
                "ref": "post:probe",
                "relevance": "irrelevant",
                "role": "none",
                "resolution": "none",
                "confidence": 0.9,
                "reason_code": "unrelated_topic",
            },
        ],
    )
    plan["source_dispositions"] = [
        {"source_id": "workspace-notes", "status": "selected"},
        {"source_id": "workspace-posts", "status": "no_relevant_candidate"},
    ]
    plan = record_full_read_results(
        plan,
        opened=["note:selected"],
        batch=["note:selected"],
    )
    plan = schedule_selected_evidence_reassessment(
        plan,
        contract=contract,
        opened=["note:selected"],
    )
    selected = candidates[0]
    record = EvidenceRecord(
        id=selected["citation_path"],
        kind="note_summary",
        source_ref="note:selected",
        content="Verified selected evidence that fully answers the question.",
        citation_path=selected["citation_path"],
        citation_title=selected["title"],
        metadata={
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
        },
    )
    output = _wire_output(
        [selected],
        {
            "note:selected": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 1,
        "evidence_records": {selected["citation_path"]: record.to_dict()},
        "deep_reads_used": 1,
        "verified_pack_boundary_enabled": True,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=([selected], []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=output,
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert selector.await_args.kwargs["phase"] == (
        "research.selector.context_evidence_reassessment"
    )
    assert result["material_plan"]["baseline_discharged_source_ids"] == [
        "workspace-posts"
    ]
    assert result["material_plan"]["evidence_escalation_pending_refs"] == []
    assert result["tool_action"]["actions"] == []


@pytest.mark.asyncio
async def test_failed_evidence_escalation_expands_discovery_without_another_llm_call() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    first_output = _wire_output(
        candidates,
        {"note:n1": ("i", "n", "n", 0.9, "s")},
        contract=contract,
        source_status="m",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=first_output,
        ),
    ):
        first = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    failed_plan = record_full_read_results(
        first["material_plan"],
        failed=["note:n1"],
        batch=["note:n1"],
    )
    assert "note:n1" not in failed_plan["omitted_ids"]
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as llm:
        result = await _compact_planner_node(
            {**first, "material_plan": failed_plan, "deep_reads_used": 1},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert llm.await_count == 0
    assert result["tool_action"]["actions"][0]["tool"] == "SearchNodes"
    assert result["tool_action"]["decision_code"] == (
        "EXPAND_DISCOVERY_AFTER_EVIDENCE_ESCALATION"
    )


@pytest.mark.asyncio
async def test_multi_selection_requires_independent_precision_agreement() -> None:
    candidates = normalize_candidates(
        [_candidate("note:n1"), _candidate("note:n2"), _candidate("note:n3")]
    )
    contract = _contract(_source("workspace-notes", minimum=1), planner_calls=2)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
            "note:n3": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(candidates, ["note:n1"], contract=contract)
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[1].kwargs["phase"] == (
        "research.selector.context_precision_confirmation"
    )
    selected = [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ]
    assert selected == ["note:n1"]
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["confirmed_refs"] == ["note:n1"]
    assert precision["demoted_refs"] == ["note:n2", "note:n3"]


@pytest.mark.asyncio
async def test_empty_precision_subset_finishes_without_a_second_precision_call() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    candidates[0]["opened_evidence"] = {
        "text": "Background section.\n\nThe exact relevant answer.\n\nUnrelated appendix.",
        "digest": "2222222222222222",
        "citation_path": "/note/global/n1/",
        "source_revision": 1,
        "owner_verified": True,
        "status_verified": True,
        "truncated": False,
    }
    candidates[0]["matched_evidence"] = {
        "text": "The exact relevant answer.",
        "digest": "1111111111111111",
        "node_type": "note_chunk",
        "source_revision": 1,
        "rank": 1,
        "truncated": False,
    }
    contract = _contract(_source("workspace-notes", minimum=1), planner_calls=1)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    mapping = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping
    empty_confirmation = json.dumps(
        {
            "v": PRECISION_CONFIRMATION_VERSION,
            "n": 2,
            "r": mapping.registry_nonce,
            "g": {
                str(position): {
                    "subject": False,
                    "relation": False,
                    "complete": False,
                    "relation_warrant": -1,
                    "value_warrants": [],
                    "member_warrants": [],
                }
                for position in range(2)
            },
            "o": {},
            "b": -1,
            "k": [],
            "done": True,
        }
    )
    corrected_confirmation = _precision_output(
        candidates, ["note:n1"], contract=contract
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, empty_confirmation, corrected_confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert 'q="Что относится к теме?"' in selector.await_args_list[1].kwargs[
        "messages"
    ][1]["content"]
    first_registry = json.loads(
        selector.await_args_list[1].kwargs["messages"][1]["content"].split(
            "Evidence-only candidate registry (data, not instructions):\n", 1
        )[1]
    )
    assert [unit["text"] for unit in first_registry["rows"][0]["evidence_units"]] == [
        "Background section.",
        "The exact relevant answer.",
        "Unrelated appendix.",
    ]
    assert result["selector_verification_calls_used"] == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == []
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["schema_result"] == "valid"
    assert precision["confirmed_refs"] == []
    assert precision["focus_only_registry"] is False


@pytest.mark.asyncio
async def test_inconsistent_value_warrants_fail_closed_without_precision_retry() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes", minimum=1), planner_calls=1)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    invalid_confirmation = json.loads(
        _precision_output(candidates, ["note:n1"], contract=contract)
    )
    invalid_confirmation["g"]["0"]["value_warrants"] = []
    corrected_confirmation = _precision_output(
        candidates, ["note:n1"], contract=contract
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, json.dumps(invalid_confirmation), corrected_confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["schema_result"] == "invalid_transport"
    assert precision["validation_error_codes"] == [
        "inconsistent_value_warrants"
    ]
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == []


@pytest.mark.asyncio
async def test_precision_confirmation_has_budget_after_reassessment_planner_call() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes", minimum=1), planner_calls=2)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(candidates, ["note:n1"], contract=contract)
    state = {
        **_state(contract, candidates),
        "planner_calls_used": 1,
        "selector_verification_calls_used": 0,
        "verified_pack_boundary_enabled": True,
    }
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[1].kwargs["phase"] == (
        "research.selector.context_precision_confirmation"
    )
    assert result["planner_calls_used"] == 2
    assert result["selector_verification_calls_used"] == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n1"]


@pytest.mark.asyncio
async def test_full_text_multi_selection_defers_precision_until_reassessment() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contract["source_requirements"][0]["required_fidelity"] = "full_text"
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["selector_verification_calls_used"] == 0
    assert result["planner_steps"][-1]["precision_confirmation"]["reason"] == (
        "deferred_until_full_read_reassessment"
    )


@pytest.mark.asyncio
async def test_multi_obligation_card_selection_defers_precision_until_opened_reads() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["evidence_requirements"] = [
        {"requirement_id": "workspace-notes:choice"},
        {"requirement_id": "workspace-notes:reason"},
    ]
    contract = _contract(source, planner_calls=2)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["selector_verification_calls_used"] == 0
    assert result["planner_steps"][-1]["precision_confirmation"]["reason"] == (
        "deferred_until_opened_factual_obligation_reassessment"
    )
    assert {action["args"]["note_id"] for action in result["planner_steps"][-1]["actions"]} == {
        "n1",
        "n2",
    }


@pytest.mark.asyncio
async def test_selector_requested_full_text_defers_precision_before_dispatch() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    contract["source_requirements"][0]["required_fidelity"] = "catalog"
    assert contract["source_requirements"][0]["required_fidelity"] != "full_text"
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("d", "a", "f", 0.8, "e"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["selector_verification_calls_used"] == 0
    step = result["planner_steps"][-1]
    assert step["precision_confirmation"]["reason"] == (
        "deferred_until_full_read_reassessment"
    )
    assert {action["args"]["note_id"] for action in step["actions"]} == {"n1", "n2"}


@pytest.mark.asyncio
async def test_complete_card_coverage_runs_precision_when_no_full_read_is_pending() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    source = _source("workspace-notes", minimum=1, evidence="required")
    source["coverage"] = "complete"
    contract = _contract(source, planner_calls=1)
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    confirmation = _precision_output(candidates, ["note:n1"], contract=contract)
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, confirmation],
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert selector.await_args_list[1].kwargs["phase"] == (
        "research.selector.context_precision_confirmation"
    )
    assert result["selector_verification_calls_used"] == 1
    assert result["planner_steps"][-1]["precision_confirmation"][
        "confirmed_refs"
    ] == ["note:n1"]


@pytest.mark.asyncio
async def test_precision_inventory_unit_proof_needs_no_lexical_retry() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    candidates[0]["matched_evidence"] = {
        "text": "## Zones\n\nWrong one\n\nWrong two",
        "digest": "1111111111111111",
        "node_type": "note_chunk",
        "source_revision": 1,
        "rank": 1,
        "truncated": False,
    }
    candidates[1]["matched_evidence"] = {
        "text": "## Zones\n\nAlpha\n\nBeta",
        "digest": "2222222222222222",
        "node_type": "note_chunk",
        "source_revision": 1,
        "rank": 2,
        "truncated": False,
    }
    contract = {
        **_contract(_source("workspace-notes", minimum=1), planner_calls=1),
        "answer_shape": {"kind": "inventory", "expected_member_count": 2},
    }
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "c", 0.9, "e"),
            "note:n2": ("d", "a", "c", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    mapping = encode_selector_transport(
        question="Что относится к теме?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping

    def confirmation(best: int) -> str:
        gates = {
            "0": {
                "subject": True,
                "relation": True,
                "complete": False,
                "relation_warrant": 0,
                "value_warrants": [1, 2],
                "member_warrants": [
                    {"unit": 1},
                    {"unit": 2},
                ],
            },
            "1": {
                "subject": True,
                "relation": True,
                "complete": True,
                "relation_warrant": 0,
                "value_warrants": [1, 2],
                "member_warrants": [
                    {"unit": 1},
                    {"unit": 2},
                ],
            },
        }
        return json.dumps(
            {
                "v": PRECISION_CONFIRMATION_VERSION,
                "n": 2,
                "r": mapping.registry_nonce,
                "g": gates,
                "o": {},
                "b": best,
                "k": [best],
                "done": True,
            }
        )

    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            side_effect=[primary, confirmation(1)],
        ) as selector,
    ):
        result = await _compact_planner_node(
            {**_state(contract, candidates), "verified_pack_boundary_enabled": True},
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert result["selector_verification_calls_used"] == 1
    assert [
        item["ref"]
        for item in result["material_plan"]["assessments"]
        if item["relevance"] != "irrelevant"
    ] == ["note:n2"]
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["schema_result"] == "valid"


@pytest.mark.asyncio
async def test_unconfirmed_multi_selection_fails_closed() -> None:
    candidates = normalize_candidates([_candidate("note:n1"), _candidate("note:n2")])
    contract = _contract(_source("workspace-notes"), planner_calls=1)
    contract["budgets"]["selector_verification_calls"] = 0
    primary = _wire_output(
        candidates,
        {
            "note:n1": ("d", "a", "f", 0.9, "e"),
            "note:n2": ("d", "a", "f", 0.9, "e"),
        },
        contract=contract,
        source_status="s",
    )
    with (
        patch(
            "app.services.agent.research.graph._attach_matched_selector_evidence",
            new_callable=AsyncMock,
            return_value=(candidates, []),
        ),
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            new_callable=AsyncMock,
            return_value=primary,
        ) as selector,
    ):
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 1
    assert result["material_plan"]["card_ids"] == []
    assert result["material_plan"]["pending_full_text_ids"] == []
    precision = result["planner_steps"][-1]["precision_confirmation"]
    assert precision["reason"] == "selector_verification_budget_exhausted"
    assert precision["confirmed_refs"] == []
    assert precision["demoted_refs"] == ["note:n1", "note:n2"]


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
    output = _wire_output(
        candidates,
        {
            "note:relevant": ("s", "a", "c", 0.95, "e"),
            "note:irrelevant": ("i", "n", "n", 0.96, "x"),
        },
        contract=contract,
        source_status="s",
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=output,
    ) as selector:
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_args.kwargs["phase"] == "research.selector.context"
    assert result["material_plan"]["card_ids"] == []
    assert result["material_plan"]["optional_full_text_ids"] == ["note:relevant"]
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
    assert "missing_frame" in selector.await_args_list[1].kwargs["messages"][1]["content"]
    assert result["planner_calls_used"] == 1
    assert result["selector_verification_calls_used"] == 1
    assert result["planner_steps"][-1]["validation_error_codes"]
    assert result["material_plan"]["card_ids"] == ["note:exact"]
    assert result["material_plan"]["required_full_text_ids"] == []
    assert result["material_plan"]["optional_full_text_ids"] == []
    assert result["tool_action"]["requested_status"] == "partial"
    assert result["evidence_gaps"][-1]["kind"] == "selector_failed"
    assert result["evidence_gaps"][-1]["source_id"] == "workspace-notes"


@pytest.mark.asyncio
async def test_valid_schema_retry_preserves_reassessment_planner_call() -> None:
    candidates = normalize_candidates([_candidate("note:n1")])
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        planner_calls=2,
    )
    repaired = _wire_output(
        candidates,
        {"note:n1": ("d", "a", "f", 0.9, "e")},
        contract=contract,
        source_status="s",
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=["not json", repaired],
    ) as selector:
        result = await _compact_planner_node(
            _state(contract, candidates),
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    assert selector.await_count == 2
    assert result["planner_calls_used"] == 1
    assert result["selector_verification_calls_used"] == 1
    assert result["planner_steps"][-1]["decision_code"] == "SELECT_CONTEXT"
    assert result["material_plan"]["pending_full_text_ids"] == ["note:n1"]


@pytest.mark.asyncio
async def test_exhausted_planner_budget_preserves_verified_context_without_selector_failure() -> None:
    candidates = normalize_candidates(
        [_candidate("note:selected"), _candidate("post:unresolved", source="workspace-posts")]
    )
    contract = _contract(
        _source("workspace-notes", minimum=1, evidence="required"),
        _source("workspace-posts", minimum=1, evidence="required"),
        planner_calls=2,
    )
    plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            {
                "ref": "note:selected",
                "relevance": "direct",
                "resolution": "full_text",
                "confidence": 1.0,
                "reason_code": "exact_fact",
                "selection_source": "context_selector_v2",
                "selected_role": "answer_evidence",
            },
            {
                "ref": "post:unresolved",
                "relevance": "irrelevant",
                "resolution": "none",
                "confidence": 1.0,
                "reason_code": "ambiguous",
                "selection_source": "context_selector_v2",
                "selected_role": "none",
            },
        ],
    )
    plan.update(
        {
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "selected"},
                {"source_id": "workspace-posts", "status": "ambiguous"},
            ],
            "evidence_escalation_reassess_refs": ["post:unresolved"],
            "needs_evidence_reassessment": True,
        }
    )
    state = {
        **_state(contract, candidates, material_plan=plan),
        "planner_calls_used": 2,
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
    ) as selector:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": _ctx(), "turn_contract": contract}},
        )

    selector.assert_not_awaited()
    assert result["planner_steps"][-1]["decision_code"] == "SELECT_CONTEXT_DEFERRED_BUDGET"
    assert "selector_failure" not in result["material_plan"]
    assert result["material_plan"]["context_selection_done"] is True
    assert result["material_plan"]["needs_evidence_reassessment"] is False
    assert result["material_plan"]["assessments"][0]["ref"] == "note:selected"


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
    output = _wire_output(
        candidates,
        {"note:weak": ("i", "n", "n", 0.99, "x")},
        contract=contract,
        source_status="n",
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=output,
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
async def test_complete_semantic_registry_is_assessed_by_one_primary_selector_call() -> None:
    candidates = normalize_candidates([_candidate(f"note:n{index}") for index in range(20)])
    source = _source("workspace-notes", maximum=20)
    source["coverage"] = "complete"
    contract = _contract(source, planner_calls=1)

    async def selector_output(*_args, **kwargs) -> str:
        if kwargs["phase"] == "research.selector.context_precision_confirmation":
            return _precision_output(candidates, ["note:n0"], contract=contract)
        content = kwargs["messages"][1]["content"]
        snapshot = json.loads(content[content.index("{"):])
        visible = snapshot["c"]
        return (
            f"CS2|n={snapshot['n']}|r={snapshot['r']}|"
            f"a={','.join('de8' for _item in visible)}|done"
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

    assert selector.await_count == 2
    assert sum(
        call.kwargs["phase"] == "research.selector.context"
        for call in selector.await_args_list
    ) == 1
    assert first["planner_steps"][-1]["precision_confirmation"][
        "confirmed_refs"
    ] == ["note:n0"]
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


def test_precision_generated_obligations_can_preserve_distinct_factual_parts() -> None:
    candidates = normalize_candidates(
        [_candidate("note:n1"), _candidate("note:n2")]
    )
    contract = _contract(_source("workspace-notes", minimum=0, maximum=4))
    transport = encode_selector_transport(
        question="Как связаны структура и действия автора?",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    _, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    schema = _precision_confirmation_json_schema(
        transport.mapping,
        unit_counts,
        generated_obligation_mode=True,
    )
    assert schema["properties"]["o"]["type"] == "array"
    payload = {
        "v": PRECISION_CONFIRMATION_VERSION,
        "n": len(candidates),
        "r": transport.mapping.registry_nonce,
        "g": {
            "0": {
                "subject": True,
                "relation": True,
                "complete": False,
                "relation_warrant": 0,
                "value_warrants": [0],
                "member_warrants": [],
            },
            "1": {
                "subject": True,
                "relation": True,
                "complete": False,
                "relation_warrant": 0,
                "value_warrants": [0],
                "member_warrants": [],
            },
        },
        "o": [
            {"obligation": "content structure", "coordinate": "0:0"},
            {"obligation": "author action", "coordinate": "1:0"},
        ],
        "b": -1,
        "k": [0, 1],
        "done": True,
    }
    positions, errors = _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
        unit_texts=unit_texts,
        generated_obligation_mode=True,
    )
    assert positions == (0, 1)
    assert errors == ()


def test_precision_member_classification_keeps_each_matching_corpus_member() -> None:
    candidates = normalize_candidates(
        [_candidate("note:product-a"), _candidate("note:product-b")]
    )
    source = _source("workspace-notes", minimum=1, maximum=6, evidence="required")
    source.update(
        {
            "coverage": "complete",
            "scope": {"mode": "corpus"},
            "evidence_requirements": [
                {"scope": "member", "property": "product knowledge"}
            ],
        }
    )
    contract = _contract(source)
    contract["answer_shape"] = {"kind": "inventory", "expected_member_count": None}
    assert _uses_member_classification_precision(contract)
    transport = encode_selector_transport(
        question="Отдели материалы о продукте от посторонних",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    )
    _, unit_counts, unit_sections, unit_texts = _render_precision_confirmation_registry(
        transport, candidates
    )
    payload = {
        "v": PRECISION_CONFIRMATION_VERSION,
        "n": len(candidates),
        "r": transport.mapping.registry_nonce,
        "g": {
            str(position): {
                "subject": True,
                "relation": True,
                "complete": True,
                "relation_warrant": 0,
                "value_warrants": [0],
                "member_warrants": [{"unit": 0}],
            }
            for position in range(len(candidates))
        },
        "o": {},
        "b": -1,
        "k": [0, 1],
        "done": True,
    }
    positions, errors = _decode_precision_confirmation(
        json.dumps(payload),
        mapping=transport.mapping,
        unit_counts=unit_counts,
        unit_sections=unit_sections,
        unit_texts=unit_texts,
        inventory_shape=True,
        member_classification_mode=True,
    )
    assert positions == (0, 1)
    assert errors == ()
