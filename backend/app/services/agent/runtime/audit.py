"""Agent audit event writers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentAuditEvent


async def write_audit_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_kind: str,
    run_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AgentAuditEvent:
    row = AgentAuditEvent(
        id=uuid.uuid4(),
        user_id=user_id,
        run_id=run_id,
        event_kind=event_kind,
        detail=detail or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row
