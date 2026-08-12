"""Спринт 5 tracing: render_run_trace over the durable agent_events chain."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token, hash_password
from app.db.models import User
from app.main import app
from app.services.agent.runtime.trace import render_run_trace
from tests.conftest import TestSessionLocal

_READ_RUN = [
    {"sequence": 1, "event_type": "graph_started", "payload": {"user_text": "Что в заметке n1?"}},
    {"sequence": 2, "event_type": "planner_step", "payload": {
        "step": 0, "tool": "OpenNote", "args": {"note_id": "n1"},
        "reasoning": "нужна заметка n1", "gap": "note content missing"}},
    {"sequence": 3, "event_type": "tool_result", "payload": {
        "step": 0, "tool": "OpenNote", "summary": "Заметка n1: Запуск в июле",
        "error": None, "record_ids": ["/note/global/n1/"]}},
    {"sequence": 4, "event_type": "answer", "payload": {
        "text": "Запуск в июле.", "claims": [{"c": 1}], "evidence_ids": ["/note/global/n1/"]}},
    {"sequence": 5, "event_type": "graph_state", "payload": {"status": "completed"}},
    {"sequence": 6, "event_type": "run_completed", "payload": {
        "status": "completed", "stopped_reason": "ready"}},
]


def test_render_run_trace_full_chain() -> None:
    body = render_run_trace(_READ_RUN, run_id="abc")
    # Decision chain is legible: planner reasoning → tool result → answer.
    assert "AGENT RUN abc" in body
    assert "status=completed" in body
    assert "user: Что в заметке n1?" in body
    assert "OpenNote" in body and "reasoning: нужна заметка n1" in body
    assert "evidence+= ['/note/global/n1/']" in body
    assert "answer: Запуск в июле." in body
    assert "terminal:" in body and "run_completed  (ready)" in body


def test_render_run_trace_shows_tool_error() -> None:
    events = [
        {"sequence": 1, "event_type": "graph_started", "payload": {"user_text": "?"}},
        {"sequence": 2, "event_type": "tool_result", "payload": {
            "step": 0, "tool": "OpenNote", "summary": "нет заметки", "error": "not_found",
            "record_ids": []}},
    ]
    body = render_run_trace(events)
    assert "error: not_found" in body
    # No evidence line when nothing was produced.
    assert "evidence+=" not in body


def test_render_run_trace_empty_is_blank() -> None:
    assert render_run_trace([]) == ""


def test_render_run_trace_accepts_orm_like_objects() -> None:
    class _Evt:
        def __init__(self, seq, et, pl):
            self.sequence, self.event_type, self.payload = seq, et, pl

    events = [
        _Evt(1, "graph_started", {"user_text": "hi"}),
        _Evt(2, "planner_step", {"step": 0, "tool": "ListPosts", "args": {}}),
    ]
    body = render_run_trace(events, run_id="x")
    assert "ListPosts" in body and "user: hi" in body


@pytest.mark.asyncio
async def test_get_agent_run_trace_renders_decision_chain(
    writer_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.tasks.agent_runs.async_session_factory", TestSessionLocal)
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"threadId": "trace-http-test", "scope": "global", "chatId": "gc1"},
            headers=writer_auth_headers,
        )
        run_id = created.json()["id"]

        from app.tasks.agent_runs import _execute_agent_run

        await _execute_agent_run(uuid.UUID(run_id), "Собери доступный контекст")

        resp = await client.get(f"/api/v1/ai/runs/{run_id}/trace/", headers=writer_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["event_count"] > 0
        assert "AGENT RUN" in body["trace"]


@pytest.mark.asyncio
async def test_get_agent_run_trace_is_owner_scoped(
    writer_auth_headers: dict[str, str],
) -> None:
    """Спринт 5: trace endpoint must not leak another user's run — same
    owner-scope contract as GET /{run_id}/."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"threadId": "trace-owner-test", "scope": "global", "chatId": "gc1"},
            headers=writer_auth_headers,
        )
        run_id = created.json()["id"]

        async with TestSessionLocal() as session:
            other = User(
                email=f"other-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=hash_password("SecretPass123"),
                is_seed=False,
            )
            session.add(other)
            await session.commit()
            other_token = create_access_token(str(other.id))

        resp = await client.get(
            f"/api/v1/ai/runs/{run_id}/trace/",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
