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


def format_sse_meta(meta: dict[str, object]) -> str:
    return f"data: {json.dumps({'meta': meta}, ensure_ascii=False)}\n\n"


def parse_sse_text_chunk(event_block: str) -> str | None:
    for line in event_block.split("\n"):
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        text = payload.get("text")
        return text if isinstance(text, str) else None
    return None


async def stream_stub_reply(text: str, scope: str = "global") -> AsyncIterator[str]:
    """Yield stub reply text as SSE chunks (Phase 2 step 3.1)."""
    full = generate_reply(text, scope=scope)
    for offset in range(0, len(full), STUB_CHUNK_SIZE):
        yield format_sse_data(full[offset : offset + STUB_CHUNK_SIZE])
        await asyncio.sleep(STUB_CHUNK_DELAY_SEC)
