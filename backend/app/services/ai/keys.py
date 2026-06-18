"""Resolve API keys for AI models by account mode (BYOK / env ref / env fallback)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.core.config import Settings, get_settings
from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.db.models import User

ENV_REF_PREFIX = "env:"

# Provider display name (profile) → settings attribute for env-fallback.
PROVIDER_ENV_ATTR: dict[str, str] = {
    "OpenAI": "openai_api_key",
    "DeepSeek": "deepseek_api_key",
}

# env:<NAME> reference → settings attribute (NAME is e.g. OPENAI_API_KEY).
ENV_VAR_ATTR: dict[str, str] = {
    "OPENAI_API_KEY": "openai_api_key",
    "DEEPSEEK_API_KEY": "deepseek_api_key",
}


class AccountMode(str, Enum):
    PRESENTATION = "presentation"
    DEMO = "demo"
    REAL = "real"


class KeySource(str, Enum):
    BYOK = "byok"
    ENV_REF = "env_ref"
    ENV_FALLBACK = "env_fallback"
    NONE = "none"


@dataclass(frozen=True)
class LlmModelKey:
    provider: str
    api_key: str = ""


@dataclass(frozen=True)
class KeyResolution:
    api_key: str | None
    source: KeySource
    account_mode: AccountMode

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def use_stub(self) -> bool:
        """Presentation/demo without a key → stub reply (Phase 2 SSE)."""
        return not self.has_key and self.account_mode != AccountMode.REAL

    @property
    def unavailable(self) -> bool:
        """Real account without a key → AI must not run."""
        return not self.has_key and self.account_mode == AccountMode.REAL


def get_account_mode(user: User) -> AccountMode:
    if not user.is_seed:
        return AccountMode.REAL
    if user.email == PRESENTATION_EMAIL:
        return AccountMode.PRESENTATION
    if user.email == DEMO_EMAIL:
        return AccountMode.DEMO
    return AccountMode.DEMO


def is_env_ref(api_key: str) -> bool:
    return api_key.startswith(ENV_REF_PREFIX)


def parse_env_ref(api_key: str) -> str:
    return api_key[len(ENV_REF_PREFIX) :]


def _settings_attr_value(settings: Settings, attr: str) -> str | None:
    value = getattr(settings, attr, "")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_env_var_name(settings: Settings, env_name: str) -> str | None:
    attr = ENV_VAR_ATTR.get(env_name)
    if attr is None:
        return None
    return _settings_attr_value(settings, attr)


def _resolve_provider_fallback(settings: Settings, provider: str) -> str | None:
    attr = PROVIDER_ENV_ATTR.get(provider)
    if attr is None:
        return None
    return _settings_attr_value(settings, attr)


def resolve_api_key(
    model: LlmModelKey,
    user: User,
    settings: Settings | None = None,
) -> KeyResolution:
    """Resolve the API key for an LLM model.

    Order:
    1. Real key in profile (BYOK) — non-empty, not ``env:<NAME>``.
    2. ``env:<NAME>`` reference (demo) — value from env/settings.
    3. Empty key + presentation/demo — env fallback by ``provider``.
    4. Nothing suitable — stub (seed) or unavailable (real).
    """
    settings = settings or get_settings()
    mode = get_account_mode(user)
    raw_key = (model.api_key or "").strip()

    if raw_key and not is_env_ref(raw_key):
        return KeyResolution(api_key=raw_key, source=KeySource.BYOK, account_mode=mode)

    if raw_key and is_env_ref(raw_key):
        env_name = parse_env_ref(raw_key)
        value = _resolve_env_var_name(settings, env_name)
        if value:
            return KeyResolution(api_key=value, source=KeySource.ENV_REF, account_mode=mode)

    if mode != AccountMode.REAL and model.provider:
        value = _resolve_provider_fallback(settings, model.provider)
        if value:
            return KeyResolution(
                api_key=value,
                source=KeySource.ENV_FALLBACK,
                account_mode=mode,
            )

    return KeyResolution(api_key=None, source=KeySource.NONE, account_mode=mode)


def resolve_model_api_key(
    model: Mapping[str, Any],
    user: User,
    settings: Settings | None = None,
) -> KeyResolution:
    """Resolve key from an AI profile model dict (``provider`` / ``apiKey``)."""
    return resolve_api_key(
        LlmModelKey(
            provider=str(model.get("provider", "")),
            api_key=str(model.get("apiKey", model.get("api_key", ""))),
        ),
        user,
        settings,
    )
