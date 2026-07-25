"""Run-level wall-clock budget (agent-runtime-sprints §6).

`max_steps` bounds how many planner iterations a run takes, but nothing bounds
its wall-clock time: each provider call already has a 120s HTTP timeout, yet a
multi-step run could still stack several of those. This module adds a single
hard deadline for the whole run, enforced *around* each LLM call via
asyncio.wait_for — so a slow provider is cut off at the deadline, not one full
call past it.

Token/cost enforcement is deliberately out of scope here. Phase-0 telemetry
records explicit char-based estimates; hard budgets still require provider
usage accounting.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Mapping
from typing import Any, AsyncIterator

from app.services.agent.runtime.context import RuntimeContext
from app.services.ai import llm
from app.services.analytics.platform_models import (
    estimate_tokens_from_messages,
    estimate_tokens_from_text,
)


class RunDeadlineExceeded(Exception):
    """Raised when a run's wall-clock budget is spent before/at an LLM call."""


def _record_llm_metric(
    ctx: RuntimeContext,
    *,
    kwargs: dict,
    phase: str,
    started_at: float,
    completion: str,
    success: bool,
    streaming: bool,
    provider_usage: Mapping[str, Any] | None = None,
    telemetry: Mapping[str, Any] | None = None,
    error_kind: str | None = None,
) -> None:
    sink = getattr(ctx, "llm_metrics", None)
    if not isinstance(sink, list):
        return
    messages = kwargs.get("messages")
    prompt_tokens = estimate_tokens_from_messages(messages) if isinstance(messages, list) else 0
    system_text = "\n".join(
        str(item.get("content") or "")
        for item in (messages or [])
        if isinstance(item, dict) and item.get("role") == "system"
    )
    cache_key = hashlib.sha256(system_text.encode("utf-8")).hexdigest()[:16] if system_text else ""
    completion_tokens = estimate_tokens_from_text(completion)
    spec = kwargs.get("spec")
    provider_usage = dict(provider_usage or {})
    telemetry = dict(telemetry or {})
    usage_availability = str(provider_usage.get("availability") or "unavailable")
    actual_input = provider_usage.get("input_tokens") if usage_availability == "measured" else None
    actual_cached = (
        provider_usage.get("cached_input_tokens") if usage_availability == "measured" else None
    )
    actual_output = provider_usage.get("output_tokens") if usage_availability == "measured" else None
    actual_total = provider_usage.get("total_tokens") if usage_availability == "measured" else None
    metric = {
        "phase": phase,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "token_method": "chars_div_4_estimate",
        "success": success,
        "streaming": streaming,
        "provider": str(getattr(spec, "name", "") or getattr(spec, "provider", "") or "unknown"),
        "model": str(kwargs.get("model") or "unknown"),
        "candidate_count": telemetry.get("candidate_count"),
        "cohort": telemetry.get("cohort"),
        "retry": bool(telemetry.get("retry")),
        "schema_result": telemetry.get("schema_result") or "not_measured",
        "timeout": error_kind in {"timeout", "deadline"},
        "provider_latency": {
            "availability": "measured",
            "value_ms": round((time.perf_counter() - started_at) * 1000, 1),
        },
        "provider_token_usage": {
            "availability": usage_availability,
            "input_tokens": actual_input,
            "cached_input_tokens": actual_cached,
            "output_tokens": actual_output,
            "total_tokens": actual_total,
        },
        "estimator_provider_delta": {
            "availability": "measured" if actual_input is not None else "unavailable",
            "input_tokens": (
                int(actual_input) - prompt_tokens if actual_input is not None else None
            ),
            "total_tokens": (
                int(actual_total) - (prompt_tokens + completion_tokens)
                if actual_total is not None
                else None
            ),
        },
        "price_snapshot": {"availability": "unavailable", "version": None},
        "estimated_cost": {"availability": "unavailable", "value_usd": None},
    }
    # Cache metadata is meaningful only when there is a stable system prefix.
    # Omitting it for user-only compatibility calls keeps the legacy metric
    # shape while phase-6 answer/planner calls retain the cache observability.
    if system_text:
        metric.update(
            {
                "prompt_cache_key": cache_key,
                "prompt_cache_eligible_tokens": estimate_tokens_from_text(system_text),
                # Provider cache usage is not exposed by the current text-only
                # LLM adapter. None is explicit rather than guessing a cache hit.
                "prompt_cache_hit_tokens": None,
            }
        )
    sink.append(metric)


async def call_llm_with_deadline(
    ctx: RuntimeContext,
    *,
    phase: str = "unspecified",
    telemetry: Mapping[str, Any] | None = None,
    **kwargs,
) -> str:
    """Call complete_chat_completion, bounded by the run's wall-clock deadline.

    If ctx.deadline_monotonic is None the call runs unbounded (only the
    underlying HTTP timeout applies). Otherwise the remaining budget caps the
    call: no time left → RunDeadlineExceeded without dialing the provider; a
    provider that overruns the remainder → asyncio.TimeoutError, surfaced as
    RunDeadlineExceeded so the executor marks the run deadline_exceeded.
    """
    started_at = time.perf_counter()
    llm_client = getattr(ctx, "llm_client", None)
    if llm_client is not None:
        kwargs.setdefault("client", llm_client)
    provider_usage: dict[str, Any] = {}
    kwargs["usage_sink"] = provider_usage
    deadline = ctx.deadline_monotonic
    try:
        if deadline is None:
            result = await llm.complete_chat_completion(**kwargs)
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunDeadlineExceeded("run wall-clock budget exhausted before LLM call")
            try:
                result = await asyncio.wait_for(llm.complete_chat_completion(**kwargs), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise RunDeadlineExceeded("run wall-clock budget exhausted during LLM call") from exc
    except Exception as exc:
        _record_llm_metric(
            ctx,
            kwargs=kwargs,
            phase=phase,
            started_at=started_at,
            completion="",
            success=False,
            streaming=False,
            provider_usage=provider_usage,
            telemetry=telemetry,
            error_kind=(
                "deadline"
                if isinstance(exc, RunDeadlineExceeded)
                else "timeout"
                if isinstance(exc, (asyncio.TimeoutError, TimeoutError))
                else type(exc).__name__
            ),
        )
        raise
    _record_llm_metric(
        ctx,
        kwargs=kwargs,
        phase=phase,
        started_at=started_at,
        completion=result,
        success=True,
        streaming=False,
        provider_usage=provider_usage,
        telemetry=telemetry,
    )
    return result


async def stream_llm_with_deadline(
    ctx: RuntimeContext,
    *,
    phase: str = "unspecified",
    **kwargs,
) -> AsyncIterator[str]:
    """Stream tokens from stream_chat_completion_tokens, bounded by the run's
    wall-clock deadline — the streaming twin of call_llm_with_deadline.

    The deadline caps the whole token stream, not each token: no budget left
    before the first token → RunDeadlineExceeded without dialing the provider;
    the deadline crossed mid-stream → RunDeadlineExceeded on the next token.
    asyncio.wait_for wraps each __anext__ so a stalled provider is cut off at
    the remaining budget, same guarantee the non-streaming path gives.
    """
    started_at = time.perf_counter()
    completion_parts: list[str] = []
    success = False
    llm_client = getattr(ctx, "llm_client", None)
    if llm_client is not None:
        kwargs.setdefault("client", llm_client)
    deadline = ctx.deadline_monotonic
    stream = llm.stream_chat_completion_tokens(**kwargs)
    agen = stream.__aiter__()
    try:
        while True:
            if deadline is None:
                timeout = None
            else:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    raise RunDeadlineExceeded("run wall-clock budget exhausted during LLM stream")
            try:
                token = await asyncio.wait_for(agen.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                success = True
                return
            except asyncio.TimeoutError as exc:
                raise RunDeadlineExceeded(
                    "run wall-clock budget exhausted during LLM stream"
                ) from exc
            completion_parts.append(token)
            yield token
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            await aclose()
        _record_llm_metric(
            ctx,
            kwargs=kwargs,
            phase=phase,
            started_at=started_at,
            completion="".join(completion_parts),
            success=success,
            streaming=True,
        )
