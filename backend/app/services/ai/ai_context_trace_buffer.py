"""In-memory ring buffer of recent AI context exchanges (dev diagnostics).

When ``AI_CONTEXT_LOG=1``, every reply is stored here — even if the terminal
filter is not set yet. Retrieve past turns (including the first message) via
``GET /api/v1/dev/ai-context-log/traces``.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_DEFAULT_MAX_PER_KEY = 30
_lock = threading.Lock()
_max_per_key = _DEFAULT_MAX_PER_KEY
_buffers: dict[str, deque["StoredContextExchange"]] = defaultdict(
    lambda: deque(maxlen=_max_per_key)
)


@dataclass(frozen=True)
class StoredContextExchange:
    recorded_at: str
    scope: str
    chat_id: str | None
    post_id: str | None
    post_chat_id: str | None
    user_text: str
    provider: str
    model: str
    pipeline: str
    request: str
    response: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordedAt": self.recorded_at,
            "scope": self.scope,
            "chatId": self.chat_id,
            "postId": self.post_id,
            "postChatId": self.post_chat_id,
            "userText": self.user_text,
            "provider": self.provider,
            "model": self.model,
            "pipeline": self.pipeline,
            "request": self.request,
            "response": self.response,
        }


def configure_trace_buffer(*, max_per_key: int) -> None:
    global _max_per_key, _buffers
    size = max(1, int(max_per_key))
    with _lock:
        _max_per_key = size
        old = _buffers
        _buffers = defaultdict(lambda: deque(maxlen=_max_per_key))
        for key, items in old.items():
            _buffers[key] = deque(items, maxlen=_max_per_key)


def lookup_keys(
    *,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
) -> list[str]:
    keys: list[str] = []
    if scope == "global":
        value = str(chat_id or "").strip()
        if value:
            keys.append(value)
        return keys

    chat_value = str(post_chat_id or "").strip()
    post_value = str(post_id or "").strip()
    if chat_value:
        keys.append(chat_value)
    if post_value and chat_value:
        keys.append(f"post:{post_value}:{chat_value}")
    return keys


def store_context_exchange(record: StoredContextExchange) -> None:
    keys = lookup_keys(
        scope=record.scope,
        chat_id=record.chat_id,
        post_id=record.post_id,
        post_chat_id=record.post_chat_id,
    )
    if not keys:
        return
    with _lock:
        for key in keys:
            _buffers[key].append(record)


def list_context_exchanges(chat_id: str, *, limit: int = 20) -> list[StoredContextExchange]:
    key = chat_id.strip()
    if not key:
        return []
    capped = max(1, min(int(limit), 100))
    with _lock:
        items = list(_buffers.get(key, ()))
    return list(reversed(items[-capped:]))


def clear_context_exchanges(chat_id: str | None = None) -> int:
    with _lock:
        if chat_id is None or not chat_id.strip():
            count = sum(len(items) for items in _buffers.values())
            _buffers.clear()
            return count
        key = chat_id.strip()
        removed = len(_buffers.pop(key, ()))
        return removed


def make_stored_exchange(
    *,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
    user_text: str,
    provider: str,
    model: str,
    pipeline: str,
    request: str,
    response: str,
) -> StoredContextExchange:
    return StoredContextExchange(
        recorded_at=datetime.now(timezone.utc).isoformat(),
        scope=scope,
        chat_id=chat_id,
        post_id=post_id,
        post_chat_id=post_chat_id,
        user_text=user_text,
        provider=provider or "",
        model=model or "",
        pipeline=pipeline,
        request=request,
        response=response,
    )
