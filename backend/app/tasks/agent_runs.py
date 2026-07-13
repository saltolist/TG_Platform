"""Durable Celery entrypoint for WorkspaceAgent runs."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.models import AgentRun, Post, Profile, User
from app.db.session import async_session_factory
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.executor import execute_agent_run
from app.services.ai.embeddings import resolve_embedding_backend
from app.services.ai.rag_reasoner import resolve_rag_reasoner_llm
from app.tasks.async_runtime import run_async


async def _execute_agent_run(run_id: uuid.UUID, user_text: str) -> None:
    settings = get_settings()
    await ensure_checkpointer_ready()
    async with async_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id))
        if run is None or run.status in {"completed", "cancelled", "interrupted"}:
            return
        user = await session.scalar(select(User).where(User.id == run.user_id))
        if user is None:
            return
        profile = await session.get(Profile, user.id)
        ai_profile = dict(profile.ai or {}) if profile else {}
        reasoner = resolve_rag_reasoner_llm(user, ai_profile, settings)
        post_data = None
        if run.post_id:
            try:
                post_uuid = uuid.UUID(run.post_id)
            except ValueError:
                post_uuid = None
            if post_uuid:
                post = await session.scalar(
                    select(Post).where(Post.id == post_uuid, Post.user_id == user.id)
                )
                post_data = dict(post.data) if post else None
        context = RuntimeContext(
            session_factory=async_session_factory,
            user_id=user.id,
            user=user,
            tenant_key=None,
            settings=settings,
            embedding_backend=resolve_embedding_backend(user, ai_profile, settings),
            scope=run.scope,
            post_data=post_data,
            ai_profile=ai_profile,
            reasoner_spec=reasoner[0] if reasoner else None,
            reasoner_model=reasoner[1] if reasoner else "",
            reasoner_api_key=reasoner[2] if reasoner else "",
        )
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

