"""Resumable, paginated exhaustive-workspace batch execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentBatchItem, AgentBatchJob, AgentRun, GlobalNote, Post
from app.services.agent.runtime.profile_limits import limits_for_profile
from app.services.ai.rag import _post_title_from_text, object_index_revision

BATCH_SCHEMA = "workspace.agent-batch/v1"
BATCH_ITEM_SCHEMA = "workspace.agent-batch-item/v1"
MIN_PAGE_SIZE = 10
MAX_PAGE_SIZE = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_page_size(value: int) -> int:
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, int(value or 100)))


async def create_batch_job(
    session: AsyncSession,
    *,
    run: AgentRun,
    query: str,
    tenant_key: str | None,
    page_size: int = 100,
    max_items: int = 10_000,
) -> tuple[AgentBatchJob, bool]:
    existing = await session.scalar(
        select(AgentBatchJob).where(AgentBatchJob.run_id == run.id)
    )
    if existing is not None:
        return existing, False
    limits = limits_for_profile("exhaustive_inventory")
    effective_page_size = _bounded_page_size(page_size)
    max_budgeted_pages = max(1, (limits.max_db_calls - 4) // 2)
    effective_max_items = min(
        max(1, int(max_items)),
        effective_page_size * max_budgeted_pages,
    )
    job = AgentBatchJob(
        id=uuid.uuid4(),
        run_id=run.id,
        user_id=run.user_id,
        tenant_key=str(tenant_key or ""),
        job_type="exhaustive_inventory",
        scope=run.scope,
        query=query,
        status="queued",
        page_size=effective_page_size,
        max_items=effective_max_items,
        max_db_calls=limits.max_db_calls,
        max_llm_calls=limits.max_llm_calls,
        cursor={"kind": "notes", "after_id": None, "page": 0},
        checkpoint={"schema": BATCH_SCHEMA, "state": "queued"},
        result_summary={
            "schema": BATCH_SCHEMA,
            "notes": 0,
            "posts": 0,
            "truncated": False,
        },
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(job)
    await session.flush()
    return job, True


def serialize_batch_job(job: AgentBatchJob) -> dict[str, Any]:
    total = int(job.total_items or 0)
    processed = int(job.processed_items or 0)
    progress = (
        min(1.0, processed / total)
        if total
        else (1.0 if job.status == "completed" else 0.0)
    )
    return {
        "schema": BATCH_SCHEMA,
        "id": str(job.id),
        "run_id": str(job.run_id) if job.run_id else None,
        "job_type": job.job_type,
        "status": job.status,
        "scope": job.scope,
        "cursor": dict(job.cursor or {}),
        "checkpoint": dict(job.checkpoint or {}),
        "processed_items": processed,
        "total_items": job.total_items,
        "progress": round(progress, 4),
        "db_calls": int(job.db_calls or 0),
        "llm_calls": int(job.llm_calls or 0),
        "limits": {
            "max_items": job.max_items,
            "max_db_calls": job.max_db_calls,
            "max_llm_calls": job.max_llm_calls,
        },
        "result_summary": dict(job.result_summary or {}),
        "error": job.error,
    }


def _note_item(row: GlobalNote, sequence: int) -> dict[str, Any]:
    data = dict(row.data or {})
    source_id = str(data.get("id") or row.id)
    title = str(data.get("title") or source_id).strip() or source_id
    body = str(data.get("body") or "")
    return {
        "id": uuid.uuid4(),
        "sequence": sequence,
        "object_kind": "note",
        "source_id": source_id,
        "source_revision": object_index_revision(data),
        "payload": {
            "schema": BATCH_ITEM_SCHEMA,
            "title": title,
            "status": str(data.get("status") or "active"),
            "excerpt": body[:4000],
            "row_id": str(row.id),
        },
    }


def _post_item(row: Post, sequence: int) -> dict[str, Any]:
    data = dict(row.data or {})
    source_id = str(data.get("id") or row.id)
    text_value = str(data.get("text") or "")
    return {
        "id": uuid.uuid4(),
        "sequence": sequence,
        "object_kind": "post",
        "source_id": source_id,
        "source_revision": object_index_revision(data),
        "payload": {
            "schema": BATCH_ITEM_SCHEMA,
            "title": _post_title_from_text(text_value) if text_value else source_id,
            "status": str(data.get("status") or "draft"),
            "excerpt": text_value[:4000],
            "row_id": str(row.id),
        },
    }


async def _initialize_total(session: AsyncSession, job: AgentBatchJob) -> None:
    totals = (
        await session.execute(
            select(
                select(func.count(GlobalNote.id))
                .where(GlobalNote.user_id == job.user_id)
                .scalar_subquery(),
                select(func.count(Post.id)).where(Post.user_id == job.user_id).scalar_subquery(),
            )
        )
    ).one()
    job.db_calls += 1
    job.total_items = int(totals[0] or 0) + int(totals[1] or 0)


async def process_batch_page(session: AsyncSession, *, job_id: uuid.UUID) -> dict[str, Any]:
    """Materialize one keyset page and commit its cursor in the same transaction."""

    job = await session.scalar(
        select(AgentBatchJob).where(AgentBatchJob.id == job_id).with_for_update()
    )
    if job is None:
        return {"status": "missing", "requeue": False}
    if job.status in {"completed", "cancelled"}:
        return {**serialize_batch_job(job), "page_items": 0, "requeue": False}
    if job.status == "paused":
        return {**serialize_batch_job(job), "page_items": 0, "requeue": False}

    job.status = "running"
    job.updated_at = _utcnow()
    if job.total_items is None:
        await _initialize_total(session, job)

    if job.db_calls + 2 > job.max_db_calls:
        job.status = "failed"
        job.error = "db_call_budget_exhausted"
        job.completed_at = _utcnow()
        return {**serialize_batch_job(job), "page_items": 0, "requeue": False}
    if job.llm_calls > job.max_llm_calls:
        job.status = "failed"
        job.error = "llm_call_budget_exhausted"
        job.completed_at = _utcnow()
        return {**serialize_batch_job(job), "page_items": 0, "requeue": False}

    cursor = dict(job.cursor or {})
    kind = str(cursor.get("kind") or "notes")
    after_id = cursor.get("after_id")
    remaining = max(0, int(job.max_items) - int(job.processed_items or 0))
    if remaining <= 0:
        summary = dict(job.result_summary or {})
        summary["truncated"] = int(job.processed_items or 0) < int(job.total_items or 0)
        job.result_summary = summary
        job.status = "completed"
        job.completed_at = _utcnow()
        job.cursor = {"kind": "done", "after_id": None, "page": cursor.get("page", 0)}
        return {**serialize_batch_job(job), "page_items": 0, "requeue": False}

    limit = min(job.page_size, remaining)
    row_id = uuid.UUID(str(after_id)) if after_id else None
    if kind == "notes":
        stmt = select(GlobalNote).where(GlobalNote.user_id == job.user_id)
        if row_id is not None:
            stmt = stmt.where(GlobalNote.id > row_id)
        rows = list((await session.scalars(stmt.order_by(GlobalNote.id).limit(limit))).all())
        items = [
            _note_item(row, int(job.processed_items or 0) + index)
            for index, row in enumerate(rows, start=1)
        ]
    elif kind == "posts":
        stmt = select(Post).where(Post.user_id == job.user_id)
        if row_id is not None:
            stmt = stmt.where(Post.id > row_id)
        rows = list((await session.scalars(stmt.order_by(Post.id).limit(limit))).all())
        items = [
            _post_item(row, int(job.processed_items or 0) + index)
            for index, row in enumerate(rows, start=1)
        ]
    else:
        rows = []
        items = []
    job.db_calls += 1

    if items:
        values = [{**item, "job_id": job.id} for item in items]
        await session.execute(
            insert(AgentBatchItem)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["job_id", "object_kind", "source_id"]
            )
        )
        job.db_calls += 1
        job.processed_items += len(items)
        summary = dict(job.result_summary or {})
        summary[f"{kind}"] = int(summary.get(kind) or 0) + len(items)
        job.result_summary = summary
        job.cursor = {
            "kind": kind,
            "after_id": str(rows[-1].id),
            "page": int(cursor.get("page") or 0) + 1,
        }
    else:
        next_kind = "posts" if kind == "notes" else "done"
        job.cursor = {
            "kind": next_kind,
            "after_id": None,
            "page": int(cursor.get("page") or 0) + 1,
        }

    done = (
        job.cursor.get("kind") == "done"
        or int(job.processed_items or 0) >= int(job.max_items)
        or int(job.processed_items or 0) >= int(job.total_items or 0)
    )
    job.checkpoint = {
        "schema": BATCH_SCHEMA,
        "state": "completed" if done else "running",
        "cursor": dict(job.cursor),
        "processed_items": int(job.processed_items or 0),
        "db_calls": int(job.db_calls or 0),
        "llm_calls": int(job.llm_calls or 0),
    }
    if done:
        summary = dict(job.result_summary or {})
        summary["truncated"] = int(job.processed_items or 0) < int(job.total_items or 0)
        job.result_summary = summary
        job.status = "completed"
        job.completed_at = _utcnow()
    await session.flush()
    return {
        **serialize_batch_job(job),
        "page_kind": kind,
        "page_items": len(items),
        "requeue": not done,
    }


async def list_batch_items(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    after_sequence: int = 0,
    limit: int = 100,
) -> list[AgentBatchItem]:
    return list(
        (
            await session.scalars(
                select(AgentBatchItem)
                .where(
                    AgentBatchItem.job_id == job_id,
                    AgentBatchItem.sequence > after_sequence,
                )
                .order_by(AgentBatchItem.sequence)
                .limit(max(1, min(MAX_PAGE_SIZE, int(limit))))
            )
        ).all()
    )


async def resume_batch_job(session: AsyncSession, job: AgentBatchJob) -> AgentBatchJob:
    if job.status not in {"failed", "paused"}:
        return job
    job.status = "queued"
    job.error = None
    job.completed_at = None
    job.updated_at = _utcnow()
    checkpoint = dict(job.checkpoint or {})
    checkpoint["state"] = "queued"
    job.checkpoint = checkpoint
    await session.flush()
    return job
