"""Agent runs API — durable execution, events, resume, cancel."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import ActionProposal, MediaAsset
from app.schemas.requests import StartAgentRunRequest
from app.services.agent.actions.executors import execute_approved_proposal
from app.services.agent.actions.proposals import approve_proposal
from app.services.agent.media.jobs import cancel_media_job, get_media_job
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.audit import write_audit_event
from app.services.agent.runtime.executor import resume_agent_graph
from app.services.agent.runtime.runs import start_run
from app.services.agent.runtime.sse_events import (
    format_agent_sse_event,
    parse_last_event_id,
)

router = APIRouter(prefix="/ai/runs", tags=["Agent Runs"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class StartRunRequest(StartAgentRunRequest):
    pass


class ResumeRequest(BaseModel):
    interrupt_id: str | None = None
    decision: str = "approve"
    payload_hash: str | None = None
    proposal_id: str | None = None


@router.post("/", status_code=201)
async def create_agent_run(
    body: StartRunRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    settings = get_settings()
    if settings.agent_runtime_engine != "langgraph":
        raise HTTPException(status_code=501, detail="Agent runtime disabled")
    run, seq = await start_run(
        session,
        user=user,
        thread_id=body.thread_id,
        scope=body.scope,
        chat_id=body.chat_id,
        post_id=body.post_id,
        post_chat_id=body.post_chat_id,
    )
    if body.user_text.strip():
        from app.tasks.agent_runs import execute_agent_run_task

        execute_agent_run_task.apply_async(
            args=[str(run.id), body.user_text],
            task_id=f"agent-run:{run.id}",
        )
    return {
        "id": str(run.id),
        "thread_id": run.thread_id,
        "status": run.status,
        "sequence": seq,
    }


@router.get("/{run_id}/")
async def get_agent_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    run = await event_service.get_run(session, user_id=user.id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": str(run.id),
        "thread_id": run.thread_id,
        "status": run.status,
        "scope": run.scope,
        "chat_id": run.chat_id,
        "post_id": run.post_id,
        "post_chat_id": run.post_chat_id,
        "current_interrupt": run.current_interrupt,
        "snapshot": run.snapshot,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/{run_id}/events/")
async def stream_agent_events(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, ge=0),
) -> StreamingResponse:
    run = await event_service.get_run(session, user_id=user.id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    after_seq = after if after is not None else parse_last_event_id(last_event_id)

    async def _gen():
        import asyncio

        from app.db.session import async_session_factory

        cursor = after_seq
        idle_rounds = 0
        while True:
            async with async_session_factory() as poll_session:
                events = await event_service.list_events(
                    poll_session,
                    run_id=run_id,
                    after_sequence=cursor,
                )
                run_row = await event_service.get_run(
                    poll_session,
                    user_id=user.id,
                    run_id=run_id,
                )
            for evt in events:
                cursor = evt.sequence
                idle_rounds = 0
                yield format_agent_sse_event(
                    sequence=evt.sequence,
                    event_type=evt.event_type,
                    payload=evt.payload,
                )
            if run_row and run_row.status in {"completed", "failed", "cancelled"}:
                break
            if not events:
                idle_rounds += 1
                if idle_rounds % 40 == 0:
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/{run_id}/resume/")
async def resume_agent_run(
    run_id: uuid.UUID,
    body: ResumeRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    run = await event_service.get_run(session, user_id=user.id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"running", "interrupted"}:
        raise HTTPException(status_code=409, detail=f"Run not resumable: {run.status}")

    settings = get_settings()
    result: dict[str, Any] = {"run_id": str(run.id), "decision": body.decision}

    if body.proposal_id and body.payload_hash and settings.agent_actions_enabled:
        proposal = await session.scalar(
            select(ActionProposal).where(
                ActionProposal.id == uuid.UUID(body.proposal_id),
                ActionProposal.run_id == run.id,
                ActionProposal.user_id == user.id,
            )
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if body.decision == "approve":
            await approve_proposal(session, proposal=proposal, approved_hash=body.payload_hash)
            applied = await execute_approved_proposal(session, proposal=proposal, user=user)
            await write_audit_event(
                session,
                user_id=user.id,
                run_id=run.id,
                event_kind="proposal_applied",
                detail={"proposal_id": str(proposal.id), "command": proposal.command},
            )
            result["proposal"] = {"id": str(proposal.id), "result": applied}
        elif body.decision == "reject":
            proposal.status = "rejected"
            await session.flush()
            await write_audit_event(
                session,
                user_id=user.id,
                run_id=run.id,
                event_kind="proposal_rejected",
                detail={"proposal_id": str(proposal.id)},
            )
            result["proposal"] = {"id": str(proposal.id), "status": "rejected"}

    if run.status == "interrupted":
        await resume_agent_graph(
            session,
            run=run,
            resume_value={
                "decision": body.decision,
                "proposal_id": body.proposal_id,
                "payload_hash": body.payload_hash,
                "interrupt_id": body.interrupt_id,
            },
        )
    else:
        await event_service.append_event(
            session,
            run_id=run.id,
            event_type="resumed",
            payload=result,
        )
        await event_service.update_run_status(session, run, status="running", current_interrupt=None)
    await session.commit()
    return result


@router.post("/{run_id}/cancel/")
async def cancel_agent_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    job_id: str | None = None,
) -> dict[str, Any]:
    run = await event_service.get_run(session, user_id=user.id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if job_id and get_settings().agent_media_enabled:
        job = await get_media_job(session, user_id=user.id, job_id=uuid.UUID(job_id))
        if job is not None:
            await cancel_media_job(session, job)

    await event_service.update_run_status(session, run, status="cancelled")
    await event_service.append_event(
        session,
        run_id=run.id,
        event_type="cancelled",
        payload={"job_id": job_id},
    )
    await session.commit()
    return {"id": str(run.id), "status": "cancelled"}


@router.get("/{run_id}/media/{job_id}/")
async def get_agent_media_job(
    run_id: uuid.UUID,
    job_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    run = await event_service.get_run(session, user_id=user.id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    job = await get_media_job(session, user_id=user.id, job_id=job_id)
    if job is None or job.run_id != run.id:
        raise HTTPException(status_code=404, detail="Media job not found")
    preview_url = None
    if job.asset_id:
        asset = await session.get(MediaAsset, job.asset_id)
        if asset is not None:
            from app.services.agent.media.storage import MediaStorage

            preview_url = MediaStorage(get_settings()).signed_preview_url(asset.object_key)
    return {
        "id": str(job.id),
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "reserved_cost": float(job.reserved_cost) if job.reserved_cost is not None else None,
        "preview_url": preview_url,
    }
