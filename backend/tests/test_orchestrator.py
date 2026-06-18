"""Tests for orchestrator model resolution."""

from __future__ import annotations

from app.core.config import Settings
from app.db.models import User
from app.services.ai.orchestrator import pick_active_orchestrator_model, resolve_orchestrator_llm


def _user(*, seed: bool = True, email: str = "demo@mail.ru") -> User:
    return User(email=email, password_hash="x", is_seed=seed)


def test_pick_active_orchestrator_model_returns_active_entry() -> None:
    profile = {
        "orchestratorModels": [
            {
                "id": "orchestrator-1",
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "apiKey": "",
                "active": False,
            },
            {
                "id": "orchestrator-2",
                "provider": "DeepSeek",
                "model": "deepseek-chat",
                "apiKey": "sk-real",
                "active": True,
            },
        ]
    }
    picked = pick_active_orchestrator_model(profile)
    assert picked is not None
    assert picked["id"] == "orchestrator-2"


def test_resolve_orchestrator_llm_uses_env_fallback_for_demo() -> None:
    profile = {
        "orchestratorModels": [
            {
                "id": "orchestrator-1",
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "apiKey": "",
                "active": True,
            }
        ]
    }
    settings = Settings(openai_api_key="sk-openai-test", deepseek_api_key="")
    resolved = resolve_orchestrator_llm(_user(), profile, settings=settings)
    assert resolved is not None
    _spec, model, api_key = resolved
    assert model == "gpt-4.1-mini"
    assert api_key == "sk-openai-test"


def test_resolve_orchestrator_llm_returns_none_without_active_model() -> None:
    profile = {"orchestratorModels": []}
    assert resolve_orchestrator_llm(_user(), profile, settings=Settings()) is None
