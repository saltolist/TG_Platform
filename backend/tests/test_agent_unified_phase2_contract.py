"""Unified integrity phase-2 typed obligation and gap tests."""

from __future__ import annotations

import json

from app.services.agent.research.catalog import build_catalog_snapshot
from app.services.agent.research.graph import (
    _apply_complete_source_policy,
    _selector_decision_is_valid,
)
from app.services.agent.research.planner_decision import LegacyContextSelectorDecision
from app.services.agent.research.sufficiency import evaluate_sufficiency
from app.services.agent.runtime.turn_contract import (
    TYPED_TURN_CONTRACT_SCHEMA,
    build_turn_contract,
    normalize_turn_contract,
    source_evidence_required,
    source_required_fidelity,
    source_selection_cardinality,
)
from app.services.agent.runtime.workspace_graph import (
    _ORDERED_DECISION_HISTORY_QUERY_GOAL,
    WORKSPACE_SYSTEM,
    _apply_classifier_answer_shape,
    _apply_classifier_dependency_gate,
    _apply_classifier_source_policy,
    _apply_decision_context_policy,
    _classifier_contract_coherence_errors,
    _materialize_classifier_turn_contract,
)


def _typed_contract(question: str) -> dict:
    return build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        typed_requirements_enabled=True,
    )


def _catalog_record(path: str, snapshot: dict) -> dict:
    return {
        "id": path,
        "kind": "catalog",
        "source_ref": path,
        "content": "authoritative catalog",
        "citation_path": path,
        "citation_title": path,
        "metadata": {"catalog_snapshot": snapshot},
    }


def _note_record(note_id: str) -> dict:
    path = f"/note/global/{note_id}/"
    return {
        "id": path,
        "kind": "note_chunk",
        "source_ref": f"note:{note_id}",
        "content": "authoritative note",
        "citation_path": path,
        "citation_title": note_id,
        "metadata": {},
    }


def test_v3_separates_all_source_obligations_and_writes_no_legacy_triplet() -> None:
    contract = _typed_contract("Сколько заметок с изображениями?")

    assert contract["schema"] == TYPED_TURN_CONTRACT_SCHEMA
    assert contract["version"] == 3
    assert contract["plan_decision"] == {
        "route": "deterministic_fast_path",
        "reason_code": "STRUCTURAL_PREDICATE",
    }
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    assert notes["discovery_obligation"] == "required"
    assert notes["evidence_obligation"] == "required"
    assert notes["selection_cardinality"] == {"min": 0, "max": 0}
    assert notes["coverage"] == "complete"
    assert notes["predicate_kind"] == "structural"
    assert notes["required_fidelity"] == "catalog"
    assert {item["property"] for item in notes["evidence_requirements"]} == {
        "total_notes",
        "has_images",
        "image_count",
    }
    assert all(
        not {"required", "min_evidence", "evidence_granularity"}.intersection(source)
        for source in contract["source_requirements"]
    )


def test_classifier_answer_shape_preserves_explicit_inventory_cardinality() -> None:
    contract = _typed_contract("List the requested category.")

    shaped = _apply_classifier_answer_shape(
        contract,
        {"kind": "inventory", "expected_member_count": 6},
    )

    assert shaped["answer_shape"] == {
        "kind": "inventory",
        "expected_member_count": 6,
    }
    assert _apply_classifier_answer_shape(
        shaped,
        {"kind": "scalar", "expected_member_count": 6},
    )["answer_shape"] == {"kind": "scalar", "expected_member_count": None}


def test_mixed_predicate_keeps_structural_requirements_on_typed_planner_route() -> None:
    contract = _typed_contract("Сколько заметок про запуск?")
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")

    assert notes["predicate_kind"] == "mixed"
    assert notes["selection_cardinality"]["min"] == 0
    assert notes["coverage"] == "complete"
    assert contract["plan_decision"] == {
        "route": "typed_planner",
        "reason_code": "MIXED_PREDICATE",
    }
    assert any(item["property"] == "total_notes" for item in notes["evidence_requirements"])


def test_classifier_adapter_maps_image_evidence_to_vision_fidelity() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Что изображено на картинках?"),
        required_sources=["images"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "images", "evidence_granularity": "full_text"}
        ],
    )
    images = next(item for item in contract["source_requirements"] if item["kind"] == "images")

    assert images["evidence_obligation"] == "required"
    assert images["required_fidelity"] == "vision"
    assert not {"required", "min_evidence", "evidence_granularity"}.intersection(images)


def test_classifier_preserves_independent_source_goals_for_implicit_dependencies() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Нужна рекомендация для следующего результата"),
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "notes",
                "query_goal": "Find plans, constraints, and unfinished sequences relevant to the recommendation.",
                "coverage": "complete",
                "evidence_granularity": "full_text",
            },
            {
                "kind": "posts",
                "query_goal": "Read recent completed artifacts to avoid repetition and preserve continuity.",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "order_dependency": "required",
                "statuses": ["published"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 5,
                "evidence_granularity": "full_text",
                "evidence_requirements": [
                    {
                        "subject": "posts",
                        "property": "ordered_history_members",
                        "operator": "filter",
                        "scope": "member",
                    }
                ],
            },
        ],
    )
    sources = {item["kind"]: item for item in contract["source_requirements"]}

    assert sources["notes"]["query_goal"].startswith("Find plans")
    assert sources["posts"]["query_goal"].startswith("Read recent")
    assert sources["notes"]["coverage"] == "complete"
    assert sources["posts"]["coverage"] == "relevant"
    assert sources["posts"]["discovery_mode"] == "catalog_window"
    assert sources["posts"]["order_by"] == "position"
    assert sources["posts"]["order_direction"] == "desc"
    assert sources["posts"]["budget"]["candidate_limit"] == 5
    assert sources["posts"]["scope"]["statuses"] == ["published"]
    assert all(item["evidence_obligation"] == "required" for item in sources.values())


def test_classifier_prompt_requires_implicit_dependency_planning_without_case_routing() -> None:
    assert "Сам выведи необходимые предпосылки" in WORKSPACE_SYSTEM
    assert 'coverage="complete"' in WORKSPACE_SYSTEM
    assert 'discovery_mode="catalog_window"' in WORKSPACE_SYSTEM
    assert 'order_dependency="required"' in WORKSPACE_SYSTEM
    assert "безликие property вроде grounded_evidence" in WORKSPACE_SYSTEM
    assert 'statuses=["draft", "scheduled", "published"]' in WORKSPACE_SYSTEM
    assert "не своди такой контекст к одной категории" in WORKSPACE_SYSTEM
    assert "Источники должны затем сопоставляться по смыслу" in WORKSPACE_SYSTEM
    assert "Это примеры предпосылок, а не предписание вида источника" in WORKSPACE_SYSTEM
    assert "downstream должен иметь право выбрать ноль" in WORKSPACE_SYSTEM
    assert "нельзя объявлять structural только потому" in WORKSPACE_SYSTEM
    assert "граница дешёвого сравнения semantic cards" in WORKSPACE_SYSTEM
    assert "Это семантическое выявление зависимостей, а не keyword routing" in WORKSPACE_SYSTEM
    assert "не доказывают норму, предпочтение, лучший вариант" in WORKSPACE_SYSTEM
    assert "В таком независимом случае выбери finish" in WORKSPACE_SYSTEM
    assert "контрфактуальный route gate" in WORKSPACE_SYSTEM
    assert "empty_workspace" in WORKSPACE_SYSTEM
    assert "Про что написать следующий пост" not in WORKSPACE_SYSTEM


def test_classifier_dependency_gate_finishes_only_from_explicit_semantic_audit() -> None:
    mistaken_read = {
        "type": "read",
        "requires_evidence": True,
        "required_sources": ["notes", "posts"],
        "source_requirements": [{"kind": "notes"}],
        "search_query": "general question",
        "workspace_dependency": {
            "basis": "dialog_or_general_knowledge",
            "empty_workspace": "answer_unchanged",
        },
    }

    result = _apply_classifier_dependency_gate(mistaken_read)

    assert result["type"] == "finish"
    assert result["requires_evidence"] is False
    assert result["required_sources"] == []
    assert result["source_requirements"] == []
    assert result["search_query"] == ""


def test_classifier_dependency_gate_preserves_workspace_dependent_read() -> None:
    workspace_read = {
        "type": "read",
        "requires_evidence": True,
        "required_sources": ["notes"],
        "workspace_dependency": {
            "basis": "workspace_state",
            "empty_workspace": "answer_changes",
        },
    }

    assert _apply_classifier_dependency_gate(workspace_read) == workspace_read


def test_classifier_dependency_gate_rejects_unanchored_normative_topical_read() -> None:
    unanchored = {
        "type": "read",
        "task_profile": "topical_answer",
        "requires_evidence": True,
        "required_sources": ["notes"],
        "source_requirements": [
            {"kind": "notes", "claim_modality": "normative"}
        ],
        "workspace_dependency": {
            "basis": "workspace_state",
            "empty_workspace": "answer_changes",
            "anchor": "general_advice",
        },
    }

    result = _apply_classifier_dependency_gate(unanchored)

    assert result["type"] == "finish"
    assert result["workspace_dependency_gate"] == (
        "finish_unanchored_normative_advice"
    )


def test_classifier_dependency_gate_keeps_explicit_workspace_normative_rule() -> None:
    anchored = {
        "type": "read",
        "task_profile": "topical_answer",
        "requires_evidence": True,
        "required_sources": ["notes"],
        "source_requirements": [
            {"kind": "notes", "claim_modality": "normative"}
        ],
        "workspace_dependency": {
            "basis": "workspace_state",
            "empty_workspace": "answer_changes",
            "anchor": "explicit_workspace_reference",
        },
    }

    assert _apply_classifier_dependency_gate(anchored) == anchored


def test_decision_policy_keeps_broad_card_window_but_caps_final_posts() -> None:
    contract = _typed_contract("Choose the next result from current work.")
    contract["task_profile"] = "recommendation"
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Which recent completed results constrain the next choice?",
                "predicate_kind": "semantic",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "order_dependency": "required",
                "statuses": ["published"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 10,
                "evidence_granularity": "full_text",
                "evidence_requirements": [
                    {
                        "subject": "posts",
                        "property": "ordered_history_members",
                        "operator": "filter",
                        "scope": "member",
                    }
                ],
            }
        ],
    )

    result = _apply_decision_context_policy(contract)
    sources = {item["kind"]: item for item in result["source_requirements"]}

    assert sources["posts"]["budget"]["candidate_limit"] == 10
    assert sources["posts"]["budget"]["deep_reads"] == 5
    assert sources["posts"]["selection_cardinality"] == {"min": 0, "max": 5}
    assert sources["notes"]["evidence_obligation"] == "optional"
    assert sources["notes"]["selection_cardinality"]["min"] == 0


def test_decision_policy_does_not_truncate_explicit_inventory() -> None:
    contract = _typed_contract("List the complete requested history.")
    contract["task_profile"] = "workspace_synthesis"
    contract["answer_shape"] = {"kind": "inventory", "expected_member_count": None}
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Which members belong to the requested history?",
                "predicate_kind": "semantic",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "order_dependency": "required",
                "statuses": ["published"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 10,
                "evidence_granularity": "full_text",
                "evidence_requirements": [
                    {
                        "subject": "posts",
                        "property": "ordered_history_members",
                        "operator": "filter",
                        "scope": "member",
                    }
                ],
            }
        ],
    )

    result = _apply_decision_context_policy(contract)
    posts = next(item for item in result["source_requirements"] if item["kind"] == "posts")

    assert posts["budget"]["candidate_limit"] == 10
    assert posts["selection_cardinality"]["max"] == 10


def test_classifier_decision_profile_separates_recommendation_from_inventory() -> None:
    contract = _typed_contract("Choose the next result from current work.")
    result = _materialize_classifier_turn_contract(
        contract,
        {
            "type": "read",
            "task_profile": "recommendation",
            "requires_evidence": True,
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["posts"],
            "source_requirements": [
                {
                    "kind": "posts",
                    "query_goal": "Which recent completed results constrain the next choice?",
                    "claim_modality": "descriptive",
                    "predicate_kind": "semantic",
                    "coverage": "relevant",
                    "discovery_mode": "catalog_window",
                    "order_dependency": "required",
                    "statuses": ["published"],
                    "order_by": "position",
                    "order_direction": "desc",
                    "candidate_limit": 10,
                    "evidence_granularity": "full_text",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "ordered_history_members",
                            "operator": "filter",
                            "scope": "member",
                        }
                    ],
                }
            ],
        },
        classified_type="read",
    )
    posts = next(item for item in result["source_requirements"] if item["kind"] == "posts")

    assert result["task_profile"] == "recommendation"
    assert result["answer_shape"] == {
        "kind": "freeform",
        "expected_member_count": None,
    }
    assert posts["budget"]["candidate_limit"] == 10
    assert posts["budget"]["deep_reads"] == 5
    assert posts["selection_cardinality"]["min"] == 0
    assert posts["selection_cardinality"]["max"] == 5
    assert posts["claim_modality"] == "descriptive"
    assert _classifier_contract_coherence_errors(result) == ()


def test_classifier_routes_finite_comparison_through_topical_answer() -> None:
    contract = _typed_contract("Which of the two recorded alternatives fits the criterion?")
    result = _materialize_classifier_turn_contract(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "requires_evidence": True,
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["notes"],
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Compare the two recorded alternatives by the requested criterion.",
                    "claim_modality": "descriptive",
                    "predicate_kind": "semantic",
                    "coverage": "relevant",
                    "discovery_mode": "semantic_relevance",
                    "order_dependency": "irrelevant",
                    "candidate_limit": 6,
                    "evidence_granularity": "full_text",
                    "evidence_requirements": [
                        {
                            "subject": "alternatives",
                            "property": "requested_difference",
                            "operator": "exists",
                            "scope": "source",
                        }
                    ],
                }
            ],
        },
        classified_type="read",
    )

    assert result["task_profile"] == "topical_answer"
    notes = next(
        item for item in result["source_requirements"] if item["kind"] == "notes"
    )
    assert notes["selection_cardinality"]["max"] == 6


def test_finite_comparison_survives_non_exhaustive_complete_coverage_repair() -> None:
    contract = _typed_contract("Which of the two recorded alternatives fits?")
    result = _materialize_classifier_turn_contract(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "requires_evidence": True,
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["notes"],
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Compare the two recorded alternatives.",
                    "claim_modality": "descriptive",
                    "predicate_kind": "semantic",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "order_dependency": "irrelevant",
                    "candidate_limit": 6,
                    "evidence_granularity": "full_text",
                    "evidence_requirements": [
                        {
                            "subject": "alternatives",
                            "property": "first outcome",
                            "operator": "exists",
                            "scope": "source",
                        },
                        {
                            "subject": "alternatives",
                            "property": "second outcome",
                            "operator": "exists",
                            "scope": "source",
                        },
                    ],
                }
            ],
        },
        classified_type="read",
    )

    notes = next(
        item for item in result["source_requirements"] if item["kind"] == "notes"
    )
    assert notes["coverage"] == "relevant"
    assert result["task_profile"] == "topical_answer"


def test_classifier_requires_typed_claim_modality_for_semantic_evidence() -> None:
    contract = _typed_contract("Which format does the saved policy require?")
    call = {
        "type": "read",
        "task_profile": "topical_answer",
        "requires_evidence": True,
        "required_sources": ["notes"],
        "source_requirements": [
            {
                "kind": "notes",
                "query_goal": "Which format does the saved policy require?",
                "predicate_kind": "semantic",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "evidence_granularity": "full_text",
            }
        ],
    }

    missing = _materialize_classifier_turn_contract(
        contract,
        call,
        classified_type="read",
    )
    assert _classifier_contract_coherence_errors(missing) == (
        "missing_claim_modality:workspace-notes",
    )

    typed = _materialize_classifier_turn_contract(
        contract,
        {
            **call,
            "source_requirements": [
                {**call["source_requirements"][0], "claim_modality": "normative"}
            ],
        },
        classified_type="read",
    )
    assert _classifier_contract_coherence_errors(typed) == ()
    notes = next(
        item for item in typed["source_requirements"] if item["kind"] == "notes"
    )
    assert notes["claim_modality"] == "normative"


def test_classifier_promotes_non_catalog_property_to_semantic_selection() -> None:
    contract = _typed_contract("List every saved functional zone.")
    result = _apply_classifier_source_policy(
        contract,
        required_sources=["notes"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "notes",
                "query_goal": "Which functional zones are explicitly listed?",
                "claim_modality": "descriptive",
                "predicate_kind": "structural",
                "coverage": "complete",
                "discovery_mode": "semantic_relevance",
                "evidence_granularity": "catalog",
                "evidence_requirements": [
                    {
                        "property": "functional_zone_name",
                        "operator": "exists",
                        "scope": "member",
                    }
                ],
            }
        ],
    )

    notes = next(item for item in result["source_requirements"] if item["kind"] == "notes")
    assert notes["predicate_kind"] == "semantic"
    assert notes["required_fidelity"] == "semantic_card"
    assert notes["selection_cardinality"]["max"] > 0


def test_workspace_synthesis_downgrades_only_non_exhaustive_complete_coverage() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Synthesize a workflow and the capabilities that enable it."),
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "requires_evidence": True,
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Find platform capabilities relevant to the workflow.",
                    "predicate_kind": "semantic",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "evidence_granularity": "full_text",
                    "evidence_requirements": [
                        {
                            "subject": "notes",
                            "property": "platform_features",
                            "operator": "exists",
                            "scope": "target",
                        }
                    ],
                },
                {
                    "kind": "posts",
                    "query_goal": "Count every post in the requested corpus.",
                    "predicate_kind": "mixed",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "evidence_granularity": "semantic_card",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "total_posts",
                            "operator": "count",
                            "scope": "aggregate",
                        }
                    ],
                },
            ],
        },
        classified_type="read",
    )
    sources = {item["kind"]: item for item in contract["source_requirements"]}

    assert contract["task_profile"] == "workspace_synthesis"
    assert sources["notes"]["coverage"] == "relevant"
    assert sources["notes"]["predicate_kind"] == "semantic"
    assert sources["posts"]["coverage"] == "complete"
    assert sources["posts"]["predicate_kind"] == "mixed"


def test_decision_policy_allows_zero_without_changing_semantic_discovery() -> None:
    contract = _typed_contract("Choose the next result from current work.")
    contract["task_profile"] = "recommendation"
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "notes",
                "query_goal": "Find indispensable planning premises.",
                "predicate_kind": "semantic",
                "coverage": "complete",
                "discovery_mode": "semantic_relevance",
                "candidate_limit": 6,
                "evidence_granularity": "full_text",
            },
            {
                "kind": "posts",
                "query_goal": "Find completed results that constrain the decision.",
                "predicate_kind": "semantic",
                "coverage": "complete",
                "discovery_mode": "semantic_relevance",
                "candidate_limit": 6,
                "evidence_granularity": "full_text",
            },
        ],
    )

    result = _apply_decision_context_policy(contract)
    sources = {item["kind"]: item for item in result["source_requirements"]}

    assert sources["notes"]["discovery_mode"] == "semantic_relevance"
    assert sources["posts"]["discovery_mode"] == "semantic_relevance"
    assert sources["notes"]["coverage"] == "complete"
    assert sources["posts"]["coverage"] == "complete"
    assert sources["notes"]["selection_cardinality"]["min"] == 0
    assert sources["posts"]["selection_cardinality"] == {"min": 0, "max": 5}
    assert sources["posts"]["budget"]["deep_reads"] == 5


def test_classifier_rejects_unknown_post_status_filters() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Choose the next deliverable from the current plan and history"),
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Inspect completed deliverables in sequence order.",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "order_dependency": "required",
                "statuses": ["completed", "published", "removed"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 4,
                "evidence_granularity": "semantic_card",
                "evidence_requirements": [
                    {
                        "subject": "posts",
                        "property": "ordered_history_members",
                        "operator": "filter",
                        "scope": "member",
                    }
                ],
            }
        ],
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert posts["scope"]["statuses"] == ["published"]
    assert posts["discovery_mode"] == "catalog_window"


def test_classifier_rejects_catalog_window_without_supported_order_contract() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Choose the next deliverable"),
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Compare a bounded completed-history premise.",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "statuses": ["published"],
                "order_by": "title",
                "order_direction": "desc",
                "candidate_limit": 4,
                "predicate_kind": "semantic",
            }
        ],
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert posts["discovery_mode"] == "semantic_relevance"
    assert posts["order_by"] is None
    assert posts["order_direction"] is None


def test_classifier_rejects_catalog_window_without_order_dependency() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Describe an author workflow from relevant workspace content"),
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Describe the author workflow and its enabling capabilities.",
                "coverage": "relevant",
                "discovery_mode": "catalog_window",
                "order_dependency": "irrelevant",
                "statuses": ["draft", "scheduled", "published"],
                "order_by": "created_at",
                "order_direction": "desc",
                "candidate_limit": 5,
                "predicate_kind": "semantic",
            }
        ],
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert posts["discovery_mode"] == "semantic_relevance"
    assert posts["order_by"] is None
    assert posts["order_direction"] is None


def test_workspace_synthesis_rejects_source_level_ordered_window_after_materialization() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Describe an end-to-end author workflow"),
        {
            "task_profile": "workspace_synthesis",
            "requires_evidence": True,
            "required_sources": ["posts"],
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "posts",
                    "query_goal": "Describe the workflow stages and enabling capabilities.",
                    "claim_modality": "descriptive",
                    "predicate_kind": "semantic",
                    "coverage": "relevant",
                    "discovery_mode": "catalog_window",
                    "order_dependency": "required",
                    "statuses": ["draft", "scheduled", "published"],
                    "order_by": "created_at",
                    "order_direction": "desc",
                    "candidate_limit": 5,
                    "evidence_granularity": "full_text",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "workflow_stages",
                            "operator": "exists",
                            "scope": "source",
                        }
                    ],
                }
            ],
        },
        classified_type="read",
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert contract["task_profile"] == "workspace_synthesis"
    assert posts["discovery_mode"] == "semantic_relevance"
    assert posts["query_goal"] == "Describe the workflow stages and enabling capabilities."
    assert posts["required_fidelity"] == "full_text"


def test_decision_classifier_recovers_explicit_order_as_a_catalog_window() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Choose the next deliverable"),
        {
            "task_profile": "recommendation",
            "requires_evidence": True,
            "required_sources": ["posts"],
            "search_query": "Choose the next deliverable",
            "answer_shape": {
                "kind": "freeform",
                "expected_member_count": None,
            },
            "source_requirements": [
                {
                    "kind": "posts",
                    "query_goal": "Observe recent completed outputs before deciding.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "statuses": ["published"],
                    "order_by": "created_at",
                    "order_direction": "desc",
                    "candidate_limit": 4,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "ordered_history_members",
                            "operator": "filter",
                            "scope": "member",
                        }
                    ],
                }
            ],
        },
        classified_type="read",
    )
    posts = next(
        item for item in contract["source_requirements"] if item["kind"] == "posts"
    )

    assert contract["task_profile"] == "recommendation"
    assert posts["coverage"] == "relevant"
    assert "уже выполненное, запланированное или незавершённое" in posts["query_goal"]
    assert "Выбери ноль" in posts["query_goal"]
    assert "давность не делает" in posts["query_goal"]
    assert posts["query_goal"] != "Observe recent completed outputs before deciding."
    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"
    assert posts["selection_cardinality"] == {"min": 0, "max": 4}
    assert posts["budget"]["candidate_limit"] == 4
    assert posts["budget"]["deep_reads"] == 4


def test_recommendation_recovers_published_companion_history_without_order() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Choose the next deliverable"),
        {
            "task_profile": "recommendation",
            "requires_evidence": True,
            "required_sources": ["notes", "posts"],
            "search_query": "Choose the next deliverable",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Find current plans that constrain the decision.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "candidate_limit": 6,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                },
                {
                    "kind": "posts",
                    "query_goal": "Assess completed outputs against the plan.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "statuses": ["published"],
                    "candidate_limit": 6,
                    "predicate_kind": "mixed",
                    "evidence_granularity": "semantic_card",
                },
            ],
        },
        classified_type="read",
    )
    sources = {item["kind"]: item for item in contract["source_requirements"]}
    posts = sources["posts"]

    assert sources["notes"]["discovery_mode"] == "semantic_relevance"
    assert posts["coverage"] == "relevant"
    assert posts["predicate_kind"] == "semantic"
    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"
    assert posts["budget"]["candidate_limit"] == 6
    assert posts["selection_cardinality"] == {"min": 0, "max": 5}
    assert "уже выполненное, запланированное или незавершённое" in posts["query_goal"]
    assert "Выбери ноль" in posts["query_goal"]


def test_recommendation_recovers_history_when_window_descriptor_is_incomplete() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Choose the next deliverable"),
        {
            "task_profile": "recommendation",
            "requires_evidence": True,
            "required_sources": ["notes", "posts"],
            "search_query": "Choose the next deliverable",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Find current plans that constrain the decision.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "candidate_limit": 6,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                },
                {
                    "kind": "posts",
                    "query_goal": "Assess current output states against the plan.",
                    "coverage": "relevant",
                    "discovery_mode": "catalog_window",
                    "statuses": ["draft", "scheduled", "published"],
                    "candidate_limit": 6,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                },
            ],
        },
        classified_type="read",
    )
    posts = next(
        source for source in contract["source_requirements"] if source["kind"] == "posts"
    )

    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"
    assert posts["scope"]["statuses"] == ["draft", "scheduled", "published"]
    assert posts["selection_cardinality"]["min"] == 0
    assert posts["selection_cardinality"]["max"] <= 5


def test_recommendation_preserves_mixed_status_decision_context() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Choose the next deliverable"),
        {
            "task_profile": "recommendation",
            "requires_evidence": True,
            "required_sources": ["notes", "posts"],
            "search_query": "Choose the next deliverable",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Find current plans that constrain the decision.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "candidate_limit": 6,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                },
                {
                    "kind": "posts",
                    "query_goal": "Inspect post statuses before choosing.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "statuses": ["published", "scheduled"],
                    "candidate_limit": 6,
                    "predicate_kind": "structural",
                    "evidence_granularity": "catalog",
                },
            ],
        },
        classified_type="read",
    )
    sources = {item["kind"]: item for item in contract["source_requirements"]}
    posts = sources["posts"]

    assert sources["notes"]["discovery_mode"] == "semantic_relevance"
    assert posts["scope"]["statuses"] == ["published", "scheduled"]
    assert posts["coverage"] == "relevant"
    assert posts["predicate_kind"] == "semantic"
    assert posts["required_fidelity"] == "semantic_card"
    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"
    assert posts["budget"]["candidate_limit"] == 6
    assert posts["selection_cardinality"] == {"min": 0, "max": 5}
    assert "Выбери ноль" in posts["query_goal"]


def test_recommendation_relates_existing_history_window_to_other_premises() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Choose the next deliverable"),
        {
            "task_profile": "recommendation",
            "requires_evidence": True,
            "required_sources": ["notes", "posts"],
            "search_query": "Choose the next deliverable",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "query_goal": "Find current plans.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "candidate_limit": 6,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                },
                {
                    "kind": "posts",
                    "query_goal": "Find audience interests in recent posts.",
                    "coverage": "relevant",
                    "discovery_mode": "catalog_window",
                    "order_dependency": "required",
                    "statuses": ["published"],
                    "order_by": "created_at",
                    "order_direction": "desc",
                    "candidate_limit": 4,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "ordered_history_members",
                            "operator": "filter",
                            "scope": "member",
                        }
                    ],
                },
            ],
        },
        classified_type="read",
    )
    posts = next(
        item for item in contract["source_requirements"] if item["kind"] == "posts"
    )

    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"
    assert posts["budget"]["candidate_limit"] == 4
    assert posts["query_goal"] == _ORDERED_DECISION_HISTORY_QUERY_GOAL
    assert "темы, интересы, отклики, ограничения" in posts["query_goal"]
    assert "иные самостоятельные сигналы" in posts["query_goal"]


def test_nondecision_classifier_does_not_reinterpret_complete_ordering() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("List every published post"),
        {
            "task_profile": "topical_answer",
            "requires_evidence": True,
            "required_sources": ["posts"],
            "search_query": "List every published post",
            "source_requirements": [
                {
                    "kind": "posts",
                    "query_goal": "List every published post.",
                    "coverage": "complete",
                    "discovery_mode": "semantic_relevance",
                    "statuses": ["published"],
                    "order_by": "created_at",
                    "order_direction": "desc",
                    "candidate_limit": 4,
                    "predicate_kind": "semantic",
                    "evidence_granularity": "semantic_card",
                    "evidence_requirements": [
                        {
                            "subject": "posts",
                            "property": "published_posts",
                            "operator": "filter",
                            "scope": "corpus",
                        }
                    ],
                }
            ],
        },
        classified_type="read",
    )
    posts = next(
        item for item in contract["source_requirements"] if item["kind"] == "posts"
    )

    assert posts["coverage"] == "complete"
    assert posts["discovery_mode"] == "semantic_relevance"
    assert posts["order_by"] is None
    assert posts["order_direction"] is None


def test_classifier_binds_post_comments_to_authoritative_post_target() -> None:
    base = build_turn_contract(
        user_text="Что пишут в комментариях к этому посту?",
        history=[],
        scope="post",
        open_post={"id": "post-42", "text": "Current post"},
        typed_requirements_enabled=True,
    )
    contract = _apply_classifier_source_policy(
        base,
        required_sources=["comments"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "comments", "coverage": "relevant", "evidence_granularity": "full_text"}
        ],
    )
    comments = next(item for item in contract["source_requirements"] if item["kind"] == "comments")

    assert comments["scope"]["mode"] == "targets"
    assert comments["scope"]["target_ids"] == ["post-42"]


def test_classifier_supports_channel_as_metadata_source() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Какая тема у моего канала?"),
        required_sources=["channel"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "channel", "coverage": "relevant", "evidence_granularity": "catalog"}
        ],
    )
    channel = next(item for item in contract["source_requirements"] if item["kind"] == "channel")

    assert channel["required_fidelity"] == "metadata"
    assert channel["evidence_obligation"] == "required"


def test_classifier_propagates_resolved_query_goal_to_semantic_sources() -> None:
    resolved = "Compare the launch constraint with the budget decision."
    contract = _apply_classifier_source_policy(
        _typed_contract("А как это соотносится с тем решением?"),
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        query_goal=resolved,
    )

    semantic_sources = [
        source
        for source in contract["source_requirements"]
        if source.get("predicate_kind") in {"semantic", "mixed"}
    ]
    assert semantic_sources
    assert all(source["query_goal"] == resolved for source in semantic_sources)


def test_required_discovery_with_zero_min_allows_no_relevant_candidate() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=[],
        classifier_requires_evidence=False,
    )
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")
    notes["coverage"] = "complete"
    snapshot = build_catalog_snapshot(
        [], kind="notes", source_requirement_id=notes["source_id"]
    )
    posts_snapshot = build_catalog_snapshot(
        [], kind="posts", source_requirement_id=posts["source_id"]
    )

    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {
                "/global/notes/": _catalog_record("/global/notes/", snapshot),
                "/posts/": _catalog_record("/posts/", posts_snapshot),
            },
            "catalog_snapshots": {
                "/global/notes/": snapshot,
                "/posts/": posts_snapshot,
            },
            "coverage_targets_by_source": {notes["source_id"]: []},
            "material_plan": {"assessments": []},
            "search_ledger": [],
        },
        contract=contract,
    )

    assert notes["selection_cardinality"]["min"] == 0
    assert result.status == "ready"
    assert result.gaps == ()


def test_required_context_discovery_requires_an_explicit_absence_disposition() -> None:
    contract = _typed_contract("Recommend the next result using relevant workspace context.")
    contract["task_profile"] = "recommendation"
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "notes",
                "query_goal": "Find any relevant plans or constraints.",
                "predicate_kind": "semantic",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "evidence_granularity": "full_text",
            },
            {
                "kind": "posts",
                "query_goal": "Find prior outputs relevant to the decision.",
                "predicate_kind": "semantic",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "evidence_granularity": "full_text",
            },
        ],
    )

    contract = _apply_decision_context_policy(contract)
    sources = {item["kind"]: item for item in contract["source_requirements"]}
    assert all(item["discovery_obligation"] == "required" for item in sources.values())
    assert all(item["selection_cardinality"]["min"] == 0 for item in sources.values())
    assert all(item["selection_cardinality"]["max"] > 0 for item in sources.values())


def test_required_evidence_with_positive_min_blocks_missing_selection() -> None:
    contract = _typed_contract("Прочитай /note/global/n1/")
    result = evaluate_sufficiency(
        state={"turn_contract": contract, "evidence_records": {}, "search_ledger": []},
        contract=contract,
    )

    assert result.status == "exhausted"
    assert {gap["kind"] for gap in result.gaps} >= {
        "missing_discovery",
        "missing_selection",
        "missing_evidence",
    }
    assert all(gap["blocks_ready"] is True for gap in result.gaps)

    ready = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {"/note/global/n1/": _note_record("n1")},
            "search_ledger": [],
        },
        contract=contract,
    )
    assert ready.status == "ready"


def test_reassessment_can_discharge_redundant_corpus_evidence_but_not_discovery() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Какие два корневых объекта предусмотрены?"),
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "notes", "evidence_granularity": "full_text"},
            {"kind": "posts", "evidence_granularity": "full_text"},
        ],
    )
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")
    note = _note_record("n1")
    post_snapshot = build_catalog_snapshot(
        [{"id": "p1", "title": "Nearby post"}],
        kind="posts",
        source_requirement_id=posts["source_id"],
    )

    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {
                "/note/global/n1/": note,
                "/posts/": _catalog_record("/posts/", post_snapshot),
            },
            "catalog_snapshots": {"/posts/": post_snapshot},
            "material_plan": {
                "baseline_discharged_source_ids": [posts["source_id"]],
                "assessments": [{"ref": "note:n1", "relevance": "direct"}],
            },
            "search_ledger": [],
        },
        contract=contract,
    )

    assert result.status == "ready"
    assert notes["source_id"] in result.satisfied_requirements
    assert posts["source_id"] in result.satisfied_requirements
    assert not any(gap["source_id"] == posts["source_id"] for gap in result.gaps)


def test_structural_property_requires_catalog_property_and_aggregate() -> None:
    contract = _typed_contract("Сколько заметок с изображениями?")
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    incomplete = build_catalog_snapshot(
        [{"id": "legacy", "title": "Legacy"}],
        kind="notes",
        source_requirement_id=notes["source_id"],
    )
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {"/global/notes/": _catalog_record("/global/notes/", incomplete)},
            "catalog_snapshots": {"/global/notes/": incomplete},
            "search_ledger": [],
        },
        contract=contract,
    )

    gaps = {gap["required"]: gap for gap in result.gaps}
    assert result.status == "follow_up_allowed"
    assert gaps["notes.has_images"]["kind"] == "missing_property"
    assert gaps["notes.has_images"]["evidence_present"] == "catalog_without_property"
    assert gaps["notes.has_images"]["allowed_actions"] == [
        "structural_aggregate",
        "open_notes",
    ]

    complete = build_catalog_snapshot(
        [
            {"id": "empty", "title": "Empty", "files": []},
            {
                "id": "image",
                "title": "Image",
                "files": [{"id": "i1", "type": "image/png"}],
            },
        ],
        kind="notes",
        source_requirement_id=notes["source_id"],
    )
    ready = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {"/global/notes/": _catalog_record("/global/notes/", complete)},
            "catalog_snapshots": {"/global/notes/": complete},
            "search_ledger": [],
        },
        contract=contract,
    )
    assert ready.status == "ready"
    assert ready.decision_code == "ALL_TYPED_REQUIREMENTS_SATISFIED"


def test_complete_semantic_source_requires_assessment_not_selection_of_every_ref() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=[],
        classifier_requires_evidence=False,
    )
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")
    notes["coverage"] = "complete"
    snapshot = build_catalog_snapshot(
        [
            {"id": "n1", "title": "One", "files": []},
            {"id": "n2", "title": "Two", "files": []},
        ],
        kind="notes",
        source_requirement_id=notes["source_id"],
    )
    posts_snapshot = build_catalog_snapshot(
        [], kind="posts", source_requirement_id=posts["source_id"]
    )
    base = {
        "turn_contract": contract,
        "evidence_records": {
            "/global/notes/": _catalog_record("/global/notes/", snapshot),
            "/posts/": _catalog_record("/posts/", posts_snapshot),
        },
        "catalog_snapshots": {
            "/global/notes/": snapshot,
            "/posts/": posts_snapshot,
        },
        "coverage_targets_by_source": {notes["source_id"]: ["note:n1", "note:n2"]},
        "search_ledger": [],
    }

    partial = evaluate_sufficiency(
        state={**base, "material_plan": {"assessments": [{"ref": "note:n1", "relevance": "irrelevant"}]}},
        contract=contract,
    )
    assert any(gap["kind"] == "incomplete_assessment" for gap in partial.gaps)

    ready = evaluate_sufficiency(
        state={
            **base,
            "material_plan": {
                "assessments": [
                    {"ref": "note:n1", "relevance": "irrelevant"},
                    {"ref": "note:n2", "relevance": "irrelevant"},
                ]
            },
        },
        contract=contract,
    )
    assert ready.status == "ready"
    assert ready.evidence_ids == ("/global/notes/", "/posts/")
    assert all("/note/" not in evidence_id for evidence_id in ready.evidence_ids)


def test_v3_selector_validation_uses_cardinality_and_never_forces_complete_selection() -> None:
    contract = _typed_contract("Какие заметки про запуск?")
    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    notes["coverage"] = "complete"
    candidates = [
        {"ref": "note:n1", "source_requirement_id": notes["source_id"]},
        {"ref": "note:n2", "source_requirement_id": notes["source_id"]},
    ]
    empty = LegacyContextSelectorDecision(selections=())

    assert _selector_decision_is_valid(
        empty,
        candidates=candidates,
        contract=contract,
        material_plan={},
    )
    assessments = [
        {"ref": "note:n1", "relevance": "irrelevant", "resolution": "card"},
        {"ref": "note:n2", "relevance": "irrelevant", "resolution": "card"},
    ]
    assert _apply_complete_source_policy(
        assessments,
        candidates=candidates,
        contract=contract,
    ) == assessments


def test_required_fidelity_is_a_typed_blocker() -> None:
    contract = _typed_contract("Прочитай /note/global/n1/")
    card = _note_record("n1")
    card["kind"] = "semantic_card"
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {"/note/global/n1/": card},
            "search_ledger": [],
        },
        contract=contract,
    )

    assert result.status == "exhausted"
    assert any(gap["kind"] == "fidelity_mismatch" for gap in result.gaps)


def test_parent_relation_remains_locator_metadata_only() -> None:
    contract = _typed_contract("Прочитай /note/post/parent-post/note-1/")
    target = contract["target_contract"]["targets"][0]

    assert target["parent_post_id"] == "parent-post"
    assert [source["kind"] for source in contract["source_requirements"]] == ["notes"]
    assert all(item["subject"] != "posts" for item in contract["evidence_requirements"])


def test_v2_checkpoint_adapter_preserves_strategy_and_serializes_typed_gaps() -> None:
    legacy = build_turn_contract(
        user_text="Прочитай /note/global/checkpoint-note/",
        history=[],
        scope="global",
    )
    normalized = normalize_turn_contract(json.loads(json.dumps(legacy)))
    old_source = legacy["source_requirements"][0]
    new_source = normalized["source_requirements"][0]

    assert normalized["schema"] == TYPED_TURN_CONTRACT_SCHEMA
    assert normalized["version"] == 3
    assert source_evidence_required(old_source) == source_evidence_required(new_source)
    assert source_selection_cardinality(old_source) == source_selection_cardinality(new_source)
    assert source_required_fidelity(old_source) == source_required_fidelity(new_source)
    assert not {"required", "min_evidence", "evidence_granularity"}.intersection(new_source)

    result = evaluate_sufficiency(
        state={"turn_contract": normalized, "evidence_records": {}, "search_ledger": []},
        contract=normalized,
    )
    checkpoint = json.loads(json.dumps({"turn_contract": normalized, "sufficiency": result.to_dict()}))
    assert checkpoint["sufficiency"]["gaps"]
    assert all(gap["schema"] == "workspace.evidence-gap/v1" for gap in checkpoint["sufficiency"]["gaps"])
