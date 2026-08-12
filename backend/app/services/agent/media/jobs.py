"""Durable media generation jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaJob


async def create_media_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    run_id: uuid.UUID | None,
    job_type: str,
    provider: str,
    model: str,
    brief: dict[str, Any],
    reserved_cost: float | None = None,
) -> MediaJob:
    now = datetime.now(timezone.utc)
    job = MediaJob(
        id=uuid.uuid4(),
        user_id=user_id,
        run_id=run_id,
        job_type=job_type,
        provider=provider,
        model=model,
        status="queued",
        stage="submit",
        progress=0.0,
        brief=brief,
        reserved_cost=reserved_cost,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()
    return job


async def get_media_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> MediaJob | None:
    return await session.scalar(
        select(MediaJob).where(MediaJob.id == job_id, MediaJob.user_id == user_id)
    )


async def update_job_progress(
    session: AsyncSession,
    job: MediaJob,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: float | None = None,
    asset_id: uuid.UUID | None = None,
    error: str | None = None,
) -> MediaJob:
    job.updated_at = datetime.now(timezone.utc)
    if status is not None:
        job.status = status
    if stage is not None:
        job.stage = stage
    if progress is not None:
        job.progress = progress
    if asset_id is not None:
        job.asset_id = asset_id
    if error is not None:
        job.error = error
    if status in {"completed", "failed", "cancelled"}:
        job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job


async def cancel_media_job(session: AsyncSession, job: MediaJob) -> MediaJob:
    if job.status in {"completed", "cancelled"}:
        return job
    if job.celery_task_id:
        try:
            from app.celery_app import celery_app

            celery_app.control.revoke(job.celery_task_id, terminate=False)
        except Exception:
            pass
    if job.provider_operation_id:
        try:
            from app.tasks.media_generation import cancel_media_generation_job

            cancel_media_generation_job.delay(str(job.id))
        except Exception:
            pass
    return await update_job_progress(session, job, status="cancelled", stage="cancelled")


async def enqueue_media_job(session: AsyncSession, job: MediaJob) -> MediaJob:
    from app.tasks.media_generation import run_media_generation_job

    async_result = run_media_generation_job.delay(str(job.id))
    job.celery_task_id = async_result.id
    await session.flush()
    return job
