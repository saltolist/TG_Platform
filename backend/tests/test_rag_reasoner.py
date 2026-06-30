"""Tests for RAG reasoner model resolution."""

from __future__ import annotations

from app.core.config import Settings
from app.db.models import User
from app.services.ai.rag_reasoner import pick_active_rag_reasoner_model, resolve_rag_reasoner_llm


def _user(*, seed: bool = True, email: str = "demo@mail.ru") -> User:
    return User(email=email, password_hash="x", is_seed=seed)


def test_pick_active_rag_reasoner_model_returns_active_entry() -> None:
    profile = {
        "ragReasonerModels": [
            {
                "id": "rag-reasoner-1",
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "apiKey": "",
                "active": False,
            },
            {
                "id": "rag-reasoner-2",
                "provider": "DeepSeek",
                "model": "deepseek-chat",
                "apiKey": "sk-real",
                "active": True,
            },
        ]
    }
    picked = pick_active_rag_reasoner_model(profile)
    assert picked is not None
    assert picked["id"] == "rag-reasoner-2"


def test_resolve_rag_reasoner_llm_uses_env_fallback_for_demo() -> None:
    profile = {
        "ragReasonerModels": [
            {
                "id": "rag-reasoner-1",
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "apiKey": "",
                "active": True,
            }
        ]
    }
    settings = Settings(openai_api_key="sk-openai-test", deepseek_api_key="")
    resolved = resolve_rag_reasoner_llm(_user(), profile, settings=settings)
    assert resolved is not None
    _spec, model, api_key = resolved
    assert model == "gpt-4.1-mini"
    assert api_key == "sk-openai-test"


def test_resolve_rag_reasoner_llm_returns_none_without_active_model() -> None:
    profile = {"ragReasonerModels": [], "orchestratorModels": []}
    assert resolve_rag_reasoner_llm(_user(), profile, settings=Settings()) is None


def test_resolve_rag_reasoner_llm_falls_back_to_orchestrator() -> None:
    profile = {
        "ragReasonerModels": [],
        "orchestratorModels": [
            {
                "id": "orchestrator-1",
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "apiKey": "",
                "active": True,
            }
        ],
    }
    settings = Settings(openai_api_key="sk-openai-test", deepseek_api_key="")
    resolved = resolve_rag_reasoner_llm(_user(), profile, settings=settings)
    assert resolved is not None
    _spec, model, api_key = resolved
    assert model == "gpt-4.1-mini"
    assert api_key == "sk-openai-test"
