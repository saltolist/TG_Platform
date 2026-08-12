"""Phase 5: compact planner protocol and deterministic sufficiency."""

from __future__ import annotations

import json
import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.agent.research.planner_decision import (
    ContextSelectorDecision,
    DecisionCode,
    PlannerDecision,
    parse_context_selector_decision,
    parse_planner_decision,
)
from app.services.agent.research.sufficiency import evaluate_sufficiency
from app.services.agent.runtime.turn_contract import build_turn_contract


def _record(kind: str, path: str, content: str = "grounded") -> dict:
    return {
        "id": path,
        "kind": kind,
        "source_ref": path,
        "content": content,
        "citation_path": path,
        "citation_title": path,
        "metadata": {},
    }


def test_compact_decision_is_strict_and_allows_bounded_batch() -> None:
    decision = parse_planner_decision(
        json.dumps(
            {
                "decision_code": "READ_TOP_CANDIDATES",
                "actions": [
                    {"tool": "OpenNote", "args": {"note_id": "n1"}},
                    {"tool": "OpenPost", "args": {"post_id": "p1"}},
                ],
                "state_updates": {"selected_candidate_ids": ["n1", "p1"]},
                "confidence": 0.9,
            }
        )
    )
    assert decision is not None
    assert len(decision.actions) == 2
    assert decision.model_dump(exclude_none=True).get("actions")

    with pytest.raises(ValidationError):
        PlannerDecision.model_validate(
            {
                "decision_code": "READ_TOP_CANDIDATES",
                "actions": [{"tool": "OpenNote", "args": {"note_id": "n1"}}],
                "observations": ["legacy rationale"],
            }
        )
    assert parse_planner_decision('{"decision_code":"READ_TOP_CANDIDATES","actions":[]}') is None


def test_context_selector_is_id_only_and_rejects_generated_content() -> None:
    decision = parse_context_selector_decision(
        '{"assessments":[{"ref":"post:p1","relevance":"direct",'
        '"role":"answer_evidence","resolution":"card","confidence":0.9,'
        '"reason_code":"topic_only"},{"ref":"attachment:f1",'
        '"relevance":"supporting","role":"answer_evidence","resolution":"vision",'
        '"confidence":0.8,"reason_code":"attachment_or_media"}],'
        '"source_dispositions":[{"source_id":"workspace-posts","status":"selected"}]}'
    )
    assert isinstance(decision, ContextSelectorDecision)
    assert [item.ref for item in decision.assessments] == ["post:p1", "attachment:f1"]
    assert parse_context_selector_decision(
        '{"assessments":[{"ref":"post:p1","relevance":"direct",'
        '"role":"answer_evidence","resolution":"card","confidence":0.9,'
        '"reason_code":"topic_only","content":"generated summary"}],'
        '"source_dispositions":[]}'
    ) is None


def test_sufficiency_excludes_discovery_summaries_and_requires_primary_source() -> None:
    contract = build_turn_contract(
        user_text="Прочитай /note/global/n1/", history=[], scope="global"
    )
    state = {
        "turn_contract": contract,
        "evidence_records": {
            "/note/global/n1/summary": _record("note_summary", "/note/global/n1/summary", "summary"),
        },
        "search_ledger": [],
    }
    result = evaluate_sufficiency(state=state, contract=contract)
    assert result.status == "exhausted"
    assert result.evidence_ids == ()
    assert result.open_requirements

    state["evidence_records"]["/note/global/n1/"] = _record(
        "note_chunk", "/note/global/n1/", "full note"
    )
    ready = evaluate_sufficiency(state=state, contract=contract)
    assert ready.status == "ready"
    assert ready.evidence_ids == ("/note/global/n1/",)
    assert ready.decision_code == "ALL_REQUIRED_EVIDENCE_PRESENT"


def test_plural_corpus_question_does_not_change_source_policy_lexically() -> None:
    contract = build_turn_contract(
        user_text="Какие из заметок рассказывают про мою систему?",
        history=[],
        scope="global",
    )
    source = contract["source_requirements"][0]
    assert source["kind"] == "notes"
    assert source["min_evidence"] == 1

    one = {
        "turn_contract": contract,
        "evidence_records": {"/note/global/n1/": _record("note_chunk", "/note/global/n1/")},
        "search_ledger": [],
    }
    assert evaluate_sufficiency(state=one, contract=contract).status == "ready"
    one["evidence_records"]["/note/global/n2/"] = _record("note_chunk", "/note/global/n2/")
    assert evaluate_sufficiency(state=one, contract=contract).status == "ready"


def test_count_question_is_satisfied_by_complete_catalog_evidence() -> None:
    contract = build_turn_contract(
        user_text="Сколько у меня постов?", history=[], scope="global"
    )
    source = next(
        item for item in contract["source_requirements"] if item["kind"] == "posts"
    )
    assert source["evidence_granularity"] == "full_text"

    state = {
        "turn_contract": contract,
        "evidence_records": {
            "/posts/": _record(
                "catalog",
                "/posts/",
                "Посты пользователя (status=all, total=147, shown=8).",
            )
        },
        "search_ledger": [],
    }
    result = evaluate_sufficiency(state=state, contract=contract)
    assert result.status == "ready"
    assert result.evidence_ids == ("/posts/",)


def test_sufficiency_has_explicit_exhausted_partial_state() -> None:
    contract = build_turn_contract(
        user_text="Что написано в заметках workspace?", history=[], scope="global"
    )
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {},
            "search_ledger": [],
            "planner_calls_used": 2,
            "search_calls_used": 1,
            "deep_reads_used": 1,
            "tool_calls_used": 3,
        },
        contract=contract,
        requested_status="partial",
    )
    assert result.status == "exhausted"
    assert result.decision_code == "PARTIAL_REQUESTED"


def test_selected_summary_candidate_must_be_deep_read() -> None:
    state = {
        "evidence_records": {"/post/other/": _record("post_text", "/post/other/")},
        "selected_candidate_ids": ["selected"],
        "search_ledger": [],
    }
    result = evaluate_sufficiency(state=state, contract={})
    assert result.status == "follow_up_allowed"
    assert "candidate:selected" in result.open_requirements

    state["evidence_records"]["/post/selected/"] = _record(
        "post_text", "/post/selected/"
    )
    assert evaluate_sufficiency(state=state, contract={}).status == "ready"


def test_sufficiency_rejects_malformed_checkpoint_evidence() -> None:
    result = evaluate_sufficiency(
        state={"evidence_records": {"broken": "not-a-record"}}, contract={}
    )
    assert result.status == "invalid"
    assert result.decision_code == "INVALID_EVIDENCE_RECORD"


def test_phase5_fixture_gate_passes() -> None:
    from scripts.agent_phase5_planner_report import build_report, check_report

    fixture_path = Path(__file__).parent / "fixtures/agent_planner_phase5/v1/scenarios.json"
    report = build_report(json.loads(fixture_path.read_text(encoding="utf-8")))
    assert check_report(report) == []
    assert report["phase5"]["estimated_latency_p95_ms"] < report["baseline"]["estimated_latency_p95_ms"]
    assert report["change"]["planner_output_reduction"] >= 0.66


@pytest.mark.asyncio
async def test_compact_planner_uses_450_token_budget_and_emits_no_rationale() -> None:
    from app.services.agent.research.graph import _compact_planner_node

    contract = build_turn_contract(
        user_text="Найди заметки про запуск", history=[], scope="global"
    )
    ctx = SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="test"),
        reasoner_model="test-model",
        reasoner_api_key="key",
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    state = {
        "user_text": "Найди заметки про запуск",
        "turn_contract": contract,
        "evidence_records": {},
        "prefetch_hits": [],
        "search_ledger": [],
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }
    config = {"configurable": {"runtime_context": ctx, "turn_contract": contract}}
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=json.dumps(
            {
                "decision_code": "SEARCH_REQUIRED_SOURCE",
                "actions": [{"tool": "SearchNodes", "args": {"query": "заметки про запуск"}}],
                "state_updates": {},
                "confidence": 0.8,
            }
        ),
    ) as call:
        result = await _compact_planner_node(state, config)
    assert call.await_args.kwargs["max_tokens"] == 450
    assert result["planner_steps"][0]["decision_code"] == "SEARCH_REQUIRED_SOURCE"
    assert "reasoning" not in result["planner_steps"][0]
    assert result["tool_action"]["actions"][0]["tool"] == "SearchNodes"


@pytest.mark.asyncio
async def test_compact_planner_recovers_unsupported_readnode_without_retry() -> None:
    from app.services.agent.research.graph import _compact_planner_node

    contract = build_turn_contract(
        user_text="Какие из заметок рассказывают про мою систему?",
        history=[],
        scope="global",
    )
    ctx = SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="test"),
        reasoner_model="test-model",
        reasoner_api_key="key",
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    state = {
        "user_text": "Какие из заметок рассказывают про мою систему?",
        "turn_contract": contract,
        "evidence_records": {},
        "prefetch_hits": [
            {"ref": "note:n1", "node_type": "note_chunk", "similarity": 0.8},
            {"ref": "post:p1", "node_type": "post_summary", "similarity": 0.7},
            {"ref": "note:n2", "node_type": "note_chunk", "similarity": 0.6},
        ],
        "search_ledger": [],
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }
    invalid_tool = json.dumps(
        {
            "decision_code": "READ_EXPLICIT_TARGET",
            "actions": [{"tool": "ReadNode", "args": {"node_id": "note:n1"}}],
            "state_updates": {},
            "confidence": 0.8,
        }
    )
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=invalid_tool,
    ) as call:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert call.await_count == 1
    assert result["planner_invalid_count"] == 1
    assert result["planner_steps"][0]["decision_code"] == "READ_TOP_CANDIDATES"
    actions = result["tool_action"]["actions"]
    assert [action["tool"] for action in actions] == ["OpenNote", "OpenPost", "OpenNote"]
    assert {
        action["args"]["note_id"]
        for action in actions
        if action["tool"] == "OpenNote"
    } == {"n1", "n2"}


@pytest.mark.asyncio
async def test_compact_planner_cannot_finish_with_actionable_required_source() -> None:
    from app.services.agent.research.graph import _compact_planner_node
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Сколько у меня постов?", history=[], scope="global"
    )
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
    )
    ctx = SimpleNamespace(
        reasoner_spec=SimpleNamespace(name="test"),
        reasoner_model="test-model",
        reasoner_api_key="key",
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    state = {
        "user_text": "Сколько у меня постов?",
        "turn_contract": contract,
        "evidence_records": {},
        "prefetch_hits": [],
        "search_ledger": [],
        "planner_calls_used": 0,
        "planner_invalid_count": 0,
        "planner_steps": [],
        "step_count": 0,
    }
    with patch(
        "app.services.agent.runtime.budget.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=json.dumps(
            {
                "decision_code": "FINISH_PARTIAL",
                "actions": [],
                "state_updates": {},
                "confidence": 0.8,
            }
        ),
    ) as call:
        result = await _compact_planner_node(
            state,
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert call.await_count == 1
    assert result["planner_steps"][0]["decision_code"] == "READ_TOP_CANDIDATES"
    assert result["tool_action"]["actions"] == [
        {
            "tool": "ListPosts",
            "args": {
                "status": "all",
                "source_requirement_id": "workspace-posts",
            },
            "intent_id": None,
        }
    ]


def test_classifier_promotes_complete_semantic_card_source_contract() -> None:
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Опиши все объекты", history=[], scope="global"
    )
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "posts",
                "coverage": "complete",
                "evidence_granularity": "semantic_card",
            }
        ],
    )
    posts = next(
        source for source in contract["source_requirements"] if source["kind"] == "posts"
    )
    assert posts["required"] is True
    assert posts["coverage"] == "complete"
    assert posts["evidence_granularity"] == "semantic_card"


def test_universal_discovery_is_split_by_source_contract() -> None:
    from app.services.agent.research.graph import _contract_discovery_actions

    question = "Какое направление канала лучше выбрать?"
    contract = build_turn_contract(user_text=question, history=[], scope="global")
    actions = _contract_discovery_actions(contract, query=question)

    assert len(actions) == 2
    assert {
        (action.args["source_requirement_id"], tuple(action.args["node_types"]))
        for action in actions
    } == {
        ("workspace-notes", ("note_summary", "note_chunk")),
        ("workspace-posts", ("post_summary", "post_text")),
    }


def test_empty_optional_discovery_finishes_without_planner_follow_up() -> None:
    contract = build_turn_contract(
        user_text="Объясни разницу между двумя подходами", history=[], scope="global"
    )
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {},
            "prefetch_hits": [],
            "search_ledger": [
                {
                    "tool": "SearchNodes",
                    "source_requirement_id": "workspace-notes",
                    "state": "exhausted",
                },
                {
                    "tool": "SearchNodes",
                    "source_requirement_id": "workspace-posts",
                    "state": "exhausted",
                },
            ],
        },
        contract=contract,
    )

    assert result.status == "ready"
    assert result.evidence_ids == ()
    assert result.decision_code == "OPTIONAL_DISCOVERY_COMPLETE"


def test_optional_discovery_with_candidate_still_reaches_planner() -> None:
    contract = build_turn_contract(
        user_text="Как лучше развить направление?", history=[], scope="global"
    )
    result = evaluate_sufficiency(
        state={
            "turn_contract": contract,
            "evidence_records": {},
            "prefetch_hits": [{"ref": "note:n1", "similarity": 0.8}],
            "search_ledger": [],
        },
        contract=contract,
    )

    assert result.status == "follow_up_allowed"


def test_multi_source_discovery_reuses_l1_hits_per_source() -> None:
    from app.services.agent.research.graph import (
        _cached_discovery_hits,
        _contract_discovery_actions,
    )

    question = "Какое направление канала лучше выбрать?"
    contract = build_turn_contract(user_text=question, history=[], scope="global")
    actions = _contract_discovery_actions(contract, query=question)
    l1 = [
        {"ref": "note:n1", "node_type": "note_summary", "similarity": 0.8},
        {"ref": "post:p1", "node_type": "post_summary", "similarity": 0.7},
    ]

    by_source = {
        action.args["source_requirement_id"]: _cached_discovery_hits(l1, action)
        for action in actions
    }
    assert [hit["ref"] for hit in by_source["workspace-notes"]] == ["note:n1"]
    assert [hit["ref"] for hit in by_source["workspace-posts"]] == ["post:p1"]


def test_candidate_refs_are_normalized_before_tool_execution() -> None:
    from app.services.agent.research.graph import _normalize_object_id

    assert _normalize_object_id("note:abc", kind="note") == "abc"
    assert _normalize_object_id("note:note:abc", kind="note") == "abc"
    assert _normalize_object_id("/note/global/abc/", kind="note") == "abc"
    assert _normalize_object_id("post:p1", kind="post") == "p1"
    assert _normalize_object_id("/post/p1/", kind="post") == "p1"


def test_phase5_flag_is_configurable() -> None:
    from app.core.config import Settings

    assert Settings().agent_planner_phase5_enabled is True
    assert Settings(agent_planner_phase5_enabled="0").agent_planner_phase5_enabled is False


@pytest.mark.asyncio
async def test_compact_tool_node_fans_out_independent_actions() -> None:
    from app.core.config import Settings
    from app.services.agent.research.graph import _compact_tool_node
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.ai.rag_tools import AgentState, ToolOutcome

    class SessionContext:
        async def __aenter__(self):
            session = AsyncMock()
            session.commit = AsyncMock()
            return session

        async def __aexit__(self, *exc):
            return False

    class Factory:
        def __call__(self):
            return SessionContext()

    user_id = uuid.uuid4()
    embedding = AsyncMock()
    ctx = RuntimeContext(
        session_factory=Factory(),
        user_id=user_id,
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=embedding,
        scope="global",
        post_data=None,
        ai_profile={},
    )
    ctx.agent_tool_state = AgentState(
        session=AsyncMock(),
        user_id=user_id,
        scope="global",
        tenant_key=None,
        embedding_backend=embedding,
    )
    both_started = asyncio.Event()
    starts = 0

    async def execute(_agent_state, action, *, ledger, contract):
        nonlocal starts
        starts += 1
        if starts == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        entry = {
            "signature": f"sig:{action.tool}",
            "intent_key": f"intent:{action.tool}",
            "tool": action.tool,
            "state": "satisfied",
        }
        return ToolOutcome(summary="ok"), [*ledger, entry], entry, False

    state = {
        "phase5_enabled": True,
        "tool_action": {
            "actions": [
                {"tool": "OpenNote", "args": {"note_id": "n1"}},
                {"tool": "OpenPost", "args": {"post_id": "p1"}},
            ]
        },
        "evidence_records": {},
        "search_ledger": [],
        "tool_outcomes": [],
        "turn_contract": {},
    }
    with patch(
        "app.services.agent.research.graph._execute_ledgered_tool",
        side_effect=execute,
    ):
        result = await _compact_tool_node(
            state, {"configurable": {"runtime_context": ctx}}
        )

    assert starts == 2
    assert result["tool_calls_used"] == 2
    assert {item["tool"] for item in result["tool_outcomes"]} == {"OpenNote", "OpenPost"}
