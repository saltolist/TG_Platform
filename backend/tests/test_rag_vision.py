"""Tests for vision model resolution."""

from __future__ import annotations

from unittest.mock import patch

from app.services.ai.rag_vision import (
    pick_active_vision_model,
    pick_fallback_vision_model,
    resolve_vision_llm,
)


def test_pick_active_vision_model_skips_unknown_provider() -> None:
    profile = {
        "visionModels": [
            {
                "id": "v1",
                "provider": "Anthropic",
                "model": "claude-3-5-sonnet",
                "active": True,
                "apiKey": "key",
            },
            {
                "id": "v2",
                "provider": "OpenAI",
                "model": "gpt-4o",
                "active": True,
                "apiKey": "sk-test",
            },
        ]
    }
    model = pick_active_vision_model(profile)
    assert model is not None
    assert model["provider"] == "OpenAI"


def test_pick_active_vision_model_none_when_inactive() -> None:
    profile = {
        "visionModels": [
            {"id": "v1", "provider": "OpenAI", "model": "gpt-4o", "active": False, "apiKey": "sk"},
        ]
    }
    assert pick_active_vision_model(profile) is None


def test_resolve_vision_llm_happy_path() -> None:
    user = object()
    profile = {
        "visionModels": [
            {"id": "v1", "provider": "OpenAI", "model": "gpt-4o", "active": True, "apiKey": "sk-test"},
        ]
    }
    with patch("app.services.ai.rag_vision.resolve_model_api_key") as mock_key:
        mock_key.return_value = type("R", (), {"has_key": True, "api_key": "sk-test"})()
        result = resolve_vision_llm(user, profile)  # type: ignore[arg-type]
    assert result is not None
    spec, model, api_key = result
    assert model == "gpt-4o"
    assert api_key == "sk-test"
    assert spec.name == "OpenAI"


def test_resolve_vision_llm_no_key() -> None:
    profile = {
        "visionModels": [
            {"id": "v1", "provider": "OpenAI", "model": "gpt-4o", "active": True, "apiKey": ""},
        ]
    }
    with patch("app.services.ai.rag_vision.resolve_model_api_key") as mock_key:
        mock_key.return_value = type("R", (), {"has_key": False, "api_key": None})()
        assert resolve_vision_llm(object(), profile) is None  # type: ignore[arg-type]


def test_pick_fallback_vision_model_prefers_active_llm_model() -> None:
    profile = {
        "llmModels": [
            {"id": "m1", "provider": "Perplexity", "model": "sonar-pro", "active": True, "apiKey": "pk"},
        ],
        "orchestratorModels": [
            {"id": "o1", "provider": "OpenAI", "model": "gpt-4o", "active": True, "apiKey": "sk"},
        ],
    }
    model = pick_fallback_vision_model(profile)
    assert model is not None
    assert model["provider"] == "Perplexity"
    assert model["model"] == "sonar-pro"


def test_resolve_vision_llm_falls_back_to_perplexity_llm() -> None:
    user = object()
    profile = {
        "llmModels": [
            {"id": "m1", "provider": "Perplexity", "model": "sonar-pro", "active": True, "apiKey": "pk-test"},
        ]
    }
    with patch("app.services.ai.rag_vision.resolve_model_api_key") as mock_key:
        mock_key.return_value = type("R", (), {"has_key": True, "api_key": "pk-test"})()
        result = resolve_vision_llm(user, profile)  # type: ignore[arg-type]
    assert result is not None
    spec, model, api_key = result
    assert spec.name == "Perplexity"
    assert model == "sonar-pro"
    assert api_key == "pk-test"


def test_resolve_vision_llm_skips_unsupported_llm_fallback_provider() -> None:
    profile = {
        "llmModels": [
            {"id": "m1", "provider": "DeepSeek", "model": "deepseek-chat", "active": True, "apiKey": "sk"},
        ]
    }
    assert pick_fallback_vision_model(profile) is None
