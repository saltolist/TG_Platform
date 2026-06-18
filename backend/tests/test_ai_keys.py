"""Tests for AI API key resolution (Phase 2, step 1)."""

import uuid

import pytest

from app.core.config import Settings
from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.db.models import User
from app.services.ai.keys import (
    AccountMode,
    KeySource,
    LlmModelKey,
    get_account_mode,
    resolve_api_key,
    resolve_model_api_key,
)


def _user(*, email: str, is_seed: bool) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="hash",
        is_seed=is_seed,
    )


@pytest.fixture
def presentation_user() -> User:
    return _user(email=PRESENTATION_EMAIL, is_seed=True)


@pytest.fixture
def demo_user() -> User:
    return _user(email=DEMO_EMAIL, is_seed=True)


@pytest.fixture
def real_user() -> User:
    return _user(email="author@example.com", is_seed=False)


@pytest.fixture
def empty_settings() -> Settings:
    return Settings(openai_api_key="", deepseek_api_key="")


@pytest.fixture
def openai_settings() -> Settings:
    return Settings(openai_api_key="sk-openai-env", deepseek_api_key="")


@pytest.fixture
def deepseek_settings() -> Settings:
    return Settings(openai_api_key="", deepseek_api_key="sk-deepseek-env")


@pytest.mark.parametrize(
    ("user", "expected_mode"),
    [
        ("presentation", AccountMode.PRESENTATION),
        ("demo", AccountMode.DEMO),
        ("real", AccountMode.REAL),
    ],
)
def test_get_account_mode(
    user: str,
    expected_mode: AccountMode,
    presentation_user: User,
    demo_user: User,
    real_user: User,
) -> None:
    users = {
        "presentation": presentation_user,
        "demo": demo_user,
        "real": real_user,
    }
    assert get_account_mode(users[user]) == expected_mode


# --- BYOK (branch 1) ---


@pytest.mark.parametrize("account", ["presentation", "demo", "real"])
def test_byok_resolves_real_profile_key(
    account: str,
    presentation_user: User,
    demo_user: User,
    real_user: User,
    empty_settings: Settings,
) -> None:
    users = {
        "presentation": presentation_user,
        "demo": demo_user,
        "real": real_user,
    }
    model = LlmModelKey(provider="OpenAI", api_key="sk-user-byok")
    result = resolve_api_key(model, users[account], empty_settings)

    assert result.source == KeySource.BYOK
    assert result.api_key == "sk-user-byok"
    assert result.has_key
    assert not result.use_stub
    assert not result.unavailable


# --- env:<NAME> (branch 2) ---


@pytest.mark.parametrize("account", ["presentation", "demo", "real"])
def test_env_ref_resolves_from_settings(
    account: str,
    presentation_user: User,
    demo_user: User,
    real_user: User,
    openai_settings: Settings,
) -> None:
    users = {
        "presentation": presentation_user,
        "demo": demo_user,
        "real": real_user,
    }
    model = LlmModelKey(provider="OpenAI", api_key="env:OPENAI_API_KEY")
    result = resolve_api_key(model, users[account], openai_settings)

    assert result.source == KeySource.ENV_REF
    assert result.api_key == "sk-openai-env"
    assert result.has_key


@pytest.mark.parametrize("account", ["presentation", "demo", "real"])
def test_env_ref_deepseek(
    account: str,
    presentation_user: User,
    demo_user: User,
    real_user: User,
    deepseek_settings: Settings,
) -> None:
    users = {
        "presentation": presentation_user,
        "demo": demo_user,
        "real": real_user,
    }
    model = LlmModelKey(provider="DeepSeek", api_key="env:DEEPSEEK_API_KEY")
    result = resolve_api_key(model, users[account], deepseek_settings)

    assert result.source == KeySource.ENV_REF
    assert result.api_key == "sk-deepseek-env"


@pytest.mark.parametrize("account", ["presentation", "demo", "real"])
def test_env_ref_unknown_name_falls_through(
    account: str,
    presentation_user: User,
    demo_user: User,
    real_user: User,
    openai_settings: Settings,
) -> None:
    users = {
        "presentation": presentation_user,
        "demo": demo_user,
        "real": real_user,
    }
    model = LlmModelKey(provider="OpenAI", api_key="env:UNKNOWN_KEY")
    result = resolve_api_key(model, users[account], openai_settings)

    if account == "real":
        assert result.source == KeySource.NONE
        assert result.unavailable
    else:
        assert result.source == KeySource.ENV_FALLBACK
        assert result.api_key == "sk-openai-env"


# --- env fallback (branch 3) — seed accounts only ---


@pytest.mark.parametrize("account", ["presentation", "demo"])
def test_env_fallback_openai_for_seed_accounts(
    account: str,
    presentation_user: User,
    demo_user: User,
    openai_settings: Settings,
) -> None:
    users = {"presentation": presentation_user, "demo": demo_user}
    model = LlmModelKey(provider="OpenAI", api_key="")
    result = resolve_api_key(model, users[account], openai_settings)

    assert result.source == KeySource.ENV_FALLBACK
    assert result.api_key == "sk-openai-env"
    assert result.has_key
    assert not result.use_stub


def test_env_fallback_not_used_for_real_account(
    real_user: User,
    openai_settings: Settings,
) -> None:
    model = LlmModelKey(provider="OpenAI", api_key="")
    result = resolve_api_key(model, real_user, openai_settings)

    assert result.source == KeySource.NONE
    assert result.api_key is None
    assert result.unavailable
    assert not result.use_stub


# --- none (branch 4) ---


@pytest.mark.parametrize("account", ["presentation", "demo"])
def test_no_key_seed_accounts_use_stub(
    account: str,
    presentation_user: User,
    demo_user: User,
    empty_settings: Settings,
) -> None:
    users = {"presentation": presentation_user, "demo": demo_user}
    model = LlmModelKey(provider="OpenAI", api_key="")
    result = resolve_api_key(model, users[account], empty_settings)

    assert result.source == KeySource.NONE
    assert result.api_key is None
    assert result.use_stub
    assert not result.unavailable


def test_no_key_real_account_unavailable(
    real_user: User,
    empty_settings: Settings,
) -> None:
    model = LlmModelKey(provider="OpenAI", api_key="")
    result = resolve_api_key(model, real_user, empty_settings)

    assert result.source == KeySource.NONE
    assert result.unavailable
    assert not result.use_stub


def test_unsupported_provider_no_fallback(
    presentation_user: User,
    openai_settings: Settings,
) -> None:
    model = LlmModelKey(provider="Anthropic", api_key="")
    result = resolve_api_key(model, presentation_user, openai_settings)

    assert result.source == KeySource.NONE
    assert result.use_stub


def test_resolve_model_api_key_from_profile_dict(real_user: User) -> None:
    settings = Settings(openai_api_key="", deepseek_api_key="")
    model = {
        "id": "llm-1",
        "provider": "OpenAI",
        "model": "gpt-4o",
        "apiKey": "sk-from-profile",
        "active": True,
    }
    result = resolve_model_api_key(model, real_user, settings)

    assert result.source == KeySource.BYOK
    assert result.api_key == "sk-from-profile"


def test_demo_fixture_api_key_uses_stub(demo_user: User, empty_settings: Settings) -> None:
    model = LlmModelKey(provider="OpenAI", api_key="sk-openai-demo")
    result = resolve_api_key(model, demo_user, empty_settings)

    assert result.source == KeySource.NONE
    assert result.api_key is None
    assert result.use_stub


def test_demo_fixture_api_key_still_byok_for_real_account(
    real_user: User,
    empty_settings: Settings,
) -> None:
    model = LlmModelKey(provider="OpenAI", api_key="sk-openai-demo")
    result = resolve_api_key(model, real_user, empty_settings)

    assert result.source == KeySource.BYOK
    assert result.api_key == "sk-openai-demo"


def test_demo_fixture_api_key_still_byok_for_presentation(
    presentation_user: User,
    empty_settings: Settings,
) -> None:
    model = LlmModelKey(provider="OpenAI", api_key="sk-openai-demo")
    result = resolve_api_key(model, presentation_user, empty_settings)

    assert result.source == KeySource.BYOK
    assert result.api_key == "sk-openai-demo"
