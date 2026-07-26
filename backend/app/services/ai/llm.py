"""OpenAI-compatible LLM client (streaming chat/completions)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from app.services.ai.providers import (
    ChatCompletionCapability,
    ProviderSpec,
    chat_completions_url,
)
from app.services.ai.sse import format_sse_data

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
    temperature: float | None = None,
    max_tokens: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[str]:
    """Yield text tokens from provider streaming API."""
    url = chat_completions_url(spec)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

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


async def complete_chat_completion(
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    client: httpx.AsyncClient | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    usage_sink: dict[str, Any] | None = None,
    output_capability: ChatCompletionCapability = ChatCompletionCapability.PLAIN,
    output_schema_name: str = "structured_output",
    output_json_schema: Mapping[str, Any] | None = None,
) -> str:
    """Non-streaming chat completion (rolling summary, etc.)."""
    url = chat_completions_url(spec)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if output_capability == ChatCompletionCapability.STRICT_JSON_SCHEMA:
        if not output_json_schema:
            raise ValueError("strict_json_schema requires output_json_schema")
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_schema_name,
                "strict": True,
                "schema": dict(output_json_schema),
            },
        }
    elif output_capability == ChatCompletionCapability.TOOL_CALLING:
        if not output_json_schema:
            raise ValueError("tool_calling requires output_json_schema")
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": output_schema_name,
                    "description": "Return the requested structured output.",
                    "strict": True,
                    "parameters": dict(output_json_schema),
                },
            }
        ]
        body["tool_choice"] = {
            "type": "function",
            "function": {"name": output_schema_name},
        }
    elif output_capability == ChatCompletionCapability.JSON_MODE:
        body["response_format"] = {"type": "json_object"}

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)

    try:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
        if usage_sink is not None:
            usage = data.get("usage")
            if isinstance(usage, Mapping):
                prompt_details = usage.get("prompt_tokens_details")
                details = prompt_details if isinstance(prompt_details, Mapping) else {}
                cached = details.get("cached_tokens")
                if cached is None:
                    cached = usage.get("prompt_cache_hit_tokens")
                input_tokens = usage.get("prompt_tokens")
                if input_tokens is None:
                    input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("completion_tokens")
                if output_tokens is None:
                    output_tokens = usage.get("output_tokens")
                total_tokens = usage.get("total_tokens")
                core_usage = (input_tokens, output_tokens, total_tokens)
                if all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in core_usage
                ):
                    usage_sink.update(
                        {
                            "availability": "measured",
                            "input_tokens": input_tokens,
                            "cached_input_tokens": (
                                cached
                                if isinstance(cached, int) and not isinstance(cached, bool)
                                else None
                            ),
                            "cached_input_availability": (
                                "measured"
                                if isinstance(cached, int) and not isinstance(cached, bool)
                                else "unavailable"
                            ),
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        }
                    )
            usage_sink.setdefault("availability", "unavailable")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        if output_capability == ChatCompletionCapability.TOOL_CALLING:
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list) or len(tool_calls) != 1:
                return ""
            function = (
                tool_calls[0].get("function")
                if isinstance(tool_calls[0], Mapping)
                else None
            )
            arguments = function.get("arguments") if isinstance(function, Mapping) else None
            return arguments if isinstance(arguments, str) else ""
        content = message.get("content")
        return content if isinstance(content, str) else ""
    finally:
        if owns_client:
            await client.aclose()


async def complete_vision_completion(
    *,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Non-streaming vision completion with OpenAI-style image_url content part."""
    import base64

    url = chat_completions_url(spec)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{image_b64}"
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "stream": False,
    }

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)

    try:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        return content if isinstance(content, str) else ""
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
