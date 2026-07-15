"""Agent runtime API tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import GlobalChat
from app.main import app
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run
from tests.conftest import TestSessionLocal, sample_global_chat


@pytest.mark.asyncio
async def test_create_and_get_agent_run(writer_auth_headers: dict[str, str]) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"threadId": "gc-test", "scope": "global", "chatId": "gc1"},
            headers=writer_auth_headers,
        )
        assert created.status_code == 201
        run_id = created.json()["id"]

        fetched = await client.get(f"/api/v1/ai/runs/{run_id}/", headers=writer_auth_headers)
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "running"
        assert body["thread_id"] == "gc-test"


@pytest.mark.asyncio
async def test_agent_run_not_found(writer_auth_headers: dict[str, str]) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/ai/runs/{uuid.uuid4()}/", headers=writer_auth_headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_executes_with_postgres_checkpoint(
    writer_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The API writes the run to the test DB, so the durable executor must read
    # from the same session factory. Without this it silently uses the prod
    # factory, never finds the run, and returns early leaving status="running".
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr("app.tasks.agent_runs.async_session_factory", TestSessionLocal)
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={
                "threadId": "durable-test",
                "scope": "global",
                "chatId": "gc1",
            },
            headers=writer_auth_headers,
        )
        assert created.status_code == 201
        run_id = created.json()["id"]

        from app.tasks.agent_runs import _execute_agent_run

        await _execute_agent_run(uuid.UUID(run_id), "Собери доступный контекст")

        fetched = await client.get(
            f"/api/v1/ai/runs/{run_id}/",
            headers=writer_auth_headers,
        )
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "completed"
        assert body["snapshot"]["run_id"] == run_id


@pytest.mark.asyncio
async def test_rebuild_runtime_context_loads_dialog_context_from_chat_history(
    writer_user,
) -> None:
    """Cross-turn deixis (agent-runtime-sprints §2.1): a run's RuntimeContext
    carries prior chat turns as dialog_context, sourced the same way the
    legacy reply path does (GlobalChat.data.history).
    """
    chat_id = str(uuid.uuid4())
    seeded_history = [
        {"role": "user", "text": "Расскажи про пост про скидки"},
        {"role": "ai", "text": "Пост про скидки собрал 500 просмотров"},
    ]

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": seeded_history},
            )
        )
        await session.commit()

        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="dialog-ctx-test",
            scope="global",
            chat_id=chat_id,
        )

        context = await rebuild_runtime_context_for_run(
            session, run, "А что по второму посту?"
        )

    assert "Пост про скидки собрал 500 просмотров" in context.dialog_context
    assert "Расскажи про пост про скидки" in context.dialog_context


@pytest.mark.asyncio
async def test_rebuild_runtime_context_empty_dialog_context_without_chat(
    writer_user,
) -> None:
    """No chat_id / unknown chat → empty dialog_context, not an error (memory
    is best-effort, never a hard dependency for the run)."""
    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="dialog-ctx-empty-test",
            scope="global",
        )

        context = await rebuild_runtime_context_for_run(session, run, "Привет")

    assert context.dialog_context == ""
