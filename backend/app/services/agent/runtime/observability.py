"""Observability helpers for agent runtime."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram

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
AGENT_STEPS = Histogram(
    "agent_run_steps",
    "Planner/tool steps taken per WorkspaceAgent run",
    buckets=(0, 1, 2, 3, 4, 6, 8, 12, 16),
)
AGENT_EMPTY_PACK = Counter(
    "agent_empty_pack_total",
    "Runs that finished with no evidence in the pack (grounding gap signal)",
)
AGENT_STOPPED_REASON = Counter(
    "agent_stopped_reason_total",
    "Terminal stopped_reason of WorkspaceAgent runs",
    ("reason",),
)
AGENT_WORKER_READY = Gauge(
    "agent_worker_ready",
    "Whether the current Celery worker child completed runtime initialization",
)
AGENT_WORKER_WARMUP = Histogram(
    "agent_worker_embedding_warmup_seconds",
    "Embedding initialization and first real embed duration",
    buckets=(0.1, 1, 2, 5, 10, 30, 60, 120),
)
AGENT_WORKER_FIRST_EMBED = Histogram(
    "agent_worker_first_embed_seconds",
    "First real embedding duration after model construction",
    buckets=(0.01, 0.1, 0.5, 1, 2, 5, 10, 30),
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
