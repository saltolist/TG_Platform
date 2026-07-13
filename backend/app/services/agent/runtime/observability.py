"""Observability helpers for agent runtime."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Histogram

logger = logging.getLogger("agent.runtime")

AGENT_RUNS = Counter(
    "agent_runs_total",
    "WorkspaceAgent runs by terminal status",
    ("status",),
)
AGENT_INTERRUPTS = Counter(
    "agent_interrupts_total",
    "WorkspaceAgent HITL interrupts",
    ("type",),
)
AGENT_DURATION = Histogram(
    "agent_run_duration_seconds",
    "WorkspaceAgent execution duration",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 180, 600),
)
MEDIA_JOBS = Counter(
    "agent_media_jobs_total",
    "Durable media jobs by kind and status",
    ("kind", "status"),
)


@contextmanager
def span(name: str, **fields: object) -> Iterator[None]:
    started = time.perf_counter()
    logger.info("span.start %s %s", name, fields)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("span.end %s elapsed_ms=%.1f %s", name, elapsed_ms, fields)
