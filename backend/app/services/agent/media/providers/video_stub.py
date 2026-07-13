"""Video generation provider stub — async submit/poll contract."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VideoSubmitResult:
    operation_id: str
    eta_sec: int = 3600


class VideoProviderStub:
    name = "video_stub"

    async def submit(
        self,
        *,
        prompt: str,
        model: str,
        duration_sec: int,
        api_key: str,
        **options: Any,
    ) -> VideoSubmitResult:
        _ = (prompt, model, duration_sec, api_key, options)
        return VideoSubmitResult(operation_id=str(uuid.uuid4()), eta_sec=duration_sec * 60)

    async def poll(self, *, operation_id: str, api_key: str) -> dict[str, Any]:
        _ = (operation_id, api_key)
        return {"status": "processing", "progress": 0.5}

    async def cancel(self, *, operation_id: str, api_key: str) -> bool:
        _ = (operation_id, api_key)
        return True
