"""Media jobs and provider contract tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.agent.media.jobs import cancel_media_job, create_media_job, update_job_progress
from app.services.agent.media.providers.openai_image import OpenAIImageProvider
from app.services.agent.media.providers.video_stub import VideoProviderStub
from app.services.agent.media.storage import MediaStorage
from app.core.config import Settings


@pytest.mark.asyncio
async def test_create_and_cancel_media_job() -> None:
    session = AsyncMock()
    session.add = lambda obj: None
    session.flush = AsyncMock()

    job = await create_media_job(
        session,
        user_id=uuid.uuid4(),
        run_id=None,
        job_type="image",
        provider="openai",
        model="dall-e-3",
        brief={"prompt": "cover"},
    )
    assert job.status == "queued"

    cancelled = await cancel_media_job(session, job)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_video_provider_submit_poll() -> None:
    provider = VideoProviderStub()
    submitted = await provider.submit(
        prompt="clip",
        model="video-stub",
        duration_sec=15,
        api_key="k",
    )
    polled = await provider.poll(operation_id=submitted.operation_id, api_key="k")
    assert polled["status"] in {"processing", "completed"}


def test_media_storage_object_key() -> None:
    storage = MediaStorage(Settings())
    key = storage.object_key(user_id=uuid.uuid4(), asset_id=uuid.uuid4(), ext="png")
    assert key.startswith("users/")
