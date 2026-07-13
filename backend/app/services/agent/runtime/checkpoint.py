"""LangGraph checkpointer factory."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_loop_savers: dict[int, object] = {}
_sync_memory_saver = MemorySaver()

def get_checkpointer():
    """Create a long-lived checkpointer; connection opening is explicit."""
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        return _sync_memory_saver
    cached = _loop_savers.get(loop_key)
    if cached is not None:
        return cached
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning("langgraph-checkpoint-postgres unavailable — using MemorySaver")
        saver = MemorySaver()
        _loop_savers[loop_key] = saver
        return saver

    from app.core.config import get_settings

    settings = get_settings()
    raw_url = settings.database_url.replace("+asyncpg", "")
    parsed = urlparse(raw_url)
    if not parsed.scheme.startswith("postgres"):
        saver = MemorySaver()
        _loop_savers[loop_key] = saver
        return saver

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=raw_url,
            max_size=10,
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
        _loop_savers[loop_key] = saver
        return saver
    except Exception as exc:  # pragma: no cover - env specific
        logger.warning("Postgres checkpointer init failed (%s) — MemorySaver", exc)
        saver = MemorySaver()
        _loop_savers[loop_key] = saver
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
    loop_key = id(asyncio.get_running_loop())
    saver = get_checkpointer()
    pool = getattr(saver, "_tg_pool", None)
    if pool is not None and getattr(saver, "_tg_ready", False):
        await pool.close()
        setattr(saver, "_tg_ready", False)
    _loop_savers.pop(loop_key, None)
