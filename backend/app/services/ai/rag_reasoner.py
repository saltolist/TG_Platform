"""Resolve RAG reasoner model for auxiliary RAG query rewrite."""

from __future__ import annotations

from typing import Any, Mapping

from app.core.config import Settings, get_settings
from app.db.models import User
from app.services.ai.keys import resolve_model_api_key
from app.services.ai.providers import ProviderSpec, get_provider_spec


def pick_active_rag_reasoner_model(ai_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    models = ai_profile.get("ragReasonerModels") or []
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


def resolve_rag_reasoner_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> tuple[ProviderSpec, str, str] | None:
    """Active RAG reasoner with a resolvable API key, or orchestrator fallback."""
    from app.services.ai.orchestrator import resolve_orchestrator_llm

    model = pick_active_rag_reasoner_model(ai_profile)
    if model is not None:
        resolution = resolve_model_api_key(model, user, settings or get_settings())
        if resolution.has_key and resolution.api_key:
            provider_name = str(model.get("provider") or "").strip()
            model_id = str(model.get("model") or "").strip()
            spec = get_provider_spec(provider_name)
            if spec is not None and model_id:
                return spec, model_id, resolution.api_key

    return resolve_orchestrator_llm(user, ai_profile, settings)
