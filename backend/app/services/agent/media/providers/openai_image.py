"""Image generation provider adapter."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ProviderSubmitResult:
    operation_id: str
    status: str = "submitted"
    content: bytes | None = None
    mime_type: str = "image/png"


class OpenAIImageProvider:
    name = "openai"

    async def submit(self, *, prompt: str, model: str, api_key: str, **options: Any) -> ProviderSubmitResult:
        if not api_key:
            raise ValueError("missing_openai_api_key")
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": options.get("size", "1024x1024"),
            "quality": options.get("quality", "auto" if model.startswith("gpt-image") else "standard"),
            "n": 1,
        }
        if not model.startswith("gpt-image"):
            body["response_format"] = "b64_json"
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            item = (payload.get("data") or [{}])[0]
            encoded = item.get("b64_json")
            if encoded:
                content = base64.b64decode(encoded)
            elif item.get("url"):
                downloaded = await client.get(str(item["url"]))
                downloaded.raise_for_status()
                content = downloaded.content
            else:
                raise RuntimeError("openai_image_missing_output")
        return ProviderSubmitResult(
            operation_id=str(payload.get("created") or "synchronous"),
            status="completed",
            content=content,
        )

    async def poll(self, *, operation_id: str, api_key: str) -> dict[str, Any]:
        _ = (operation_id, api_key)
        return {"status": "completed", "progress": 1.0}

    async def cancel(self, *, operation_id: str, api_key: str) -> bool:
        _ = (operation_id, api_key)
        return False
