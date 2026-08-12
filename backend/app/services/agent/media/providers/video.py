"""Async video provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.services.agent.media.providers.video_stub import VideoProviderStub, VideoSubmitResult


@dataclass(frozen=True)
class VideoPollResult:
    status: str
    progress: float
    output_url: str | None = None


class OpenAIVideoProvider(VideoProviderStub):
    name = "openai_video"

    async def submit(
        self,
        *,
        prompt: str,
        model: str,
        duration_sec: int,
        api_key: str,
        **options: Any,
    ) -> VideoSubmitResult:
        if not api_key:
            raise ValueError("missing_openai_api_key")
        body = {
            "model": model,
            "prompt": prompt,
            "seconds": duration_sec,
            "size": options.get("size", "1280x720"),
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/videos",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        return VideoSubmitResult(
            operation_id=str(payload["id"]),
            eta_sec=int(payload.get("eta") or duration_sec * 30),
        )

    async def poll(self, *, operation_id: str, api_key: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"https://api.openai.com/v1/videos/{operation_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        status = str(payload.get("status") or "processing")
        return {
            "status": status,
            "progress": float(payload.get("progress") or (1.0 if status == "completed" else 0.5)),
            "output_url": (
                f"https://api.openai.com/v1/videos/{operation_id}/content"
                if status == "completed"
                else None
            ),
        }

    async def cancel(self, *, operation_id: str, api_key: str) -> bool:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://api.openai.com/v1/videos/{operation_id}/cancel",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return response.is_success


class GoogleVeoProvider(VideoProviderStub):
    name = "google_veo"

    async def submit(
        self,
        *,
        prompt: str,
        model: str,
        duration_sec: int,
        api_key: str,
        **options: Any,
    ) -> VideoSubmitResult:
        if not api_key:
            raise ValueError("missing_google_api_key")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:predictLongRunning?key={api_key}"
        )
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "durationSeconds": duration_sec,
                "aspectRatio": options.get("aspect_ratio", "16:9"),
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        return VideoSubmitResult(operation_id=str(payload["name"]), eta_sec=duration_sec * 30)

    async def poll(self, *, operation_id: str, api_key: str) -> dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/{operation_id}?key={api_key}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not payload.get("done"):
            return {"status": "processing", "progress": 0.5}
        videos = ((payload.get("response") or {}).get("generatedVideos") or [])
        output_url = ((videos[0].get("video") or {}).get("uri") if videos else None)
        return {"status": "completed", "progress": 1.0, "output_url": output_url}

    async def cancel(self, *, operation_id: str, api_key: str) -> bool:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"{operation_id}:cancel?key={api_key}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url)
        return response.is_success


def resolve_video_provider(provider: str):
    key = provider.strip().lower()
    if key == "openai":
        return OpenAIVideoProvider()
    if key == "google":
        return GoogleVeoProvider()
    return VideoProviderStub()
