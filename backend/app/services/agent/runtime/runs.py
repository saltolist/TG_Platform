"""Agent run orchestration facade."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
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
