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

VISION_PROVIDER_MODELS: dict[str, list[str]] = {
    "OpenAI": ["gpt-4o", "gpt-4.1"],
    "Anthropic": ["claude-3-7-sonnet", "claude-3-5-sonnet"],
    "Google": ["gemini-1.5-pro", "gemini-1.5-flash"],
}

IMAGE_GENERATION_PROVIDER_MODELS: dict[str, list[str]] = {
    "OpenAI": ["dall-e-3", "gpt-image-1"],
    "Stability": ["stable-image-ultra", "stable-image-core"],
    "Google": ["imagen-3"],
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


def _slug(value: str) -> str:
    return value.lower().replace("/", "-").replace(".", "-")


def youngest_model_name(provider: str, catalog: dict[str, list[str]]) -> str | None:
    """Youngest (smallest) model = last entry in the provider catalog."""
    names = catalog.get(provider, [])
    return names[-1] if names else None


def _api_key_for_provider(
    provider: str,
    *,
    env_map: dict[str, tuple[str, str]],
    use_env_ref: bool,
) -> str:
    if not use_env_ref:
        return ""
    env_name, _ = env_map[provider]
    return f"{ENV_REF_PREFIX}{env_name}"


def _make_model_entry(
    *,
    id_prefix: str,
    provider: str,
    model_name: str,
    api_key: str,
    active: bool,
    include_in_multi: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"{id_prefix}-{_slug(provider)}-{_slug(model_name)}",
        "provider": provider,
        "model": model_name,
        "apiKey": api_key,
        "active": active,
        "includeInMulti": include_in_multi,
    }


def _build_llm_models(
    settings: Settings,
    *,
    id_prefix: str,
    use_env_ref: bool,
) -> list[dict[str, Any]]:
    providers = _llm_providers_with_keys(settings)
    models: list[dict[str, Any]] = []
    for index, provider in enumerate(providers):
        model_name = youngest_model_name(provider, LLM_PROVIDER_MODELS)
        if not model_name:
            continue
        models.append(
            _make_model_entry(
                id_prefix=id_prefix,
                provider=provider,
                model_name=model_name,
                api_key=_api_key_for_provider(
                    provider,
                    env_map=LLM_PROVIDER_ENV,
                    use_env_ref=use_env_ref,
                ),
                active=index == 0,
                include_in_multi=index == 0,
            )
        )
    return models


def _build_web_models(settings: Settings, *, id_prefix: str, use_env_ref: bool) -> list[dict[str, Any]]:
    if not any_llm_env_key(settings):
        return []
    providers = _web_providers_with_keys(settings)
    models: list[dict[str, Any]] = []
    for index, provider in enumerate(providers):
        model_name = youngest_model_name(provider, WEB_SEARCH_PROVIDER_MODELS)
        if not model_name:
            continue
        models.append(
            _make_model_entry(
                id_prefix=id_prefix,
                provider=provider,
                model_name=model_name,
                api_key=_api_key_for_provider(
                    provider,
                    env_map=WEB_PROVIDER_ENV,
                    use_env_ref=use_env_ref,
                ),
                active=index == 0,
            )
        )
    return models


def _build_provider_catalog_models(
    llm_providers: list[str],
    catalog: dict[str, list[str]],
    *,
    id_prefix: str,
    env_map: dict[str, tuple[str, str]],
    use_env_ref: bool,
) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    eligible = [provider for provider in llm_providers if provider in catalog]
    for index, provider in enumerate(eligible):
        model_name = youngest_model_name(provider, catalog)
        if not model_name:
            continue
        models.append(
            _make_model_entry(
                id_prefix=id_prefix,
                provider=provider,
                model_name=model_name,
                api_key=_api_key_for_provider(provider, env_map=env_map, use_env_ref=use_env_ref),
                active=index == 0,
            )
        )
    return models


def _build_single_llm_derived_model(
    settings: Settings,
    *,
    id_prefix: str,
    use_env_ref: bool,
) -> list[dict[str, Any]]:
    """One youngest LLM model for exclusive categories (orchestrator, reasoners)."""
    providers = _llm_providers_with_keys(settings)
    if not providers:
        return []
    provider = providers[0]
    model_name = youngest_model_name(provider, LLM_PROVIDER_MODELS)
    if not model_name:
        return []
    return [
        _make_model_entry(
            id_prefix=id_prefix,
            provider=provider,
            model_name=model_name,
            api_key=_api_key_for_provider(provider, env_map=LLM_PROVIDER_ENV, use_env_ref=use_env_ref),
            active=True,
        )
    ]


def build_env_backed_ai_profile(
    settings: Settings,
    stub_ai: dict[str, Any],
    *,
    id_prefix: str,
    use_env_ref: bool,
) -> dict[str, Any]:
    """Demo / presentation / guest: youngest model per provider when LLM env keys exist."""
    if not any_llm_env_key(settings):
        return deepcopy(stub_ai)

    llm_providers = _llm_providers_with_keys(settings)
    return {
        "llmModels": _build_llm_models(settings, id_prefix=f"{id_prefix}-llm", use_env_ref=use_env_ref),
        "webSearchModels": _build_web_models(settings, id_prefix=f"{id_prefix}-web", use_env_ref=use_env_ref),
        "visionModels": _build_provider_catalog_models(
            llm_providers,
            VISION_PROVIDER_MODELS,
            id_prefix=f"{id_prefix}-vision",
            env_map=LLM_PROVIDER_ENV,
            use_env_ref=use_env_ref,
        ),
        "imageGenerationModels": _build_provider_catalog_models(
            llm_providers,
            IMAGE_GENERATION_PROVIDER_MODELS,
            id_prefix=f"{id_prefix}-image",
            env_map=LLM_PROVIDER_ENV,
            use_env_ref=use_env_ref,
        ),
        "orchestratorModels": _build_single_llm_derived_model(
            settings,
            id_prefix=f"{id_prefix}-orchestrator",
            use_env_ref=use_env_ref,
        ),
        "webReasonerModels": _build_single_llm_derived_model(
            settings,
            id_prefix=f"{id_prefix}-web-reasoner",
            use_env_ref=use_env_ref,
        ),
        "ragReasonerModels": _build_single_llm_derived_model(
            settings,
            id_prefix=f"{id_prefix}-rag-reasoner",
            use_env_ref=use_env_ref,
        ),
        "multiResponseEnabled": stub_ai.get("multiResponseEnabled", False),
        "systemPrompt": stub_ai.get("systemPrompt", ""),
    }


def build_demo_ai_profile(settings: Settings, stub_ai: dict[str, Any]) -> dict[str, Any]:
    if not any_llm_env_key(settings):
        ai = deepcopy(stub_ai)
        ai["webSearchModels"] = []
        return ai
    return build_env_backed_ai_profile(settings, stub_ai, id_prefix="demo", use_env_ref=True)


def build_presentation_ai_profile(settings: Settings, stub_ai: dict[str, Any]) -> dict[str, Any]:
    return build_env_backed_ai_profile(settings, stub_ai, id_prefix="presentation", use_env_ref=False)


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
