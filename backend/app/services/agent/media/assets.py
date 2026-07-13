"""Media asset records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaAsset


async def create_media_asset(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID | None,
    object_key: str,
    mime_type: str,
    byte_size: int,
    checksum: str | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_sec: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> MediaAsset:
    asset = MediaAsset(
        id=uuid.uuid4(),
        user_id=user_id,
        job_id=job_id,
        object_key=object_key,
        mime_type=mime_type,
        byte_size=byte_size,
        checksum=checksum,
        width=width,
        height=height,
        duration_sec=duration_sec,
        metadata_=metadata or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(asset)
    await session.flush()
    return asset
