"""Small concurrency checks for the durable event path."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.models import AgentEvent
from app.services.agent.runtime.events import append_event, create_run
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_concurrent_event_sequences_are_unique(writer_user) -> None:
    async with TestSessionLocal() as session:
        run = await create_run(
            session,
            user_id=writer_user.id,
            thread_id="load-sequence",
            scope="global",
        )
        await session.commit()
        run_id = run.id

    async def append(index: int) -> int:
        async with TestSessionLocal() as session:
            event = await append_event(
                session,
                run_id=run_id,
                event_type="load_probe",
                payload={"index": index},
            )
            await session.commit()
            return event.sequence

    sequences = await asyncio.gather(*(append(index) for index in range(25)))
    assert sorted(sequences) == list(range(1, 26))

    async with TestSessionLocal() as session:
        persisted = (
            await session.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id)
                .order_by(AgentEvent.sequence)
            )
        ).all()
        assert [event.sequence for event in persisted] == list(range(1, 26))

