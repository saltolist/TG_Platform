"""Server-Sent Events helpers for AI reply streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.services.ai.stub import generate_reply

STUB_CHUNK_SIZE = 12
STUB_CHUNK_DELAY_SEC = 0.04


def format_sse_data(text: str) -> str:
    return f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"


async def stream_stub_reply(text: str, scope: str = "global") -> AsyncIterator[str]:
    """Yield stub reply text as SSE chunks (Phase 2 step 3.1)."""
    full = generate_reply(text, scope=scope)
    for offset in range(0, len(full), STUB_CHUNK_SIZE):
        yield format_sse_data(full[offset : offset + STUB_CHUNK_SIZE])
        await asyncio.sleep(STUB_CHUNK_DELAY_SEC)
