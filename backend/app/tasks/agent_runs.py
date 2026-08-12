"""Durable Celery entrypoint for WorkspaceAgent runs."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models import AgentRun, User
from app.db.session import async_session_factory
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
from app.services.agent.runtime.executor import (
    execute_agent_run,
    is_retryable_run_exception,
)
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run
from app.services.ai.keys import resolve_model_api_key
from app.services.ai.providers import get_provider_spec
from app.tasks.async_runtime import WorkerNotReadyError, run_async, runtime_status

logger = logging.getLogger(__name__)


def _is_cross_loop_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "different loop" in message or "attached to a different loop" in message


async def _fail_unready_agent_run(run_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        }:
            return
        await event_service.update_run_status(
            session,
            run,
            status="failed",
            error="worker_not_ready",
        )
        await event_service.append_event(
            session,
            run_id=run.id,
            event_type="run_failed",
            payload={"error": "worker_not_ready", "stopped_reason": "worker_not_ready"},
        )
        await session.commit()


async def _execute_agent_run(
    run_id: uuid.UUID,
    user_text: str,
    *,
    defer_retryable_failures: bool = False,
    shadow_reasoner_model: str | None = None,
    shadow_reasoner_provider: str | None = None,
) -> None:
    await ensure_checkpointer_ready()
    async with async_session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id))
        if run is None or run.status in {"completed", "cancelled", "interrupted"}:
            return
        user = await session.scalar(select(User).where(User.id == run.user_id))
        if user is None:
            return
        # Single source of truth for context assembly, shared with HITL resume
        # (agent-runtime-sprints §1.5). user_text feeds dialog_context (§2.1).
        context = await rebuild_runtime_context_for_run(session, run, user_text)
        if shadow_reasoner_model:
            # Formal-canary diagnostics only. The normal API never supplies this
            # value, and the answer model remains the user's selected model.
            model = str(shadow_reasoner_model).strip()
            if not model or len(model) > 128 or any(char.isspace() for char in model):
                raise ValueError("invalid_shadow_reasoner_model")
            provider_name = str(shadow_reasoner_provider or "").strip()
            if provider_name:
                spec = get_provider_spec(provider_name)
                model_entry = next(
                    (
                        item
                        for group in ("ragReasonerModels", "orchestratorModels", "llmModels")
                        for item in (context.ai_profile.get(group) or ())
                        if isinstance(item, dict)
                        and str(item.get("provider") or "").strip() == provider_name
                        and str(item.get("model") or "").strip() == model
                    ),
                    None,
                )
                if spec is None or model_entry is None:
                    raise ValueError("invalid_shadow_reasoner_provider_model")
                key = resolve_model_api_key(model_entry, user, context.settings)
                if not key.api_key:
                    raise ValueError("shadow_reasoner_provider_key_unavailable")
                context.reasoner_spec = spec
                context.planner_spec = spec
                context.reasoner_api_key = key.api_key
                context.planner_api_key = key.api_key
            context.reasoner_model = model
            context.planner_model = model
            await event_service.append_event(
                session,
                run_id=run.id,
                event_type="diagnostic_model_binding",
                payload={
                    "schema": "workspace.diagnostic-model-binding/v1",
                    "role": "planner_research",
                    "model": model,
                    "provider": provider_name or getattr(context.reasoner_spec, "name", ""),
                    "answer_model": context.answer_model,
                    "source": "formal_canary_shadow",
                },
            )
            await session.commit()
        if context.turn_contract.get("execution_mode") == "batch":
            from app.services.agent.runtime.batch import create_batch_job, serialize_batch_job
            from app.tasks.agent_batch import execute_agent_batch_task

            job, created = await create_batch_job(
                session,
                run=run,
                query=user_text,
                tenant_key=context.tenant_key,
            )
            payload = serialize_batch_job(job)
            run.snapshot = {
                "schema": "workspace.agent-run-batch/v1",
                "user_text": user_text,
                "turn_contract": dict(context.turn_contract),
                "target_contract": dict(context.turn_contract.get("target_contract") or {}),
                "batch_job": payload,
            }
            if created:
                await event_service.append_event(
                    session,
                    run_id=run.id,
                    event_type="batch_enqueued",
                    payload=payload,
                )
            await session.commit()
            if created or job.status == "queued":
                result = execute_agent_batch_task.apply_async(
                    args=[str(job.id)],
                    task_id=f"agent-batch:{job.id}:0",
                )
                job.celery_task_id = result.id
                await session.commit()
            return
        await execute_agent_run(
            session,
            run=run,
            user=user,
            user_text=user_text,
            runtime_context=context,
            defer_retryable_failures=defer_retryable_failures,
        )


@celery_app.task(
    name="app.tasks.agent_runs.execute_agent_run_task",
    bind=True,
    acks_late=True,
    max_retries=5,
)
def execute_agent_run_task(
    self,
    run_id: str,
    user_text: str,
    shadow_reasoner_model: str | None = None,
    shadow_reasoner_provider: str | None = None,
) -> None:
    status = runtime_status()
    if status.get("status") == "warmup_failed":
        run_async(_fail_unready_agent_run(uuid.UUID(run_id)))
        raise WorkerNotReadyError("interactive worker embedding warmup failed")
    retries_remaining = int(self.request.retries or 0) < int(self.max_retries or 0)
    coroutine = _execute_agent_run(
        uuid.UUID(run_id),
        user_text,
        defer_retryable_failures=retries_remaining,
        shadow_reasoner_model=shadow_reasoner_model,
        shadow_reasoner_provider=shadow_reasoner_provider,
    )
    try:
        run_async(coroutine)
    except Exception as exc:
        close = getattr(coroutine, "close", None)
        if close is not None:
            close()
        if _is_cross_loop_error(exc):
            logger.exception(
                "Agent run %s failed with a cross-loop programming error; retry suppressed",
                run_id,
            )
            raise
        if not is_retryable_run_exception(exc) or not retries_remaining:
            raise
        raise self.retry(
            exc=exc,
            countdown=min(60, 2 ** min(self.request.retries, 5)),
        )


@celery_app.task(name="app.tasks.agent_runs.runtime_health", queue="agent-interactive")
def runtime_health() -> dict[str, object]:
    """Readiness probe executed inside an actual agent worker child."""
    return runtime_status()
