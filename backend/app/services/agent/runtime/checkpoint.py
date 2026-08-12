"""LangGraph checkpointer factory."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_loop_savers: dict[asyncio.AbstractEventLoop, object] = {}
_persistent_loops: set[asyncio.AbstractEventLoop] = set()
_sync_memory_saver = MemorySaver()


def reset_checkpointer_after_fork() -> None:
    """Discard loop-bound checkpointers inherited by a prefork child."""
    _loop_savers.clear()
    _persistent_loops.clear()


def mark_checkpointer_loop_persistent() -> None:
    """Allow pooling only on an explicitly owned, long-lived runtime loop."""
    _persistent_loops.add(asyncio.get_running_loop())


def get_checkpointer():
    """Create a long-lived checkpointer; connection opening is explicit."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _sync_memory_saver
    for stale_loop in [item for item in _loop_savers if item.is_closed()]:
        _loop_savers.pop(stale_loop, None)
        _persistent_loops.discard(stale_loop)
    cached = _loop_savers.get(loop)
    if cached is not None:
        return cached
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning("langgraph-checkpoint-postgres unavailable — using MemorySaver")
        saver = MemorySaver()
        _loop_savers[loop] = saver
        return saver

    from app.core.config import get_settings

    settings = get_settings()
    raw_url = settings.database_url.replace("+asyncpg", "")
    parsed = urlparse(raw_url)
    if not parsed.scheme.startswith("postgres"):
        saver = MemorySaver()
        _loop_savers[loop] = saver
        return saver

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool, AsyncNullConnectionPool

        pool_class = (
            AsyncConnectionPool
            if not settings.agent_runtime_phase1_enabled or loop in _persistent_loops
            else AsyncNullConnectionPool
        )
        pool = pool_class(
            conninfo=raw_url,
            max_size=max(1, settings.db_pool_size),
            min_size=0,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        saver = AsyncPostgresSaver(pool)
        setattr(saver, "_tg_pool", pool)
        setattr(saver, "_tg_ready", False)
        setattr(saver, "_tg_setup_lock", asyncio.Lock())
        _loop_savers[loop] = saver
        return saver
    except Exception as exc:  # pragma: no cover - env specific
        logger.warning("Postgres checkpointer init failed (%s) — MemorySaver", exc)
        saver = MemorySaver()
        _loop_savers[loop] = saver
        return saver


async def ensure_checkpointer_ready():
    """Open the Postgres pool and create checkpoint tables exactly once."""
    saver = get_checkpointer()
    pool = getattr(saver, "_tg_pool", None)
    if pool is None or getattr(saver, "_tg_ready", False):
        return saver

    lock = getattr(saver, "_tg_setup_lock")
    async with lock:
        if getattr(saver, "_tg_ready", False):
            return saver
        await pool.open()
        await saver.setup()
        setattr(saver, "_tg_ready", True)
    return saver


async def close_checkpointer() -> None:
    loop = asyncio.get_running_loop()
    saver = get_checkpointer()
    pool = getattr(saver, "_tg_pool", None)
    if pool is not None and getattr(saver, "_tg_ready", False):
        await pool.close()
        setattr(saver, "_tg_ready", False)
    _loop_savers.pop(loop, None)
    _persistent_loops.discard(loop)
