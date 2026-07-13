"""Combined agent E2E smoke tests (ADR-012 phase 7)."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.agent.runtime.sse_events import format_agent_sse_event, parse_last_event_id


def test_sse_last_event_id_parsing() -> None:
    assert parse_last_event_id("42") == 42
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("bad") == 0


def test_typed_sse_agent_event_shape() -> None:
    chunk = format_agent_sse_event(sequence=1, event_type="run_started", payload={"ok": True})
    assert chunk.startswith("id: 1")
    assert '"agent"' in chunk


@pytest.mark.asyncio
async def test_run_lifecycle_cancel(writer_auth_headers: dict[str, str]) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"thread_id": "e2e", "scope": "global"},
            headers=writer_auth_headers,
        )
        run_id = created.json()["id"]
        cancelled = await client.post(
            f"/api/v1/ai/runs/{run_id}/cancel/",
            headers=writer_auth_headers,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        snapshot = await client.get(f"/api/v1/ai/runs/{run_id}/", headers=writer_auth_headers)
        assert snapshot.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cross_tenant_run_isolation(writer_auth_headers: dict[str, str]) -> None:
    from app.core.security import create_access_token, hash_password
    from app.db.models import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as session:
        other = User(
            email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("SecretPass123"),
            is_seed=False,
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)
        other_headers = {"Authorization": f"Bearer {create_access_token(str(other.id))}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"thread_id": "iso"},
            headers=writer_auth_headers,
        )
        run_id = created.json()["id"]
        forbidden = await client.get(f"/api/v1/ai/runs/{run_id}/", headers=other_headers)
        assert forbidden.status_code == 404
