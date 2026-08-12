"""Typed SSE event formatting for agent runs."""

from __future__ import annotations

import json
from typing import Any


def format_agent_sse_event(
    *,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    body = {
        "agent": {
            "sequence": sequence,
            "type": event_type,
            "payload": payload,
        }
    }
    return f"id: {sequence}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def format_agent_sse_text(text: str, *, sequence: int | None = None) -> str:
    prefix = f"id: {sequence}\n" if sequence is not None else ""
    return f"{prefix}data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"


def format_agent_sse_meta(meta: dict[str, object], *, sequence: int | None = None) -> str:
    prefix = f"id: {sequence}\n" if sequence is not None else ""
    return f"{prefix}data: {json.dumps({'meta': meta}, ensure_ascii=False)}\n\n"


def parse_last_event_id(header_value: str | None) -> int:
    if not header_value:
        return 0
    try:
        return max(0, int(header_value.strip()))
    except ValueError:
        return 0
