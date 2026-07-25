from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.ai.semantic_summary import (
    SELECTOR_SUMMARY_MAX_CHARS,
    build_semantic_discovery_card,
    build_semantic_summary_projections,
)


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
            return_value=(
                '{"discovery_summary":"Карточка описывает пространственную систему и '
                'навигацию по знаниям.","selector_summary":"Пространственная система '
                'и навигация по знаниям."}'
            ),
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
    assert model == "llm:OpenAI:small:v2"
    complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_semantic_summary_one_call_returns_dual_bounded_projection() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    raw = (
        '{"discovery_summary":"Длинная карточка продукта, ограничений и владельцев.",'
        '"selector_summary":"Продукт, ограничения и владельцы."}'
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value=raw,
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Продукт",
            text_value="Описание продукта, ограничений и владельцев.",
        )

    assert complete.await_count == 1
    assert projections.discovery_summary.startswith("Длинная карточка")
    assert len(projections.selector_summary) <= SELECTOR_SUMMARY_MAX_CHARS
    assert projections.model_key == "llm:OpenAI:small:v2"


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
    assert model == "extractive:v2"
