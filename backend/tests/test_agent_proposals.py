"""Action proposal HITL tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.db.models import ActionProposal, AgentRun
from app.services.agent.actions.policy import requires_approval
from app.services.agent.actions.proposals import approve_proposal, create_proposal, payload_hash


def test_all_post_mutations_require_approval() -> None:
    assert requires_approval("create_post") is True
    assert requires_approval("edit_post") is True
    assert requires_approval("search_nodes") is False


def test_payload_hash_stable() -> None:
    p = {"a": 1, "b": 2}
    assert payload_hash(p) == payload_hash({"b": 2, "a": 1})


@pytest.mark.asyncio
async def test_approve_proposal_idempotent_hash() -> None:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.add = lambda obj: None

    run = AgentRun(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        thread_id="t1",
    )
    proposal = await create_proposal(
        session,
        run=run,
        user_id=run.user_id,
        command="edit_post",
        payload={"post_id": "p1", "patch": {"text": "hi"}},
    )
    with pytest.raises(ValueError, match="payload_hash_mismatch"):
        await approve_proposal(session, proposal=proposal, approved_hash="bad")

    approved = await approve_proposal(session, proposal=proposal, approved_hash=proposal.payload_hash)
    assert approved.status == "approved"


@pytest.mark.asyncio
async def test_execute_applied_proposal_is_idempotent() -> None:
    from unittest.mock import AsyncMock

    from app.db.models import AgentRun
    from app.services.agent.actions.executors import execute_approved_proposal

    session = AsyncMock()
    session.flush = AsyncMock()
    user_id = uuid.uuid4()
    run = AgentRun(id=uuid.uuid4(), user_id=user_id, thread_id="t1")
    proposal = ActionProposal(
        id=uuid.uuid4(),
        run_id=run.id,
        user_id=user_id,
        command="edit_post",
        payload={"post_id": "p1", "patch": {"text": "hi"}},
        payload_hash="hash",
        idempotency_key="k1",
        status="applied",
        result={"post_id": "p1"},
    )
    user = type("U", (), {"id": user_id})()
    result = await execute_approved_proposal(session, proposal=proposal, user=user)
    assert result == {"post_id": "p1"}
    session.flush.assert_not_called()


# --- Спринт 5: HITL текст отражает реальный результат исполнения ---


def test_action_result_text_reflects_real_execution() -> None:
    from app.services.agent.runtime.workspace_graph import _action_result_text

    approved = _action_result_text(
        {"decision": "approve", "applied": {"post_id": "p1", "status": "published"}}
    )
    assert "выполнено" in approved
    assert "p1" in approved and "published" in approved


def test_action_result_text_approve_without_result_is_honest() -> None:
    from app.services.agent.runtime.workspace_graph import _action_result_text

    # Апрув прошёл, но результат исполнения не прокинут — не врём «выполнено».
    text = _action_result_text({"decision": "approve", "applied": None})
    assert "недоступен" in text


def test_action_result_text_reject() -> None:
    from app.services.agent.runtime.workspace_graph import _action_result_text

    assert _action_result_text({"decision": "reject"}) == "Предложенное действие отклонено."


def test_tool_outcome_payload_extracts_latest() -> None:
    from app.services.agent.runtime.executor import _tool_outcome_payload

    chunk = {"tool": {"tool_outcomes": [
        {"step": 0, "tool": "OpenNote", "error": None},
        {"step": 1, "tool": "ListPosts", "error": None},
    ]}}
    assert _tool_outcome_payload(chunk)["tool"] == "ListPosts"
    # Не tool-узел / пусто → None.
    assert _tool_outcome_payload({"planner": {"planner_steps": [{}]}}) is None
    assert _tool_outcome_payload({"tool": {"tool_outcomes": []}}) is None
