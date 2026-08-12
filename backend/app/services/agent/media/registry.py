"""Profile-driven media provider capability registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MediaKind = Literal["image", "video"]
ExecutionMode = Literal["sync", "async_poll", "async_webhook"]


@dataclass(frozen=True)
class MediaCapability:
    provider: str
    model: str
    kind: MediaKind
    mode: ExecutionMode
    supports_cancel: bool = True
    max_duration_sec: int | None = None


# Only providers with real adapters are advertised to runtime/UI.
SUPPORTED_CAPABILITIES: tuple[MediaCapability, ...] = (
    MediaCapability("OpenAI", "dall-e-3", "image", "async_poll"),
    MediaCapability("OpenAI", "gpt-image-1", "image", "async_poll"),
    MediaCapability("OpenAI", "sora", "video", "async_poll", max_duration_sec=60),
    MediaCapability("Google", "veo-2", "video", "async_poll", max_duration_sec=120),
)


def capability_key(provider: str, model: str) -> str:
    return f"{provider.strip()}:{model.strip()}".lower()


def lookup_capability(provider: str, model: str) -> MediaCapability | None:
    key = capability_key(provider, model)
    for cap in SUPPORTED_CAPABILITIES:
        if capability_key(cap.provider, cap.model) == key:
            return cap
    return None


def supported_image_catalog() -> dict[str, list[str]]:
    catalog: dict[str, list[str]] = {}
    for cap in SUPPORTED_CAPABILITIES:
        if cap.kind != "image":
            continue
        catalog.setdefault(cap.provider, []).append(cap.model)
    return catalog


def supported_video_catalog() -> dict[str, list[str]]:
    catalog: dict[str, list[str]] = {}
    for cap in SUPPORTED_CAPABILITIES:
        if cap.kind != "video":
            continue
        catalog.setdefault(cap.provider, []).append(cap.model)
    return catalog


def resolve_profile_media_model(
    ai_profile: dict[str, Any],
    *,
    kind: MediaKind,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    field = "imageGenerationModels" if kind == "image" else "videoGenerationModels"
    models = ai_profile.get(field) or []
    if model_id:
        for item in models:
            if str(item.get("id")) == model_id:
                return dict(item)
    for item in models:
        if item.get("active"):
            return dict(item)
    return dict(models[0]) if models else None
