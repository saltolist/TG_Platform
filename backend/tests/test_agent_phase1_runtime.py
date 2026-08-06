"""Phase 1 gates: Celery loop ownership, fork reset, warmup and queues."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
import httpx
from psycopg_pool import AsyncConnectionPool, AsyncNullConnectionPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.celery_app import celery_app
from app.services.agent.runtime import checkpoint
from app.services.ai import embeddings
from app.tasks import agent_runs, async_runtime
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
def isolated_worker_loop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(async_runtime, "_loop", None)
    monkeypatch.setattr(async_runtime, "_worker_pid", None)
    yield
    loop = async_runtime._loop
    if loop is not None and not loop.is_closed():
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    monkeypatch.setattr(async_runtime, "_loop", None)
    asyncio.set_event_loop(None)


def test_1000_sequential_and_parallel_runs_share_one_worker_loop(
    isolated_worker_loop,
) -> None:
    seen: set[int] = set()

    async def setup_database():
        engine = create_async_engine(TEST_DATABASE_URL, pool_size=5, max_overflow=0)
        return engine, async_sessionmaker(engine, expire_on_commit=False)

    engine, session_factory = async_runtime.run_async(setup_database())

    async def unit() -> None:
        seen.add(id(asyncio.get_running_loop()))
        async with session_factory() as session:
            assert await session.scalar(text("SELECT 1")) == 1

    for _ in range(500):
        async_runtime.run_async(unit())

    async def parallel() -> None:
        for start in range(0, 500, 25):
            await asyncio.gather(*(unit() for _ in range(start, start + 25)))

    async_runtime.run_async(parallel())

    async def dispose_database() -> None:
        await engine.dispose()
        # Let asyncpg finish cancellation/close callbacks before the owned loop
        # is torn down by the fixture (notably required on Python 3.14).
        await asyncio.sleep(0)

    async_runtime.run_async(dispose_database())
    assert len(seen) == 1
    assert async_runtime.runtime_status()["loop_id"] == next(iter(seen))


def test_fork_reset_discards_parent_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.session import engine

    dispose = Mock()
    embedding_reset = Mock()
    checkpointer_reset = Mock()
    monkeypatch.setattr(engine.sync_engine, "dispose", dispose)
    monkeypatch.setattr(embeddings, "reset_embedding_runtime_after_fork", embedding_reset)
    monkeypatch.setattr(checkpoint, "reset_checkpointer_after_fork", checkpointer_reset)

    async_runtime.reset_after_fork()

    dispose.assert_called_once_with(close=False)
    embedding_reset.assert_called_once_with()
    checkpointer_reset.assert_called_once_with()
    assert async_runtime.runtime_status()["status"] == "initializing"


@pytest.mark.asyncio
async def test_short_lived_loop_uses_null_checkpointer_pool() -> None:
    checkpoint.reset_checkpointer_after_fork()
    saver = checkpoint.get_checkpointer()
    assert isinstance(getattr(saver, "_tg_pool"), AsyncNullConnectionPool)
    checkpoint.reset_checkpointer_after_fork()


@pytest.mark.asyncio
async def test_owned_runtime_loop_uses_bounded_checkpointer_pool() -> None:
    checkpoint.reset_checkpointer_after_fork()
    checkpoint.mark_checkpointer_loop_persistent()
    saver = checkpoint.get_checkpointer()
    pool = getattr(saver, "_tg_pool")
    assert isinstance(pool, AsyncConnectionPool)
    assert pool.max_size >= 1
    checkpoint.reset_checkpointer_after_fork()


@pytest.mark.asyncio
async def test_worker_warmup_constructs_model_and_performs_real_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = embeddings.get_settings().model_copy(update={"rag_enabled": True})
    model = object()
    embedded: list[str] = []

    async def fake_embed(self, text: str) -> list[float]:
        assert embeddings._fastembed_models[self._model_name] is model
        embedded.append(text)
        return [0.1]

    def fake_get_model(name: str):
        embeddings._fastembed_models[name] = model
        return model

    monkeypatch.setattr(embeddings, "get_settings", lambda: settings)
    monkeypatch.setattr(embeddings, "_get_fastembed_model", fake_get_model)
    monkeypatch.setattr(embeddings.LocalEmbeddingBackend, "embed_query", fake_embed)

    result = await embeddings.warmup_local_embedding_runtime()

    assert result["ready"] is True
    assert result["embedding_init_ms"] is not None
    assert result["first_embed_ms"] is not None
    assert embedded == ["workspace agent worker readiness probe"]


@pytest.mark.asyncio
async def test_interactive_worker_readiness_warms_checkpointer_and_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_embedding_warmup():
        calls.append("embedding")
        return {
            "ready": True,
            "status": "ready",
            "embedding_init_ms": 1.0,
            "first_embed_ms": 2.0,
        }

    async def fake_checkpointer_warmup():
        calls.append("checkpointer")

    def fake_graph_compile():
        calls.append("graph")
        return object()

    monkeypatch.setenv("TG_CELERY_WORKER_KIND", "interactive")
    monkeypatch.setattr(embeddings, "warmup_local_embedding_runtime", fake_embedding_warmup)
    monkeypatch.setattr(checkpoint, "ensure_checkpointer_ready", fake_checkpointer_warmup)
    monkeypatch.setattr(
        "app.services.agent.runtime.workspace_graph.get_compiled_workspace_graph",
        fake_graph_compile,
    )

    result = await async_runtime.initialize_worker_runtime()

    assert result["ready"] is True
    assert calls == ["embedding", "checkpointer", "graph"]
    assert result["checkpointer_init_ms"] is not None
    assert result["graph_compile_ms"] is not None


def test_celery_routes_isolate_interactive_and_heavy_work() -> None:
    assert celery_app.conf.task_routes
    routes = celery_app.conf.task_routes
    assert (
        routes["app.tasks.agent_runs.execute_agent_run_task"]["queue"]
        == "agent-interactive"
    )
    assert routes["media_generation.run_job"]["queue"] == "agent-heavy"
    assert routes["media_generation.cancel_provider_operation"]["queue"] == "agent-heavy"
    assert routes["app.tasks.analytics_snapshot.capture_all_channel_snapshots"]["queue"] == "analytics"
    assert celery_app.conf.worker_proc_alive_timeout == 90.0


def test_phase1_flag_parses_string_values() -> None:
    from app.core.config import Settings

    assert Settings(agent_runtime_phase1_enabled="1").agent_runtime_phase1_enabled is True
    assert Settings(agent_runtime_phase1_enabled="0").agent_runtime_phase1_enabled is False


def test_local_embedding_key_fingerprints_runtime_and_pooling() -> None:
    backend = embeddings.LocalEmbeddingBackend()
    assert backend.model_key.endswith("@fastembed=0.8.0;pooling=mean")


def test_cross_loop_programming_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    retry = Mock(side_effect=AssertionError("retry must be suppressed"))
    monkeypatch.setattr(
        agent_runs,
        "run_async",
        Mock(side_effect=RuntimeError("Future attached to a different loop")),
    )
    monkeypatch.setattr(agent_runs.execute_agent_run_task, "retry", retry)

    with pytest.raises(RuntimeError, match="different loop"):
        agent_runs.execute_agent_run_task.run(str(uuid.uuid4()), "test")

    retry.assert_not_called()


def test_transient_transport_error_uses_bounded_celery_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_signal = RuntimeError("retry scheduled")
    retry = Mock(side_effect=retry_signal)

    def fail_transport(coroutine):
        coroutine.close()
        raise httpx.ConnectError("dns unavailable")

    monkeypatch.setattr(agent_runs, "run_async", Mock(side_effect=fail_transport))
    monkeypatch.setattr(agent_runs.execute_agent_run_task, "retry", retry)

    with pytest.raises(RuntimeError, match="retry scheduled"):
        agent_runs.execute_agent_run_task.run(str(uuid.uuid4()), "test")

    retry.assert_called_once()
    assert retry.call_args.kwargs["countdown"] == 1


def test_runtime_health_probe_exposes_worker_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_runs,
        "runtime_status",
        lambda: {"ready": True, "status": "ready"},
    )
    assert agent_runs.runtime_health.run() == {"ready": True, "status": "ready"}


def test_prometheus_prefork_metrics_are_aggregated(tmp_path) -> None:
    multiprocess_dir = tmp_path / "prometheus"
    multiprocess_dir.mkdir()
    script = textwrap.dedent(
        """
        import os

        from prometheus_client import CollectorRegistry, generate_latest, multiprocess
        from app.services.agent.runtime.observability import (
            AGENT_RUNS,
            AGENT_WORKER_READY,
        )

        pid = os.fork()
        if pid == 0:
            AGENT_RUNS.labels("completed").inc(2)
            AGENT_WORKER_READY.set(1)
            os._exit(0)

        os.waitpid(pid, 0)
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        output = generate_latest(registry).decode()
        assert 'agent_runs_total{status="completed"} 2.0' in output
        assert 'agent_worker_ready 1.0' in output

        multiprocess.mark_process_dead(pid)
        output_after_shutdown = generate_latest(registry).decode()
        assert 'agent_runs_total{status="completed"} 2.0' in output_after_shutdown
        assert 'agent_worker_ready 1.0' not in output_after_shutdown
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "PROMETHEUS_MULTIPROC_DIR": str(multiprocess_dir),
    }

    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=os.fspath(Path(__file__).parents[1]),
        env=env,
        capture_output=True,
        text=True,
    )


def test_failed_warmup_rejects_interactive_task_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry = Mock(side_effect=AssertionError("retry must be suppressed"))
    monkeypatch.setattr(
        agent_runs,
        "runtime_status",
        lambda: {"ready": False, "status": "warmup_failed"},
    )
    monkeypatch.setattr(agent_runs.execute_agent_run_task, "retry", retry)

    def close_unready_coroutine(coroutine):
        coroutine.close()

    run_async = Mock(side_effect=close_unready_coroutine)
    monkeypatch.setattr(agent_runs, "run_async", run_async)

    with pytest.raises(async_runtime.WorkerNotReadyError, match="warmup failed"):
        agent_runs.execute_agent_run_task.run(str(uuid.uuid4()), "test")

    retry.assert_not_called()
    run_async.assert_called_once()
