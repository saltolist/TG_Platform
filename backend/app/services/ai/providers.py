"""Supported AI providers: chat/completions and embeddings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str


# Chat/completions providers (OpenAI-compatible /v1/chat/completions)
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "OpenAI": ProviderSpec("OpenAI", "https://api.openai.com"),
    "DeepSeek": ProviderSpec("DeepSeek", "https://api.deepseek.com"),
}


def get_provider_spec(provider: str) -> ProviderSpec | None:
    return PROVIDER_SPECS.get(provider.strip()) if provider else None


def chat_completions_url(spec: ProviderSpec) -> str:
    return f"{spec.base_url.rstrip('/')}/v1/chat/completions"


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
