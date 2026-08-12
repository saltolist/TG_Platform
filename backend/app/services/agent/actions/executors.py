"""Deterministic action executors — invoked only after approval."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionProposal, User
from app.services.posts.commands import execute_post_command


async def execute_approved_proposal(
    session: AsyncSession,
    *,
    proposal: ActionProposal,
    user: User,
) -> dict[str, Any]:
    await session.refresh(proposal, with_for_update=True)
    if proposal.status == "applied" and proposal.result:
        return dict(proposal.result)
    if proposal.status == "approved" and proposal.result:
        return dict(proposal.result)

    result = await execute_post_command(
        session,
        user=user,
        command=proposal.command,
        payload=proposal.payload,
        resource_version=proposal.resource_version,
    )
    proposal.result = result
    proposal.status = "applied"
    await session.flush()
    return result
