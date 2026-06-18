"""Provider model catalogs and AI profile builders for seed accounts (mirror frontend composer.ts)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.config import Settings

ENV_REF_PREFIX = "env:"

# Mirror of frontend/src/shared/config/composer.ts
LLM_PROVIDER_MODELS: dict[str, list[str]] = {
    "OpenAI": ["gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
    "Perplexity": ["sonar", "sonar-pro"],
    "Anthropic": ["claude-3-7-sonnet", "claude-3-5-sonnet"],
    "Mistral": ["mistral-large", "mistral-small"],
    "Google": ["gemini-1.5-pro", "gemini-1.5-flash"],
    "DeepSeek": ["deepseek-chat", "deepseek-reasoner"],
    "OpenRouter": [
        "meta-llama/llama-3.1-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
    ],
}

WEB_SEARCH_PROVIDER_MODELS: dict[str, list[str]] = {
    "Perplexity": ["search-api"],
    "OpenAI": ["responses-api-web-search"],
    "Tavily": ["search-v1"],
    "SerpAPI": ["google-search"],
    "Exa": ["exa-neural"],
}

# LLM provider → (env var name, settings attribute)
LLM_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "OpenAI": ("OPENAI_API_KEY", "openai_api_key"),
    "DeepSeek": ("DEEPSEEK_API_KEY", "deepseek_api_key"),
}

WEB_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "Tavily": ("TAVILY_API_KEY", "tavily_api_key"),
    "Perplexity": ("PERPLEXITY_API_KEY", "perplexity_api_key"),
    "OpenAI": ("OPENAI_API_KEY", "openai_api_key"),
    "SerpAPI": ("SERPAPI_API_KEY", "serpapi_api_key"),
    "Exa": ("EXA_API_KEY", "exa_api_key"),
}

TOP_MODEL_COUNT = 2


def _settings_has_attr(settings: Settings, attr: str) -> bool:
    value = getattr(settings, attr, "")
    return isinstance(value, str) and bool(value.strip())


def _llm_providers_with_keys(settings: Settings) -> list[str]:
    return [
        provider
        for provider, (_, attr) in LLM_PROVIDER_ENV.items()
        if _settings_has_attr(settings, attr)
    ]


def _web_providers_with_keys(settings: Settings) -> list[str]:
    return [
        provider
        for provider, (_, attr) in WEB_PROVIDER_ENV.items()
        if _settings_has_attr(settings, attr)
    ]


def any_llm_env_key(settings: Settings) -> bool:
    return bool(_llm_providers_with_keys(settings))


def _top_model_names(provider: str, catalog: dict[str, list[str]], count: int = TOP_MODEL_COUNT) -> list[str]:
    names = catalog.get(provider, [])
    return names[: min(count, len(names))]


def _slug(value: str) -> str:
    return value.lower().replace("/", "-").replace(".", "-")


def _build_catalog_models(
    *,
    providers: list[str],
    catalog: dict[str, list[str]],
    id_prefix: str,
    api_key: str,
    activate_all: bool = False,
) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for provider in providers:
        for index, model_name in enumerate(_top_model_names(provider, catalog)):
            is_first = index == 0
            models.append(
                {
                    "id": f"{id_prefix}-{_slug(provider)}-{_slug(model_name)}",
                    "provider": provider,
                    "model": model_name,
                    "apiKey": api_key,
                    "active": True if activate_all else is_first,
                    "includeInMulti": is_first,
                }
            )
    return models


def build_demo_llm_models(settings: Settings, stub_llm_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """demo-full: env refs for providers with keys; fixture stubs when none configured."""
    providers = _llm_providers_with_keys(settings)
    if not providers:
        return deepcopy(stub_llm_models)

    built: list[dict[str, Any]] = []
    for provider in providers:
        env_name, _ = LLM_PROVIDER_ENV[provider]
        built.extend(
            _build_catalog_models(
                providers=[provider],
                catalog=LLM_PROVIDER_MODELS,
                id_prefix="llm",
                api_key=f"{ENV_REF_PREFIX}{env_name}",
                activate_all=True,
            )
        )
    return built


def build_demo_web_models(settings: Settings) -> list[dict[str, Any]]:
    """demo-full: web models only for web env keys (with LLM env present); else empty."""
    if not any_llm_env_key(settings):
        return []
    providers = _web_providers_with_keys(settings)
    if not providers:
        return []

    built: list[dict[str, Any]] = []
    for provider in providers:
        env_name, _ = WEB_PROVIDER_ENV[provider]
        built.extend(
            _build_catalog_models(
                providers=[provider],
                catalog=WEB_SEARCH_PROVIDER_MODELS,
                id_prefix="web",
                api_key=f"{ENV_REF_PREFIX}{env_name}",
                activate_all=True,
            )
        )
    return built


def build_demo_ai_profile(settings: Settings, stub_ai: dict[str, Any]) -> dict[str, Any]:
    ai = deepcopy(stub_ai)
    ai["llmModels"] = build_demo_llm_models(settings, stub_ai.get("llmModels", []))
    ai["webSearchModels"] = build_demo_web_models(settings)
    return ai


def build_presentation_ai_profile(settings: Settings, stub_ai: dict[str, Any]) -> dict[str, Any]:
    """Presentation: stub JSON without LLM env keys; dynamic catalog when keys exist."""
    if not any_llm_env_key(settings):
        return deepcopy(stub_ai)

    llm_models = _build_catalog_models(
        providers=_llm_providers_with_keys(settings),
        catalog=LLM_PROVIDER_MODELS,
        id_prefix="llm-presentation",
        api_key="",
        activate_all=True,
    )

    web_models: list[dict[str, Any]] = []
    if any_llm_env_key(settings):
        web_models = _build_catalog_models(
            providers=_web_providers_with_keys(settings),
            catalog=WEB_SEARCH_PROVIDER_MODELS,
            id_prefix="web-presentation",
            api_key="",
            activate_all=True,
        )

    return {
        "llmModels": llm_models,
        "webSearchModels": web_models,
        "visionModels": [],
        "imageGenerationModels": [],
        "orchestratorModels": [],
        "webReasonerModels": [],
        "ragReasonerModels": [],
        "multiResponseEnabled": stub_ai.get("multiResponseEnabled", False),
        "systemPrompt": stub_ai.get("systemPrompt", ""),
    }


def build_seed_ai_profile(
    fixture_name: str,
    stub_ai: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    if fixture_name == "presentation":
        return build_presentation_ai_profile(settings, stub_ai)
    if fixture_name == "demo-full":
        return build_demo_ai_profile(settings, stub_ai)
    return deepcopy(stub_ai)
