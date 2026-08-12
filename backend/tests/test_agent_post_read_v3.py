from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.graph import (
    OBLIGATION_CLASSIFICATION_VERSION,
    POST_READ_LABEL_VERSION,
    _assemble_obligation_coverage_positions,
    _bound_unanchored_cross_record_edges,
    _build_card_recall_cohort,
    _candidate_retrieval_signal,
    _cross_record_inventory_row_shards,
    _decode_post_read_labels,
    _frozen_query_ir,
    _member_classification_source_ids,
    _post_read_obligation_shards,
    _post_read_label_json_schema,
    _run_precision_confirmation,
    route_research_verify,
)
from app.services.agent.research.material_plan import (
    compile_material_plan,
    empty_material_plan,
    merge_material_plan,
    normalize_candidates,
)
from app.services.agent.research.planner_decision import ContextSelectorDecision
from app.services.agent.research.selector_transport import encode_selector_transport
from app.services.ai.providers import ChatCompletionCapability


def _source(
    source_id: str,
    *,
    required: bool = True,
    maximum: int = 8,
) -> dict:
    return {
        "source_id": source_id,
        "kind": "posts" if source_id.endswith("posts") else "notes",
        "discovery_obligation": "required",
        "evidence_obligation": "required" if required else "optional",
        "selection_cardinality": {"min": 0, "max": maximum},
        "coverage": "relevant",
        "predicate_kind": "semantic",
        "required_fidelity": "full_text",
        "scope": {"mode": "corpus"},
    }


def _contract(
    *sources: dict,
    obligations: tuple[str, ...] = ("first fact", "second fact"),
    selection_mode: str = "composition",
) -> dict:
    return {
        "schema": "workspace.turn/v3",
        "version": 3,
        "task_profile": "workspace_synthesis",
        "selection_mode": selection_mode,
        "answer_shape": {"kind": "freeform"},
        "answer_obligations": [
            {"obligation_id": f"answer:{index}", "description": description}
            for index, description in enumerate(obligations)
        ],
        "source_requirements": list(sources),
    }


def _candidate(ref: str, source_id: str = "workspace-notes") -> dict:
    return {
        "ref": ref,
        "kind": ref.split(":", 1)[0],
        "title": ref,
        "selector_summary": f"Card for {ref}.",
        "selector_summary_version": 2,
        "source_revision": 1,
        "source_requirement_id": source_id,
        "source_requirement_ids": [source_id],
        "status": "active",
        "available_fidelity": ["semantic_card", "full_text"],
    }


def _opened_candidates(*rows: tuple[str, str]) -> list[dict]:
    candidates = normalize_candidates(
        [_candidate(ref, source_id) for ref, source_id in rows]
    )
    for candidate in candidates:
        candidate["opened_evidence"] = {
            "text": f"Verified full text for {candidate['ref']}.",
            "digest": "1111111111111111",
            "citation_path": f"/{candidate['ref'].replace(':', '/')}/",
            "source_revision": 1,
            "owner_verified": True,
            "status_verified": True,
            "truncated": False,
        }
    return candidates


def test_candidate_retrieval_signal_preserves_matched_rank_without_similarity() -> None:
    assert _candidate_retrieval_signal({"matched_evidence_rank": 1}) == 0.5
    assert _candidate_retrieval_signal({"matched_evidence_rank": 6}) == pytest.approx(
        1 / 7
    )
    assert _candidate_retrieval_signal(
        {"semantic_rank_score": 0.42, "matched_evidence_rank": 1}
    ) == 0.42
    assert _candidate_retrieval_signal({}) == 0.0


def test_post_read_obligation_shards_have_single_edge_owner() -> None:
    shards = _post_read_obligation_shards(6, 4)

    assert shards == ((0, 1), (2, 3), (4, 5))
    assert sorted(index for shard in shards for index in shard) == list(range(6))
    assert _post_read_obligation_shards(3, 2) == ((0, 1), (2,))
    assert _post_read_obligation_shards(2, 1) == ((0, 1),)


def test_cross_record_inventory_shards_own_each_row_once() -> None:
    candidates = _opened_candidates(
        ("note:premise-a", "workspace-notes"),
        ("note:premise-b", "workspace-notes"),
        ("post:member-a", "workspace-posts"),
        ("post:member-b", "workspace-posts"),
        ("post:member-c", "workspace-posts"),
        ("post:member-d", "workspace-posts"),
        ("post:member-e", "workspace-posts"),
    )
    notes = _source("workspace-notes")
    posts = _source("workspace-posts")
    posts["coverage"] = "complete"

    shards = _cross_record_inventory_row_shards(
        candidates=candidates,
        contract=_contract(
            notes,
            posts,
            selection_mode="cross_record_inventory",
        ),
        available_calls=4,
    )

    assert shards == (
        ((0, 1), (0, 1)),
        ((0, 1, 2, 3), (2, 3)),
        ((0, 1, 4, 5), (4, 5)),
        ((0, 1, 6), (6,)),
    )
    assert sorted(position for _context, owners in shards for position in owners) == list(
        range(len(candidates))
    )


@pytest.mark.asyncio
async def test_source_scoped_row_shards_preserve_global_indexes_and_retry_topology() -> None:
    candidates = _opened_candidates(
        ("note:premise", "workspace-notes"),
        ("post:member", "workspace-posts"),
    )
    notes = _source("workspace-notes")
    posts = _source("workspace-posts")
    posts["coverage"] = "complete"
    contract = _contract(
        notes,
        posts,
        selection_mode="cross_record_inventory",
    )
    contract["answer_obligations"][0]["source_ids"] = ["workspace-notes"]
    contract["answer_obligations"][1]["source_ids"] = ["workspace-posts"]

    async def assessment_for_shard(*_args, **kwargs):
        phase = str(kwargs["phase"])
        if ".row_shard_2" in phase and not phase.endswith(".schema_retry"):
            return "{}"
        schema = kwargs["output_json_schema"]
        label_schemas = schema["properties"]["labels"]["properties"]
        member_shard = ".row_shard_2" in phase
        labels = {}
        for key, label_schema in label_schemas.items():
            support_schema = label_schema["properties"]["support"]
            owned = int(key) == (len(label_schemas) - 1 if member_shard else 0)
            allowed = support_schema["items"]["properties"]["obligation_index"].get(
                "enum", []
            )
            labels[key] = {
                "support": [
                    {
                        "obligation_index": allowed[0],
                        "warrant_unit": 0,
                        "fit": "exact",
                        "prominence": "primary",
                    }
                ]
                if owned and allowed
                else []
            }
        return json.dumps(
            {
                "v": POST_READ_LABEL_VERSION,
                "n": schema["properties"]["n"]["const"],
                "r": schema["properties"]["r"]["const"],
                "labels": labels,
                "done": True,
            }
        )

    selector = AsyncMock(side_effect=assessment_for_shard)
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        selector,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_primary(candidates),
            material_plan=empty_material_plan(),
            selector_question="Map the plan to every matching post.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
            include_opened_recovery_pool=True,
        )

    assert deadline is False
    assert calls == 3
    assert selector.await_count == 3
    assert trace["schema_result"] == "valid"
    assert trace["post_read_shards"] == [
        {
            "obligation_indexes": [0],
            "owner_positions": [0],
            "schema_result": "valid",
        },
        {
            "obligation_indexes": [0, 1],
            "owner_positions": [1],
            "schema_result": "valid",
        },
    ]
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:premise", "post:member"}


def _mapping(candidates: list[dict], contract: dict):
    return encode_selector_transport(
        question="Explain both facts.",
        dialog_context="",
        contract=contract,
        candidates=candidates,
    ).mapping


def _assessment_payload(
    mapping,
    labels: dict[str, dict],
) -> str:
    return json.dumps(
        {
            "v": POST_READ_LABEL_VERSION,
            "n": len(mapping.candidate_refs),
            "r": mapping.registry_nonce,
            "labels": {
                position: {
                    **label,
                    "support": [
                        {
                            **edge,
                            "prominence": edge.get("prominence", "primary"),
                        }
                        for edge in label.get("support") or ()
                    ],
                }
                for position, label in labels.items()
            },
            "done": True,
        }
    )


def _primary(candidates: list[dict]) -> ContextSelectorDecision:
    return ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct",
                    "role": "answer_evidence",
                    "resolution": "full_text",
                    "confidence": 0.9,
                    "reason_code": "detailed_summary",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": source_id, "status": "selected"}
                for source_id in sorted(
                    {
                        source_id
                        for candidate in candidates
                        for source_id in candidate.get("source_requirement_ids") or ()
                    }
                )
            ],
        }
    )


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        reasoner_spec=SimpleNamespace(
            name="OpenAI",
            chat_capabilities=(ChatCompletionCapability.STRICT_JSON_SCHEMA,),
        ),
        reasoner_model="fixture-model",
        reasoner_api_key="fixture-key",
        planner_llm=None,
        embedding_backend=object(),
        llm_metrics=[],
    )


def test_post_read_v5_schema_is_row_local_and_warrant_bounded() -> None:
    candidates = _opened_candidates(
        ("note:first", "workspace-notes"),
        ("note:second", "workspace-notes"),
    )
    contract = _contract(_source("workspace-notes"))
    mapping = _mapping(candidates, contract)
    schema = _post_read_label_json_schema(
        mapping,
        (("answer:0", "answer:1"), ("answer:0", "answer:1")),
        (2, 5),
    )

    assert set(schema["properties"]) == {"v", "n", "r", "labels", "done"}
    labels = schema["properties"]["labels"]["properties"]
    assert labels["0"]["properties"]["support"]["items"]["properties"][
        "warrant_unit"
    ]["maximum"] == 1
    assert labels["1"]["properties"]["support"]["items"]["properties"][
        "warrant_unit"
    ]["maximum"] == 4
    assert labels["0"]["properties"]["support"]["items"]["properties"][
        "prominence"
    ]["enum"] == ["mention", "section", "primary"]


def test_post_read_v5_schema_enforces_row_scoped_obligations() -> None:
    candidates = _opened_candidates(
        ("note:premise", "workspace-notes"),
        ("post:member", "workspace-posts"),
        ("post:context-only", "workspace-posts"),
    )
    mapping = _mapping(
        candidates,
        _contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            selection_mode="cross_record_inventory",
        ),
    )
    schema = _post_read_label_json_schema(
        mapping,
        (("answer:0",), ("answer:1",), ()),
        (1, 1, 1),
    )
    labels = schema["properties"]["labels"]["properties"]

    assert labels["0"]["properties"]["support"]["items"]["properties"][
        "obligation_index"
    ]["enum"] == [0]
    assert labels["1"]["properties"]["support"]["items"]["properties"][
        "obligation_index"
    ]["enum"] == [1]
    assert labels["2"]["properties"]["support"]["maxItems"] == 0


def test_cross_record_placeholder_guard_retains_two_row_recall_hedges() -> None:
    candidates = _opened_candidates(
        ("note:plan", "workspace-notes"),
        ("post:real", "workspace-posts"),
        ("post:noise-a", "workspace-posts"),
        ("post:noise-b", "workspace-posts"),
        ("post:noise-c", "workspace-posts"),
    )
    candidates[2]["semantic_score"] = 0.4
    candidates[3]["semantic_score"] = 0.3
    candidates[4]["semantic_score"] = 0.2
    notes = _source("workspace-notes")
    posts = _source("workspace-posts")
    posts["coverage"] = "complete"
    contract = _contract(
        notes,
        posts,
        selection_mode="cross_record_inventory",
    )
    contract["answer_obligations"][0]["source_ids"] = ["workspace-notes"]
    contract["answer_obligations"][1]["source_ids"] = ["workspace-posts"]
    decision_obligations = (
        ("answer:0",),
        ("answer:1",),
        ("answer:1",),
        ("answer:1",),
        ("answer:1",),
    )
    edges = {(0, 0): 0, **{(position, 1): 0 for position in range(1, 5)}}

    filtered, trace = _bound_unanchored_cross_record_edges(
        candidates=candidates,
        contract=contract,
        decision_obligations=decision_obligations,
        unit_texts=(
            ("Plan topics: integrated workspace and channel-aware AI.",),
            (
                "Channel-aware AI uses the plan topics and provides an integrated "
                "workspace with enough detail to establish the mapping.",
            ),
            ("placeholder-a",),
            ("placeholder-b",),
            ("placeholder-c",),
        ),
        edges=edges,
    )

    assert set(filtered) == {(0, 0), (1, 1), (2, 1), (3, 1)}
    assert trace["retained_uncertain_positions"] == [2, 3]
    assert trace["removed_positions"] == [4]


def test_cross_record_guard_bounds_redundant_premise_proofs_per_obligation() -> None:
    candidates = _opened_candidates(
        ("note:plan-best", "workspace-notes"),
        ("note:plan-hedge", "workspace-notes"),
        ("note:plan-redundant", "workspace-notes"),
        ("post:member", "workspace-posts"),
    )
    for position, score in enumerate((0.9, 0.8, 0.7, 0.6)):
        candidates[position]["semantic_score"] = score
    notes = _source("workspace-notes")
    posts = _source("workspace-posts")
    posts["coverage"] = "complete"
    contract = _contract(
        notes,
        posts,
        selection_mode="cross_record_inventory",
    )
    contract["answer_obligations"][0]["source_ids"] = ["workspace-notes"]
    contract["answer_obligations"][1]["source_ids"] = ["workspace-posts"]

    filtered, trace = _bound_unanchored_cross_record_edges(
        candidates=candidates,
        contract=contract,
        decision_obligations=(
            ("answer:0",),
            ("answer:0",),
            ("answer:0",),
            ("answer:1",),
        ),
        unit_texts=(
            ("Plan topics alpha, beta, and gamma with complete mapping details.",),
            ("Plan topics alpha, beta, and gamma with complete mapping details.",),
            ("Plan topics alpha, beta, and gamma with complete mapping details.",),
            (
                "Alpha is developed as a complete member with enough content to "
                "establish the mapping predicate.",
            ),
        ),
        edges={(0, 0): 0, (1, 0): 0, (2, 0): 0, (3, 1): 0},
    )

    assert set(filtered) == {(0, 0), (1, 0), (3, 1)}
    assert trace["retained_premise_edges"] == [[0, 0], [1, 0]]
    assert trace["removed_premise_edges"] == [[2, 0]]


def test_cross_record_guard_preserves_roles_when_both_corpora_are_complete() -> None:
    candidates = _opened_candidates(
        ("note:premise", "workspace-notes"),
        ("post:member", "workspace-posts"),
        ("post:noise-a", "workspace-posts"),
        ("post:noise-b", "workspace-posts"),
        ("post:noise-c", "workspace-posts"),
    )
    for position, score in enumerate((0.9, 0.8, 0.4, 0.3, 0.2)):
        candidates[position]["semantic_score"] = score
    notes = _source("workspace-notes")
    posts = _source("workspace-posts")
    notes["coverage"] = "complete"
    posts["coverage"] = "complete"
    contract = _contract(notes, posts, selection_mode="cross_record_inventory")
    contract["answer_obligations"][0]["source_ids"] = ["workspace-notes"]
    contract["answer_obligations"][1]["source_ids"] = ["workspace-posts"]

    filtered, trace = _bound_unanchored_cross_record_edges(
        candidates=candidates,
        contract=contract,
        decision_obligations=(
            ("answer:0",),
            ("answer:1",),
            ("answer:1",),
            ("answer:1",),
            ("answer:1",),
        ),
        unit_texts=(
            ("Creator problems: context loss and switching between tools.",),
            (
                "The integrated workspace solves context loss and switching "
                "between tools with a complete mapped workflow.",
            ),
            ("placeholder-a",),
            ("placeholder-b",),
            ("placeholder-c",),
        ),
        edges={(0, 0): 0, **{(position, 1): 0 for position in range(1, 5)}},
    )

    assert set(filtered) == {(0, 0), (1, 1), (2, 1), (3, 1)}
    assert trace["applied"] is True
    assert trace["removed_positions"] == [4]


@pytest.mark.parametrize(
    "label",
    [
        {
            "support": [
                {"obligation_index": 0, "warrant_unit": 0, "fit": "invalid"}
            ],
        },
        {
            "support": [
                {"obligation_index": 0, "warrant_unit": 0, "fit": "exact"},
                {"obligation_index": 4, "warrant_unit": 0, "fit": "exact"},
            ],
        },
        {
            "support": [
                {"obligation_index": 0, "warrant_unit": 3, "fit": "exact"}
            ],
        },
    ],
)
def test_post_read_v5_rejects_contradictory_or_invalid_edges(label: dict) -> None:
    candidates = _opened_candidates(("note:first", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"), obligations=("first fact",)
    )
    mapping = _mapping(candidates, contract)
    raw = _assessment_payload(mapping, {"0": label})

    positions, edges, gates, errors = _decode_post_read_labels(
        raw,
        mapping=mapping,
        unit_counts=(1,),
        decision_obligations=(("answer:0",),),
    )

    assert positions is None
    assert edges == {}
    assert gates == ()
    assert errors


def test_post_read_v5_canonicalizes_duplicate_obligation_edges() -> None:
    candidates = _opened_candidates(("note:first", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"), obligations=("requested fact",)
    )
    mapping = _mapping(candidates, contract)
    raw = _assessment_payload(
        mapping,
        {
            "0": {
                "support": [
                    {"obligation_index": 0, "warrant_unit": 0, "fit": "broad"},
                    {"obligation_index": 0, "warrant_unit": 0, "fit": "exact"},
                ]
            }
        },
    )

    positions, edges, gates, errors = _decode_post_read_labels(
        raw,
        mapping=mapping,
        unit_counts=(1,),
        decision_obligations=(("answer:0",),),
    )

    assert positions == (0,)
    assert edges == {(0, 0): 0}
    assert gates[0]["support_fits"] == {"0": "exact"}
    assert gates[0]["support_prominence"] == {"0": "primary"}
    assert errors == ()


def test_post_read_v5_partial_or_broad_labels_do_not_close_obligations() -> None:
    candidates = _opened_candidates(("note:first", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"), obligations=("requested fact",)
    )
    mapping = _mapping(candidates, contract)
    raw = _assessment_payload(
        mapping,
        {
            "0": {
                "support": [
                    {
                        "obligation_index": 0,
                        "warrant_unit": 0,
                        "fit": "partial",
                    }
                ]
            }
        },
    )

    positions, edges, gates, errors = _decode_post_read_labels(
        raw,
        mapping=mapping,
        unit_counts=(1,),
        decision_obligations=(("answer:0",),),
    )

    assert positions == ()
    assert edges == {}
    assert gates[0]["complete"] is False
    assert gates[0]["support_fits"] == {"0": "partial"}
    assert errors == ()


def test_deterministic_assembler_prefers_exact_over_broad() -> None:
    candidates = _opened_candidates(
        ("note:broad", "workspace-notes"),
        ("note:exact", "workspace-notes"),
    )
    positions, _trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"), obligations=("requested fact",)
        ),
        material_plan=empty_material_plan(),
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}},
        pair_scores={(0, 0): 0.5, (1, 0): 3.0},
        include_prior_selected=False,
    )

    assert positions == (1,)


def test_post_read_assembler_preserves_confirmed_composition_union() -> None:
    candidates = _opened_candidates(
        ("note:first-proof", "workspace-notes"),
        ("note:second-proof", "workspace-notes"),
        ("note:broad-background", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"), obligations=("requested fact",)
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 2}},
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}, 2: {0: 0}},
        pair_scores={(0, 0): 3.2, (1, 0): 3.2, (2, 0): 0.5},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1)
    assert trace["membership_policy"] == "bounded_confirmed_union"
    assert trace["coverage_seed_positions"] == [0]
    assert trace["budget_evicted_positions"] == []


def test_record_keeps_bounded_self_contained_full_read_ambiguity() -> None:
    candidates = _opened_candidates(
        ("note:winner", "workspace-notes"),
        ("note:critical-alternative", "workspace-notes"),
        ("note:partial", "workspace-notes"),
        ("note:third-alternative", "workspace-notes"),
        ("note:fourth-alternative", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("chosen alternative", "reason for rejecting the other"),
            selection_mode="record",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=2,
        support={
            0: {0: 0, 1: 1},
            1: {0: 0, 1: 1},
            2: {0: 0},
            3: {0: 0, 1: 1},
            4: {0: 0, 1: 1},
        },
        pair_scores={
            (0, 0): 3.40,
            (0, 1): 3.40,
            (1, 0): 3.39,
            (1, 1): 3.39,
            (2, 0): 3.38,
            (3, 0): 3.37,
            (3, 1): 3.37,
            (4, 0): 3.36,
            (4, 1): 3.36,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 3)
    assert trace["membership_policy"] == "bounded_confirmed_union"
    assert trace["coverage_seed_positions"] == [0]
    assert trace["budget_evicted_positions"] == [4]


def test_post_read_composition_evicts_only_after_full_text_confirmation() -> None:
    candidates = _opened_candidates(
        ("note:strongest", "workspace-notes"),
        ("note:second", "workspace-notes"),
        ("note:weakest", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("requested fact",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 2}},
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}, 2: {0: 0}},
        pair_scores={(0, 0): 3.4, (1, 0): 3.3, (2, 0): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1)
    assert trace["membership_policy"] == "bounded_confirmed_union"
    assert trace["budget_evicted_positions"] == [2]


def test_member_inventory_preserves_all_confirmed_members_within_budget() -> None:
    candidates = _opened_candidates(
        ("note:first-member", "workspace-notes"),
        ("note:second-member", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("requested member category",),
            selection_mode="member_inventory",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 2}},
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}},
        pair_scores={(0, 0): 3.2, (1, 0): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1)
    assert trace["membership_policy"] == "bounded_confirmed_union"


def test_cross_record_inventory_preserves_every_confirmed_mapping_member() -> None:
    candidates = _opened_candidates(
        ("note:first-premise", "workspace-notes"),
        ("post:second-premise", "workspace-posts"),
        ("post:duplicate-second-premise", "workspace-posts"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first premise", "second premise"),
            selection_mode="cross_record_inventory",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 3}},
        obligation_count=2,
        support={0: {0: 0}, 1: {1: 0}, 2: {1: 0}},
        pair_scores={(0, 0): 3.2, (1, 1): 3.2, (2, 1): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["membership_policy"] == "bounded_confirmed_union"


def test_cross_record_comparison_preserves_distinct_confirmed_premises() -> None:
    candidates = _opened_candidates(
        ("note:first-premise", "workspace-notes"),
        ("post:second-premise", "workspace-posts"),
        ("note:mechanism", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first claim", "second claim", "mechanism"),
            selection_mode="cross_record_comparison",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 5}},
        obligation_count=3,
        support={0: {0: 0}, 1: {1: 0}, 2: {2: 0}},
        pair_scores={(0, 0): 3.2, (1, 1): 3.2, (2, 2): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["membership_policy"] == "bounded_confirmed_union"


def test_cross_record_comparison_bounds_recall_reserve_to_two_rows() -> None:
    candidates = _opened_candidates(
        ("note:first-premise", "workspace-notes"),
        ("post:second-premise", "workspace-posts"),
        ("note:mechanism", "workspace-notes"),
        ("note:redundant-a", "workspace-notes"),
        ("post:redundant-b", "workspace-posts"),
        ("post:redundant-c", "workspace-posts"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first claim", "second claim", "mechanism"),
            selection_mode="cross_record_comparison",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=3,
        support={
            0: {0: 0},
            1: {1: 0},
            2: {2: 0},
            3: {0: 0},
            4: {1: 0},
            5: {2: 0},
        },
        pair_scores={
            (0, 0): 3.4,
            (1, 1): 3.4,
            (2, 2): 3.4,
            (3, 0): 3.2,
            (4, 1): 3.2,
            (5, 2): 3.2,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2, 3, 4)
    assert trace["budget_evicted_positions"] == [5]


def test_workspace_synthesis_adds_one_contextual_row_from_missing_source() -> None:
    candidates = _opened_candidates(
        ("note:exact", "workspace-notes"),
        ("post:broad-first", "workspace-posts"),
        ("post:broad-second", "workspace-posts"),
        ("post:broad-third", "workspace-posts"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("architecture relation",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={0: {0: 0}},
        pair_scores={(0, 0): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
        contextual_support_positions=(1, 2, 3),
    )

    assert positions == (0, 1)
    assert trace["contextual_support_positions"] == [1]


def test_topical_composition_adds_only_one_contextual_row_per_missing_source() -> None:
    candidates = _opened_candidates(
        ("note:exact", "workspace-notes"),
        ("post:partial-first", "workspace-posts"),
        ("post:partial-second", "workspace-posts"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("requested capability",),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={0: {0: 0}},
        pair_scores={(0, 0): 3.4},
        include_prior_selected=False,
        preserve_confirmed=True,
        contextual_support_positions=(1, 2),
    )

    assert positions == (0, 1)
    assert trace["contextual_support_positions"] == [1]


def test_contextual_and_false_negative_rows_share_uncertainty_budget() -> None:
    candidates = _opened_candidates(
        ("note:exact", "workspace-notes"),
        ("post:partial", "workspace-posts"),
        ("note:near-empty-label", "workspace-notes"),
        ("post:second-near-empty-label", "workspace-posts"),
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    ranks = {
        "note:exact": 0.70,
        "post:partial": 0.69,
        "note:near-empty-label": 0.68,
        "post:second-near-empty-label": 0.67,
    }
    for ref, rank in ranks.items():
        candidates[position_by_ref[ref]]["semantic_rank_score"] = rank
    exact_position = position_by_ref["note:exact"]
    contextual_position = position_by_ref["post:partial"]
    reserve_position = position_by_ref["note:near-empty-label"]

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("requested route",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={exact_position: {0: 0}},
        pair_scores={(exact_position, 0): 3.4},
        include_prior_selected=False,
        preserve_confirmed=True,
        contextual_support_positions=(contextual_position,),
    )

    assert positions == tuple(sorted((exact_position, contextual_position, reserve_position)))
    assert trace["contextual_support_positions"] == [contextual_position]
    assert trace["recall_reserve_positions"] == [reserve_position]
    assert trace["uncertainty_budget_used"] == 2


def test_optional_source_exact_alternatives_saturate_uncertainty_budget() -> None:
    candidates = _opened_candidates(
        ("note:proof-cover", "workspace-notes"),
        ("note:exact-alternative-a", "workspace-notes"),
        ("note:exact-alternative-b", "workspace-notes"),
        ("note:exact-alternative-c", "workspace-notes"),
        ("post:partial-or-empty-label", "workspace-posts"),
    )
    for position, candidate in enumerate(candidates):
        candidate["semantic_rank_score"] = 0.70 - position * 0.01

    notes = _source("workspace-notes", required=False)
    notes["membership_cardinality"] = {"min": 0, "max": 8}

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            notes,
            _source("workspace-posts", required=False),
            obligations=("requested route",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={position: {0: 0} for position in range(4)},
        pair_scores={(position, 0): 3.40 - position * 0.01 for position in range(4)},
        include_prior_selected=False,
        preserve_confirmed=True,
        contextual_support_positions=(4,),
    )

    assert positions == (0, 1, 2)
    assert trace["optional_confirmed_ambiguity_positions"] == [1, 2]
    assert trace["budget_evicted_positions"] == [3, 4]
    assert trace["confirmed_membership_overflow_positions"] == []
    assert trace["contextual_support_positions"] == []
    assert trace["recall_reserve_positions"] == []
    assert trace["uncertainty_budget_used"] == 2


def test_required_source_exact_alternatives_share_uncertainty_budget() -> None:
    candidates = _opened_candidates(
        ("note:proof-cover", "workspace-notes"),
        ("note:exact-alternative-a", "workspace-notes"),
        ("note:exact-alternative-b", "workspace-notes"),
        ("note:exact-alternative-c", "workspace-notes"),
        ("post:empty-label", "workspace-posts"),
    )
    for position, candidate in enumerate(candidates):
        candidate["semantic_rank_score"] = 0.70 - position * 0.01

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("requested route",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={position: {0: 0} for position in range(4)},
        pair_scores={
            (position, 0): 3.40 - position * 0.01
            for position in range(4)
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["optional_confirmed_ambiguity_positions"] == [1, 2]
    assert trace["recall_reserve_positions"] == []
    assert trace["uncertainty_budget_used"] == 2


def test_composition_allows_one_exact_confirmation_past_inferred_source_target() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("note:first-alternative", "workspace-notes"),
        ("note:boundary-proof", "workspace-notes"),
        ("note:second-boundary-proof", "workspace-notes"),
    )
    notes = _source("workspace-notes", maximum=6)
    notes["membership_cardinality"] = {"min": 0, "max": 2}

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            notes,
            obligations=("workflow", "platform capabilities"),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=2,
        support={position: {0: 0, 1: 0} for position in range(4)},
        pair_scores={
            (position, obligation): 3.40 - position * 0.01
            for position in range(4)
            for obligation in range(2)
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["confirmed_membership_overflow_positions"] == [2]
    assert trace["budget_evicted_positions"] == [3]


def test_workspace_synthesis_bounds_confirmed_union_to_uncertainty_budget() -> None:
    candidates = _opened_candidates(
        *(
            (f"note:proof-{position}", "workspace-notes")
            for position in range(7)
        )
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("first", "second", "third", "fourth"),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=4,
        support={position: {0: 0, 1: 0, 2: 0, 3: 0} for position in range(7)},
        pair_scores={
            (position, obligation): 3.4 - position * 0.01
            for position in range(7)
            for obligation in range(4)
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["budget_evicted_positions"] == [3, 4, 5, 6]


def test_value_inventory_strength_expansion_shares_recall_reserve_budget() -> None:
    candidates = _opened_candidates(
        ("note:critical-four-values", "workspace-notes"),
        ("note:broad-five-values", "workspace-notes"),
        ("note:reserve-a", "workspace-notes"),
        ("note:reserve-b", "workspace-notes"),
    )
    for position, candidate in enumerate(candidates):
        candidate["semantic_rank_score"] = 0.80 - position * 0.01
    contract = _contract(
        _source("workspace-notes"),
        obligations=("first", "second", "third", "fourth", "fifth"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"
    contract["answer_shape"] = {
        "kind": "inventory",
        "inventory_unit": "value",
        "expected_member_count": 5,
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=5,
        support={
            0: {0: 0, 1: 0, 2: 0, 4: 0},
            1: {0: 0, 1: 0, 2: 0, 3: 0, 4: 0},
        },
        pair_scores={
            **{
                (0, obligation): 3.40
                for obligation in (0, 1, 2, 4)
            },
            **{(1, obligation): 3.20 for obligation in range(5)},
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["coverage_seed_positions"] == [0, 1]
    assert trace["minimum_complete_cover_size"] == 1
    assert trace["coverage_strength_expansion_count"] == 1
    assert trace["recall_reserve_positions"] == [2]
    assert trace["uncertainty_budget_used"] == 2


def test_composition_strength_expansion_shares_context_and_recall_budget() -> None:
    candidates = _opened_candidates(
        ("note:self-contained", "workspace-notes"),
        ("note:strong-specialist", "workspace-notes"),
        ("post:contextual", "workspace-posts"),
        ("post:recall-reserve", "workspace-posts"),
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    self_contained = position_by_ref["note:self-contained"]
    specialist = position_by_ref["note:strong-specialist"]
    contextual = position_by_ref["post:contextual"]
    recall_reserve = position_by_ref["post:recall-reserve"]
    candidates[recall_reserve]["semantic_rank_score"] = 0.80

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first premise", "second premise"),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=2,
        support={
            self_contained: {0: 0, 1: 0},
            specialist: {0: 0},
        },
        pair_scores={
            (self_contained, 0): 3.20,
            (self_contained, 1): 3.20,
            (specialist, 0): 3.40,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
        contextual_support_positions=(contextual,),
    )

    assert positions == tuple(sorted((self_contained, specialist, contextual)))
    assert trace["minimum_complete_cover_size"] == 1
    assert trace["coverage_strength_expansion_count"] == 1
    assert trace["contextual_support_positions"] == [contextual]
    assert trace["recall_reserve_positions"] == []
    assert recall_reserve in trace["budget_evicted_positions"]
    assert trace["uncertainty_budget_used"] == 2


def test_integrated_synthesis_preserves_backbone_and_rank_one_frontier() -> None:
    candidates = _opened_candidates(
        ("note:integration-backbone", "workspace-notes"),
        ("note:first-specialist", "workspace-notes"),
        ("note:second-specialist", "workspace-notes"),
        ("post:third-specialist", "workspace-posts"),
        ("post:retrieval-frontier", "workspace-posts"),
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    backbone = position_by_ref["note:integration-backbone"]
    first = position_by_ref["note:first-specialist"]
    second = position_by_ref["note:second-specialist"]
    third = position_by_ref["post:third-specialist"]
    frontier = position_by_ref["post:retrieval-frontier"]
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first component", "second component", "third component"),
        selection_mode="composition",
    )
    contract["task_profile"] = "workspace_synthesis"
    contract["answer_operations"] = [
        {
            "kind": "synthesis",
            "input_obligation_ids": ["answer:0", "answer:1", "answer:2"],
        }
    ]
    recall_profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 3,
        "rows": {
            "post:retrieval-frontier": {
                "2": {"semantic_rank": 1, "semantic_score": 0.75}
            }
        },
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": recall_profile,
        },
        obligation_count=3,
        support={
            backbone: {0: 0, 1: 0, 2: 0},
            first: {0: 0},
            second: {1: 0},
            third: {2: 0},
            frontier: {2: 0},
        },
        pair_scores={
            (backbone, 0): 3.20,
            (backbone, 1): 3.20,
            (backbone, 2): 3.20,
            (first, 0): 3.40,
            (second, 1): 3.40,
            (third, 2): 3.40,
            (frontier, 2): 3.30,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == tuple(sorted((backbone, first, second, third, frontier)))
    assert trace["minimum_complete_cover_positions"] == [backbone]
    assert trace["composition_backbone_positions"] == [backbone]
    assert trace["retrieval_frontier_positions"] == [frontier]


def test_integrated_synthesis_preserves_maximal_near_complete_backbone() -> None:
    candidates = _opened_candidates(
        ("note:near-complete-overview", "workspace-notes"),
        ("note:first-specialist", "workspace-notes"),
        ("note:second-specialist", "workspace-notes"),
        ("post:third-specialist", "workspace-posts"),
        ("post:fourth-specialist", "workspace-posts"),
        ("post:fifth-specialist", "workspace-posts"),
    )
    overview, first, second, third, fourth, fifth = range(len(candidates))
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first", "second", "third", "fourth", "fifth"),
        selection_mode="composition",
    )
    contract["answer_operations"] = [
        {
            "kind": "synthesis",
            "input_obligation_ids": [f"answer:{index}" for index in range(5)],
        }
    ]
    support = {
        overview: {0: 0, 1: 0, 2: 0, 3: 0},
        first: {0: 0},
        second: {1: 0},
        third: {2: 0},
        fourth: {3: 0},
        fifth: {4: 0},
    }
    pair_scores = {
        **{(overview, index): 3.20 for index in range(4)},
        (first, 0): 3.40,
        (second, 1): 3.40,
        (third, 2): 3.40,
        (fourth, 3): 3.40,
        (fifth, 4): 3.40,
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=5,
        support=support,
        pair_scores=pair_scores,
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == tuple(range(len(candidates)))
    assert trace["composition_backbone_positions"] == [overview]
    assert trace["composition_backbone_maximum_breadth"] == 4
    assert trace["composition_backbone_minimum_breadth"] == 4


def test_integrated_synthesis_preserves_n_minus_one_beside_complete_backbone() -> None:
    candidates = _opened_candidates(
        ("note:complete-overview", "workspace-notes"),
        ("note:near-complete-premise", "workspace-notes"),
        ("post:specialist", "workspace-posts"),
    )
    complete, near_complete, specialist = range(len(candidates))
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first", "second", "third", "fourth", "fifth"),
        selection_mode="composition",
    )
    contract["answer_operations"] = [
        {
            "kind": "synthesis",
            "input_obligation_ids": [f"answer:{index}" for index in range(5)],
        }
    ]

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=5,
        support={
            complete: {index: 0 for index in range(5)},
            near_complete: {index: 0 for index in range(4)},
            specialist: {4: 0},
        },
        pair_scores={
            **{(complete, index): 3.30 for index in range(5)},
            **{(near_complete, index): 3.40 for index in range(4)},
            (specialist, 4): 3.40,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert near_complete in positions
    assert complete in positions
    assert trace["composition_backbone_maximum_breadth"] == 5
    assert trace["composition_backbone_minimum_breadth"] == 4


def test_integrated_synthesis_retrieval_frontier_can_hedge_empty_post_read_label() -> None:
    candidates = _opened_candidates(
        ("note:complete-overview", "workspace-notes"),
        ("post:top-retrieval-premise", "workspace-posts"),
    )
    complete, frontier = range(len(candidates))
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first", "second", "third"),
        selection_mode="composition",
    )
    contract["answer_operations"] = [
        {
            "kind": "synthesis",
            "input_obligation_ids": ["answer:0", "answer:1", "answer:2"],
        }
    ]
    recall_profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 3,
        "rows": {
            "post:top-retrieval-premise": {
                "1": {"semantic_rank": 1, "semantic_score": 0.75}
            }
        },
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": recall_profile,
        },
        obligation_count=3,
        support={complete: {0: 0, 1: 0, 2: 0}, frontier: {}},
        pair_scores={(complete, 0): 3.30, (complete, 1): 3.30, (complete, 2): 3.30},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (complete, frontier)
    assert trace["retrieval_frontier_positions"] == [frontier]


def test_composition_near_complete_frontier_is_not_limited_to_synthesis_profile() -> None:
    candidates = _opened_candidates(
        ("note:recommendation-overview", "workspace-notes"),
        ("note:constraint", "workspace-notes"),
        ("post:history", "workspace-posts"),
        ("note:unfinished-specialist", "workspace-notes"),
    )
    overview, constraint, history, specialist = range(len(candidates))
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("unfinished idea", "constraint", "decision history"),
        selection_mode="composition",
    )
    contract["task_profile"] = "recommendation"
    contract["answer_shape"] = {"kind": "freeform"}
    contract["answer_operations"] = []

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=3,
        support={
            overview: {0: 0, 1: 0},
            constraint: {1: 0},
            history: {2: 0},
            specialist: {0: 0},
        },
        pair_scores={
            (overview, 0): 3.40,
            (overview, 1): 3.40,
            (constraint, 1): 3.35,
            (history, 2): 3.35,
            (specialist, 0): 3.60,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert overview in positions
    assert trace["composition_backbone_maximum_breadth"] == 2
    assert trace["composition_backbone_minimum_breadth"] == 2


def test_confirmed_reserve_prefers_complete_aggregate_proof() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("note:single-edge-specialist", "workspace-notes"),
        ("post:complete-alternative", "workspace-posts"),
        ("note:second-complete-alternative", "workspace-notes"),
    )
    support = {
        position: {0: 0, 1: 1, 2: 2}
        for position in range(len(candidates))
    }
    pair_scores = {
        (0, 0): 3.50,
        (0, 1): 3.50,
        (0, 2): 3.50,
        (1, 0): 3.49,
        (1, 1): 3.20,
        (1, 2): 3.20,
        (2, 0): 3.35,
        (2, 1): 3.35,
        (2, 2): 3.35,
        (3, 0): 3.34,
        (3, 1): 3.34,
        (3, 2): 3.34,
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first", "second", "third"),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 3}},
        obligation_count=3,
        support=support,
        pair_scores=pair_scores,
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 2, 3)
    assert trace["budget_evicted_positions"] == [1]


def test_confirmed_reserve_uses_recall_signal_only_within_proof_band() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("post:published-proof", "workspace-posts"),
        ("post:draft-proof", "workspace-posts"),
    )
    candidates[1]["semantic_rank_score"] = 0.70
    candidates[2]["semantic_rank_score"] = 0.80
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first fact", "second fact"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 2}},
        obligation_count=2,
        support={position: {0: 0, 1: 1} for position in range(3)},
        pair_scores={
            (0, 0): 3.50,
            (0, 1): 3.50,
            (1, 0): 3.304,
            (1, 1): 3.304,
            (2, 0): 3.305,
            (2, 1): 3.305,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 2)
    assert trace["confirmed_diversity_positions"] == [2]


def test_topical_composition_keeps_two_best_cross_source_proofs() -> None:
    candidates = _opened_candidates(
        ("note:broad-overview", "workspace-notes"),
        ("post:first-capability", "workspace-posts"),
        ("post:second-capability", "workspace-posts"),
        ("note:generic-background", "workspace-notes"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first", "second", "first consequence", "second consequence"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=4,
        support={position: {index: 0 for index in range(4)} for position in range(4)},
        pair_scores={
            (0, 0): 3.40,
            (0, 1): 3.40,
            (0, 2): 3.40,
            (0, 3): 3.40,
            (1, 0): 3.39,
            (1, 1): 3.20,
            (1, 2): 3.39,
            (1, 3): 3.20,
            (2, 0): 3.20,
            (2, 1): 3.39,
            (2, 2): 3.20,
            (2, 3): 3.39,
            (3, 0): 3.38,
            (3, 1): 3.38,
            (3, 2): 3.38,
            (3, 3): 3.38,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 2, 3)
    assert trace["confirmed_diversity_positions"] == [2]
    assert trace["budget_evicted_positions"] == [1]


def test_topical_composition_keeps_source_proofs_without_forcing_ownership() -> None:
    candidates = _opened_candidates(
        ("note:broad-overview", "workspace-notes"),
        ("note:high-scoring-restatement", "workspace-notes"),
        ("post:first-workflow-proof", "workspace-posts"),
        ("post:second-workflow-proof", "workspace-posts"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first", "second"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=2,
        support={position: {0: 0, 1: 0} for position in range(4)},
        pair_scores={
            (0, 0): 3.40,
            (0, 1): 3.40,
            (1, 0): 3.39,
            (1, 1): 3.39,
            (2, 0): 3.38,
            (2, 1): 3.20,
            (3, 0): 3.20,
            (3, 1): 3.38,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 2, 3)
    assert trace["confirmed_diversity_positions"] == [2]
    assert trace["budget_evicted_positions"] == [1]


def test_value_inventory_does_not_trade_stronger_record_for_source_diversity() -> None:
    candidates = _opened_candidates(
        ("note:complete-list", "workspace-notes"),
        ("note:strong-support", "workspace-notes"),
        ("post:corroboration-a", "workspace-posts"),
        ("post:corroboration-b", "workspace-posts"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("list exists", "members are distinct"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"
    contract["answer_shape"] = {
        "kind": "inventory",
        "inventory_unit": "value",
        "expected_member_count": 5,
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 3}},
        obligation_count=2,
        support={position: {0: 0, 1: 0} for position in range(4)},
        pair_scores={
            (0, 0): 3.40,
            (0, 1): 3.40,
            (1, 0): 3.39,
            (1, 1): 3.39,
            (2, 0): 3.38,
            (2, 1): 3.38,
            (3, 0): 3.37,
            (3, 1): 3.37,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["budget_evicted_positions"] == [3]


def test_complex_synthesis_keeps_bounded_full_read_recall_reserve() -> None:
    candidates = _opened_candidates(
        ("note:complete", "workspace-notes"),
        ("post:high-rank-a", "workspace-posts"),
        ("note:high-rank-b", "workspace-notes"),
        ("post:high-rank-c", "workspace-posts"),
    )
    candidates[1]["semantic_rank_score"] = 0.76
    candidates[2]["semantic_rank_score"] = 0.70
    candidates[3]["semantic_rank_score"] = 0.69
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("one", "two", "three", "four", "five"),
    )

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 3}},
        obligation_count=5,
        support={0: {index: 0 for index in range(5)}},
        pair_scores={(0, index): 3.4 for index in range(5)},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert set(trace["recall_reserve_positions"]) == {1, 2}


def test_recall_reserve_balances_sources_before_semantic_rank() -> None:
    candidates = _opened_candidates(
        ("note:proof-cover", "workspace-notes"),
        ("note:exact-alternative", "workspace-notes"),
        ("note:higher-rank-empty-label", "workspace-notes"),
        ("post:lower-rank-empty-label", "workspace-posts"),
    )
    candidates[2]["semantic_rank_score"] = 0.75
    candidates[3]["semantic_rank_score"] = 0.65
    notes = _source("workspace-notes", required=False)
    notes["membership_cardinality"] = {"min": 0, "max": 8}

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            notes,
            _source("workspace-posts", required=False),
            obligations=("requested route",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}},
        pair_scores={(0, 0): 3.40, (1, 0): 3.39},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 3)
    assert trace["optional_confirmed_ambiguity_positions"] == [1]
    assert trace["recall_reserve_positions"] == [3]
    assert trace["recall_reserve_rank_policy"] == "source_balanced_retrieval_floor"


def test_post_read_false_negative_reserve_requires_near_ranked_opened_row() -> None:
    candidates = _opened_candidates(
        ("note:first-premise", "workspace-notes"),
        ("post:second-premise", "workspace-posts"),
        ("note:near-ranked-empty-label", "workspace-notes"),
        ("note:low-ranked-empty-label", "workspace-notes"),
    )
    candidates[0]["semantic_rank_score"] = 0.64
    candidates[1]["semantic_rank_score"] = 0.62
    candidates[2]["semantic_rank_score"] = 0.58
    candidates[3]["semantic_rank_score"] = 0.49

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("first premise", "second premise"),
            selection_mode="cross_record_comparison",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 4}},
        obligation_count=2,
        support={0: {0: 0}, 1: {1: 0}},
        pair_scores={(0, 0): 3.4, (1, 1): 3.4},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["recall_reserve_positions"] == [2]


def test_recommendation_keeps_recent_published_rows_as_context_not_membership() -> None:
    candidates = _opened_candidates(
        ("post:recent-1", "workspace-posts"),
        ("post:recent-2", "workspace-posts"),
        ("post:recent-3", "workspace-posts"),
        ("note:first", "workspace-notes"),
        ("note:second", "workspace-notes"),
        ("note:third", "workspace-notes"),
    )
    for position, candidate in enumerate(candidates[:3], start=1):
        candidate["status"] = "published" if position <= 2 else "draft"
        candidate["catalog_window_memberships"] = [
            {
                "source_requirement_id": "workspace-posts",
                "position": position,
                "window_size": 3,
            }
        ]
    notes = _source("workspace-notes", maximum=3)
    posts = _source("workspace-posts", maximum=3)
    posts.update(
        {
            "discovery_mode": "catalog_window",
            "order_dependency": "required",
            "budget": {"candidate_limit": 3},
        }
    )
    contract = _contract(
        notes,
        posts,
        obligations=("first", "second", "third"),
    )
    contract["task_profile"] = "recommendation"

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 5}},
        obligation_count=3,
        support={3: {0: 0}, 4: {1: 0}, 5: {2: 0}},
        pair_scores={(3, 0): 0.9, (4, 1): 0.8, (5, 2): 0.7},
        include_prior_selected=False,
    )

    assert positions == (3, 4, 5)
    assert trace["structural_seed_positions"] == []
    assert trace["structural_context_positions"] == [0, 1]
    assert trace["uncovered_obligation_indexes"] == []


def test_workspace_synthesis_allows_one_row_to_close_multiple_obligations() -> None:
    candidates = _opened_candidates(
        ("note:broad-overview", "workspace-notes"),
        ("note:second-premise", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("first independent premise", "second independent premise"),
            selection_mode="composition",
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0, 1: 0}, 1: {1: 0}},
        pair_scores={(0, 0): 3.2, (0, 1): 3.2, (1, 1): 3.1},
        include_prior_selected=False,
    )

    assert positions == (0,)
    assert trace["distinct_premise_positions"] is False
    assert trace["multi_obligation_premise_positions"] == [0]


def test_workspace_synthesis_prefers_strongest_proofs_before_pack_size() -> None:
    candidates = _opened_candidates(
        ("note:self-contained", "workspace-notes"),
        ("note:first-specialist", "workspace-notes"),
        ("note:second-specialist", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            obligations=("first premise", "second premise"),
            selection_mode="composition",
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0, 1: 1}, 1: {0: 0}, 2: {1: 0}},
        pair_scores={(0, 0): 3.20, (0, 1): 3.20, (1, 0): 3.25, (2, 1): 3.25},
        include_prior_selected=False,
    )

    assert positions == (1, 2)
    assert trace["membership_policy"] == "minimal_proof_cover"
    assert trace["coverage_objective"] == "strongest_per_obligation"
    assert trace["coverage_seed_positions"] == [1, 2]


def test_composition_reserve_prefers_nearest_specialized_proofs() -> None:
    candidates = _opened_candidates(
        ("note:broad-best", "workspace-notes"),
        ("note:first-specialist", "workspace-notes"),
        ("note:second-specialist", "workspace-notes"),
        ("note:broad-decoy", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes", required=False),
            obligations=("first premise", "second premise"),
            selection_mode="composition",
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={
            0: {0: 0, 1: 0},
            1: {0: 0},
            2: {1: 0},
            3: {0: 0, 1: 0},
        },
        pair_scores={
            (0, 0): 3.40,
            (0, 1): 3.40,
            (1, 0): 3.39,
            (2, 1): 3.39,
            (3, 0): 3.38,
            (3, 1): 3.38,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["confirmed_rank_policy"] == "source_balanced_two_edge_regret"
    assert trace["optional_confirmed_ambiguity_positions"] == [1, 2]


def test_composition_confirmed_rank_uses_retrieval_before_score_ties() -> None:
    candidates = _opened_candidates(
        ("post:coverage-seed", "workspace-posts"),
        ("note:slightly-stronger-a", "workspace-notes"),
        ("note:slightly-stronger-b", "workspace-notes"),
        ("note:retrieval-winner", "workspace-notes"),
    )
    retrieval_by_ref = {
        "post:coverage-seed": 0.50,
        "note:slightly-stronger-a": 0.40,
        "note:slightly-stronger-b": 0.30,
        "note:retrieval-winner": 0.90,
    }
    for candidate in candidates:
        candidate["semantic_rank_score"] = retrieval_by_ref[candidate["ref"]]
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    seed = position_by_ref["post:coverage-seed"]
    first = position_by_ref["note:slightly-stronger-a"]
    second = position_by_ref["note:slightly-stronger-b"]
    retrieval_winner = position_by_ref["note:retrieval-winner"]
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("requested premise",),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={position: {0: 0} for position in range(4)},
        pair_scores={
            (seed, 0): 3.50,
            (first, 0): 3.49,
            (second, 0): 3.48,
            (retrieval_winner, 0): 3.40,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == tuple(sorted((seed, first, retrieval_winner)))
    assert trace["optional_confirmed_ambiguity_positions"] == [
        retrieval_winner,
        first,
    ]
    assert second in trace["budget_evicted_positions"]


def test_cross_record_confirmed_rank_uses_obligation_recall_profile() -> None:
    candidates = _opened_candidates(
        ("note:first-seed", "workspace-notes"),
        ("post:second-seed", "workspace-posts"),
        ("note:aggregate-alternative", "workspace-notes"),
        ("post:synthetic-score-winner", "workspace-posts"),
        ("post:recall-profile-winner", "workspace-posts"),
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    first_seed = position_by_ref["note:first-seed"]
    second_seed = position_by_ref["post:second-seed"]
    aggregate = position_by_ref["note:aggregate-alternative"]
    synthetic_winner = position_by_ref["post:synthetic-score-winner"]
    recall_winner = position_by_ref["post:recall-profile-winner"]
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first side", "second side"),
        selection_mode="cross_record_comparison",
    )
    recall_profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 2,
        "rows": {
            "post:synthetic-score-winner": {
                "1": {"semantic_rank": 3, "semantic_score": 0.45}
            },
            "post:recall-profile-winner": {
                "1": {"lexical_rank": 1, "lexical_score": 0.50}
            },
        },
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": recall_profile,
        },
        obligation_count=2,
        support={
            first_seed: {0: 0},
            second_seed: {1: 0},
            aggregate: {0: 0, 1: 0},
            synthetic_winner: {0: 0},
            recall_winner: {0: 0},
        },
        pair_scores={
            (first_seed, 0): 3.50,
            (second_seed, 1): 3.50,
            (aggregate, 0): 3.20,
            (aggregate, 1): 3.20,
            (synthetic_winner, 0): 3.39,
            (recall_winner, 0): 3.38,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == tuple(
        sorted((first_seed, second_seed, synthetic_winner, recall_winner))
    )
    assert aggregate in trace["budget_evicted_positions"]
    assert trace["confirmed_recall_profile_policy"] == (
        "confirmed_obligation_probe_rank"
    )


def test_cross_record_recall_profile_precedes_breadth_in_bounded_reserve() -> None:
    candidates = _opened_candidates(
        ("note:first-seed", "workspace-notes"),
        ("post:second-seed", "workspace-posts"),
        ("note:broad-alternative-a", "workspace-notes"),
        ("note:broad-alternative-b", "workspace-notes"),
        ("post:retrieved-premise", "workspace-posts"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("first side", "second side"),
        selection_mode="cross_record_comparison",
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    first_seed = position_by_ref["note:first-seed"]
    second_seed = position_by_ref["post:second-seed"]
    broad_a = position_by_ref["note:broad-alternative-a"]
    broad_b = position_by_ref["note:broad-alternative-b"]
    retrieved_premise = position_by_ref["post:retrieved-premise"]
    recall_profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 2,
        "rows": {
            "post:retrieved-premise": {
                "0": {"lexical_rank": 1, "lexical_score": 0.50}
            },
        },
    }

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": recall_profile,
        },
        obligation_count=2,
        support={
            first_seed: {0: 0},
            second_seed: {1: 0},
            broad_a: {0: 0, 1: 0},
            broad_b: {0: 0, 1: 0},
            retrieved_premise: {0: 0},
        },
        pair_scores={
            (first_seed, 0): 3.50,
            (second_seed, 1): 3.50,
            (broad_a, 0): 3.39,
            (broad_a, 1): 3.39,
            (broad_b, 0): 3.38,
            (broad_b, 1): 3.38,
            (retrieved_premise, 0): 3.37,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == tuple(
        sorted((first_seed, second_seed, broad_a, retrieved_premise))
    )
    assert trace["budget_evicted_positions"] == [broad_b]
    assert trace["confirmed_rank_policy"] == (
        "cross_record_recall_then_proof_regret"
    )


def test_composition_rebalances_sources_after_each_confirmed_alternative() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("post:first-alternative", "workspace-posts"),
        ("post:second-alternative", "workspace-posts"),
        ("note:strong-note-alternative", "workspace-notes"),
    )

    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            obligations=("requested premise",),
            selection_mode="composition",
        ),
        material_plan={**empty_material_plan(), "budget": {"max_objects": 8}},
        obligation_count=1,
        support={position: {0: 0} for position in range(4)},
        pair_scores={
            (0, 0): 3.40,
            (1, 0): 3.39,
            (2, 0): 3.38,
            (3, 0): 3.37,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 1, 2)
    assert trace["optional_confirmed_ambiguity_positions"] == [2, 1]
    assert trace["budget_evicted_positions"] == [3]


@pytest.mark.asyncio
async def test_bounded_complete_corpus_owns_read_capacity_before_optional_probes() -> None:
    raw_candidates = [
        _candidate("note:first", "workspace-notes"),
        _candidate("note:second", "workspace-notes"),
        _candidate("note:third", "workspace-notes"),
        _candidate("post:optional-first", "workspace-posts"),
        _candidate("post:optional-second", "workspace-posts"),
    ]
    for candidate in raw_candidates:
        candidate["estimated_full_text_chars"] = 2_000
    candidates = normalize_candidates(raw_candidates)
    notes = _source("workspace-notes")
    notes["coverage"] = "complete"
    contract = _contract(
        notes,
        _source("workspace-posts", required=False),
        obligations=("requested member category",),
        selection_mode="member_inventory",
    )
    optional_ref = "post:optional-first"
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct"
                    if candidate["ref"] == optional_ref
                    else "irrelevant",
                    "role": "answer_evidence"
                    if candidate["ref"] == optional_ref
                    else "none",
                    "resolution": "full_text"
                    if candidate["ref"] == optional_ref
                    else "none",
                    "confidence": 1.0,
                    "reason_code": "detailed_summary"
                    if candidate["ref"] == optional_ref
                    else "ambiguous",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "search_more"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )
    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    optional_positions = {
        position_by_ref["post:optional-first"],
        position_by_ref["post:optional-second"],
    }
    pair_scores = {
        (position, 0): 10.0 if position in optional_positions else 0.1
        for position in range(len(candidates))
    }

    with patch(
        "app.services.agent.research.graph._obligation_pair_scores",
        new_callable=AsyncMock,
        return_value=(pair_scores, {"scoring": "fixture"}),
    ):
        _decision, calls, trace, deadline = await _build_card_recall_cohort(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            primary=primary,
            material_plan={
                **empty_material_plan(),
                "budget": {"max_objects": 3, "max_full_text_chars": 6_000},
            },
            selector_question="Find every requested member.",
        )

    note_positions = {
        position_by_ref["note:first"],
        position_by_ref["note:second"],
        position_by_ref["note:third"],
    }
    assert calls == 0
    assert deadline is False
    assert trace["registry_probe_budget_fit"] is False
    assert trace["complete_probe_budget_fit"] is True
    assert set(trace["complete_probe_positions"]) == note_positions
    assert set(trace["deterministic_assembler"]["read_shortlist_positions"]) == note_positions


@pytest.mark.asyncio
async def test_unknown_size_required_complete_corpus_uses_fair_read_reservation() -> None:
    raw_candidates = [
        *[
            _candidate(f"note:required-{index}", "workspace-notes")
            for index in range(7)
        ],
        _candidate("post:optional-first", "workspace-posts"),
        _candidate("post:optional-second", "workspace-posts"),
    ]
    candidates = normalize_candidates(raw_candidates)
    notes = _source("workspace-notes")
    notes["coverage"] = "complete"
    posts = _source("workspace-posts", required=False)
    posts["coverage"] = "complete"
    contract = _contract(
        notes,
        posts,
        obligations=("requested member category",),
        selection_mode="member_inventory",
    )
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "direct"
                    if candidate["ref"] == "post:optional-first"
                    else "irrelevant",
                    "role": "answer_evidence"
                    if candidate["ref"] == "post:optional-first"
                    else "none",
                    "resolution": "full_text"
                    if candidate["ref"] == "post:optional-first"
                    else "none",
                    "confidence": 1.0,
                    "reason_code": "detailed_summary"
                    if candidate["ref"] == "post:optional-first"
                    else "ambiguous",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "search_more"},
                {"source_id": "workspace-posts", "status": "selected"},
            ],
        }
    )
    pair_scores = {
        (position, 0): 10.0
        if str(candidate["ref"]).startswith("post:")
        else 0.1
        for position, candidate in enumerate(candidates)
    }

    with patch(
        "app.services.agent.research.graph._obligation_pair_scores",
        new_callable=AsyncMock,
        return_value=(pair_scores, {"scoring": "fixture"}),
    ):
        _decision, _calls, trace, _deadline = await _build_card_recall_cohort(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            primary=primary,
            material_plan={
                **empty_material_plan(),
                "budget": {"max_objects": 8, "max_full_text_chars": 12_000},
            },
            selector_question="Find every requested member.",
        )

    position_by_ref = {
        candidate["ref"]: position for position, candidate in enumerate(candidates)
    }
    required_positions = {
        position_by_ref[f"note:required-{index}"] for index in range(7)
    }
    shortlist = set(
        trace["deterministic_assembler"]["read_shortlist_positions"]
    )
    assert trace["complete_probe_budget_fit"] is True
    assert set(trace["complete_probe_positions"]) == required_positions
    assert required_positions <= shortlist
    assert len(shortlist) == 8


@pytest.mark.asyncio
async def test_semantic_synthesis_uses_atomic_obligations_and_does_not_protect_complete_source() -> None:
    raw_candidates = [
        *[
            _candidate(f"note:catalog-{index}", "workspace-notes")
            for index in range(7)
        ],
        _candidate("post:strong-hit", "workspace-posts"),
        _candidate("post:second-hit", "workspace-posts"),
    ]
    candidates = normalize_candidates(raw_candidates)
    candidates[7]["semantic_rank_score"] = 0.95
    candidates[8]["semantic_rank_score"] = 0.90
    notes = _source("workspace-notes")
    notes["coverage"] = "complete"
    notes["query_goal"] = "broad notes source goal"
    posts = _source("workspace-posts")
    posts["query_goal"] = "broad posts source goal"
    contract = _contract(
        notes,
        posts,
        obligations=("first frozen premise", "second frozen premise"),
        selection_mode="composition",
    )
    primary = ContextSelectorDecision.model_validate(
        {
            "assessments": [
                {
                    "ref": candidate["ref"],
                    "relevance": "irrelevant",
                    "role": "none",
                    "resolution": "none",
                    "confidence": 1.0,
                    "reason_code": "ambiguous",
                }
                for candidate in candidates
            ],
            "source_dispositions": [
                {"source_id": "workspace-notes", "status": "search_more"},
                {"source_id": "workspace-posts", "status": "search_more"},
            ],
        }
    )

    async def score_atomic_obligations(*_args, **kwargs):
        assert kwargs["obligation_descriptions"] == (
            "first frozen premise",
            "second frozen premise",
        )
        scores = {
            (position, obligation_index): (
                1.0
                if position == 7 + obligation_index
                else 0.1
            )
            for position in range(len(candidates))
            for obligation_index in range(2)
        }
        return scores, {"scoring": "fixture"}

    with patch(
        "app.services.agent.research.graph._obligation_pair_scores",
        new_callable=AsyncMock,
        side_effect=score_atomic_obligations,
    ):
        _decision, _calls, trace, _deadline = await _build_card_recall_cohort(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            primary=primary,
            material_plan={
                **empty_material_plan(),
                "budget": {"max_objects": 8, "max_full_text_chars": 12_000},
            },
            selector_question="Find both premises.",
        )

    shortlist = set(trace["deterministic_assembler"]["read_shortlist_positions"])
    assert trace["complete_probe_positions"] == []
    assert {7, 8} <= shortlist
    assert trace["retrieval_probe_positions"][:2] == [7, 8]
    profile = trace["obligation_recall_profile"]
    assert profile["schema"] == "workspace.obligation-recall-profile/v1"
    assert profile["obligation_count"] == 2
    assert profile["rows"][candidates[7]["ref"]]["0"]["semantic_rank"] == 1
    assert profile["rows"][candidates[8]["ref"]]["1"]["semantic_rank"] == 1


def test_composition_uncertainty_uses_missing_obligation_probe_profile() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("post:cross-source-alternative", "workspace-posts"),
        ("note:strong-proof-without-probe", "workspace-notes"),
        ("note:typed-origin-probe", "workspace-notes"),
    )
    positions = {candidate["ref"]: index for index, candidate in enumerate(candidates)}
    seed = positions["note:coverage-seed"]
    post = positions["post:cross-source-alternative"]
    generic = positions["note:strong-proof-without-probe"]
    probe = positions["note:typed-origin-probe"]
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("ordinary premise", "typed origin premise"),
        selection_mode="composition",
    )
    profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 2,
        "rows": {
            candidates[probe]["ref"]: {
                "1": {"semantic_rank": 1, "semantic_score": 0.41}
            }
        },
    }

    selected, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": profile,
        },
        obligation_count=2,
        support={
            seed: {0: 0, 1: 0},
            post: {0: 0},
            generic: {0: 0},
            probe: {0: 0},
        },
        pair_scores={
            (seed, 0): 3.40,
            (seed, 1): 3.40,
            (post, 0): 3.38,
            (generic, 0): 3.39,
            (probe, 0): 3.20,
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert selected == tuple(sorted((seed, post, probe)))
    assert trace["confirmed_recall_profile_policy"] == (
        "confirmed_obligation_probe_rank"
    )


def test_composition_uncertainty_uses_profile_for_confirmed_edges() -> None:
    candidates = _opened_candidates(
        ("note:coverage-seed", "workspace-notes"),
        ("post:score-decoy-a", "workspace-posts"),
        ("post:score-decoy-b", "workspace-posts"),
        ("post:profile-winner", "workspace-posts"),
    )
    positions = {candidate["ref"]: index for index, candidate in enumerate(candidates)}
    seed = positions["note:coverage-seed"]
    first_decoy = positions["post:score-decoy-a"]
    second_decoy = positions["post:score-decoy-b"]
    profile_winner = positions["post:profile-winner"]
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        obligations=("prepare", "publish", "enabling mechanism"),
        selection_mode="composition",
    )
    contract["task_profile"] = "topical_answer"
    profile = {
        "schema": "workspace.obligation-recall-profile/v1",
        "query_ir_digest": _frozen_query_ir(contract)["digest"],
        "obligation_count": 3,
        "rows": {
            candidates[profile_winner]["ref"]: {
                "2": {
                    "semantic_rank": 1,
                    "semantic_score": 0.62,
                    "lexical_rank": 1,
                    "lexical_score": 0.27,
                }
            }
        },
    }

    selected, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan={
            **empty_material_plan(),
            "budget": {"max_objects": 8},
            "obligation_recall_profile": profile,
        },
        obligation_count=3,
        support={position: {0: 0, 1: 0, 2: 0} for position in range(4)},
        pair_scores={
            **{(seed, obligation): 3.40 for obligation in range(3)},
            **{(first_decoy, obligation): 3.39 for obligation in range(3)},
            **{(second_decoy, obligation): 3.38 for obligation in range(3)},
            **{(profile_winner, obligation): 3.20 for obligation in range(3)},
        },
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert selected == tuple(sorted((seed, first_decoy, profile_winner)))
    assert trace["optional_confirmed_ambiguity_positions"] == [
        profile_winner,
        first_decoy,
    ]
    assert second_decoy in trace["budget_evicted_positions"]


@pytest.mark.asyncio
async def test_valid_empty_post_read_result_locks_an_empty_material_queue() -> None:
    candidates = _opened_candidates(("note:card-positive", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"), obligations=("requested fact",)
    )
    baseline = _primary(candidates)

    async def empty_semantic_result(*_args, **kwargs) -> str:
        schema = kwargs["output_json_schema"]
        if "support" in schema["properties"]:
            return json.dumps(
                {
                    "v": OBLIGATION_CLASSIFICATION_VERSION,
                    "n": schema["properties"]["n"]["const"],
                    "r": schema["properties"]["r"]["const"],
                    "support": {
                        "0": {"position": -1, "warrant_unit": -1}
                    },
                    "done": True,
                }
            )
        return json.dumps(
            {
                "v": POST_READ_LABEL_VERSION,
                "n": schema["properties"]["n"]["const"],
                "r": schema["properties"]["r"]["const"],
                "labels": {"0": {"support": []}},
                "done": True,
            }
        )

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=empty_semantic_result,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=baseline,
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert trace["post_read_audit_schema_result"] == "valid"
    assert trace["post_read_audit_edges"] == []
    assert trace["post_read_membership_finalized"] is True
    assert trace["post_read_membership_positions"] == []
    assessments = [item.model_dump(mode="json") for item in decision.assessments]
    assert all(item["relevance"] == "irrelevant" for item in assessments)

    prior_plan = merge_material_plan(
        empty_material_plan(),
        candidates=candidates,
        assessments=[
            item.model_dump(mode="json") for item in baseline.assessments
        ],
    )
    locked_plan = {
        **prior_plan,
        "membership_locked": True,
        "membership_locked_refs": [],
    }
    final_plan = compile_material_plan(
        locked_plan,
        candidates=candidates,
        assessments=assessments,
        contract=contract,
    )

    assert final_plan["membership_locked"] is True
    assert final_plan["membership_locked_refs"] == []
    assert final_plan["materialization_queue"] == []


@pytest.mark.asyncio
async def test_missing_obligation_audit_recovers_only_uncovered_primary_edge() -> None:
    candidates = _opened_candidates(
        ("note:primary-negative", "workspace-notes"),
        ("note:audit-proof", "workspace-notes"),
    )
    contract = _contract(
        _source("workspace-notes"), obligations=("requested fact",)
    )
    runtime_context = _ctx()

    async def provider(ctx, **kwargs) -> str:
        ctx.llm_metrics.append(
            {
                "phase": kwargs["phase"],
                "schema_result": kwargs["telemetry"]["schema_result"],
                "retry": False,
            }
        )
        schema = kwargs["output_json_schema"]
        if "support" in schema["properties"]:
            return json.dumps(
                {
                    "v": OBLIGATION_CLASSIFICATION_VERSION,
                    "n": 2,
                    "r": schema["properties"]["r"]["const"],
                        "support": {
                            "0": {"position": 0, "warrant_unit": 0}
                    },
                    "done": True,
                }
            )
        return json.dumps(
            {
                "v": POST_READ_LABEL_VERSION,
                "n": 2,
                "r": schema["properties"]["r"]["const"],
                "labels": {
                    "0": {"support": []},
                    "1": {"support": []},
                },
                "done": True,
            }
        )

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=provider,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": runtime_context}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_primary(candidates),
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert trace["post_read_missing_obligation_indexes"] == [0]
    assert trace["post_read_audit_edges"] == [
        {"position": 0, "obligation_index": 0, "warrant_unit": 0}
    ]
    assert runtime_context.llm_metrics[-1]["schema_result"] == "valid"
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:audit-proof"}


def test_post_read_partial_rows_are_kept_only_when_needed_for_coverage() -> None:
    candidates = _opened_candidates(
        ("note:exact", "workspace-notes"),
        ("note:redundant-partial", "workspace-notes"),
        ("note:indispensable-partial", "workspace-notes"),
    )
    positions, _trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(_source("workspace-notes")),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0}, 1: {0: 0}, 2: {1: 0}},
        pair_scores={(0, 0): 3.0, (1, 0): 2.0, (2, 1): 2.0},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (0, 2)


def test_deterministic_assembler_composes_partial_rows_and_enforces_source_scope() -> None:
    candidates = _opened_candidates(
        ("note:first", "workspace-notes"),
        ("post:second", "workspace-posts"),
        ("attachment:optional", "workspace-attachments"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
        _source("workspace-attachments", required=False),
    )
    position_by_ref = {
        str(candidate["ref"]): position
        for position, candidate in enumerate(candidates)
    }
    note_position = position_by_ref["note:first"]
    post_position = position_by_ref["post:second"]
    optional_position = position_by_ref["attachment:optional"]
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={
            note_position: {0: 0},
            post_position: {1: 0},
            optional_position: {0: 0, 1: 0},
        },
        pair_scores={
            (note_position, 0): 2.0,
            (post_position, 1): 2.0,
            (optional_position, 0): 3.0,
            (optional_position, 1): 3.0,
        },
        include_prior_selected=False,
    )

    assert positions == tuple(sorted((note_position, post_position)))
    assert optional_position not in positions
    assert trace["source_coverage_optimized"] is False


def test_source_neutral_membership_allows_proof_from_optional_discovery_corpus() -> None:
    candidates = _opened_candidates(
        ("post:planner-preferred", "workspace-posts"),
        ("note:stronger-proof", "workspace-notes"),
    )
    contract = _contract(
        _source("workspace-posts"),
        _source("workspace-notes", required=False),
        obligations=("requested fact",),
    )
    contract["membership_source_scope"] = "source_neutral"
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=contract,
        material_plan=empty_material_plan(),
        obligation_count=1,
        support={0: {0: 0}, 1: {0: 0}},
        pair_scores={(0, 0): 0.5, (1, 0): 3.2},
        include_prior_selected=False,
        preserve_confirmed=True,
    )

    assert positions == (1,)
    assert trace["membership_source_scope"] == "source_neutral"


def test_member_registry_includes_complete_discovery_required_source() -> None:
    source = _source("workspace-posts", required=False)
    source["coverage"] = "complete"

    assert _member_classification_source_ids(_contract(source)) == {
        "workspace-posts"
    }


def test_member_registry_prefers_evidence_corpus_over_optional_discovery_corpus() -> None:
    notes = _source("workspace-notes")
    notes["coverage"] = "complete"
    posts = _source("workspace-posts", required=False)
    posts["coverage"] = "complete"

    assert _member_classification_source_ids(_contract(notes, posts)) == {
        "workspace-notes"
    }


def test_relational_member_registry_includes_both_mapping_sides() -> None:
    notes = _source("workspace-notes")
    posts = _source("workspace-posts", required=False)
    contract = _contract(
        notes,
        posts,
        obligations=("mapping side",),
        selection_mode="cross_record_inventory",
    )

    assert _member_classification_source_ids(contract) == {
        "workspace-notes",
        "workspace-posts",
    }


@pytest.mark.asyncio
async def test_full_read_member_classification_finalizes_membership() -> None:
    candidates = _opened_candidates(
        ("note:member", "workspace-notes"),
        ("post:optional-context", "workspace-posts"),
    )
    notes = _source("workspace-notes")
    notes["coverage"] = "complete"
    posts = _source("workspace-posts", required=False)
    posts["coverage"] = "complete"
    contract = _contract(
        notes,
        posts,
        obligations=("which note is a requested member",),
        selection_mode="member_inventory",
    )
    contract["answer_shape"] = {
        "kind": "inventory",
        "inventory_unit": "record",
        "expected_member_count": None,
    }

    async def provider(*_args, **kwargs) -> str:
        schema = kwargs["output_json_schema"]
        assert schema["properties"]["n"]["const"] == 1
        return json.dumps(
            {
                "v": 1,
                "n": 1,
                "r": schema["properties"]["r"]["const"],
                "labels": {"0": {"match": True, "warrant_unit": 0}},
                "done": True,
            }
        )

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        side_effect=provider,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_primary(candidates),
            material_plan=empty_material_plan(),
            selector_question="Classify all notes.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 1
    assert deadline is False
    assert trace["post_read_membership_finalized"] is True
    assert trace["post_read_membership_positions"] == [0]
    assert trace["post_read_assessment_mode"] == "single_registry_member_classification"
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:member"}


def test_record_can_use_one_row_for_multiple_obligations() -> None:
    candidates = _opened_candidates(("note:complete", "workspace-notes"))
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"), selection_mode="record"
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0, 1: 0}},
        pair_scores={(0, 0): 3.0, (0, 1): 3.0},
        include_prior_selected=False,
    )

    assert positions == (0,)
    assert trace["covered_obligation_indexes"] == [0, 1]


def test_cross_record_inventory_requires_distinct_members() -> None:
    candidates = _opened_candidates(
        ("note:first", "workspace-notes"),
        ("note:second", "workspace-notes"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"), selection_mode="cross_record_inventory"
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0, 1: 0}, 1: {1: 0}},
        pair_scores={(0, 0): 3.0, (0, 1): 3.0, (1, 1): 2.0},
        include_prior_selected=False,
    )

    assert positions == (0, 1)
    assert trace["distinct_premise_positions"] is True


def test_cross_record_comparison_requires_distinct_evidence_premises() -> None:
    candidates = _opened_candidates(
        ("note:complete-overview", "workspace-notes"),
        ("note:first-premise", "workspace-notes"),
        ("post:second-premise", "workspace-posts"),
    )
    positions, trace = _assemble_obligation_coverage_positions(
        candidates=candidates,
        contract=_contract(
            _source("workspace-notes"),
            _source("workspace-posts"),
            selection_mode="cross_record_comparison",
        ),
        material_plan=empty_material_plan(),
        obligation_count=2,
        support={0: {0: 0, 1: 0}, 1: {0: 0}, 2: {1: 0}},
        pair_scores={(0, 0): 3.2, (0, 1): 3.2, (1, 0): 3.1, (2, 1): 3.1},
        include_prior_selected=False,
    )

    assert len(positions) == 2
    assert 0 in positions
    assert trace["distinct_premise_positions"] is True


@pytest.mark.asyncio
async def test_post_read_v3_uses_one_full_registry_call_and_no_embedding_membership() -> None:
    candidates = _opened_candidates(
        ("note:first", "workspace-notes"),
        ("post:second", "workspace-posts"),
    )
    contract = _contract(
        _source("workspace-notes"),
        _source("workspace-posts"),
    )
    async def assessment_for_registry(*_args, **kwargs):
        schema = kwargs["output_json_schema"]
        if str(kwargs["phase"]).endswith("missing_obligation_audit"):
            support_keys = schema["properties"]["support"]["properties"]
            return json.dumps(
                {
                    "v": OBLIGATION_CLASSIFICATION_VERSION,
                    "n": schema["properties"]["n"]["const"],
                    "r": schema["properties"]["r"]["const"],
                    "support": {
                        key: {
                            "position": int(key),
                            "warrant_unit": 0,
                        }
                        for key in support_keys
                    },
                    "done": True,
                }
            )
        edge = {
            "obligation_index": 0,
            "warrant_unit": 0,
            "fit": "partial",
            "prominence": "primary",
        }
        return json.dumps(
            {
                "v": POST_READ_LABEL_VERSION,
                "n": schema["properties"]["n"]["const"],
                "r": schema["properties"]["r"]["const"],
                "labels": {
                    "0": {"support": [edge]},
                    "1": {"support": []},
                },
                "done": True,
            }
        )

    selector = AsyncMock(side_effect=assessment_for_registry)
    embedding_rank = AsyncMock(side_effect=AssertionError("embedding membership call"))

    with (
        patch(
            "app.services.agent.runtime.budget.call_llm_with_deadline",
            selector,
        ),
        patch(
            "app.services.agent.research.graph._obligation_pair_scores",
            embedding_rank,
        ),
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_primary(candidates),
            material_plan=empty_material_plan(),
            selector_question="Explain both facts.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert selector.await_count == 2
    assert embedding_rank.await_count == 0
    assert selector.await_args_list[0].kwargs["output_schema_name"].endswith(
        "post_read_assessment_v5"
    )
    assert selector.await_args_list[1].kwargs["output_schema_name"].endswith(
        "missing_obligation_audit_v4"
    )
    for call in selector.await_args_list:
        prompt = call.kwargs["messages"][1]["content"]
        assert "source_goals" not in prompt
        assert "source_requirement_ids" not in prompt
        assert "query_focus_units" not in prompt
    primary_schema = selector.await_args_list[0].kwargs["output_json_schema"]
    edge_properties = (
        primary_schema["properties"]["labels"]["properties"]["0"]
        ["properties"]["support"]["items"]["properties"]
    )
    assert edge_properties["fit"]["enum"] == ["broad", "partial", "exact"]
    assert edge_properties["prominence"]["enum"] == [
        "mention",
        "section",
        "primary",
    ]
    audit_schema = selector.await_args_list[1].kwargs["output_json_schema"]
    assert "labels" not in audit_schema["properties"]
    assert set(audit_schema["properties"]["support"]["properties"]) == {"0", "1"}
    assert trace["precision_protocol"] == "post_read_assessment_v5"
    assert trace["membership_owner"] == "deterministic_assembler"
    assert trace["post_read_assessment_call_count"] == 2
    assert trace["post_read_assessment_mode"] == "single_registry_full_obligations"
    assert trace["post_read_shards"] == [
        {"obligation_indexes": [0, 1], "schema_result": "valid"}
    ]
    assert trace["post_read_assessments"] == [
        {
            "position": 0,
            "support": [],
        },
        {
            "position": 1,
            "support": [],
        },
    ]
    assert trace["post_read_missing_obligation_indexes"] == [0, 1]
    assert trace["post_read_audit_edges"] == [
        {"position": 0, "obligation_index": 0, "warrant_unit": 0},
        {"position": 1, "obligation_index": 1, "warrant_unit": 0}
    ]
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:first", "post:second"}


@pytest.mark.asyncio
async def test_post_read_provider_failure_retries_only_failed_shard() -> None:
    candidates = _opened_candidates(("note:complete", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"),
        obligations=("first", "second", "third"),
        selection_mode="composition",
    )

    async def assessment_for_shard(*_args, **kwargs):
        phase = str(kwargs["phase"])
        if ".obligation_shard_2" in phase and not phase.endswith(".schema_retry"):
            raise RuntimeError("provider disconnected")
        schema = kwargs["output_json_schema"]
        support_schema = (
            schema["properties"]["labels"]["properties"]["0"]
            ["properties"]["support"]
        )
        allowed = support_schema["items"]["properties"]["obligation_index"].get(
            "enum", []
        )
        return json.dumps(
            {
                "v": POST_READ_LABEL_VERSION,
                "n": schema["properties"]["n"]["const"],
                "r": schema["properties"]["r"]["const"],
                "labels": {
                    "0": {
                        "support": [
                            {
                                "obligation_index": index,
                                "warrant_unit": 0,
                                "fit": "exact",
                                "prominence": "primary",
                            }
                            for index in allowed
                        ]
                    }
                },
                "done": True,
            }
        )

    selector = AsyncMock(side_effect=assessment_for_shard)
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        selector,
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=_primary(candidates),
            material_plan=empty_material_plan(),
            selector_question="Explain all three facts.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=3,
            include_opened_recovery_pool=True,
        )

    phases = [call.kwargs["phase"] for call in selector.await_args_list]
    assert calls == 3
    assert deadline is False
    assert phases.count("research.selector.context_precision_confirmation") == 1
    assert phases.count(
        "research.selector.context_precision_confirmation.obligation_shard_2"
    ) == 1
    assert phases.count(
        "research.selector.context_precision_confirmation.obligation_shard_2.schema_retry"
    ) == 1
    assert trace["schema_result"] == "valid"
    assert trace["post_read_assessment_call_count"] == 3
    assert {
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    } == {"note:complete"}


@pytest.mark.asyncio
async def test_decoder_failure_preserves_safe_baseline_as_unverified() -> None:
    candidates = _opened_candidates(("note:first", "workspace-notes"))
    contract = _contract(
        _source("workspace-notes"), obligations=("requested fact",)
    )
    baseline = _primary(candidates)

    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value="{}",
    ):
        decision, calls, trace, deadline = await _run_precision_confirmation(
            config={"configurable": {"runtime_context": _ctx()}},
            contract=contract,
            candidates=candidates,
            selector_candidates=candidates,
            primary=baseline,
            material_plan=empty_material_plan(),
            selector_question="Find the requested fact.",
            transport_tier=ChatCompletionCapability.STRICT_JSON_SCHEMA,
            verification_calls_used=0,
            verification_call_limit=2,
            include_opened_recovery_pool=True,
        )

    assert calls == 2
    assert deadline is False
    assert trace["degraded"] is True
    assert trace["fallback"] == "validated_primary_baseline"
    assert trace["precision_error"]["error_class"] == "invalid_transport"
    assert [
        item.ref
        for item in decision.assessments
        if item.relevance.value != "irrelevant"
    ] == ["note:first"]


def test_soft_deadline_preserves_mandatory_post_read_membership_turn() -> None:
    state = {
        "phase5_enabled": True,
        "soft_deadline_reached": True,
        "deadline_exhausted": False,
        "step_count": 1,
        "max_steps": 10,
        "sufficiency": {"status": "exhausted"},
        "tool_action": {"requested_status": "partial"},
        "material_plan": {
            "needs_evidence_reassessment": True,
            "evidence_escalation_reassess_refs": ["note:first"],
            "pending_full_text_ids": [],
        },
    }

    assert route_research_verify(state) == "planner"
    assert route_research_verify(
        {
            **state,
            "material_plan": {
                **state["material_plan"],
                "pending_full_text_ids": ["note:first"],
                "needs_evidence_reassessment": False,
                "evidence_escalation_reassess_refs": [],
            },
        }
    ) == "planner"
    assert route_research_verify(
        {
            **state,
            "material_plan": {
                **state["material_plan"],
                "needs_evidence_reassessment": False,
                "evidence_escalation_reassess_refs": [],
            },
        }
    ) == "pack"
    assert route_research_verify({**state, "deadline_exhausted": True}) == "pack"
