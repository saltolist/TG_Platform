"""Web search execution: three paths (A / B / C).

Path A — OpenAI Responses API with built-in web_search tool
Path B — Perplexity sonar models (built-in web search via chat completions)
Path C — Perplexity Search API (standalone retriever → context for LLM)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.ai.providers import WebSearchPath, WebSearchProviderSpec

_log = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=30.0)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WebCite:
    url: str
    title: str
    domain: str

    @classmethod
    def from_url(cls, url: str, title: str = "") -> "WebCite":
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.removeprefix("www.")
        except Exception:
            domain = url
        return cls(url=url, title=title or domain, domain=domain)


@dataclass
class WebSearchResult:
    """Accumulated result after a web search call."""
    text: str = ""
    cites: list[WebCite] = field(default_factory=list)
    # For path C only — raw search context injected into messages
    context: str = ""


# ---------------------------------------------------------------------------
# Path A — OpenAI Responses API
# ---------------------------------------------------------------------------

async def _stream_openai_responses(
    *,
    spec: WebSearchProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, list[WebCite]]]:
    """Stream tokens + annotations from OpenAI Responses API with web_search tool."""
    endpoint = spec.endpoint or "https://api.openai.com/v1/responses"
    input_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    body = {
        "model": model,
        "input": input_messages,
        "tools": [{"type": "web_search_preview"}],
        "stream": True,
    }
    cites: list[WebCite] = []
    annotations_seen: set[str] = set()

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        async with client.stream(
            "POST",
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[5:].strip()
                if not payload_str or payload_str == "[DONE]":
                    continue
                try:
                    event = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                # Text delta
                ev_type = event.get("type", "")
                if ev_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield delta, []

                # Annotations from completed output item
                elif ev_type == "response.output_item.done":
                    item = event.get("item") or {}
                    for part in item.get("content") or []:
                        for ann in part.get("annotations") or []:
                            if ann.get("type") == "url_citation":
                                url = ann.get("url", "")
                                title = ann.get("title", "")
                                if url and url not in annotations_seen:
                                    annotations_seen.add(url)
                                    cites.append(WebCite.from_url(url, title))

    if cites:
        yield "", cites


async def run_path_a(
    *,
    spec: WebSearchProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, list[WebCite]]]:
    return _stream_openai_responses(
        spec=spec, model=model, api_key=api_key, messages=messages
    )


# ---------------------------------------------------------------------------
# Path B — Perplexity sonar (built-in search via chat completions)
# ---------------------------------------------------------------------------

async def _stream_perplexity_sonar(
    *,
    spec: WebSearchProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, list[WebCite]]]:
    endpoint = spec.endpoint or "https://api.perplexity.ai/v1/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    cites: list[WebCite] = []
    citations_collected = False

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        async with client.stream(
            "POST",
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[5:].strip()
                if not payload_str or payload_str == "[DONE]":
                    continue
                try:
                    event = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                choices = event.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content", "")
                    if delta:
                        yield delta, []

                # Perplexity returns citations as top-level array in the final chunk
                if not citations_collected:
                    raw_cites = event.get("citations") or []
                    for entry in raw_cites:
                        if isinstance(entry, str):
                            cites.append(WebCite.from_url(entry))
                        elif isinstance(entry, dict):
                            cites.append(WebCite.from_url(
                                entry.get("url", ""), entry.get("title", "")
                            ))
                    if raw_cites:
                        citations_collected = True

    if cites:
        yield "", cites


async def run_path_b(
    *,
    spec: WebSearchProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, list[WebCite]]]:
    return _stream_perplexity_sonar(
        spec=spec, model=model, api_key=api_key, messages=messages
    )


# ---------------------------------------------------------------------------
# Path C — Perplexity Search API (retriever only → returns context string)
# ---------------------------------------------------------------------------

async def call_perplexity_search(
    *,
    query: str,
    api_key: str,
    max_results: int = 5,
) -> tuple[str, list[WebCite]]:
    """Call Perplexity Search API and return (context_markdown, cites)."""
    endpoint = "https://api.perplexity.ai/search"
    body = {"query": query, "return_citations": True, "max_results": max_results}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    cites: list[WebCite] = []
    context_lines: list[str] = []

    results = data.get("results") or []
    for i, r in enumerate(results, 1):
        url = r.get("url", "")
        title = r.get("title", "") or url
        snippet = r.get("snippet", "") or r.get("content", "")
        if url:
            cites.append(WebCite.from_url(url, title))
        if snippet:
            context_lines.append(f"[{i}] {title}\n{snippet}")

    context = "\n\n".join(context_lines)
    return context, cites


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def execute_web_search(
    *,
    spec: WebSearchProviderSpec,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    query: str = "",
) -> AsyncIterator[tuple[str, list[WebCite]]]:
    """Dispatch to the correct path based on spec.path."""
    if spec.path == WebSearchPath.OPENAI_RESPONSES:
        return await run_path_a(spec=spec, model=model, api_key=api_key, messages=messages)
    if spec.path == WebSearchPath.PERPLEXITY_SONAR:
        return await run_path_b(spec=spec, model=model, api_key=api_key, messages=messages)
    if spec.path == WebSearchPath.PERPLEXITY_SEARCH:
        # Path C: search only — caller gets context + cites; streaming not used here
        async def _path_c() -> AsyncIterator[tuple[str, list[WebCite]]]:
            ctx, cites = await call_perplexity_search(query=query, api_key=api_key)
            yield "", cites
            yield ctx, []
        return _path_c()
    raise ValueError(f"Unknown web search path: {spec.path}")
