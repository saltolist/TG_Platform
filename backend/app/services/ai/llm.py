"""OpenAI-compatible LLM client (streaming chat/completions)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from app.services.ai.providers import ProviderSpec, chat_completions_url
from app.services.ai.sse import format_sse_data

DEFAULT_SYSTEM_PROMPT = (
    "Ты AI-ассистент TG Platform. Помогай автору Telegram-канала с текстами, "
    "идеями и анализом. Отвечай на языке пользователя, кратко и по делу."
)

_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=30.0)

_LLM_ERROR_GENERIC = (
    "Не удалось получить ответ от модели. Проверьте API ключ и настройки провайдера."
)


def llm_http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "Неверный или недействительный API ключ провайдера."
    if status == 429:
        return "Превышен лимит запросов к провайдеру. Попробуйте позже."
    return _LLM_ERROR_GENERIC


def build_reply_messages(
    ai_profile: Mapping[str, Any],
    user_text: str,
    scope: str = "global",
) -> list[dict[str, str]]:
    """Minimal message list until full context assembly (step 3.3)."""
    system_prompt = str(ai_profile.get("systemPrompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
    text = user_text.strip()
    if scope == "post":
        text = f"[Чат поста · контекст поста подключится на шаге 3.3]\n{text}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]


def parse_openai_stream_line(line: str) -> str | None:
    """Extract text delta from one SSE line of OpenAI-compatible stream."""
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    return content if isinstance(content, str) and content else None


async def stream_chat_completion_tokens(
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[str]:
    """Yield text tokens from provider streaming API."""
    url = chat_completions_url(spec)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)

    try:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                token = parse_openai_stream_line(line)
                if token:
                    yield token
    finally:
        if owns_client:
            await client.aclose()


async def stream_llm_sse(
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Stream LLM tokens as SSE `data: {"text": "..."}` chunks."""
    yielded = False
    try:
        async for token in stream_chat_completion_tokens(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        ):
            yielded = True
            yield format_sse_data(token)
    except httpx.HTTPStatusError as exc:
        yield format_sse_data(llm_http_error_message(exc))
        return
    except httpx.HTTPError:
        yield format_sse_data(
            "Не удалось связаться с провайдером LLM. Проверьте сеть и повторите попытку."
        )
        return

    if not yielded:
        yield format_sse_data(_LLM_ERROR_GENERIC)
