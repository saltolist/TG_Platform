"""Utilities for encrypting/masking BYOK keys in an AI profile dict.

The AI profile is stored as JSON in ``profiles.ai``.  Models live under:
  - ``llmModels``
  - ``webSearchModels``
  - ``orchestratorModels``
  - ``embeddingsModel``  (single object, not a list)

Each model object may have an ``apiKey`` field.

Rules:
- ``env:<NAME>`` references are NOT secrets — do not encrypt.
- Demo-fixture keys (e.g. ``sk-openai-demo``) are NOT real secrets — do not encrypt.
- Already-encrypted values (prefix ``enc:v1:``) are kept as-is.
- When returning the profile to the client, real keys are replaced with a preview
  (first 3 chars + 10 asterisks + last 3 chars) so they never leave the backend.
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.config import Settings, get_settings
from app.core.crypto import ENC_PREFIX, decrypt_byok, encrypt_byok, is_encrypted
from app.services.ai.keys import DEMO_FIXTURE_API_KEYS, ENV_REF_PREFIX

_LIST_FIELDS = (
    "llmModels",
    "webSearchModels",
    "orchestratorModels",
    "webReasonerModels",
    "ragReasonerModels",
    "visionModels",
    "imageGenerationModels",
)
_SINGLE_FIELDS = ("embeddingsModel",)

MASKED_VALUE = "__masked__"
API_KEY_PREVIEW_STAR_COUNT = 10


def mask_api_key_preview(plaintext: str) -> str:
    """Build a client-safe preview: first 3 + 10 stars + last 3."""
    if not plaintext:
        return ""
    stars = "*" * API_KEY_PREVIEW_STAR_COUNT
    if len(plaintext) >= 6:
        return plaintext[:3] + stars + plaintext[-3:]
    if len(plaintext) <= 3:
        return plaintext[:3].ljust(3, "*") + stars + plaintext[-3:].rjust(3, "*")
    return plaintext[:3] + stars + plaintext[-3:]


def is_api_key_preview(value: str) -> bool:
    """True for legacy ``__masked__`` or a preview token sent back by the client."""
    if not value:
        return False
    if value == MASKED_VALUE:
        return True
    marker = "*" * API_KEY_PREVIEW_STAR_COUNT
    pos = value.find(marker)
    return 0 < pos <= 3


def _is_real_byok(api_key: str) -> bool:
    """Return True if the key is a real secret that should be encrypted."""
    if not api_key:
        return False
    if api_key.startswith(ENV_REF_PREFIX):
        return False
    if api_key in DEMO_FIXTURE_API_KEYS:
        return False
    if is_api_key_preview(api_key):
        return False
    return True


def _encrypt_key(api_key: str, settings: Settings | None) -> str:
    if not _is_real_byok(api_key):
        return api_key
    if is_encrypted(api_key):
        return api_key
    return encrypt_byok(api_key, settings)


def _mask_key_for_response(api_key: str, settings: Settings | None) -> str:
    """Replace real keys with a preview for client responses."""
    if not api_key:
        return api_key
    if api_key.startswith(ENV_REF_PREFIX):
        return api_key
    if api_key in DEMO_FIXTURE_API_KEYS:
        return api_key
    if is_api_key_preview(api_key):
        return api_key
    if is_encrypted(api_key):
        plaintext = decrypt_byok(api_key, settings)
        if not plaintext:
            return MASKED_VALUE
        return mask_api_key_preview(plaintext)
    return mask_api_key_preview(api_key)


def encrypt_profile_keys(
    profile: dict[str, Any],
    settings: Settings | None = None,
    *,
    previous_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of *profile* with BYOK keys encrypted.

    When *previous_profile* is provided and a client sends a preview / legacy mask
    as the key (meaning "don't change"), the original encrypted value is restored
    from *previous_profile* instead of overwriting with the preview.
    """
    result = copy.deepcopy(profile)

    for field in _LIST_FIELDS:
        models: list[dict[str, Any]] = result.get(field) or []
        prev_models: list[dict[str, Any]] = (previous_profile or {}).get(field) or []
        for i, model in enumerate(models):
            raw = str(model.get("apiKey") or "")
            if is_api_key_preview(raw):
                if i < len(prev_models):
                    model["apiKey"] = prev_models[i].get("apiKey", "")
                else:
                    model["apiKey"] = ""
            else:
                model["apiKey"] = _encrypt_key(raw, settings)

    for field in _SINGLE_FIELDS:
        model = result.get(field)
        if not isinstance(model, dict):
            continue
        prev_model = (previous_profile or {}).get(field) or {}
        raw = str(model.get("apiKey") or "")
        if is_api_key_preview(raw):
            model["apiKey"] = prev_model.get("apiKey", "")
        else:
            model["apiKey"] = _encrypt_key(raw, settings)

    return result


def reveal_profile_keys_for_owner(
    profile: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return a copy of *profile* with encrypted BYOK keys decrypted for the account owner."""
    settings = settings or get_settings()
    result = copy.deepcopy(profile)

    for field in _LIST_FIELDS:
        for model in result.get(field) or []:
            raw = str(model.get("apiKey") or "")
            model["apiKey"] = _reveal_key_for_owner(raw, settings)

    for field in _SINGLE_FIELDS:
        model = result.get(field)
        if isinstance(model, dict):
            raw = str(model.get("apiKey") or "")
            model["apiKey"] = _reveal_key_for_owner(raw, settings)

    return result


def reveal_model_api_key_from_profile(
    profile: dict[str, Any],
    *,
    model_id: str,
    field: str,
    settings: Settings | None = None,
) -> str | None:
    """Return the decrypted API key for a single model entry, or None if not found."""
    settings = settings or get_settings()
    if field not in _LIST_FIELDS:
        return None
    for model in profile.get(field) or []:
        if str(model.get("id", "")) != model_id:
            continue
        raw = str(model.get("apiKey") or "")
        if not raw:
            return None
        return _reveal_key_for_owner(raw, settings)
    return None


def _reveal_key_for_owner(api_key: str, settings: Settings | None) -> str:
    if not api_key:
        return api_key
    if api_key.startswith(ENV_REF_PREFIX):
        return api_key
    if api_key in DEMO_FIXTURE_API_KEYS:
        return api_key
    if is_encrypted(api_key):
        return decrypt_byok(api_key, settings)
    return api_key


def mask_profile_keys(
    profile: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return a copy of *profile* with real API keys replaced by preview tokens."""
    settings = settings or get_settings()
    result = copy.deepcopy(profile)

    for field in _LIST_FIELDS:
        for model in result.get(field) or []:
            raw = str(model.get("apiKey") or "")
            model["apiKey"] = _mask_key_for_response(raw, settings)

    for field in _SINGLE_FIELDS:
        model = result.get(field)
        if isinstance(model, dict):
            raw = str(model.get("apiKey") or "")
            model["apiKey"] = _mask_key_for_response(raw, settings)

    return result


def decrypt_model_api_key(api_key: str, settings: Settings | None = None) -> str:
    """Decrypt a single model's apiKey at resolution time."""
    if not api_key or api_key.startswith(ENV_REF_PREFIX):
        return api_key
    if is_api_key_preview(api_key):
        return ""
    if api_key.startswith(ENC_PREFIX):
        return decrypt_byok(api_key, settings)
    return api_key
