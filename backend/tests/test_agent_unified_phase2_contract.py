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
    WORKSPACE_SYSTEM,
    _apply_classifier_source_policy,
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
                "statuses": ["published"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 5,
                "evidence_granularity": "full_text",
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
    assert 'statuses=["published"]' in WORKSPACE_SYSTEM
    assert "Источники должны затем сопоставляться по смыслу" in WORKSPACE_SYSTEM
    assert "Это семантическое выявление зависимостей, а не keyword routing" in WORKSPACE_SYSTEM
    assert "Про что написать следующий пост" not in WORKSPACE_SYSTEM


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
                "statuses": ["completed", "published", "removed"],
                "order_by": "position",
                "order_direction": "desc",
                "candidate_limit": 4,
                "evidence_granularity": "semantic_card",
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
