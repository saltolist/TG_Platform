"""Wall-clock budget tests (agent-runtime-sprints §6).

Deterministic: no real sleeping. A deadline in the past means remaining <= 0,
so the guard fires immediately; a deadline in the future means the (mocked)
call runs. The asyncio.wait_for path is exercised via a slow fake call against
a tiny remaining budget.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.services.agent.runtime import budget
from app.services.agent.runtime.budget import (
    RunDeadlineExceeded,
    call_llm_with_deadline,
    stream_llm_with_deadline,
)

_CALL_KWARGS = dict(messages=[], spec=None, model="m", api_key="k")


@pytest.mark.asyncio
async def test_no_deadline_calls_through(monkeypatch) -> None:
    async def fake(**kwargs):
        return "ok"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)
    ctx = SimpleNamespace(deadline_monotonic=None)
    assert await call_llm_with_deadline(ctx, **_CALL_KWARGS) == "ok"


@pytest.mark.asyncio
async def test_future_deadline_allows_call(monkeypatch) -> None:
    async def fake(**kwargs):
        return "ok"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)
    ctx = SimpleNamespace(deadline_monotonic=time.monotonic() + 60)
    assert await call_llm_with_deadline(ctx, **_CALL_KWARGS) == "ok"


@pytest.mark.asyncio
async def test_expired_deadline_refuses_without_calling(monkeypatch) -> None:
    called = False

    async def fake(**kwargs):
        nonlocal called
        called = True
        return "ok"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)
    ctx = SimpleNamespace(deadline_monotonic=time.monotonic() - 1)
    with pytest.raises(RunDeadlineExceeded):
        await call_llm_with_deadline(ctx, **_CALL_KWARGS)
    assert called is False, "provider must not be dialed when budget is spent"


@pytest.mark.asyncio
async def test_overrunning_call_is_cut_off(monkeypatch) -> None:
    async def slow(**kwargs):
        await asyncio.sleep(5)
        return "too late"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", slow)
    # ~10ms of budget left; the 5s call must be cut off as a deadline breach.
    ctx = SimpleNamespace(deadline_monotonic=time.monotonic() + 0.01)
    with pytest.raises(RunDeadlineExceeded):
        await call_llm_with_deadline(ctx, **_CALL_KWARGS)


@pytest.mark.asyncio
async def test_call_records_phase_timing_and_token_estimates(monkeypatch) -> None:
    async def fake(**kwargs):
        return "done"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)
    ctx = SimpleNamespace(deadline_monotonic=None, llm_client=None, llm_metrics=[])
    result = await call_llm_with_deadline(
        ctx,
        phase="research.planner",
        **{**_CALL_KWARGS, "messages": [{"role": "user", "content": "12345678"}]},
    )
    assert result == "done"
    assert ctx.llm_metrics == [
        {
            "phase": "research.planner",
            "duration_ms": pytest.approx(0, abs=50),
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
            "token_method": "chars_div_4_estimate",
            "success": True,
            "streaming": False,
            "provider": "unknown",
            "model": "m",
        }
    ]


@pytest.mark.asyncio
async def test_stream_records_one_aggregate_metric(monkeypatch) -> None:
    async def fake_stream(**kwargs):
        yield "ab"
        yield "cd"

    monkeypatch.setattr(budget.llm, "stream_chat_completion_tokens", fake_stream)
    ctx = SimpleNamespace(deadline_monotonic=None, llm_client=None, llm_metrics=[])
    chunks = [
        chunk
        async for chunk in stream_llm_with_deadline(
            ctx,
            phase="answer.generate",
            **{**_CALL_KWARGS, "messages": [{"role": "user", "content": "12345678"}]},
        )
    ]
    assert chunks == ["ab", "cd"]
    assert len(ctx.llm_metrics) == 1
    assert ctx.llm_metrics[0]["phase"] == "answer.generate"
    assert ctx.llm_metrics[0]["prompt_tokens"] == 2
    assert ctx.llm_metrics[0]["completion_tokens"] == 1
    assert ctx.llm_metrics[0]["total_tokens"] == 3
    assert ctx.llm_metrics[0]["success"] is True
    assert ctx.llm_metrics[0]["streaming"] is True
