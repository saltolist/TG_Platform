"""Immutable action proposals with HITL."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionProposal, AgentRun


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create_proposal(
    session: AsyncSession,
    *,
    run: AgentRun,
    user_id: uuid.UUID,
    command: str,
    payload: dict[str, Any],
    resource_version: str | None = None,
    warnings: list[str] | None = None,
    ttl_minutes: int = 30,
) -> ActionProposal:
    idem = f"{run.id}:{command}:{payload_hash(payload)}"
    existing = await session.scalar(
        select(ActionProposal).where(ActionProposal.idempotency_key == idem)
    )
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    proposal = ActionProposal(
        id=uuid.uuid4(),
        run_id=run.id,
        user_id=user_id,
        command=command,
        payload=payload,
        payload_hash=payload_hash(payload),
        resource_version=resource_version,
        warnings=warnings or [],
        status="pending",
        idempotency_key=idem,
        expires_at=now + timedelta(minutes=ttl_minutes),
        created_at=now,
    )
    session.add(proposal)
    await session.flush()
    return proposal


async def approve_proposal(
    session: AsyncSession,
    *,
    proposal: ActionProposal,
    approved_hash: str,
) -> ActionProposal:
    if proposal.status == "approved" and proposal.result:
        return proposal
    if proposal.status != "pending":
        raise ValueError(f"proposal_not_pending:{proposal.status}")
    if proposal.expires_at and proposal.expires_at < datetime.now(timezone.utc):
        proposal.status = "expired"
        await session.flush()
        raise ValueError("proposal_expired")
    if approved_hash != proposal.payload_hash:
        raise ValueError("payload_hash_mismatch")
    proposal.status = "approved"
    proposal.approved_at = datetime.now(timezone.utc)
    await session.flush()
    return proposal
