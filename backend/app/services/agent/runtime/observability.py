"""Observability helpers for agent runtime."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

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
AGENT_DURATION_BY_MODE = Histogram(
    "agent_run_duration_by_mode_seconds",
    "WorkspaceAgent duration split by execution mode and warm state",
    ("execution_mode", "worker_warm"),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 180, 600),
)
AGENT_PHASE_DURATION = Histogram(
    "agent_phase_duration_seconds",
    "WorkspaceAgent phase duration by execution mode and warm state",
    ("phase", "execution_mode", "worker_warm"),
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
AGENT_TOOL_CALLS = Counter(
    "agent_tool_calls_total",
    "WorkspaceAgent tool calls by tool, error and cache status",
    ("tool", "error_code", "cache_hit"),
)
AGENT_DUPLICATE_SUPPRESSIONS = Counter(
    "agent_duplicate_tool_suppressions_total",
    "Tool calls served from the run ledger/cache instead of the provider",
)
AGENT_BATCH_PAGES = Counter(
    "agent_batch_pages_total",
    "Durable Workspace Agent batch pages by result status",
    ("status",),
)
AGENT_BATCH_PAGE_DURATION = Histogram(
    "agent_batch_page_duration_seconds",
    "Duration of one checkpointed Workspace Agent batch page",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
AGENT_BATCH_ITEMS = Counter(
    "agent_batch_items_total",
    "Materialized Workspace Agent batch items",
    ("kind",),
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
AGENT_MESSAGE_CONTEXT_ITEMS = Histogram(
    "agent_message_context_items",
    "Message context and referent set sizes per completed run",
    ("kind",),
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 50, 100),
)
AGENT_REFERENT_CONFIDENCE = Histogram(
    "agent_referent_resolution_confidence",
    "Confidence of bounded referent selections",
    buckets=(0, 0.25, 0.5, 0.7, 0.85, 0.95, 1.0),
)
AGENT_ROUTES = Counter(
    "agent_route_total",
    "WorkspaceAgent classifier routes",
    ("route",),
)
AGENT_RETRIEVAL_SEARCHES = Counter(
    "agent_retrieval_search_total",
    "New semantic search calls by tool",
    ("tool",),
)
AGENT_PLAN_DECISIONS = Counter(
    "agent_plan_decisions_total",
    "Deterministic plan decisions before optional planner calls",
    ("route", "reason_code"),
)
AGENT_PLANNER_NOOPS = Counter(
    "agent_planner_noops_total",
    "Planner calls suppressed because authoritative state had no delta",
)
AGENT_UNIFIED_RUNS = Counter(
    "agent_unified_runs_total",
    "Unified integrity runs by selector, pack boundary and terminal coverage",
    ("selector_schema", "pack_schema", "coverage"),
)
AGENT_SELECTOR_REGISTRY_SIZE = Histogram(
    "agent_selector_registry_size",
    "Visible candidates presented to the single Context Selector",
    buckets=(0, 1, 4, 8, 16, 32, 64, 100, 128, 192, 256, 257, 512),
)
AGENT_SELECTOR_ASSESSMENT_COVERAGE = Histogram(
    "agent_selector_assessment_coverage_ratio",
    "Fraction of visible semantic refs with a typed Selector assessment",
    buckets=(0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0),
)
AGENT_UNIFIED_READY_BLOCKS = Counter(
    "agent_unified_ready_blocks_total",
    "Unified ready decisions blocked by deterministic safety reason",
    ("reason",),
)
AGENT_REUSED_CONTEXT_REFS = Histogram(
    "agent_reused_context_refs",
    "Known message-context refs reopened by exact id",
    buckets=(0, 1, 2, 3, 5, 8),
)
AGENT_USED_CONTEXT_REFS = Histogram(
    "agent_used_context_refs",
    "Validated context refs used by the final answer",
    buckets=(0, 1, 2, 3, 5, 8, 13),
)
AGENT_EVIDENCE_FIDELITY = Counter(
    "agent_evidence_fidelity_total",
    "Final EvidencePack items by fidelity",
    ("fidelity",),
)
AGENT_CLARIFICATIONS = Counter(
    "agent_clarifications_total",
    "Deterministic clarification responses",
)
AGENT_LEGACY_RESOLVER = Counter(
    "agent_legacy_resolver_total",
    "Legacy semantic referent resolver selections",
)
AGENT_CONTEXT_MISMATCH = Counter(
    "agent_message_context_mismatch_total",
    "Message context refs absent from the final EvidencePack",
)
AGENT_STOPPED_REASON = Counter(
    "agent_stopped_reason_total",
    "Terminal stopped_reason of WorkspaceAgent runs",
    ("reason",),
)
AGENT_WORKER_READY = Gauge(
    "agent_worker_ready",
    "Whether the current Celery worker child completed runtime initialization",
    multiprocess_mode="livesum",
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


def normalize_phase_timings(value: Any) -> dict[str, float]:
    """Return finite, non-negative phase durations suitable for metrics/JSON."""

    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        try:
            duration = max(0.0, float(raw))
        except (TypeError, ValueError):
            continue
        if duration:
            result[str(key)] = round(duration, 1)
    return result


def observe_run_phases(
    phase_timings: dict[str, float],
    *,
    execution_mode: str,
    worker_warm: bool,
) -> None:
    warm_label = "warm" if worker_warm else "cold"
    for phase, duration_ms in normalize_phase_timings(phase_timings).items():
        AGENT_PHASE_DURATION.labels(phase, execution_mode, warm_label).observe(duration_ms / 1000)
