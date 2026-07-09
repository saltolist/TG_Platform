"""Tests for runtime AI context log filter API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.ai.context_log import get_chat_filter, init_chat_filter


@pytest.mark.asyncio
async def test_dev_context_log_disabled_returns_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.dev_context_log.get_settings", lambda: type("S", (), {"ai_context_log": False})())
    response = await client.put("/api/v1/dev/ai-context-log/", json={"chatId": "gc1"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dev_context_log_set_and_read(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.dev_context_log.get_settings", lambda: type("S", (), {"ai_context_log": True})())
    init_chat_filter("")

    put = await client.put("/api/v1/dev/ai-context-log/", json={"chatId": "gc1"})
    assert put.status_code == 200
    assert put.json() == {"enabled": True, "chatId": "gc1"}
    assert get_chat_filter() == "gc1"

    get = await client.get("/api/v1/dev/ai-context-log/")
    assert get.status_code == 200
    assert get.json() == {"enabled": True, "chatId": "gc1"}

    clear = await client.put("/api/v1/dev/ai-context-log/", json={"chatId": ""})
    assert clear.status_code == 200
    assert clear.json()["chatId"] == ""


@pytest.mark.asyncio
async def test_dev_context_log_traces_endpoint(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.dev_context_log.get_settings", lambda: type("S", (), {"ai_context_log": True})())

    from app.services.ai.ai_context_trace_buffer import clear_context_exchanges, make_stored_exchange, store_context_exchange

    clear_context_exchanges()
    store_context_exchange(
        make_stored_exchange(
            scope="post",
            chat_id=None,
            post_id="p1",
            post_chat_id="c1",
            user_text="hello",
            provider="x",
            model="y",
            pipeline="pipe",
            request="req",
            response="resp",
        )
    )

    response = await client.get("/api/v1/dev/ai-context-log/traces/", params={"chatId": "c1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["traces"][0]["userText"] == "hello"
    assert payload["traces"][0]["pipeline"] == "pipe"
