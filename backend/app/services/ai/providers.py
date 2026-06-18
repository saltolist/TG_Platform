"""Supported LLM providers (OpenAI-compatible chat/completions)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "OpenAI": ProviderSpec("OpenAI", "https://api.openai.com"),
    "DeepSeek": ProviderSpec("DeepSeek", "https://api.deepseek.com"),
}


def get_provider_spec(provider: str) -> ProviderSpec | None:
    return PROVIDER_SPECS.get(provider.strip()) if provider else None


def chat_completions_url(spec: ProviderSpec) -> str:
    return f"{spec.base_url.rstrip('/')}/v1/chat/completions"
