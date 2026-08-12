"""Structured trace of AI reply context assembly (RAG cascade + prompt build).

When ``AI_CONTEXT_LOG=1``, pipeline steps are always collected and stored in the
in-memory trace buffer (see ``ai_context_trace_buffer``). Terminal output
(``AI PIPELINE``) still requires a chat filter — use ``./scripts/ai-log-chat.sh``
or fetch past turns via ``GET /api/v1/dev/ai-context-log/traces``.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services.ai.context_log import logger as context_logger

_BANNER = "═" * 72
_SECTION = "─" * 72

_active: ContextVar["ReplyPipelineTracer | None"] = ContextVar(
    "reply_pipeline_tracer", default=None
)


def _preview(text: str, limit: int = 160) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def _post_snapshot(post_data: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(post_data, Mapping):
        return ["post: (none)"]
    post_id = str(post_data.get("id") or "").strip() or "?"
    status = str(post_data.get("status") or "?")
    text = str(post_data.get("text") or "").strip()
    text_html = post_data.get("textHtml")
    has_html = isinstance(text_html, str) and bool(text_html.strip())
    media = post_data.get("media")
    media_count = len(media) if isinstance(media, list) else 0
    notes = post_data.get("notes")
    notes_count = len(notes) if isinstance(notes, list) else 0
    lines = [
        f"post_id={post_id} status={status}",
        f"text_chars={len(text)} textHtml={'yes' if has_html else 'no'} "
        f"media={media_count} notes={notes_count}",
    ]
    if text:
        lines.append(f"text_preview: {_preview(text)}")
    elif has_html:
        lines.append(f"textHtml_preview: {_preview(str(text_html))}")
    return lines


@dataclass
class PipelineStep:
    phase: str
    lines: list[str]


@dataclass
class ReplyPipelineTracer:
    scope: str
    chat_id: str | None
    post_id: str | None
    post_chat_id: str | None
    user_text: str
    steps: list[PipelineStep] = field(default_factory=list)

    def add(self, phase: str, lines: str | list[str]) -> None:
        if isinstance(lines, str):
            payload = [lines] if lines.strip() else []
        else:
            payload = [line for line in lines if str(line).strip()]
        if not payload:
            return
        self.steps.append(PipelineStep(phase=phase, lines=payload))

    def render(self) -> str:
        if not self.steps:
            return ""
        label_parts = [f"scope={self.scope}"]
        if self.scope == "post":
            label_parts.append(f"post={self.post_id or '?'}")
            label_parts.append(f"chat={self.post_chat_id or '?'}")
        else:
            label_parts.append(f"chat={self.chat_id or '?'}")
        header = "  ".join(label_parts)
        body_lines = [
            _BANNER,
            f"AI PIPELINE  {header}",
            f"user: {_preview(self.user_text, 240)}",
            _SECTION,
        ]
        for index, step in enumerate(self.steps, start=1):
            body_lines.append(f"[{index}] {step.phase}")
            body_lines.extend(f"    {line}" for line in step.lines)
            if index < len(self.steps):
                body_lines.append("")
        body_lines.append(_BANNER)
        return "\n".join(body_lines)

    def emit(self) -> str:
        body = self.render()
        if body:
            context_logger.info("\n%s", body)
        return body


def begin_reply_pipeline_trace(
    *,
    enabled: bool,
    chat_filter: str,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
    user_text: str,
    post_data: Mapping[str, Any] | None = None,
    rag_enabled: bool = False,
    rag_settings: Mapping[str, Any] | None = None,
) -> None:
    """Start collecting pipeline steps when ``AI_CONTEXT_LOG=1`` (filter not required)."""
    if not enabled:
        _active.set(None)
        return

    tracer = ReplyPipelineTracer(
        scope=scope,
        chat_id=chat_id,
        post_id=post_id,
        post_chat_id=post_chat_id,
        user_text=user_text,
    )
    tracer.add("1. request", _post_snapshot(post_data))
    if rag_settings:
        tracer.add(
            "2. rag.config",
            [
                f"rag_enabled={rag_enabled}",
                *(f"{key}={value}" for key, value in rag_settings.items()),
            ],
        )
    elif not rag_enabled:
        tracer.add("2. rag.config", "rag_enabled=False — retrieval skipped")
    _active.set(tracer)


def pipeline_trace() -> ReplyPipelineTracer | None:
    return _active.get()


def trace_step(phase: str, lines: str | list[str]) -> None:
    tracer = _active.get()
    if tracer is not None:
        tracer.add(phase, lines)


def trace_mapping(phase: str, payload: Mapping[str, Any]) -> None:
    try:
        text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(payload)
    trace_step(phase, _preview(text, 500))


def format_retrieval_hits(results: list[Mapping[str, Any]], *, limit: int = 5) -> list[str]:
    if not results:
        return ["(no hits)"]
    lines: list[str] = []
    for index, item in enumerate(results[:limit], start=1):
        node_type = str(item.get("node_type") or "?")
        similarity = float(item.get("similarity") or 0.0)
        scope = str(item.get("scope") or "")
        post_ref = str(item.get("post_id") or item.get("note_id") or "")
        chunk = str(item.get("chunk_text") or "").strip()
        lines.append(
            f"{index}. {node_type} scope={scope} post/note={post_ref} "
            f"sim={similarity:.3f} preview={_preview(chunk, 100)!r}"
        )
    if len(results) > limit:
        lines.append(f"… +{len(results) - limit} more")
    return lines


def render_reply_pipeline_trace() -> str:
    tracer = _active.get()
    if tracer is None:
        return ""
    return tracer.render()


def emit_reply_pipeline_trace(*, log_stdout: bool = True) -> str:
    tracer = _active.get()
    if tracer is None:
        return ""
    body = tracer.render()
    if log_stdout and body:
        context_logger.info("\n%s", body)
    _active.set(None)
    return body


__all__ = [
    "begin_reply_pipeline_trace",
    "emit_reply_pipeline_trace",
    "format_retrieval_hits",
    "pipeline_trace",
    "render_reply_pipeline_trace",
    "trace_mapping",
    "trace_step",
]
