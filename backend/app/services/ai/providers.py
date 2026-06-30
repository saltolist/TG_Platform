"""Supported AI providers: chat/completions, embeddings and web search."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str


# Chat/completions providers (OpenAI-compatible /v1/chat/completions)
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "OpenAI": ProviderSpec("OpenAI", "https://api.openai.com"),
    "DeepSeek": ProviderSpec("DeepSeek", "https://api.deepseek.com"),
    "Perplexity": ProviderSpec("Perplexity", "https://api.perplexity.ai"),
}


def get_provider_spec(provider: str) -> ProviderSpec | None:
    return PROVIDER_SPECS.get(provider.strip()) if provider else None


def chat_completions_url(spec: ProviderSpec) -> str:
    return f"{spec.base_url.rstrip('/')}/v1/chat/completions"


# ---------------------------------------------------------------------------
# Web search providers
# ---------------------------------------------------------------------------

class WebSearchPath(str, Enum):
    """Execution path for a web search provider."""
    OPENAI_RESPONSES = "openai_responses"   # Path A: OpenAI Responses API with web_search tool
    PERPLEXITY_SONAR = "perplexity_sonar"   # Path B: Perplexity sonar LLM (built-in search)
    PERPLEXITY_SEARCH = "perplexity_search" # Path C: Perplexity Search API (standalone retriever)


@dataclass(frozen=True)
class WebSearchProviderSpec:
    name: str
    path: WebSearchPath
    # API endpoint; None means provider-specific logic resolves it
    endpoint: str | None = None


WEB_SEARCH_PROVIDER_SPECS: dict[str, WebSearchProviderSpec] = {
    # "OpenAI / responses-api-web-search" → OpenAI Responses API
    "OpenAI:responses-api-web-search": WebSearchProviderSpec(
        name="OpenAI responses-api",
        path=WebSearchPath.OPENAI_RESPONSES,
        endpoint="https://api.openai.com/v1/responses",
    ),
    # "Perplexity / search-api" → Perplexity Search API (standalone, path C)
    "Perplexity:search-api": WebSearchProviderSpec(
        name="Perplexity Search API",
        path=WebSearchPath.PERPLEXITY_SEARCH,
        endpoint="https://api.perplexity.ai/search",
    ),
}

# Perplexity sonar models use built-in search (path B) via regular chat endpoint
_PERPLEXITY_SONAR_PREFIXES = ("sonar",)


def get_web_search_spec(provider: str, model: str) -> WebSearchProviderSpec | None:
    """Resolve a web search spec from provider + model.

    Perplexity sonar models are detected by model name prefix (path B).
    Named combinations are looked up in WEB_SEARCH_PROVIDER_SPECS (paths A/C).
    """
    key = f"{provider.strip()}:{model.strip()}"
    if key in WEB_SEARCH_PROVIDER_SPECS:
        return WEB_SEARCH_PROVIDER_SPECS[key]

    if provider.strip() == "Perplexity":
        for prefix in _PERPLEXITY_SONAR_PREFIXES:
            if model.strip().startswith(prefix):
                return WebSearchProviderSpec(
                    name=f"Perplexity {model}",
                    path=WebSearchPath.PERPLEXITY_SONAR,
                    endpoint=chat_completions_url(PROVIDER_SPECS["Perplexity"]),
                )

    return None


# Embeddings providers (OpenAI-compatible /v1/embeddings)
# Key: display name (same as PROVIDER_ENV_ATTR in keys.py)
# Value: (base_url, default model name, embedding dimensionality)

@dataclass(frozen=True)
class EmbeddingProviderSpec:
    name: str
    base_url: str
    default_model: str
    dim: int


EMBEDDING_PROVIDER_SPECS: dict[str, EmbeddingProviderSpec] = {
    "OpenAI": EmbeddingProviderSpec(
        name="OpenAI",
        base_url="https://api.openai.com",
        default_model="text-embedding-3-small",
        dim=1536,
    ),
}


def get_embedding_provider_spec(provider: str) -> EmbeddingProviderSpec | None:
    return EMBEDDING_PROVIDER_SPECS.get(provider.strip()) if provider else None


def embeddings_url(spec: EmbeddingProviderSpec) -> str:
    return f"{spec.base_url.rstrip('/')}/v1/embeddings"
