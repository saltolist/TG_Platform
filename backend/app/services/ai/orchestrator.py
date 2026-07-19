"""Resolve orchestrator model for auxiliary AI tasks (rolling summary, etc.)."""

from __future__ import annotations

from typing import Any, Mapping

from app.core.config import Settings, get_settings
from app.db.models import User
from app.services.ai.keys import resolve_model_api_key
from app.services.ai.providers import ProviderSpec, get_provider_spec


def pick_active_orchestrator_model(ai_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    models = ai_profile.get("orchestratorModels") or []
    if not isinstance(models, list):
        return None
    for model in models:
        if not isinstance(model, Mapping):
            continue
        provider = str(model.get("provider") or "").strip()
        model_name = str(model.get("model") or "").strip()
        if model.get("active") and provider and model_name:
            return dict(model)
    return None


def pick_active_answer_model(ai_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the user-selected answer/chat model, if configured."""
    models = ai_profile.get("llmModels") or []
    if not isinstance(models, list):
        return None
    for model in models:
        if not isinstance(model, Mapping):
            continue
        if (
            model.get("active")
            and str(model.get("provider") or "").strip()
            and str(model.get("model") or "").strip()
        ):
            return dict(model)
    return None


def resolve_answer_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> tuple[ProviderSpec, str, str] | None:
    """Resolve the model selected for user-facing answers.

    Orchestrator remains a compatibility fallback for profiles created before
    the answer model was separated from planner/reasoner configuration.
    """
    model = pick_active_answer_model(ai_profile)
    if model is not None:
        resolution = resolve_model_api_key(model, user, settings or get_settings())
        provider_name = str(model.get("provider") or "").strip()
        model_id = str(model.get("model") or "").strip()
        spec = get_provider_spec(provider_name)
        if resolution.has_key and resolution.api_key and spec is not None and model_id:
            return spec, model_id, resolution.api_key
    return resolve_orchestrator_llm(user, ai_profile, settings)


def resolve_orchestrator_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> tuple[ProviderSpec, str, str] | None:
    """Active orchestrator with a resolvable API key, or None."""
    model = pick_active_orchestrator_model(ai_profile)
    if model is None:
        return None

    resolution = resolve_model_api_key(model, user, settings or get_settings())
    if not resolution.has_key or not resolution.api_key:
        return None

    provider_name = str(model.get("provider") or "").strip()
    model_id = str(model.get("model") or "").strip()
    spec = get_provider_spec(provider_name)
    if spec is None or not model_id:
        return None

    return spec, model_id, resolution.api_key
