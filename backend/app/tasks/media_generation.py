"""Durable Celery media generation workers."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from app.celery_app import celery_app
from app.services.agent.runtime.observability import MEDIA_JOBS
from app.tasks.async_runtime import run_async

logger = logging.getLogger(__name__)


async def _resolve_job_key(session, job) -> str:
    from app.core.config import get_settings
    from app.db.models import Profile, User
    from app.services.ai.keys import resolve_model_api_key

    user = await session.get(User, job.user_id)
    profile = await session.get(Profile, job.user_id)
    if user is None or profile is None:
        raise ValueError("media_profile_not_found")
    field = "imageGenerationModels" if job.job_type == "image" else "videoGenerationModels"
    models = (profile.ai or {}).get(field) or []
    model_id = str((job.brief or {}).get("model_id") or "")
    selected = next(
        (
            item
            for item in models
            if (model_id and str(item.get("id") or "") == model_id)
            or (
                str(item.get("provider") or "").lower() == job.provider.lower()
                and str(item.get("model") or "") == job.model
            )
        ),
        None,
    )
    if selected is None:
        raise ValueError("media_model_not_in_profile")
    resolution = resolve_model_api_key(selected, user, get_settings())
    if not resolution.has_key or not resolution.api_key:
        raise ValueError("media_provider_key_missing")
    return resolution.api_key


async def _download_output(url: str, *, provider: str, api_key: str) -> tuple[bytes, str]:
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if provider.lower() == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider.lower() == "google" and "key=" not in url:
        params["key"] = api_key
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "video/mp4").split(";")[0]


async def _process_media_job(job_id: str) -> dict[str, str]:
    from app.core.config import get_settings
    from app.db.models import AgentRun, MediaJob
    from app.db.session import async_session_factory
    from app.services.agent.media.assets import create_media_asset
    from app.services.agent.media.jobs import update_job_progress
    from app.services.agent.media.providers.openai_image import OpenAIImageProvider
    from app.services.agent.media.providers.video import resolve_video_provider
    from app.services.agent.media.registry import lookup_capability
    from app.services.agent.media.storage import MediaStorage
    from app.services.agent.media.validation import validate_image_bytes, validate_video_bytes
    from app.services.agent.runtime import events as event_service
    from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready
    from app.services.agent.runtime.executor import resume_agent_graph

    settings = get_settings()
    jid = uuid.UUID(job_id)
    await ensure_checkpointer_ready()

    async with async_session_factory() as session:
        job = await session.scalar(select(MediaJob).where(MediaJob.id == jid))
        if job is None:
            return {"job_id": job_id, "status": "missing"}
        if job.status == "cancelled":
            return {"job_id": job_id, "status": "cancelled"}

        capability = lookup_capability(job.provider, job.model)
        if capability is None or capability.kind != job.job_type:
            await update_job_progress(
                session,
                job,
                status="failed",
                error="unsupported_media_capability",
            )
            await session.commit()
            return {"job_id": job_id, "status": "failed"}

        api_key = await _resolve_job_key(session, job)
        brief = dict(job.brief or {})
        options = dict(brief.get("options") or {})
        requested_duration = int(options.get("duration_sec") or 5)
        media_bytes: bytes | None = None
        mime_type = "image/png" if job.job_type == "image" else "video/mp4"

        if job.job_type == "image":
            await update_job_progress(
                session,
                job,
                status="running",
                stage="generating",
                progress=0.1,
            )
            submitted = await OpenAIImageProvider().submit(
                prompt=str(brief.get("prompt") or ""),
                model=job.model,
                api_key=api_key,
                **options,
            )
            job.provider_operation_id = submitted.operation_id
            media_bytes = submitted.content
            mime_type = submitted.mime_type
        else:
            provider = resolve_video_provider(job.provider)
            if not job.provider_operation_id:
                submitted = await provider.submit(
                    prompt=str(brief.get("prompt") or ""),
                    model=job.model,
                    duration_sec=int(options.pop("duration_sec", requested_duration)),
                    api_key=api_key,
                    **options,
                )
                job.provider_operation_id = submitted.operation_id
                await update_job_progress(
                    session,
                    job,
                    status="running",
                    stage="processing",
                    progress=0.1,
                )
                await session.commit()
                return {"job_id": job_id, "status": "processing"}

            polled = await provider.poll(
                operation_id=job.provider_operation_id,
                api_key=api_key,
            )
            if polled.get("status") not in {"completed", "succeeded"}:
                await update_job_progress(
                    session,
                    job,
                    status="running",
                    stage="processing",
                    progress=float(polled.get("progress") or 0.5),
                )
                await session.commit()
                return {"job_id": job_id, "status": "processing"}
            output_url = str(polled.get("output_url") or "")
            if not output_url:
                raise RuntimeError("media_provider_missing_output")
            media_bytes, mime_type = await _download_output(
                output_url,
                provider=job.provider,
                api_key=api_key,
            )

        if job.status == "cancelled":
            await session.commit()
            return {"job_id": job_id, "status": "cancelled_late"}
        if media_bytes is None:
            raise RuntimeError("media_provider_missing_bytes")

        validation = (
            validate_image_bytes(media_bytes, declared_mime=mime_type)
            if job.job_type == "image"
            else validate_video_bytes(
                media_bytes,
                declared_mime=mime_type,
                max_duration_sec=capability.max_duration_sec,
                duration_sec=float(requested_duration),
            )
        )
        if not validation.ok:
            await update_job_progress(session, job, status="failed", error=validation.error)
            await session.commit()
            return {"job_id": job_id, "status": "failed"}

        storage = MediaStorage(settings)
        asset_id = uuid.uuid4()
        extension = "png" if validation.mime_type == "image/png" else (
            "webm" if validation.mime_type == "video/webm" else "mp4"
        )
        object_key = storage.object_key(
            user_id=job.user_id,
            asset_id=asset_id,
            ext=extension,
        )
        stored = await storage.put_bytes(
            object_key=object_key,
            data=media_bytes,
            mime_type=validation.mime_type,
        )
        asset = await create_media_asset(
            session,
            user_id=job.user_id,
            job_id=job.id,
            object_key=object_key,
            mime_type=validation.mime_type,
            byte_size=int(stored.get("byte_size") or 0),
            checksum=str(stored.get("checksum") or ""),
            width=validation.width,
            height=validation.height,
            duration_sec=validation.duration_sec,
        )
        await update_job_progress(
            session,
            job,
            status="completed",
            stage="completed",
            progress=1.0,
            asset_id=asset.id,
        )
        if job.run_id:
            result = {
                "type": "media_job_result",
                "job_id": str(job.id),
                "asset_id": str(asset.id),
                "preview_url": storage.signed_preview_url(object_key),
            }
            await event_service.append_event(
                session,
                run_id=job.run_id,
                event_type="media_job_completed",
                payload=result,
            )
            run = await session.get(AgentRun, job.run_id)
            if run and run.status == "interrupted":
                await resume_agent_graph(session, run=run, resume_value=result)
        await session.commit()
        return {
            "job_id": job_id,
            "status": "completed",
            "asset_id": str(asset.id),
            "kind": job.job_type,
        }


async def _cancel_provider_operation(job_id: str) -> None:
    from app.db.models import MediaJob
    from app.db.session import async_session_factory
    from app.services.agent.media.providers.openai_image import OpenAIImageProvider
    from app.services.agent.media.providers.video import resolve_video_provider

    async with async_session_factory() as session:
        job = await session.get(MediaJob, uuid.UUID(job_id))
        if job is None or not job.provider_operation_id:
            return
        api_key = await _resolve_job_key(session, job)
        provider: Any = (
            OpenAIImageProvider()
            if job.job_type == "image"
            else resolve_video_provider(job.provider)
        )
        await provider.cancel(operation_id=job.provider_operation_id, api_key=api_key)


@celery_app.task(
    name="media_generation.run_job",
    bind=True,
    max_retries=120,
    acks_late=True,
)
def run_media_generation_job(self, job_id: str) -> dict[str, str]:
    try:
        result = run_async(_process_media_job(job_id))
        if result.get("status") == "processing":
            raise self.retry(countdown=5)
        MEDIA_JOBS.labels(result.get("kind", "unknown"), result.get("status", "unknown")).inc()
        return result
    except self.MaxRetriesExceededError:
        logger.exception("media job %s exhausted retries", job_id)
        raise
    except Exception as exc:
        logger.warning("media job %s retrying: %s", job_id, exc)
        raise self.retry(exc=exc, countdown=min(60, 2 ** min(self.request.retries, 5)))


@celery_app.task(name="media_generation.cancel_provider_operation")
def cancel_media_generation_job(job_id: str) -> None:
    run_async(_cancel_provider_operation(job_id))

