"""One persistent asyncio loop and child-process runtime for Celery workers.

Celery's prefork parent imports the application before forking.  Async engines,
checkpointer pools, model runtimes and futures created in that parent must not
be reused by the child.  This module owns the child lifecycle and gives every
Celery task in a process the same event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_worker_pid: int | None = None
_worker_warmup: dict[str, Any] = {
    "ready": False,
    "status": "not_initialized",
    "embedding_init_ms": None,
    "first_embed_ms": None,
    "checkpointer_init_ms": None,
    "graph_compile_ms": None,
    "pid": None,
}
logger = logging.getLogger(__name__)


class WorkerNotReadyError(RuntimeError):
    """Raised when a task is invoked before the worker runtime is initialized."""


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _worker_pid
    pid = os.getpid()
    if _worker_pid != pid:
        _loop = None
        _worker_pid = pid
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _worker_pid = pid
    else:
        try:
            current = asyncio.get_event_loop()
        except RuntimeError:
            current = None
        if current is not _loop:
            asyncio.set_event_loop(_loop)
    return _loop


def runtime_status() -> dict[str, Any]:
    return {**_worker_warmup, "loop_id": id(_loop) if _loop is not None else None}


def reset_after_fork() -> None:
    """Drop resources inherited from Celery's prefork parent."""
    global _loop, _worker_pid
    _loop = None
    _worker_pid = os.getpid()
    _worker_warmup.clear()
    _worker_warmup.update(
        ready=False,
        status="initializing",
        embedding_init_ms=None,
        first_embed_ms=None,
        checkpointer_init_ms=None,
        graph_compile_ms=None,
        pid=_worker_pid,
    )

    from app.db.session import engine

    # SQLAlchemy documents dispose(close=False) as the fork-safe child reset:
    # inherited parent connections are discarded without touching the parent.
    engine.sync_engine.dispose(close=False)
    from app.services.ai.embeddings import reset_embedding_runtime_after_fork

    reset_embedding_runtime_after_fork()
    from app.services.agent.runtime.checkpoint import reset_checkpointer_after_fork

    reset_checkpointer_after_fork()


async def initialize_worker_runtime() -> dict[str, Any]:
    """Warm all child-local interactive dependencies before accepting work."""
    _ensure_loop()
    from app.services.agent.runtime.checkpoint import mark_checkpointer_loop_persistent

    mark_checkpointer_loop_persistent()
    started = time.perf_counter()
    try:
        if os.environ.get("TG_CELERY_WORKER_KIND", "interactive") != "interactive":
            result: dict[str, Any] = {
                "ready": True,
                "status": "ready_non_interactive",
                "embedding_init_ms": None,
                "first_embed_ms": None,
                "checkpointer_init_ms": None,
                "graph_compile_ms": None,
            }
        else:
            from app.services.ai.embeddings import warmup_local_embedding_runtime

            result = await warmup_local_embedding_runtime()
            checkpointer_started = time.perf_counter()
            from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready

            await ensure_checkpointer_ready()
            result["checkpointer_init_ms"] = round(
                (time.perf_counter() - checkpointer_started) * 1000, 1
            )

            graph_started = time.perf_counter()
            from app.services.agent.runtime.workspace_graph import (
                get_compiled_workspace_graph,
            )

            get_compiled_workspace_graph()
            result["graph_compile_ms"] = round(
                (time.perf_counter() - graph_started) * 1000, 1
            )
        _worker_warmup.update(result)
        _worker_warmup["worker_init_ms"] = round((time.perf_counter() - started) * 1000, 1)
        _worker_warmup["pid"] = os.getpid()
        _worker_warmup["ready"] = bool(result.get("ready", True))
        from app.services.agent.runtime.observability import (
            AGENT_WORKER_FIRST_EMBED,
            AGENT_WORKER_READY,
            AGENT_WORKER_WARMUP,
        )

        AGENT_WORKER_READY.set(1 if _worker_warmup["ready"] else 0)
        if result.get("embedding_init_ms") is not None:
            AGENT_WORKER_WARMUP.observe(float(result["embedding_init_ms"]) / 1000)
        if result.get("first_embed_ms") is not None:
            AGENT_WORKER_FIRST_EMBED.observe(float(result["first_embed_ms"]) / 1000)
        logger.info(
            "worker_runtime.ready pid=%s status=%s worker_init_ms=%s "
            "embedding_init_ms=%s first_embed_ms=%s checkpointer_init_ms=%s "
            "graph_compile_ms=%s",
            _worker_warmup["pid"],
            _worker_warmup["status"],
            _worker_warmup["worker_init_ms"],
            _worker_warmup.get("embedding_init_ms"),
            _worker_warmup.get("first_embed_ms"),
            _worker_warmup.get("checkpointer_init_ms"),
            _worker_warmup.get("graph_compile_ms"),
        )
    except Exception as exc:  # noqa: BLE001 - readiness is observable, worker stays diagnosable
        _worker_warmup.update(
            ready=False,
            status="warmup_failed",
            error=type(exc).__name__,
            embedding_init_ms=round((time.perf_counter() - started) * 1000, 1),
            pid=os.getpid(),
        )
        from app.services.agent.runtime.observability import AGENT_WORKER_READY

        AGENT_WORKER_READY.set(0)
        logger.exception("Celery worker embedding warmup failed")
    return runtime_status()


def initialize_worker_process() -> dict[str, Any]:
    """Celery ``worker_process_init`` hook entrypoint."""
    reset_after_fork()
    loop = _ensure_loop()
    return loop.run_until_complete(initialize_worker_runtime())


def shutdown_worker_process() -> None:
    """Close child-local async resources before Celery tears down the child."""
    global _loop
    if _loop is None or _loop.is_closed():
        return

    async def _shutdown() -> None:
        from app.services.agent.runtime.checkpoint import close_checkpointer

        await close_checkpointer()
        from app.db.session import engine

        await engine.dispose()

    try:
        _loop.run_until_complete(_shutdown())
        _loop.run_until_complete(_loop.shutdown_asyncgens())
    except Exception:  # noqa: BLE001 - shutdown must not mask task result
        logger.exception("Celery worker async runtime shutdown failed")
    finally:
        _worker_warmup.update(ready=False, status="stopped")
        from app.services.agent.runtime.observability import AGENT_WORKER_READY

        AGENT_WORKER_READY.set(0)
        _loop.close()
        asyncio.set_event_loop(None)
        _loop = None


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    return _ensure_loop().run_until_complete(coro)
