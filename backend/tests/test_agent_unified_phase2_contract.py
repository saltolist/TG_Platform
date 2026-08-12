"""Unified integrity phase-2 typed obligation and gap tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.catalog import build_catalog_snapshot
from app.services.agent.research.graph import (
    _apply_complete_source_policy,
    _decision_answer_obligation_registry,
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
    _ORDERED_DECISION_HISTORY_OBLIGATION,
    _ORDERED_DECISION_HISTORY_QUERY_GOAL,
    _RECOMMENDATION_CANDIDATE_PLAN_OBLIGATION,
    WORKSPACE_SYSTEM,
    _apply_classifier_answer_obligations,
    _apply_classifier_answer_shape,
    _apply_classifier_dependency_gate,
    _apply_inventory_context_policy,
    _apply_classifier_source_policy,
    _apply_decision_context_policy,
    _classifier_contract_coherence_errors,
    _explicit_inventory_cardinality,
    _materialize_classifier_turn_contract,
    _planner_query_obligation_specs,
    _resolve_inventory_unit,
    _semantic_classifier_delta,
    _workspace_classifier_transport,
)
from app.services.ai.providers import ChatCompletionCapability


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


def test_compact_budget_reserves_opened_evidence_reassessment_window() -> None:
    contract = _typed_contract("Explain how the product workflow works.")

    assert contract["execution_mode"] == "compact"
    budgets = contract["budgets"]
    assert budgets["bootstrap_deadline_ms"] == 35_000
    assert budgets["soft_deadline_ms"] == 45_000
    assert budgets["hard_deadline_ms"] == 120_000
    assert (
        budgets["bootstrap_deadline_ms"]
        < budgets["soft_deadline_ms"]
        < budgets["hard_deadline_ms"]
    )


def test_workspace_classifier_uses_json_mode_only_when_provider_advertises_it() -> None:
    json_provider = SimpleNamespace(
        chat_capabilities=(
            ChatCompletionCapability.STRICT_JSON_SCHEMA,
            ChatCompletionCapability.JSON_MODE,
            ChatCompletionCapability.PLAIN,
        )
    )

    assert (
        _workspace_classifier_transport(json_provider)
        == ChatCompletionCapability.JSON_MODE
    )
    assert (
        _workspace_classifier_transport(json_provider, typed_read=True)
        == ChatCompletionCapability.STRICT_JSON_SCHEMA
    )
    assert _workspace_classifier_transport(object()) == ChatCompletionCapability.PLAIN


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
        {
            "kind": "inventory",
            "expected_member_count": 6,
            "inventory_unit": "value",
        },
    )

    assert shaped["answer_shape"] == {
        "kind": "inventory",
        "expected_member_count": 6,
        "inventory_unit": "value",
    }
    assert _apply_classifier_answer_shape(
        shaped,
        {"kind": "scalar", "expected_member_count": 6},
    )["answer_shape"] == {
        "kind": "scalar",
        "expected_member_count": None,
        "inventory_unit": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "unit"),
    [
        ("Which five posts contain images?", "record"),
        ("Which five functions are planned for the series?", "value"),
    ],
)
async def test_inventory_unit_is_resolved_before_discovery(
    question: str, unit: str
) -> None:
    payload = json.dumps({"v": 1, "inventory_unit": unit, "done": True})
    call = {
        "type": "read",
        "selection_mode": "member_inventory",
        "answer_shape": {
            "kind": "inventory",
            "expected_member_count": 5,
            "inventory_unit": "record" if unit == "value" else "value",
        },
        "answer_obligations": [question],
    }
    spec = SimpleNamespace(
        name="OpenAI",
        chat_capabilities=(ChatCompletionCapability.STRICT_JSON_SCHEMA,),
    )

    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=payload,
    ) as resolver:
        resolved = await _resolve_inventory_unit(
            SimpleNamespace(),
            call=call,
            user_text=question,
            spec=spec,
            model="selected-model",
            api_key="test-key",
            timeout_s=5.0,
        )

    assert resolved["answer_shape"]["inventory_unit"] == unit
    assert resolver.await_args.kwargs["output_json_schema"]["properties"][
        "inventory_unit"
    ]["enum"] == ["record", "value"]


def test_classifier_materializes_source_neutral_atomic_answer_obligations() -> None:
    contract = _apply_classifier_answer_obligations(
        _typed_contract("Map each requested mechanism to its workflow problem."),
        [
            "context retrieval solves missing context",
            "one workspace removes service switching",
            "Telegram synchronization closes the publishing loop",
            "One workspace removes service switching",
        ],
    )

    assert contract["answer_obligations"] == [
        {
            "obligation_id": "answer:0",
            "description": "context retrieval solves missing context",
        },
        {
            "obligation_id": "answer:1",
            "description": "one workspace removes service switching",
        },
        {
            "obligation_id": "answer:2",
            "description": "Telegram synchronization closes the publishing loop",
        },
    ]
    assert _decision_answer_obligation_registry(contract) == (
        (
            "answer:0",
            {
                "operator": "exists",
                "property": "context retrieval solves missing context",
                "claim_modality": "descriptive",
            },
        ),
        (
            "answer:1",
            {
                "operator": "exists",
                "property": "one workspace removes service switching",
                "claim_modality": "descriptive",
            },
        ),
        (
            "answer:2",
            {
                "operator": "exists",
                "property": "Telegram synchronization closes the publishing loop",
                "claim_modality": "descriptive",
            },
        ),
    )


def test_planner_obligation_specs_preserve_only_valid_semantic_origins() -> None:
    assert _planner_query_obligation_specs(
        [
            {
                "description": "explicit future editorial plan",
                "origin": "candidate_plan",
            },
            {
                "description": "bounded published state",
                "origin": "decision_history",
            },
            {
                "description": "ordinary workspace fact",
                "origin": "candidate-selected-origin",
            },
            "legacy atomic premise",
        ]
    ) == (
        ("explicit future editorial plan", "candidate_plan"),
        ("bounded published state", "decision_history"),
        ("legacy atomic premise", ""),
    )


def test_classifier_preserves_typed_origin_without_inventing_one_for_legacy() -> None:
    contract = _apply_classifier_answer_obligations(
        _typed_contract("Recommend the next artifact from workspace state."),
        [
            {
                "description": "explicit committed candidate for the next artifact",
                "origin": "candidate_plan",
            },
            {
                "description": "untrusted origin cannot affect classification",
                "origin": "candidate-selected-origin",
            },
            "legacy fact",
        ],
    )

    assert contract["answer_obligations"] == [
        {
            "obligation_id": "answer:0",
            "description": "explicit committed candidate for the next artifact",
            "origin": "candidate_plan",
        },
        {
            "obligation_id": "answer:1",
            "description": "untrusted origin cannot affect classification",
        },
        {
            "obligation_id": "answer:2",
            "description": "legacy fact",
        },
    ]


def test_typed_source_descriptors_bound_bare_required_source_summary() -> None:
    contract = _apply_classifier_source_policy(
        _typed_contract("Explain the relationship between notes and posts."),
        required_sources=["notes", "posts", "attachments", "analytics"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "notes", "query_goal": "Find the structural premise."},
            {"kind": "posts", "query_goal": "Find the workflow premise."},
        ],
    )
    required_kinds = {
        source["kind"]
        for source in contract["source_requirements"]
        if source_evidence_required(source)
    }

    assert required_kinds == {"notes", "posts"}


def test_unified_classifier_delta_preserves_planner_ir_while_policy_fields_drift() -> None:
    question = "Как заметки связаны с постами и что из этого следует?"
    contract = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    variant_a = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "answer_obligations": [
                "Широкая переформулировка всей темы",
            ],
            "required_sources": ["notes", "posts", "attachments"],
            "answer_shape": {"kind": "inventory", "expected_member_count": 17},
            "source_requirements": [
                {
                    "kind": "notes",
                    "coverage": "complete",
                    "statuses": ["published"],
                    "evidence_granularity": "full_text",
                },
                {
                    "kind": "posts",
                    "coverage": "relevant",
                    "discovery_mode": "catalog_window",
                    "candidate_limit": 2,
                },
            ],
        },
        user_text=question,
    )
    variant_b = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "answer_obligations": [
                "Связь заметок и постов",
                "Следствие этой связи",
            ],
            "required_sources": ["posts"],
            "answer_shape": {"kind": "inventory", "expected_member_count": 17},
            "source_requirements": [
                {
                    "kind": "posts",
                    "coverage": "relevant",
                    "statuses": ["draft", "scheduled"],
                    "evidence_granularity": "catalog",
                },
                {"kind": "notes", "coverage": "complete"},
                {"kind": "attachments", "coverage": "complete"},
            ],
        },
        user_text=question,
    )

    assert {
        key: value
        for key, value in variant_a.items()
        if key != "answer_obligations"
    } == {
        key: value
        for key, value in variant_b.items()
        if key != "answer_obligations"
    }
    assert variant_a["required_sources"] == ["notes", "posts"]
    assert [item["kind"] for item in variant_a["source_requirements"]] == ["notes", "posts"]
    assert variant_a["task_profile"] == "workspace_synthesis"
    assert variant_a["answer_shape"] == {
        "kind": "inventory",
        "expected_member_count": 17,
        "inventory_unit": None,
    }
    assert [item["description"] for item in variant_a["answer_obligations"]] == [
        "Широкая переформулировка всей темы",
    ]
    assert [item["description"] for item in variant_b["answer_obligations"]] == [
        "Связь заметок и постов",
        "Следствие этой связи",
    ]
    materialized_a = _materialize_classifier_turn_contract(
        contract,
        variant_a,
        classified_type="read",
    )
    materialized_b = _materialize_classifier_turn_contract(
        contract,
        variant_b,
        classified_type="read",
    )
    assert {
        key: value
        for key, value in materialized_a.items()
        if key != "answer_obligations"
    } == {
        key: value
        for key, value in materialized_b.items()
        if key != "answer_obligations"
    }


def test_atomic_obligations_keep_reporting_preamble_with_its_claim() -> None:
    question = (
        "The materials say, that the agent knows the channel, but how does it "
        "avoid loading the full archive?"
    )
    contract = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "required_sources": ["notes", "posts"],
        },
        user_text=question,
    )

    descriptions = [
        item["description"] for item in delta["answer_obligations"]
    ]
    assert descriptions[0] == (
        "The materials say, that the agent knows the channel"
    )
    assert "The materials say" not in descriptions


def test_atomic_obligations_split_reporting_claim_and_coordinated_workflow_stages() -> None:
    query = (
        "В материалах сказано, что AI знает весь канал, но при этом не загружает "
        "весь архив. Есть ли здесь противоречие и как это устроено на практике?"
    )
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        contract,
        {"type": "read", "task_profile": "workspace_synthesis"},
        user_text=query,
    )
    descriptions = [item["description"] for item in delta["answer_obligations"]]
    assert delta["selection_mode"] == "cross_record_comparison"
    assert descriptions == [
        "В материалах сказано, что AI знает весь канал",
        "но при этом не загружает весь архив. Есть ли здесь противоречие "
        "[referent: В материалах сказано, что AI знает весь канал]",
        "как это устроено на практике [referent: В материалах сказано, что AI знает "
        "весь канал; но при этом не загружает весь архив. Есть ли здесь противоречие]",
    ]

    workflow_query = "Как подготовить и опубликовать пост без переключения между сервисами?"
    workflow_contract = build_turn_contract(
        user_text=workflow_query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    workflow_delta = _semantic_classifier_delta(
        workflow_contract,
        {"type": "read", "task_profile": "workspace_synthesis"},
        user_text=workflow_query,
    )
    assert [item["description"] for item in workflow_delta["answer_obligations"]] == [
        "Как подготовить пост без переключения между сервисами",
        "Как опубликовать пост без переключения между сервисами",
    ]

    enabling_query = (
        "Собери сквозной рабочий процесс автора: как подготовить и опубликовать пост "
        "без переключения между сервисами и какие возможности платформы это обеспечивают?"
    )
    enabling_contract = build_turn_contract(
        user_text=enabling_query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    enabling_delta = _semantic_classifier_delta(
        enabling_contract,
        {"type": "read", "task_profile": "workspace_synthesis"},
        user_text=enabling_query,
    )
    assert [item["description"] for item in enabling_delta["answer_obligations"]] == [
        "как подготовить пост без переключения между сервисами",
        "как опубликовать пост без переключения между сервисами",
        "какие возможности платформы это обеспечивают [referent: как подготовить пост "
        "без переключения между сервисами; как опубликовать пост без переключения "
        "между сервисами]",
    ]


def test_invalid_contradiction_planner_shape_falls_back_to_three_evidence_premises() -> None:
    query = (
        "В материалах сказано, что AI знает весь канал, но при этом не загружает "
        "весь архив. Есть ли здесь противоречие и как это устроено на практике?"
    )
    base = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "cross_record_comparison",
            "answer_obligations": [
                "есть ли противоречие",
                "как это устроено на практике",
            ],
            "required_sources": ["notes", "posts"],
        },
        user_text=query,
    )

    descriptions = [item["description"] for item in delta["answer_obligations"]]
    assert len(descriptions) == 3
    assert "AI знает весь канал" in descriptions[0]
    assert "не загружает весь архив" in descriptions[1]
    assert "как это устроено" in descriptions[2]


def test_record_mode_keeps_relation_self_contained_but_allows_multiple_rows() -> None:
    query = "Как в TG Platform связаны структура контента и действия автора внутри платформы?"
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "required_sources": ["notes"],
        },
        user_text=query,
    )

    assert delta["selection_mode"] == "composition"
    assert [item["description"] for item in delta["answer_obligations"]] == [
        "Как в TG Platform связаны структура контента и действия автора внутри платформы",
    ]


def test_record_mode_preserves_finite_alternative_comparison() -> None:
    query = "Из двух вариантов какой подходит и почему не второй?"
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "required_sources": ["notes"],
        },
        user_text=query,
    )

    assert delta["selection_mode"] == "record"
    assert delta["answer_obligations"] == [
        {"description": query, "origin": "comparison_side"}
    ]


def test_finite_alternative_comparison_compiles_to_one_record_boundary() -> None:
    query = (
        "Из двух вариантов поставки какой подходит для реальной работы с каналом "
        "и своими данными, и почему не второй?"
    )
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "cross_record_comparison",
            "required_sources": ["notes"],
        },
        user_text=query,
    )

    assert delta["selection_mode"] == "record"
    assert delta["answer_obligations"] == [
        {"description": query, "origin": "comparison_side"}
    ]


def test_classifier_can_select_bounded_cross_record_comparison_without_inventory() -> None:
    query = (
        "Check whether the claims made by different records are compatible and "
        "explain their relationship."
    )
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "comparison",
            "selection_mode": "cross_record_comparison",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "coverage": "relevant"},
                {"kind": "posts", "coverage": "relevant"},
            ],
        },
        user_text=query,
    )

    assert delta["selection_mode"] == "cross_record_comparison"
    assert delta["answer_shape"]["kind"] == "freeform"
    assert all(
        source["coverage"] == "relevant"
        for source in delta["source_requirements"]
    )


def test_unqualified_workspace_read_preserves_notes_and_posts_discovery() -> None:
    question = "Какие два типа корневых объектов есть в пространственной модели TG Platform?"
    contract = _typed_contract(question)
    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "required_sources": ["posts"],
            "source_requirements": [{"kind": "posts", "coverage": "relevant"}],
        },
        user_text=question,
    )

    assert delta["required_sources"] == []
    assert [item["kind"] for item in delta["source_requirements"]] == [
        "notes",
        "posts",
    ]
    assert delta["_runtime_source_neutral_discovery"] is True
    materialized = _materialize_classifier_turn_contract(
        contract, delta, classified_type="read"
    )
    sources = {item["kind"]: item for item in materialized["source_requirements"]}
    assert sources["notes"]["discovery_obligation"] == "required"
    assert sources["posts"]["discovery_obligation"] == "required"
    assert sources["notes"]["evidence_obligation"] == "optional"
    assert sources["posts"]["evidence_obligation"] == "optional"
    assert materialized["membership_source_scope"] == "source_neutral"


def test_unqualified_read_infers_source_neutral_membership_without_delta_marker() -> None:
    question = "Какие пять ключевых функций TG Platform запланированы для серии?"
    contract = _typed_contract(question)

    materialized = _materialize_classifier_turn_contract(
        contract,
        {
            "type": "read",
            "required_sources": ["posts"],
            "source_requirements": [
                {"kind": "posts", "coverage": "relevant"}
            ],
        },
        classified_type="read",
        user_text=question,
    )

    assert materialized["membership_source_scope"] == "source_neutral"


def test_value_inventory_membership_is_not_restricted_to_named_record_source() -> None:
    question = "Какие пять функций запланированы для серии постов?"
    contract = _typed_contract(question)

    materialized = _materialize_classifier_turn_contract(
        contract,
        {
            "type": "read",
            "answer_shape": {
                "kind": "inventory",
                "inventory_unit": "value",
                "expected_member_count": 5,
            },
            "required_sources": ["posts"],
            "source_requirements": [
                {"kind": "posts", "coverage": "complete"}
            ],
        },
        classified_type="read",
        user_text=question,
    )

    assert materialized["membership_source_scope"] == "source_neutral"


def test_explicit_value_count_is_a_deterministic_query_ir_boundary() -> None:
    question = "Какие пять ключевых функций TG Platform запланированы для серии постов?"
    contract = _typed_contract(question)

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "answer_shape": {"kind": "scalar"},
            "required_sources": ["posts"],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        contract,
        delta,
        classified_type="read",
        user_text=question,
    )

    assert materialized["answer_shape"] == {
        "kind": "inventory",
        "expected_member_count": 5,
        "inventory_unit": "value",
    }
    assert materialized["membership_source_scope"] == "source_neutral"


def test_composition_read_keeps_both_corpora_when_query_names_only_posts() -> None:
    question = "Как в TG Platform связаны структура контента и действия автора внутри платформы?"
    contract = _typed_contract(question)
    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "composition",
            "required_sources": ["posts"],
            "source_requirements": [{"kind": "posts", "coverage": "relevant"}],
        },
        user_text=question,
    )

    assert delta["required_sources"] == []
    assert [item["kind"] for item in delta["source_requirements"]] == [
        "notes",
        "posts",
    ]
    assert delta["_runtime_source_neutral_discovery"] is True


def test_classifier_cannot_expand_bounded_workflow_into_cross_record_inventory() -> None:
    query = "Explain the connected author workflow and the mechanisms that enable it."
    contract = build_turn_contract(
        user_text=query,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "cross_record_inventory",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "coverage": "relevant"},
                {"kind": "posts", "coverage": "complete"},
            ],
        },
        user_text=query,
    )

    assert delta["selection_mode"] == "composition"
    assert all(
        source["coverage"] == "relevant"
        for source in delta["source_requirements"]
    )


def test_record_membership_preserves_atomic_planner_obligations() -> None:
    question = (
        "Из двух вариантов поставки какой подходит для реальной работы с каналом "
        "и своими данными, и почему не второй?"
    )
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "answer_obligations": [
                "платформа в целом подходит для работы",
                "у платформы есть несколько возможностей",
            ],
            "required_sources": ["notes"],
            "source_requirements": [
                {"kind": "notes", "query_goal": question},
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        base,
        delta,
        classified_type="read",
    )

    assert materialized["selection_mode"] == "record"
    assert materialized["answer_obligations"] == [
        {
            "obligation_id": "answer:0",
            "description": "платформа в целом подходит для работы",
            "origin": "comparison_side",
        },
        {
            "obligation_id": "answer:1",
            "description": "у платформы есть несколько возможностей",
            "origin": "comparison_side",
        },
    ]


def test_delivery_word_does_not_turn_value_inventory_into_post_records() -> None:
    question = (
        "Какие два контура поставки предусмотрены для TG Platform и чем "
        "полноценный вариант отличается от демонстрационного?"
    )

    assert _explicit_inventory_cardinality(question) == (2, "value")


def test_topical_composition_freezes_planner_semantic_obligations() -> None:
    question = "How is content structured and what actions can the author take?"
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "composition",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "answer_obligations": [
                "How the content structure is represented",
                "Which author actions operate on that structure",
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "query_goal": question},
                {"kind": "posts", "query_goal": question},
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        base,
        delta,
        classified_type="read",
    )

    assert materialized["selection_mode"] == "composition"
    assert [item["description"] for item in materialized["answer_obligations"]] == [
        "How the content structure is represented",
        "Which author actions operate on that structure",
    ]


def test_composition_cardinality_is_compiled_from_frozen_answer_obligations() -> None:
    question = "Explain the workflow and the capabilities that enable it."
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "composition",
            "answer_obligations": ["workflow", "enabling capabilities"],
            "required_sources": ["notes"],
            "source_requirements": [
                {
                    "kind": "notes",
                    "evidence_requirements": [
                        {
                            "property": "workflow",
                            "operator": "exists",
                            "scope": "source",
                        },
                        {
                            "property": "enabling capabilities",
                            "operator": "exists",
                            "scope": "source",
                        },
                        {
                            "property": "supporting implementation detail",
                            "operator": "exists",
                            "scope": "source",
                        },
                        {
                            "property": "supporting operational detail",
                            "operator": "exists",
                            "scope": "source",
                        },
                        {
                            "property": "supporting architecture detail",
                            "operator": "exists",
                            "scope": "source",
                        },
                    ],
                }
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        base, delta, classified_type="read"
    )
    notes = next(
        source
        for source in materialized["source_requirements"]
        if source["kind"] == "notes"
    )

    assert notes["membership_cardinality"] == {"min": 0, "max": 2}
    assert notes["selection_cardinality"]["max"] > 2


def test_source_neutral_obligations_bound_composition_membership() -> None:
    question = "Build an onboarding route from four independent premises."
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "composition",
            "answer_obligations": [
                "choose the deployment contour",
                "deploy the platform",
                "understand the interface",
                "understand the spatial model",
            ],
            "required_sources": ["notes"],
            "source_requirements": [
                {
                    "kind": "notes",
                    "evidence_requirements": [
                        {
                            "property": "onboarding route",
                            "operator": "exists",
                            "scope": "source",
                        }
                    ],
                }
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        base, delta, classified_type="read"
    )
    notes = next(
        source
        for source in materialized["source_requirements"]
        if source["kind"] == "notes"
    )

    assert notes["membership_cardinality"] == {"min": 0, "max": 4}


def test_invalid_planner_obligations_fall_back_to_frozen_query_parser() -> None:
    question = "How is content structured and what actions can the author take?"
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "composition",
            "answer_obligations": [" ", {"description": "candidate-derived"}, None],
            "required_sources": ["notes", "posts"],
        },
        user_text=question,
    )

    assert [item["description"] for item in delta["answer_obligations"]] == [
        "How is content structured",
        "what actions can the author take",
    ]


def test_synthesis_operation_is_frozen_without_becoming_evidence_membership() -> None:
    question = "How are the content structure and author actions connected?"
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "composition",
            "answer_shape": {"kind": "freeform"},
            "answer_obligations": [
                {"description": "the content structure", "origin": "fact"},
                {"description": "the author actions", "origin": "fact"},
                {
                    "description": "derive how the structure enables the actions",
                    "origin": "synthesis_operation",
                },
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "query_goal": "Find structure facts."},
                {"kind": "posts", "query_goal": "Find action facts."},
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        base, delta, classified_type="read"
    )

    assert [
        item["description"] for item in materialized["answer_obligations"]
    ] == ["the content structure", "the author actions"]
    assert materialized["answer_operations"] == [
        {
            "operation_id": "operation:0",
            "description": "derive how the structure enables the actions",
            "kind": "synthesis",
            "input_obligation_ids": ["answer:0", "answer:1"],
        }
    ]


def test_planner_obligations_are_bounded_and_deduplicated_before_discovery() -> None:
    question = "Explain the workspace architecture."
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    obligations = ["  Stable premise  ", "stable premise"] + [
        f"Premise {index}" for index in range(20)
    ]
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "composition",
            "answer_obligations": obligations,
            "required_sources": ["notes", "posts"],
        },
        user_text=question,
    )

    descriptions = [item["description"] for item in delta["answer_obligations"]]
    assert len(descriptions) == 12
    assert descriptions[:2] == ["Stable premise", "Premise 0"]


def test_unified_classifier_delta_does_not_create_attachment_source_without_query_predicate() -> None:
    question = "Какие материалы подтверждают связь плана и опубликованных постов?"
    contract = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "required_sources": ["attachments", "notes"],
            "source_requirements": [
                {"kind": "attachments", "coverage": "complete"},
                {"kind": "notes", "coverage": "complete"},
            ],
        },
        user_text=question,
    )

    assert "attachments" not in delta["required_sources"]
    assert all(item["kind"] != "attachments" for item in delta["source_requirements"])


def test_unified_semantic_inventory_does_not_parse_unrelated_word_as_posts() -> None:
    question = (
        "Проверь все заметки и отдели заметки со знаниями о продукте "
        "от посторонних или тестовых материалов."
    )
    contract = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "predicate_kind": "semantic"},
                {"kind": "posts", "predicate_kind": "semantic"},
            ],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        contract,
        delta,
        classified_type="read",
    )
    notes = next(
        item for item in materialized["source_requirements"] if item["kind"] == "notes"
    )
    posts = next(
        item for item in materialized["source_requirements"] if item["kind"] == "posts"
    )

    assert delta["required_sources"] == ["notes"]
    assert delta["answer_shape"]["kind"] == "inventory"
    assert notes["predicate_kind"] == "mixed"
    assert notes["coverage"] == "complete"
    assert notes["required_fidelity"] == "semantic_card"
    assert posts["evidence_obligation"] == "optional"


def test_unified_cross_record_audit_separates_premise_from_member_inventory() -> None:
    question = (
        "Сопоставь план серии постов с опубликованными материалами: "
        "какие темы уже раскрыты и какими постами?"
    )
    contract = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "required_sources": ["posts"],
            "source_requirements": [{"kind": "posts", "coverage": "complete"}],
        },
        user_text=question,
    )
    materialized = _materialize_classifier_turn_contract(
        contract,
        delta,
        classified_type="read",
    )
    notes = next(
        item for item in materialized["source_requirements"] if item["kind"] == "notes"
    )
    posts = next(
        item for item in materialized["source_requirements"] if item["kind"] == "posts"
    )

    assert materialized["task_profile"] == "workspace_synthesis"
    assert materialized["answer_shape"]["kind"] == "inventory"
    assert notes["coverage"] == "relevant"
    assert posts["coverage"] == "complete"
    assert posts["scope"]["statuses"] == ["draft", "scheduled", "published"]
    obligations = materialized["answer_obligations"]
    assert len(obligations) == 2
    assert obligations[0]["description"].startswith(
        "premise, plan, index, or queue row"
    )
    assert obligations[1]["description"].startswith("individual result member")
    assert all(
        not item["description"].startswith("существ") for item in obligations
    )
    assert obligations[0]["source_ids"] == [notes["source_id"]]
    assert obligations[1]["source_ids"] == [posts["source_id"]]


def test_cross_record_mode_classifies_lifecycle_instead_of_prefiltering_members() -> None:
    question = (
        "Сопоставь план серии с опубликованными материалами и укажи состояние "
        "каждого совпавшего результата."
    )
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "workspace_synthesis",
            "selection_mode": "cross_record_inventory",
            "answer_shape": {"kind": "freeform", "expected_member_count": None},
            "answer_obligations": [
                "члены плана",
                "совпавшие результаты",
                "lifecycle каждого совпадения",
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "coverage": "complete"},
                {
                    "kind": "posts",
                    "coverage": "complete",
                    "statuses": ["published"],
                },
            ],
        },
        user_text=question,
    )
    contract = _materialize_classifier_turn_contract(
        base,
        delta,
        classified_type="read",
    )
    sources = {item["kind"]: item for item in contract["source_requirements"]}

    assert contract["answer_shape"]["kind"] == "freeform"
    assert contract["selection_mode"] == "cross_record_inventory"
    assert sources["notes"]["coverage"] == "complete"
    assert sources["posts"]["coverage"] == "complete"
    assert sources["posts"]["scope"]["statuses"] == [
        "draft",
        "scheduled",
        "published",
    ]
    assert sources["posts"]["required_fidelity"] == "semantic_card"
    obligations = contract["answer_obligations"]
    assert len(obligations) == 2
    assert obligations[0]["origin"] == "mapping_premise"
    assert obligations[0]["source_ids"] == [sources["notes"]["source_id"]]
    assert obligations[1]["origin"] == "mapping_member"
    assert obligations[1]["source_ids"] == [sources["posts"]["source_id"]]


def test_member_inventory_freezes_one_positive_inclusion_obligation() -> None:
    question = "List every note in the requested category; exclude test material."
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "exhaustive_inventory",
            "selection_mode": "member_inventory",
            "answer_shape": {
                "kind": "inventory",
                "inventory_unit": "record",
                "expected_member_count": None,
            },
            "answer_obligations": [
                "which record matches the requested category",
                "which record is unrelated or test material",
            ],
            "required_sources": ["notes"],
            "source_requirements": [{"kind": "notes", "coverage": "complete"}],
        },
        user_text=question,
    )

    assert delta["selection_mode"] == "member_inventory"
    assert delta["answer_obligations"] == [
        {
            "description": "which record matches the requested category",
            "origin": "member_predicate",
        }
    ]


def test_topical_record_inventory_normalizes_composition_to_member_inventory() -> None:
    question = "Which published materials confirm the requested capability?"
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )

    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "composition",
            "answer_shape": {
                "kind": "inventory",
                "inventory_unit": "record",
                "expected_member_count": None,
            },
            "answer_obligations": [
                "record confirms the requested capability",
                "record belongs to the requested lifecycle class",
            ],
            "required_sources": ["posts"],
            "source_requirements": [{"kind": "posts", "coverage": "complete"}],
        },
        user_text=question,
    )

    assert delta["selection_mode"] == "member_inventory"
    assert delta["answer_obligations"] == [
        {
            "description": "record confirms the requested capability",
            "origin": "member_predicate",
        }
    ]


def test_recommendation_ir_rejects_inventory_shape_and_observes_all_lifecycle_states() -> None:
    question = "Choose the next deliverable from the current workspace state."
    base = build_turn_contract(
        user_text=question,
        history=[],
        scope="global",
        semantic_referent_enabled=False,
        typed_requirements_enabled=True,
    )
    delta = _semantic_classifier_delta(
        base,
        {
            "type": "read",
            "task_profile": "recommendation",
            "selection_mode": "member_inventory",
            "answer_shape": {"kind": "inventory", "expected_member_count": None},
            "answer_obligations": [
                "current plan constrains the next deliverable",
                "current output state avoids duplication",
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes", "coverage": "relevant"},
                {
                    "kind": "posts",
                    "coverage": "complete",
                    "statuses": ["published"],
                },
            ],
        },
        user_text=question,
    )
    contract = _materialize_classifier_turn_contract(
        base,
        delta,
        classified_type="read",
    )
    posts = next(
        item for item in contract["source_requirements"] if item["kind"] == "posts"
    )

    assert contract["task_profile"] == "recommendation"
    assert contract["answer_shape"] == {
        "kind": "freeform",
        "expected_member_count": None,
        "inventory_unit": None,
    }
    assert contract["selection_mode"] == "composition"
    assert posts["scope"]["statuses"] == ["draft", "scheduled", "published"]
    assert posts["discovery_mode"] == "catalog_window"
    assert posts["order_dependency"] == "required"
    assert posts["order_by"] == "created_at"
    assert posts["order_direction"] == "desc"


def test_optional_evidence_preserves_preclassified_required_discovery() -> None:
    base = _typed_contract("Compare the published result with any relevant context.")
    notes = next(item for item in base["source_requirements"] if item["kind"] == "notes")
    notes["discovery_obligation"] = "required"

    contract = _apply_classifier_source_policy(
        base,
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {"kind": "posts", "query_goal": "Find the published result."}
        ],
    )
    classified_notes = next(
        item for item in contract["source_requirements"] if item["kind"] == "notes"
    )

    assert classified_notes["evidence_obligation"] == "optional"
    assert classified_notes["discovery_obligation"] == "required"


def test_inventory_policy_runs_after_answer_shape_and_exposes_required_members() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Classify every relevant note, including all lifecycle states."),
        {
            "task_profile": "workspace_synthesis",
            "requires_evidence": True,
            "required_sources": ["notes"],
            "search_query": "Classify every relevant note.",
            "answer_shape": {"kind": "inventory", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "coverage": "relevant",
                    "predicate_kind": "semantic",
                    "evidence_granularity": "catalog",
                },
            ],
        },
        classified_type="read",
    )

    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")
    assert notes["coverage"] == "complete"
    assert notes["required_fidelity"] == "semantic_card"
    assert notes["scope"]["statuses"] == []
    assert posts["evidence_obligation"] == "optional"
    assert posts["coverage"] == "relevant"
    assert _apply_inventory_context_policy({**contract, "answer_shape": {"kind": "record"}})[
        "source_requirements"
    ] == contract["source_requirements"]


def test_lifecycle_inventory_requires_posts_and_uses_compact_member_cards() -> None:
    contract = _materialize_classifier_turn_contract(
        _typed_contract("Which published materials confirm the capability?"),
        {
            "task_profile": "workspace_synthesis",
            "requires_evidence": True,
            "required_sources": ["notes"],
            "search_query": "Which published materials confirm the capability?",
            "answer_shape": {"kind": "inventory", "expected_member_count": None},
            "source_requirements": [
                {
                    "kind": "notes",
                    "coverage": "complete",
                    "predicate_kind": "semantic",
                    "evidence_granularity": "full_text",
                }
            ],
        },
        classified_type="read",
    )

    notes = next(item for item in contract["source_requirements"] if item["kind"] == "notes")
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")
    assert notes["required_fidelity"] == "semantic_card"
    assert posts["evidence_obligation"] == "required"
    assert posts["coverage"] == "complete"
    assert posts["required_fidelity"] == "semantic_card"
    assert posts["scope"]["statuses"] == []


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
    assert (
        'selection_mode":"record|composition|cross_record_comparison|member_inventory|cross_record_inventory"'
        in WORKSPACE_SYSTEM
    )
    assert "cross_record_comparison означает ограниченную проверку" in WORKSPACE_SYSTEM
    assert "cross_record_inventory означает сопоставление" in WORKSPACE_SYSTEM
    assert "положительный inclusion predicate" in WORKSPACE_SYSTEM
    assert "положительные inclusion predicates обеих сторон mapping" in WORKSPACE_SYSTEM
    assert "никогда не быть grounded_evidence" in WORKSPACE_SYSTEM
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
        "inventory_unit": None,
    }
    assert posts["budget"]["candidate_limit"] == 10
    assert posts["budget"]["deep_reads"] == 5
    assert posts["selection_cardinality"]["min"] == 0
    assert posts["selection_cardinality"]["max"] == 5
    assert posts["claim_modality"] == "descriptive"
    assert _classifier_contract_coherence_errors(result) == ()


def test_recommendation_raw_question_becomes_checkable_workspace_premise() -> None:
    question = "What should I publish next?"
    contract = _typed_contract(question)

    result = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "recommendation",
            "selection_mode": "composition",
            "answer_shape": {"kind": "freeform"},
            "answer_obligations": [question],
            "required_sources": ["notes", "posts"],
            "source_requirements": [{"kind": "notes"}, {"kind": "posts"}],
        },
        user_text=question,
    )

    obligation = result["answer_obligations"][0]["description"]
    assert obligation != question
    assert "workspace themes" in obligation
    assert question in obligation


def test_recommendation_freezes_typed_decision_premise_origins() -> None:
    question = "What should I publish next?"
    contract = _typed_contract(question)

    result = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "recommendation",
            "selection_mode": "composition",
            "answer_shape": {"kind": "freeform"},
            "answer_obligations": [
                {
                    "description": "an explicit committed candidate for a future post",
                    "origin": "candidate_plan",
                },
                {
                    "description": "an unfinished or scheduled post changes the choice",
                    "origin": "unfinished_state",
                },
                {
                    "description": "an explicit editorial constraint changes the choice",
                    "origin": "constraint_signal",
                },
                {
                    "description": "a member-shaped future candidate",
                    "origin": "member_predicate",
                },
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [{"kind": "notes"}, {"kind": "posts"}],
        },
        user_text=question,
    )

    assert [
        (item["description"], item["origin"])
        for item in result["answer_obligations"]
    ] == [
        ("an explicit committed candidate for a future post", "candidate_plan"),
        ("an unfinished or scheduled post changes the choice", "unfinished_state"),
        ("an explicit editorial constraint changes the choice", "constraint_signal"),
        ("a member-shaped future candidate", "candidate_plan"),
    ]


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


def test_record_mode_cannot_contradict_two_declared_required_corpora() -> None:
    question = "Which of the two recorded alternatives fits, and why not the other?"
    contract = _typed_contract(question)

    result = _semantic_classifier_delta(
        contract,
        {
            "type": "read",
            "task_profile": "topical_answer",
            "selection_mode": "record",
            "answer_shape": {"kind": "freeform"},
            "answer_obligations": [
                "the first alternative outcome",
                "the second alternative outcome",
            ],
            "required_sources": ["notes", "posts"],
            "source_requirements": [
                {"kind": "notes"},
                {"kind": "posts"},
            ],
        },
        user_text=question,
    )

    assert result["selection_mode"] == "cross_record_comparison"


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


def test_publish_action_does_not_narrow_semantic_search_to_published_posts() -> None:
    question = "Как подготовить и опубликовать пост без переключения между сервисами?"
    contract = _apply_classifier_source_policy(
        _typed_contract(question),
        required_sources=["posts"],
        classifier_requires_evidence=True,
        query_goal=question,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Describe preparation and publication workflow.",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "statuses": ["published"],
                "predicate_kind": "semantic",
            }
        ],
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert posts["scope"]["statuses"] == []


def test_explicit_published_record_predicate_keeps_status_filter() -> None:
    question = "Какие опубликованные материалы подтверждают двустороннюю работу?"
    contract = _apply_classifier_source_policy(
        _typed_contract(question),
        required_sources=["posts"],
        classifier_requires_evidence=True,
        query_goal=question,
        classified_source_requirements=[
            {
                "kind": "posts",
                "query_goal": "Find published evidence.",
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "statuses": ["published"],
                "predicate_kind": "semantic",
            }
        ],
    )
    posts = next(item for item in contract["source_requirements"] if item["kind"] == "posts")

    assert posts["scope"]["statuses"] == ["published"]


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
    assert [
        item
        for item in contract["answer_obligations"]
        if item.get("origin") == "candidate_plan"
    ] == [
        {
            "obligation_id": "answer:0",
            "description": _RECOMMENDATION_CANDIDATE_PLAN_OBLIGATION,
            "origin": "candidate_plan",
        }
    ]
    assert contract["answer_obligations"][-1] == {
        "obligation_id": f"answer:{len(contract['answer_obligations']) - 1}",
        "description": _ORDERED_DECISION_HISTORY_OBLIGATION,
        "origin": "ordered_decision_history",
    }


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
