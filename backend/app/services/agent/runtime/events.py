"""Agent run and event persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEvent, AgentRun

_UNSET = object()


async def create_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    scope: str = "global",
    chat_id: str | None = None,
    post_id: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> AgentRun:
    now = datetime.now(timezone.utc)
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=user_id,
        thread_id=thread_id,
        scope=scope,
        chat_id=chat_id,
        post_id=post_id,
        status="running",
        snapshot=snapshot or {},
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    return run


async def get_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )


async def update_run_status(
    session: AsyncSession,
    run: AgentRun,
    *,
    status: str,
    error: str | None = None,
    current_interrupt: dict[str, Any] | None | object = _UNSET,
    snapshot: dict[str, Any] | None = None,
) -> AgentRun:
    run.status = status
    run.updated_at = datetime.now(timezone.utc)
    if error is not None:
        run.error = error
    if current_interrupt is not _UNSET:
        run.current_interrupt = current_interrupt
    if snapshot is not None:
        run.snapshot = snapshot
    if status in {"completed", "failed", "cancelled"}:
        run.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return run


async def append_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> AgentEvent:
    # Serialize sequence allocation per run. PostgreSQL advisory xact locks are
    # scoped to this transaction and avoid max(sequence)+1 races.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:run_id))"),
        {"run_id": str(run_id)},
    )
    next_seq = await session.scalar(
        select(func.coalesce(func.max(AgentEvent.sequence), 0) + 1).where(
            AgentEvent.run_id == run_id
        )
    )
    sequence = int(next_seq or 1)
    event = AgentEvent(
        id=uuid.uuid4(),
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    after_sequence: int = 0,
    limit: int = 500,
) -> list[AgentEvent]:
    stmt = (
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id, AgentEvent.sequence > after_sequence)
        .order_by(AgentEvent.sequence.asc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())
