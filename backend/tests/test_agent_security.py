"""Load/security tests for agent runtime."""

from __future__ import annotations

import pytest

from app.services.agent.media.registry import lookup_capability, supported_video_catalog
from app.services.agent.media.validation import validate_image_bytes, validate_video_bytes


def test_supported_video_catalog_matches_registry() -> None:
    catalog = supported_video_catalog()
    assert "OpenAI" in catalog
    assert lookup_capability("OpenAI", "sora") is not None


def test_validate_image_rejects_empty() -> None:
    result = validate_image_bytes(b"")
    assert result.ok is False


def test_validate_video_duration_limit() -> None:
    result = validate_video_bytes(
        b"video",
        declared_mime="video/mp4",
        max_duration_sec=30,
        duration_sec=45,
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_media_registry_resolve_profile_model() -> None:
    from app.services.agent.media.registry import resolve_profile_media_model

    profile = {
        "imageGenerationModels": [{"id": "img1", "provider": "OpenAI", "model": "dall-e-3", "active": True}],
        "videoGenerationModels": [{"id": "vid1", "provider": "OpenAI", "model": "sora", "active": True}],
    }
    image = resolve_profile_media_model(profile, kind="image")
    video = resolve_profile_media_model(profile, kind="video")
    assert image is not None
    assert video is not None
