"""Agent run orchestration facade."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Post, Profile, User
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.context import RuntimeContext


async def start_run(
    session: AsyncSession,
    *,
    user: User,
    thread_id: str,
    scope: str = "global",
    chat_id: str | None = None,
    post_id: str | None = None,
) -> tuple[Any, int]:
    run = await event_service.create_run(
        session,
        user_id=user.id,
        thread_id=thread_id,
        scope=scope,
        chat_id=chat_id,
        post_id=post_id,
    )
    evt = await event_service.append_event(
        session,
        run_id=run.id,
        event_type="run_started",
        payload={"thread_id": thread_id, "scope": scope},
    )
    await session.commit()
    return run, evt.sequence


def build_runtime_context(
    *,
    session_factory,
    user: User,
    tenant_key: str | None,
    settings,
    embedding_backend,
    scope: str,
    post_data: dict[str, Any] | None,
    ai_profile: dict[str, Any],
) -> RuntimeContext:
    return RuntimeContext(
        session_factory=session_factory,
        user_id=user.id,
        user=user,
        tenant_key=tenant_key,
        settings=settings,
        embedding_backend=embedding_backend,
        scope=scope,
        post_data=post_data,
        ai_profile=ai_profile,
    )


async def rebuild_runtime_context_for_run(session: AsyncSession, run: AgentRun) -> RuntimeContext:
    """Reconstruct the full RuntimeContext for a persisted run.

    Used by the initial executor and, crucially, by HITL resume — the resume
    cfg must carry runtime_context or any research/answer node reached after the
    interrupt raises KeyError on config["configurable"]["runtime_context"]
    (agent-runtime-sprints §1.5). Single source of truth for context assembly so
    the two paths cannot drift.
    """
    from app.core.config import get_settings
    from app.db.session import async_session_factory
    from app.services.ai.embeddings import resolve_embedding_backend
    from app.services.ai.rag_reasoner import resolve_rag_reasoner_llm

    settings = get_settings()
    user = await session.scalar(select(User).where(User.id == run.user_id))
    if user is None:
        raise RuntimeError("agent_run_user_not_found")
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
    return RuntimeContext(
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
