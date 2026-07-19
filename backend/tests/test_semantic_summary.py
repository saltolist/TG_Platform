from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.ai.semantic_summary import build_semantic_discovery_card


@pytest.mark.asyncio
async def test_semantic_card_uses_orchestrator_and_bounds_output() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    with (
        patch(
            "app.services.ai.semantic_summary.resolve_orchestrator_llm",
            return_value=resolved,
        ),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value="Карточка описывает пространственную систему и навигацию по знаниям.",
        ) as complete,
    ):
        card, model = await build_semantic_discovery_card(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Система",
            text_value="Подробное описание устройства пространства.",
        )

    assert "пространственную систему" in card
    assert model == "llm:OpenAI:small:v1"
    complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_semantic_card_has_extract_fallback_without_llm() -> None:
    with patch(
        "app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=None
    ):
        card, model = await build_semantic_discovery_card(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="post",
            title="Релиз",
            text_value="Описание новой версии продукта.",
        )

    assert card.startswith("Релиз:")
    assert model == "extractive:v1"
