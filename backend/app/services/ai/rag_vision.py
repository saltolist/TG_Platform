"""Resolve vision model for attachment image captioning."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.core.config import Settings, get_settings
from app.db.models import User
from app.services.ai.keys import resolve_model_api_key
from app.services.ai.providers import PROVIDER_SPECS, ProviderSpec, get_provider_spec

logger = logging.getLogger(__name__)


def pick_active_vision_model(ai_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    models = ai_profile.get("visionModels") or []
    if not isinstance(models, list):
        return None
    for model in models:
        if not isinstance(model, Mapping):
            continue
        provider = str(model.get("provider") or "").strip()
        model_name = str(model.get("model") or "").strip()
        if not (model.get("active") and provider and model_name):
            continue
        if provider not in PROVIDER_SPECS:
            logger.debug("Skipping vision model %s/%s — provider not in PROVIDER_SPECS", provider, model_name)
            continue
        return dict(model)
    return None


def resolve_vision_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> tuple[ProviderSpec, str, str] | None:
    """Active OpenAI-compatible vision model with a resolvable API key."""
    model = pick_active_vision_model(ai_profile)
    if model is None:
        return None
    resolution = resolve_model_api_key(model, user, settings or get_settings())
    if not (resolution.has_key and resolution.api_key):
        return None
    provider_name = str(model.get("provider") or "").strip()
    model_id = str(model.get("model") or "").strip()
    spec = get_provider_spec(provider_name)
    if spec is None or not model_id:
        return None
    return spec, model_id, resolution.api_key
