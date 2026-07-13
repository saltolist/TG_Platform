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
