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
from app.services.agent.runtime.budget import RunDeadlineExceeded, call_llm_with_deadline

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
