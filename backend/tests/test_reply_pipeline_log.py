"""Tests for AI reply pipeline trace logging."""

from __future__ import annotations

from app.services.ai.reply_pipeline_log import (
    ReplyPipelineTracer,
    begin_reply_pipeline_trace,
    emit_reply_pipeline_trace,
    format_retrieval_hits,
    pipeline_trace,
    trace_step,
)
from app.services.ai.context_log import init_chat_filter, set_chat_filter


def test_format_retrieval_hits_empty() -> None:
    assert format_retrieval_hits([]) == ["(no hits)"]


def test_format_retrieval_hits_summarizes_rows() -> None:
    lines = format_retrieval_hits(
        [
            {
                "node_type": "post_text",
                "scope": "global",
                "post_id": "p1",
                "similarity": 0.81,
                "chunk_text": "Черновик поста про розетки",
            }
        ]
    )
    assert len(lines) == 1
    assert "post_text" in lines[0]
    assert "0.810" in lines[0]
    assert "розетки" in lines[0]


def test_pipeline_trace_collects_steps_when_enabled_without_filter() -> None:
    init_chat_filter("")
    set_chat_filter("")

    begin_reply_pipeline_trace(
        enabled=True,
        chat_filter="",
        scope="global",
        chat_id="gc-test",
        post_id=None,
        post_chat_id=None,
        user_text="Что в черновике?",
        post_data={"id": "p1", "status": "draft", "text": "Текст"},
        rag_enabled=True,
        rag_settings={"rag_mode": "off"},
    )
    assert pipeline_trace() is not None
    trace_step("3. rag.L0", "pass")

    tracer = pipeline_trace()
    assert tracer is not None
    assert any(step.phase == "3. rag.L0" for step in tracer.steps)

    body = emit_reply_pipeline_trace(log_stdout=False)
    assert "AI PIPELINE" in body
    assert pipeline_trace() is None


def test_pipeline_trace_disabled_when_ai_context_log_off() -> None:
    begin_reply_pipeline_trace(
        enabled=False,
        chat_filter="gc-test",
        scope="global",
        chat_id="gc-test",
        post_id=None,
        post_chat_id=None,
        user_text="hello",
    )
    trace_step("3. rag.L0", "should not appear")
    assert pipeline_trace() is None


def test_emit_empty_tracer_is_noop() -> None:
    tracer = ReplyPipelineTracer(
        scope="global",
        chat_id="x",
        post_id=None,
        post_chat_id=None,
        user_text="hi",
    )
    tracer.emit()
