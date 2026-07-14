"""Agent runtime API tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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
