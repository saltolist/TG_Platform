"""Phase 3: search intent ledger, cache and validator-event contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.research.graph import research_planner_node, research_tool_node
from app.services.agent.research.search_ledger import (
    canonical_tool_signature,
    finish_intent,
    prepare_intent,
    render_search_ledger_for_planner,
)
from app.services.agent.runtime.context import RuntimeContext
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_tools import ToolOutcome


def _contract() -> dict:
    return {
        "target_contract": {"revision": 4},
        "source_requirements": [
            {
                "source_id": "workspace-notes-1",
                "kind": "notes",
                "required": True,
                "scope": {"mode": "corpus", "corpus": "workspace"},
                "freshness": {"mode": "latest_available"},
                "budget": {"search_calls": 2, "rewrite_calls": 1},
            }
        ],
    }


def test_canonical_signature_is_stable_and_revision_scoped() -> None:
    contract = _contract()
    first = canonical_tool_signature(
        "SearchNodes",
        {"query": "  Система   запуска ", "node_types": ["note", "post"], "k": 4},
        source_requirement_id="workspace-notes-1",
        contract=contract,
    )
    second = canonical_tool_signature(
        "SearchNodes",
        {"query": "система запуска", "node_types": ["post", "note"], "k": 4},
        source_requirement_id="workspace-notes-1",
        contract=contract,
    )
    assert first == second
    changed = {**contract, "target_contract": {"revision": 5}}
    assert canonical_tool_signature(
        "SearchNodes",
        {"query": "система запуска", "node_types": ["note", "post"], "k": 4},
        source_requirement_id="workspace-notes-1",
        contract=changed,
    ) != first


def test_ledger_caches_success_and_empty_search_outcomes() -> None:
    contract = _contract()
    prepared = prepare_intent(
        [], tool="SearchNodes", args={"query": "система"}, contract=contract
    )
    ledger = finish_intent(
        prepared.ledger,
        intent_key=prepared.entry["intent_key"],
        summary="one result",
        error=None,
        hits=[{"ref": "note:n1"}],
    )
    duplicate = prepare_intent(
        ledger, tool="SearchNodes", args={"query": " СИСТЕМА "}, contract=contract
    )
    assert duplicate.execute is False
    assert duplicate.cached is True
    assert duplicate.entry["state"] == "satisfied"

    empty_prepared = prepare_intent(
        [], tool="SearchNodes", args={"query": "нет такого"}, contract=contract
    )
    empty_ledger = finish_intent(
        empty_prepared.ledger,
        intent_key=empty_prepared.entry["intent_key"],
        summary="Поиск не дал результатов.",
        error=None,
    )
    empty_duplicate = prepare_intent(
        empty_ledger, tool="SearchNodes", args={"query": "нет такого"}, contract=contract
    )
    assert empty_duplicate.execute is False
    assert empty_duplicate.entry["state"] == "exhausted"
    assert empty_duplicate.entry["exhausted_reason"] == "empty_result"
    assert "exhausted_reason=empty_result" in render_search_ledger_for_planner(
        empty_duplicate.ledger
    )


def test_only_one_gap_linked_rewrite_is_allowed() -> None:
    contract = _contract()
    first = prepare_intent(
        [], tool="SearchNodes", args={"query": "система"}, contract=contract
    )
    ledger = finish_intent(
        first.ledger,
        intent_key=first.entry["intent_key"],
        summary="one result",
        error=None,
        hits=[{"ref": "note:n1"}],
    )
    no_gap = prepare_intent(
        ledger,
        tool="SearchNodes",
        args={"query": "запуск"},
        contract=contract,
    )
    assert no_gap.execute is False
    assert no_gap.entry["exhausted_reason"] == "rewrite_requires_evidence_gap"

    rewrite = prepare_intent(
        no_gap.ledger,
        tool="SearchNodes",
        args={"query": "запуск"},
        contract=contract,
        evidence_gap="нужны факты о запуске",
    )
    assert rewrite.execute is True
    rewrite_ledger = finish_intent(
        rewrite.ledger,
        intent_key=rewrite.entry["intent_key"],
        summary="rewritten result",
        error=None,
        hits=[{"ref": "note:n2"}],
    )
    second = prepare_intent(
        rewrite_ledger,
        tool="SearchNodes",
        args={"query": "третья формулировка"},
        contract=contract,
        evidence_gap="ещё один gap",
    )
    assert second.execute is False
    assert second.entry["exhausted_reason"] == "rewrite_limit_reached"


def _ctx() -> RuntimeContext:
    ctx = RuntimeContext(
        session_factory=lambda: _SessionContext(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
    )
    return ctx


class _SessionContext:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_tool_node_does_not_repeat_successful_external_call() -> None:
    ctx = _ctx()
    state = {
        "tool_action": {"tool": "SearchNodes", "args": {"query": "система"}},
        "evidence_records": {},
        "search_ledger": [],
        "tool_outcomes": [],
        "turn_contract": _contract(),
        "step_count": 1,
    }
    with patch(
        "app.services.agent.research.graph._execute_tool",
        new_callable=AsyncMock,
        return_value=ToolOutcome(
            summary="one result", hits=({"ref": "note:n1", "similarity": 0.9},)
        ),
    ) as execute:
        first = await research_tool_node(state, {"configurable": {"runtime_context": ctx}})
        second_state = {**first, "step_count": 2}
        second = await research_tool_node(
            second_state, {"configurable": {"runtime_context": ctx}}
        )
    assert execute.await_count == 1
    assert second["tool_outcomes"][-1]["cached"] is True
    assert second["search_ledger"][-1]["state"] == "satisfied"


@pytest.mark.asyncio
async def test_seed_executes_source_scoped_discovery_instead_of_mixed_l1() -> None:
    from app.services.agent.research.graph import research_seed_node

    ctx = _ctx()
    l1 = [
        {
            "node_type": "note_chunk",
            "note_id": "n1",
            "file_id": "",
            "similarity": 0.81,
        }
    ]
    state = {
        "user_text": "найди систему",
        "search_query": "найди систему",
        "research_transcript": [],
        "search_ledger": [],
        "turn_contract": _contract(),
    }
    with (
        patch("app.services.agent.research.graph._workspace_inventory", new=AsyncMock(return_value="")),
            patch(
                "app.services.agent.research.graph._execute_tool",
                new_callable=AsyncMock,
                return_value=ToolOutcome(
                    summary="one result",
                    hits=({"ref": "note:n1", "similarity": 0.81},),
                ),
            ) as execute,
    ):
        result = await research_seed_node(
            state,
            {
                "configurable": {
                    "runtime_context": ctx,
                    "turn_contract": _contract(),
                    "l1_results": l1,
                    "dialog_ledger": (),
                }
            },
        )
        execute.assert_awaited_once()
    action = execute.await_args.args[1]
    assert action.tool == "SearchNodes"
    assert action.args["source_requirement_id"] == "workspace-notes-1"
    assert action.args["node_types"] == ["note_summary", "note_chunk"]
    assert result["search_ledger"][-1]["state"] == "satisfied"


def _decision_note_contract(*, candidate_limit: int = 3) -> dict:
    return {
        "version": 3,
        "target_contract": {"revision": 4, "targets": []},
        "task_profile": "recommendation",
        "answer_shape": {"kind": "freeform", "expected_member_count": None},
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "role": "context",
                "query_goal": "Find premises that can constrain the next decision.",
                "discovery_obligation": "required",
                "evidence_obligation": "required",
                "selection_cardinality": {"min": 0, "max": candidate_limit},
                "coverage": "relevant",
                "discovery_mode": "semantic_relevance",
                "order_by": None,
                "order_direction": None,
                "predicate_kind": "semantic",
                "required_fidelity": "semantic_card",
                "evidence_requirements": [],
                "scope": {
                    "mode": "corpus",
                    "corpus": "workspace",
                    "owner": "current_user",
                    "target_ids": [],
                    "statuses": [],
                },
                "budget": {
                    "search_calls": 1,
                    "rewrite_calls": 0,
                    "candidate_limit": candidate_limit,
                    "deep_reads": 2,
                },
            }
        ],
    }


def _note_card(note_id: str) -> dict:
    return {
        "ref": f"note:{note_id}",
        "label": f"note:{note_id}",
        "origin": "authoritative_catalog",
        "node_type": "note_summary",
        "summary_only": True,
        "index_revision": 1,
        "source_revision": 1,
        "selector_summary": f"Decision premise {note_id}.",
        "selector_summary_version": 13,
        "selector_semantic_flags": {"v": 2},
        "title": f"Note {note_id}",
        "status": "active",
        "source_requirement_id": "workspace-notes",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("catalog_size", "expected_refs", "loads_finite_cards"),
    [
        (3, {"note:n1", "note:n2", "note:n3"}, True),
        (4, {"note:n1", "note:n2", "note:n3", "note:n4"}, True),
        (11, {"note:n1"}, False),
    ],
)
async def test_seed_adds_only_a_finite_decision_note_catalog(
    catalog_size: int,
    expected_refs: set[str],
    loads_finite_cards: bool,
) -> None:
    from app.services.agent.research.graph import research_seed_node

    ctx = _ctx()
    ctx.settings = Settings(
        agent_unified_catalog_v1_enabled=True,
        agent_typed_requirements_v1_enabled=True,
        agent_unified_selector_v1_enabled=True,
        agent_verified_pack_boundary_v1_enabled=True,
        agent_planner_policy_v1_enabled=True,
    )
    contract = _decision_note_contract(candidate_limit=3)
    members = tuple(
        {
            "kind": "note",
            "id": f"n{index}",
            "title": f"Note n{index}",
            "status": "active",
            "revision": 1,
        }
        for index in range(1, catalog_size + 1)
    )
    cards = [_note_card(str(item["id"])) for item in members]
    semantic_hit = _note_card("n1") | {
        "origin": "semantic_search",
        "similarity": 0.9,
    }
    state = {
        "user_text": "What should be produced next?",
        "search_query": "What should be produced next?",
        "research_transcript": [],
        "search_ledger": [],
        "turn_contract": contract,
    }
    with (
        patch(
            "app.services.agent.research.graph._workspace_inventory",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.services.agent.research.graph.tool_list_all_notes",
            new=AsyncMock(
                return_value=ToolOutcome(
                    summary="bounded probe",
                    items=members,
                    result_count=len(members),
                )
            ),
        ) as probe,
        patch(
            "app.services.agent.research.graph._catalog_member_candidates",
            new=AsyncMock(return_value=(cards, len(cards))),
        ) as load_cards,
        patch(
            "app.services.agent.research.graph._execute_tool",
            new=AsyncMock(
                return_value=ToolOutcome(
                    summary="one semantic result",
                    hits=(semantic_hit,),
                )
            ),
        ),
    ):
        result = await research_seed_node(
            state,
            {
                "configurable": {
                    "runtime_context": ctx,
                    "turn_contract": contract,
                    "dialog_ledger": (),
                }
            },
        )

    assert probe.await_count == 1
    assert probe.await_args.kwargs == {
        "source_requirement_id": "workspace-notes",
        "limit": 11,
        "record": False,
    }
    assert load_cards.await_count == int(loads_finite_cards)
    assert {item["ref"] for item in result["candidate_envelopes"]} == expected_refs
    assert not result["material_plan"].get("required_full_text_ids")


@pytest.mark.asyncio
async def test_second_finish_becomes_validator_event() -> None:
    ctx = _ctx()
    ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
    ctx.reasoner_model = "gpt-4o-mini"
    ctx.reasoner_api_key = "test-key"
    state = {
        "user_text": "найди факты",
        "step_count": 0,
        "max_steps": 4,
        "evidence_records": {},
        "turn_contract": {},
        "research_transcript": [],
        "research_hints": [],
        "planner_steps": [],
        "search_ledger": [],
        "finish_retrieval_attempted": True,
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"tool":"FinishRetrieval","args":{"status":"ready","evidence_ids":[]}}',
    ):
        result = await research_planner_node(
            state, {"configurable": {"runtime_context": ctx, "turn_contract": {}}}
        )
    assert result["tool_action"]["tool"] == "ValidatorEvent"
    assert result["planner_steps"][-1]["tool"] == "ValidatorEvent"
