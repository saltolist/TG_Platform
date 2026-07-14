"""Durable Celery entrypoint for WorkspaceAgent runs."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models import AgentRun, User
from app.db.session import async_session_factory
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.executor import execute_agent_run
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run
from app.tasks.async_runtime import run_async


async def _execute_agent_run(run_id: uuid.UUID, user_text: str) -> None:
    await ensure_checkpointer_ready()
    async with async_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id))
        if run is None or run.status in {"completed", "cancelled", "interrupted"}:
            return
        user = await session.scalar(select(User).where(User.id == run.user_id))
        if user is None:
            return
        # Single source of truth for context assembly, shared with HITL resume
        # (agent-runtime-sprints §1.5).
        context = await rebuild_runtime_context_for_run(session, run)
        await execute_agent_run(
            session,
            run=run,
            user=user,
            user_text=user_text,
            runtime_context=context,
        )


@celery_app.task(
    name="app.tasks.agent_runs.execute_agent_run_task",
    bind=True,
    acks_late=True,
    max_retries=5,
)
def execute_agent_run_task(self, run_id: str, user_text: str) -> None:
    try:
        run_async(_execute_agent_run(uuid.UUID(run_id), user_text))
    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=min(60, 2 ** min(self.request.retries, 5)),
        )

