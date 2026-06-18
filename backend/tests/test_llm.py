"""Tests for OpenAI-compatible LLM client (Phase 2, step 3.2)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import httpx
from httpx import AsyncClient

from app.core.config import Settings
from app.db.models import Profile, User
from app.services.ai.llm import (
    build_reply_messages,
    parse_openai_stream_line,
    stream_chat_completion_tokens,
    stream_llm_sse,
)
from app.services.ai.providers import chat_completions_url, get_provider_spec
from app.services.ai.sse import format_sse_data
from tests.conftest import TestSessionLocal, guest_auth_headers, writer_auth_headers


def parse_sse_text(body: str) -> str:
    chunks: list[str] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = json.loads(block[6:])
        chunks.append(str(payload.get("text", "")))
    return "".join(chunks)


def test_get_provider_spec_known() -> None:
    openai = get_provider_spec("OpenAI")
    deepseek = get_provider_spec("DeepSeek")
    assert openai is not None
    assert deepseek is not None
    assert chat_completions_url(openai) == "https://api.openai.com/v1/chat/completions"
    assert chat_completions_url(deepseek) == "https://api.deepseek.com/v1/chat/completions"
    assert get_provider_spec("Anthropic") is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('data: {"choices":[{"delta":{"content":"Hi"}}]}', "Hi"),
        ("data: [DONE]", None),
        ("", None),
        ("data: not-json", None),
    ],
)
def test_parse_openai_stream_line(line: str, expected: str | None) -> None:
    assert parse_openai_stream_line(line) == expected


def test_build_reply_messages_uses_profile_system_prompt() -> None:
    messages = build_reply_messages(
        {"systemPrompt": "Custom system"},
        "Привет",
        scope="global",
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Custom system"
    assert messages[1]["content"] == "Привет"


def test_build_reply_messages_post_scope_marker() -> None:
    messages = build_reply_messages({}, "Текст", scope="post")
    assert "[Чат поста" in messages[1]["content"]
    assert "Текст" in messages[1]["content"]


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeHttpClient:
    def __init__(self, lines: list[str], recorder: list[dict[str, Any]]) -> None:
        self._lines = lines
        self._recorder = recorder

    def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict) -> Any:
        self._recorder.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )

        class _Ctx:
            def __init__(self, lines: list[str]) -> None:
                self._lines = lines

            async def __aenter__(self) -> _FakeStreamResponse:
                return _FakeStreamResponse(self._lines)

            async def __aexit__(self, *args: object) -> None:
                return None

        return _Ctx(self._lines)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "base_host", "model"),
    [
        ("OpenAI", "api.openai.com", "gpt-4o"),
        ("DeepSeek", "api.deepseek.com", "deepseek-chat"),
    ],
)
async def test_stream_chat_completion_tokens_openai_compatible(
    provider: str, base_host: str, model: str
) -> None:
    spec = get_provider_spec(provider)
    assert spec is not None
    recorder: list[dict[str, Any]] = []
    client = _FakeHttpClient(
        [
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ],
        recorder,
    )

    tokens: list[str] = []
    async for token in stream_chat_completion_tokens(
        spec=spec,
        model=model,
        api_key="sk-test",
        messages=[{"role": "user", "content": "Hi"}],
        client=client,  # type: ignore[arg-type]
    ):
        tokens.append(token)

    assert tokens == ["Hel", "lo"]
    assert len(recorder) == 1
    assert base_host in recorder[0]["url"]
    assert recorder[0]["json"]["model"] == model
    assert recorder[0]["json"]["stream"] is True
    assert recorder[0]["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_ai_reply_unsupported_provider_returns_422(
    client: AsyncClient, writer_user: User, writer_auth_headers: dict[str, str]
) -> None:
    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=writer_user.id,
                ai={
                    "systemPrompt": "Test",
                    "llmModels": [
                        {
                            "id": "anthropic-1",
                            "provider": "Anthropic",
                            "model": "claude-3-5-sonnet",
                            "apiKey": "sk-ant-test",
                            "active": True,
                        }
                    ],
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/ai/reply/",
        headers=writer_auth_headers,
        json={"text": "Hello", "scope": "global"},
    )
    assert response.status_code == 422
    assert "Anthropic" in response.json()["error"]


@pytest.mark.asyncio
async def test_ai_reply_llm_stream_with_mocked_http(
    client: AsyncClient,
    presentation_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream_llm_sse(**kwargs: object) -> AsyncIterator[str]:
        yield format_sse_data("Mock")
        yield format_sse_data(" LLM")

    settings = Settings(deepseek_api_key="sk-env-deepseek")
    monkeypatch.setattr("app.api.v1.ai.stream_llm_sse", fake_stream_llm_sse)
    monkeypatch.setattr("app.api.v1.ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.ai.keys.get_settings", lambda: settings)

    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=presentation_user.id,
                ai={
                    "systemPrompt": "Test",
                    "llmModels": [
                        {
                            "id": "ds-1",
                            "provider": "DeepSeek",
                            "model": "deepseek-chat",
                            "apiKey": "",
                            "active": True,
                        }
                    ],
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/ai/reply/",
        headers=guest_auth_headers(),
        json={"text": "Hello", "scope": "global", "llmId": "ds-1"},
    )

    assert response.status_code == 200
    assert parse_sse_text(response.text) == "Mock LLM"


@pytest.mark.asyncio
async def test_ai_reply_request_api_key_overrides_profile_for_demo(
    client: AsyncClient,
    presentation_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_stream_llm_sse(**kwargs: object) -> AsyncIterator[str]:
        captured.update(kwargs)
        yield format_sse_data("BYOK")

    settings = Settings(openai_api_key="", deepseek_api_key="")
    monkeypatch.setattr("app.api.v1.ai.stream_llm_sse", fake_stream_llm_sse)
    monkeypatch.setattr("app.api.v1.ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.ai.keys.get_settings", lambda: settings)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, presentation_user.id)
        if profile is None:
            profile = Profile(user_id=presentation_user.id, ai={})
            session.add(profile)
        profile.ai = {
            "systemPrompt": "Test",
            "llmModels": [
                {
                    "id": "ds-demo",
                    "provider": "DeepSeek",
                    "model": "deepseek-chat",
                    "apiKey": "env:DEEPSEEK_API_KEY",
                    "active": True,
                }
            ],
        }
        await session.commit()

    response = await client.post(
        "/api/v1/ai/reply/",
        headers=guest_auth_headers(),
        json={
            "text": "Hello",
            "scope": "global",
            "llmId": "ds-demo",
            "apiKey": "sk-user-deepseek",
        },
    )

    assert response.status_code == 200
    assert parse_sse_text(response.text) == "BYOK"
    assert captured["api_key"] == "sk-user-deepseek"


@pytest.mark.asyncio
async def test_ai_reply_uses_client_provider_when_overlay_differs_from_db(
    client: AsyncClient,
    presentation_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_stream_llm_sse(**kwargs: object) -> AsyncIterator[str]:
        captured.update(kwargs)
        yield format_sse_data("DeepSeek OK")

    settings = Settings(openai_api_key="", deepseek_api_key="")
    monkeypatch.setattr("app.api.v1.ai.stream_llm_sse", fake_stream_llm_sse)
    monkeypatch.setattr("app.api.v1.ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.ai.keys.get_settings", lambda: settings)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, presentation_user.id)
        if profile is None:
            profile = Profile(user_id=presentation_user.id, ai={})
            session.add(profile)
        profile.ai = {
            "systemPrompt": "Test",
            "llmModels": [
                {
                    "id": "llm-1",
                    "provider": "OpenAI",
                    "model": "gpt-4o",
                    "apiKey": "sk-openai-demo",
                    "active": True,
                }
            ],
        }
        await session.commit()

    response = await client.post(
        "/api/v1/ai/reply/",
        headers=guest_auth_headers(),
        json={
            "text": "Hello",
            "scope": "global",
            "llmId": "overlay-deepseek-1",
            "provider": "DeepSeek",
            "model": "deepseek-chat",
            "apiKey": "sk-user-deepseek",
        },
    )

    assert response.status_code == 200
    assert parse_sse_text(response.text) == "DeepSeek OK"
    assert captured["model"] == "deepseek-chat"
    assert captured["api_key"] == "sk-user-deepseek"


@pytest.mark.asyncio
async def test_stream_llm_sse_returns_error_text_on_http_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(401, request=request)

    async def failing_tokens(**kwargs: object) -> AsyncIterator[str]:
        raise httpx.HTTPStatusError("Unauthorized", request=request, response=response)
        yield ""  # pragma: no cover

    monkeypatch.setattr("app.services.ai.llm.stream_chat_completion_tokens", failing_tokens)

    spec = get_provider_spec("DeepSeek")
    assert spec is not None

    body = "".join(
        [
            chunk
            async for chunk in stream_llm_sse(
                spec=spec,
                model="deepseek-chat",
                api_key="sk-bad",
                messages=[{"role": "user", "content": "Hi"}],
            )
        ]
    )
    text = parse_sse_text(body)
    assert "недействительный" in text.lower()


@pytest.mark.asyncio
async def test_ai_reply_invalid_key_returns_error_text_for_real_account(
    client: AsyncClient,
    writer_user: User,
    writer_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(401, request=request)

    async def failing_tokens(**kwargs: object) -> AsyncIterator[str]:
        raise httpx.HTTPStatusError("Unauthorized", request=request, response=response)
        yield ""  # pragma: no cover

    monkeypatch.setattr("app.services.ai.llm.stream_chat_completion_tokens", failing_tokens)

    async with TestSessionLocal() as session:
        session.add(
            Profile(
                user_id=writer_user.id,
                ai={
                    "systemPrompt": "Test",
                    "llmModels": [
                        {
                            "id": "llm-1",
                            "provider": "OpenAI",
                            "model": "gpt-4o",
                            "apiKey": "sk-bad-real",
                            "active": True,
                        }
                    ],
                },
            )
        )
        await session.commit()

    http_response = await client.post(
        "/api/v1/ai/reply/",
        headers=writer_auth_headers,
        json={"text": "Hello", "scope": "global", "llmId": "llm-1"},
    )
    assert http_response.status_code == 200
    text = parse_sse_text(http_response.text)
    assert "недействительный" in text.lower()
