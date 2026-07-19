"""Celery entrypoint for resumable exhaustive Workspace Agent jobs."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models import AgentBatchJob, AgentRun
from app.db.session import async_session_factory
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.batch import process_batch_page
from app.services.agent.runtime.observability import (
    AGENT_BATCH_ITEMS,
    AGENT_BATCH_PAGE_DURATION,
    AGENT_BATCH_PAGES,
    AGENT_DURATION,
    AGENT_DURATION_BY_MODE,
    AGENT_RUNS,
)
from app.tasks.async_runtime import run_async

logger = logging.getLogger(__name__)


async def _process_agent_batch(job_id: uuid.UUID) -> dict[str, object]:
    async with async_session_factory() as session:
        job = await session.scalar(select(AgentBatchJob).where(AgentBatchJob.id == job_id))
        if job is None:
            return {"status": "missing", "requeue": False}
        run = await session.get(AgentRun, job.run_id) if job.run_id else None
        if run is not None and run.status == "cancelled":
            job.status = "cancelled"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"status": "cancelled", "requeue": False}

        outcome = await process_batch_page(session, job_id=job_id)
        job = await session.get(AgentBatchJob, job_id)
        if job is None:
            await session.commit()
            return outcome
        payload = {key: value for key, value in outcome.items() if key != "requeue"}
        if run is not None:
            snapshot = dict(run.snapshot or {})
            snapshot["batch_job"] = payload
            await event_service.append_event(
                session,
                run_id=run.id,
                event_type="batch_progress",
                payload=payload,
            )
            if job.status == "completed":
                answer = (
                    "Пакетная инвентаризация завершена: "
                    f"обработано {job.processed_items} из "
                    f"{job.total_items or 0} объектов."
                )
                snapshot.update(
                    {
                        "status": "completed",
                        "answer_text": answer,
                        "output_schema": "exhaustive_inventory.v1",
                        "batch_result": dict(job.result_summary or {}),
                    }
                )
                await event_service.update_run_status(
                    session, run, status="completed", snapshot=snapshot
                )
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="answer",
                    payload={
                        "text": answer,
                        "claims": [],
                        "evidence_ids": [],
                        "output_schema": "exhaustive_inventory.v1",
                        "batch_job_id": str(job.id),
                    },
                )
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="run_metrics",
                    payload={
                        "schema": "workspace.run-metrics/v1",
                        "execution_mode": "batch",
                        "db_calls": job.db_calls,
                        "llm_calls": job.llm_calls,
                        "processed_items": job.processed_items,
                    },
                )
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="run_completed",
                    payload={"status": "completed", "batch_job_id": str(job.id)},
                )
                total_seconds = max(
                    0.0,
                    (job.completed_at - job.created_at).total_seconds()
                    if job.completed_at
                    else 0.0,
                )
                AGENT_DURATION.observe(total_seconds)
                AGENT_DURATION_BY_MODE.labels("batch", "warm").observe(total_seconds)
                AGENT_RUNS.labels("completed").inc()
            elif job.status == "failed":
                await event_service.update_run_status(
                    session, run, status="failed", error=job.error, snapshot=snapshot
                )
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="run_failed",
                    payload={"error": job.error or "batch_failed"},
                )
                AGENT_RUNS.labels("failed").inc()
            else:
                run.snapshot = snapshot
        await session.commit()
        return outcome


async def _fail_batch(job_id: uuid.UUID, error: str) -> None:
    async with async_session_factory() as session:
        job = await session.get(AgentBatchJob, job_id)
        if job is None or job.status in {"completed", "cancelled"}:
            return
        job.status = "failed"
        job.error = error[:2000]
        job.completed_at = datetime.now(timezone.utc)
        if job.run_id:
            run = await session.get(AgentRun, job.run_id)
            if run is not None:
                await event_service.update_run_status(
                    session, run, status="failed", error=job.error
                )
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="run_failed",
                    payload={"error": "batch_failed"},
                )
        await session.commit()


@celery_app.task(
    name="app.tasks.agent_batch.execute_agent_batch_task",
    bind=True,
    acks_late=True,
    max_retries=5,
)
def execute_agent_batch_task(self, job_id: str) -> None:
    batch_id = uuid.UUID(job_id)
    started_at = time.perf_counter()
    try:
        outcome = run_async(_process_agent_batch(batch_id))
    except Exception as exc:
        logger.exception("Agent batch %s page failed", job_id)
        if self.request.retries >= self.max_retries - 1:
            run_async(_fail_batch(batch_id, str(exc)))
            raise
        raise self.retry(exc=exc, countdown=min(60, 2 ** min(self.request.retries, 5)))
    AGENT_BATCH_PAGE_DURATION.observe(time.perf_counter() - started_at)
    AGENT_BATCH_PAGES.labels(str(outcome.get("status") or "unknown")).inc()
    page_items = int(outcome.get("page_items") or 0)
    if page_items:
        AGENT_BATCH_ITEMS.labels(str(outcome.get("page_kind") or "unknown")).inc(page_items)
    if outcome.get("requeue"):
        page = int(((outcome.get("cursor") or {}).get("page") or 0))
        result = self.apply_async(
            args=[job_id],
            task_id=f"agent-batch:{job_id}:{page}",
        )

        async def _record_task_id() -> None:
            async with async_session_factory() as session:
                job = await session.get(AgentBatchJob, batch_id)
                if job is not None:
                    job.celery_task_id = result.id
                    await session.commit()

        run_async(_record_task_id())
