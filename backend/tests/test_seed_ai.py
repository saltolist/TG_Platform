"""Tests for AI model catalog and seed AI profile builders (Phase 2, step 2)."""

import json

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.db.seed import FIXTURES_DIR, run_seed
from app.services.ai.model_catalog import (
    build_demo_ai_profile,
    build_presentation_ai_profile,
)
from tests.conftest import TestSessionLocal, guest_auth_headers


def _load_fixture_ai(name: str) -> dict:
    data = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return data["profile"]["ai"]


def test_demo_empty_env_uses_stub_llm_models() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(Settings(), stub)
    assert ai["llmModels"] == stub["llmModels"]
    assert ai["llmModels"][0]["apiKey"] == "sk-openai-demo"
    assert ai["webSearchModels"] == []


def test_demo_openai_env_uses_youngest_model_only() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(Settings(openai_api_key="sk-env"), stub)
    assert len(ai["llmModels"]) == 1
    assert ai["llmModels"][0] == {
        "id": "demo-llm-openai-gpt-4-1-mini",
        "provider": "OpenAI",
        "model": "gpt-4.1-mini",
        "apiKey": "env:OPENAI_API_KEY",
        "active": True,
        "includeInMulti": True,
    }
    assert len(ai["webSearchModels"]) == 1
    assert ai["webSearchModels"][0]["model"] == "responses-api-web-search"
    assert len(ai["orchestratorModels"]) == 1
    assert ai["orchestratorModels"][0]["model"] == "gpt-4.1-mini"
    assert len(ai["visionModels"]) == 1
    assert ai["visionModels"][0]["model"] == "gpt-4.1"
    assert len(ai["imageGenerationModels"]) == 1
    assert ai["imageGenerationModels"][0]["model"] == "gpt-image-1"
    assert len(ai["webReasonerModels"]) == 1
    assert len(ai["ragReasonerModels"]) == 1


def test_demo_openai_and_deepseek_env() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(
        Settings(openai_api_key="sk-o", deepseek_api_key="sk-d"),
        stub,
    )
    assert len(ai["llmModels"]) == 2
    assert ai["llmModels"][0]["provider"] == "OpenAI"
    assert ai["llmModels"][0]["active"] is True
    assert ai["llmModels"][1]["provider"] == "DeepSeek"
    assert ai["llmModels"][1]["model"] == "deepseek-reasoner"
    assert ai["llmModels"][1]["active"] is False
    assert len(ai["webSearchModels"]) == 1
    assert ai["webSearchModels"][0]["provider"] == "OpenAI"


def test_demo_deepseek_only_no_web_models() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(Settings(deepseek_api_key="sk-d"), stub)
    assert len(ai["llmModels"]) == 1
    assert ai["llmModels"][0]["provider"] == "DeepSeek"
    assert ai["llmModels"][0]["model"] == "deepseek-reasoner"
    assert ai["webSearchModels"] == []
    assert ai["visionModels"] == []
    assert ai["imageGenerationModels"] == []


def test_demo_openai_and_tavily_web_models() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(
        Settings(openai_api_key="sk-o", tavily_api_key="tvly-x"),
        stub,
    )
    assert len(ai["webSearchModels"]) == 2
    assert ai["webSearchModels"][0]["provider"] == "Tavily"
    assert ai["webSearchModels"][0]["model"] == "search-v1"
    assert ai["webSearchModels"][0]["active"] is True
    assert ai["webSearchModels"][1]["provider"] == "OpenAI"
    assert ai["webSearchModels"][1]["active"] is False


def test_demo_web_keys_without_llm_env_stay_empty() -> None:
    stub = _load_fixture_ai("demo-full")
    ai = build_demo_ai_profile(Settings(tavily_api_key="tvly-x"), stub)
    assert ai["webSearchModels"] == []


def test_presentation_no_llm_keys_uses_fixture_stub() -> None:
    stub = _load_fixture_ai("presentation")
    ai = build_presentation_ai_profile(Settings(), stub)
    assert ai == stub


def test_presentation_deepseek_only_llm_models() -> None:
    stub = _load_fixture_ai("presentation")
    ai = build_presentation_ai_profile(Settings(deepseek_api_key="sk-d"), stub)
    assert len(ai["llmModels"]) == 1
    assert ai["llmModels"][0]["provider"] == "DeepSeek"
    assert ai["llmModels"][0]["model"] == "deepseek-reasoner"
    assert ai["llmModels"][0]["active"] is True
    assert ai["llmModels"][0]["apiKey"] == ""
    assert ai["webSearchModels"] == []
    assert len(ai["orchestratorModels"]) == 1
    assert ai["orchestratorModels"][0]["model"] == "deepseek-reasoner"


def test_presentation_llm_and_tavily_web_models() -> None:
    stub = _load_fixture_ai("presentation")
    ai = build_presentation_ai_profile(
        Settings(openai_api_key="sk-o", tavily_api_key="tvly-x"),
        stub,
    )
    assert len(ai["llmModels"]) == 1
    assert ai["llmModels"][0]["provider"] == "OpenAI"
    assert ai["llmModels"][0]["model"] == "gpt-4.1-mini"
    assert len(ai["webSearchModels"]) == 2
    web_providers = {m["provider"] for m in ai["webSearchModels"]}
    assert web_providers == {"Tavily", "OpenAI"}


def test_web_keys_without_llm_do_not_change_presentation_stub() -> None:
    stub = _load_fixture_ai("presentation")
    ai = build_presentation_ai_profile(Settings(tavily_api_key="tvly-x"), stub)
    assert ai == stub


async def _seed(settings: Settings | None = None) -> None:
    async with TestSessionLocal() as session:
        await run_seed(session, settings=settings)


@pytest.mark.asyncio
async def test_seed_demo_profile_reflects_openai_env(client: AsyncClient) -> None:
    await _seed(Settings(openai_api_key="sk-env", deepseek_api_key=""))

    login = await client.post(
        "/api/v1/auth/login/",
        json={"email": "demo@mail.ru", "password": "Demo!2026"},
    )
    assert login.status_code == 200

    ai = await client.get("/api/v1/profile/ai/")
    assert ai.status_code == 200
    llm_models = ai.json()["llmModels"]
    assert len(llm_models) == 1
    assert llm_models[0]["apiKey"] == "env:OPENAI_API_KEY"
    assert llm_models[0]["model"] == "gpt-4.1-mini"
    assert len(ai.json()["webSearchModels"]) == 1
    assert len(ai.json()["orchestratorModels"]) == 1


@pytest.mark.asyncio
async def test_seed_presentation_profile_reflects_deepseek_env(client: AsyncClient) -> None:
    await _seed(Settings(deepseek_api_key="sk-d"))

    ai = await client.get("/api/v1/profile/ai/", headers=guest_auth_headers())
    assert ai.status_code == 200
    body = ai.json()
    assert len(body["llmModels"]) == 1
    assert body["llmModels"][0]["provider"] == "DeepSeek"
    assert body["llmModels"][0]["model"] == "deepseek-reasoner"
    assert body["webSearchModels"] == []
    assert body["orchestratorModels"][0]["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_reseed_updates_models_when_env_changes(client: AsyncClient) -> None:
    await _seed(Settings())
    ai_stub = await client.get("/api/v1/profile/ai/", headers=guest_auth_headers())
    assert ai_stub.json()["llmModels"][0]["apiKey"] == "sk-openai-demo"

    await _seed(Settings(openai_api_key="sk-env"))
    ai_env = await client.get("/api/v1/profile/ai/", headers=guest_auth_headers())
    assert ai_env.json()["llmModels"][0]["provider"] == "OpenAI"
    assert ai_env.json()["llmModels"][0]["model"] == "gpt-4.1-mini"
    assert ai_env.json()["llmModels"][0]["apiKey"] == ""
