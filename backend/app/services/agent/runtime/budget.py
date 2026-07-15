"""Run-level wall-clock budget (agent-runtime-sprints §6).

`max_steps` bounds how many planner iterations a run takes, but nothing bounds
its wall-clock time: each provider call already has a 120s HTTP timeout, yet a
multi-step run could still stack several of those. This module adds a single
hard deadline for the whole run, enforced *around* each LLM call via
asyncio.wait_for — so a slow provider is cut off at the deadline, not one full
call past it.

Token/cost budgeting is deliberately out of scope here (agent-runtime-remaining.md
§6b): it needs provider usage accounting and is bounded indirectly today by
max_steps + per-call max_tokens + the evidence pack char cap.
"""

from __future__ import annotations

import asyncio
import time

from app.services.agent.runtime.context import RuntimeContext
from app.services.ai import llm


class RunDeadlineExceeded(Exception):
    """Raised when a run's wall-clock budget is spent before/at an LLM call."""


async def call_llm_with_deadline(ctx: RuntimeContext, **kwargs) -> str:
    """Call complete_chat_completion, bounded by the run's wall-clock deadline.

    If ctx.deadline_monotonic is None the call runs unbounded (only the
    underlying HTTP timeout applies). Otherwise the remaining budget caps the
    call: no time left → RunDeadlineExceeded without dialing the provider; a
    provider that overruns the remainder → asyncio.TimeoutError, surfaced as
    RunDeadlineExceeded so the executor marks the run deadline_exceeded.
    """
    deadline = ctx.deadline_monotonic
    if deadline is None:
        return await llm.complete_chat_completion(**kwargs)

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RunDeadlineExceeded("run wall-clock budget exhausted before LLM call")
    try:
        return await asyncio.wait_for(llm.complete_chat_completion(**kwargs), timeout=remaining)
    except asyncio.TimeoutError as exc:
        raise RunDeadlineExceeded("run wall-clock budget exhausted during LLM call") from exc
