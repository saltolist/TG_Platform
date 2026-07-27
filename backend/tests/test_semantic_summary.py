from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.ai.providers import ChatCompletionCapability, ProviderSpec
from app.services.ai.semantic_summary import (
    DISCOVERY_SUMMARY_MAX_CHARS,
    SELECTOR_SUMMARY_TARGET_MAX_CHARS,
    SELECTOR_SUMMARY_VERSION,
    SELECTOR_SUMMARY_MAX_CHARS,
    _SUMMARY_JSON_SCHEMA,
    _SYSTEM,
    build_semantic_discovery_card,
    build_semantic_summary_projections,
    semantic_summary_model_key,
)


@pytest.mark.asyncio
async def test_semantic_card_uses_orchestrator_and_bounds_output() -> None:
    resolved = (
        ProviderSpec(
            name="OpenAI",
            base_url="https://example.test",
            chat_capabilities=(ChatCompletionCapability.STRICT_JSON_SCHEMA,),
        ),
        "small",
        "secret",
    )
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
    assert (
        complete.await_args.kwargs["output_capability"]
        == ChatCompletionCapability.STRICT_JSON_SCHEMA
    )
    assert complete.await_args.kwargs["output_json_schema"] == _SUMMARY_JSON_SCHEMA


def test_semantic_summary_schema_does_not_constrain_llm_string_length() -> None:
    properties = _SUMMARY_JSON_SCHEMA["properties"]
    assert "maxLength" not in properties["discovery_summary"]
    assert "maxLength" not in properties["selector_summary"]
    assert "pattern" not in properties["selector_summary"]
    assert SELECTOR_SUMMARY_TARGET_MAX_CHARS < SELECTOR_SUMMARY_MAX_CHARS
    assert "название категории, количество и названия элементов" in _SYSTEM
    assert "корневой или вложенный" in _SYSTEM
    assert "Не используй скобки" in _SYSTEM


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
async def test_semantic_summary_regenerates_overlong_llm_card_without_slicing() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    overlong = (
        '{"discovery_summary":"Полная discovery карточка.",'
        f'"selector_summary":"{"x" * (SELECTOR_SUMMARY_MAX_CHARS + 1)}"}}'
    )
    valid = (
        '{"discovery_summary":"Полная discovery карточка.",'
        '"selector_summary":"Пять функций: кабинет, AI, синхронизация, аналитика и поиск."}'
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=[overlong, valid],
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Функции",
            text_value="Подробное перечисление пяти функций.",
        )

    assert complete.await_count == 2
    assert projections.selector_summary == (
        "Пять функций: кабинет, AI, синхронизация, аналитика и поиск."
    )
    assert projections.generation_status == "llm_valid_retry"
    retry_messages = complete.await_args_list[1].kwargs["messages"]
    assert "не обрезай предыдущий текст" in retry_messages[-1]["content"]


@pytest.mark.asyncio
async def test_semantic_card_uses_answer_model_when_orchestrator_is_unavailable() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "answer-small", "secret")
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=None),
        patch("app.services.ai.semantic_summary.resolve_answer_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value=(
                '{"discovery_summary":"Карточка релиза и его изменений.",'
                '"selector_summary":"Релиз и его ключевые изменения."}'
            ),
        ),
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="post",
            title="Релиз",
            text_value="Описание новой версии продукта.",
        )

    assert projections.selector_summary == "Релиз и его ключевые изменения."
    assert projections.selector_summary_version == SELECTOR_SUMMARY_VERSION
    assert projections.model_key == "llm:OpenAI:answer-small:v2"
    assert projections.generation_status == "llm_valid"


@pytest.mark.asyncio
async def test_semantic_card_has_discovery_only_fallback_without_llm() -> None:
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=None),
        patch("app.services.ai.semantic_summary.resolve_answer_llm", return_value=None),
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="post",
            title="Релиз",
            text_value="Описание новой версии продукта.",
        )

    assert projections.discovery_summary.startswith("Релиз:")
    assert projections.selector_summary == ""
    assert projections.selector_summary_version == 0
    assert projections.model_key == "extractive:v2"
    assert projections.generation_status == "model_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_result",
    [
        TimeoutError(),
        RuntimeError("provider failed"),
        "not-json",
        '{"selector_summary":"only"}',
        (
            '{"discovery_summary":"Достаточная карточка discovery.",'
            f'"selector_summary":"{"x" * (SELECTOR_SUMMARY_MAX_CHARS + 1)}"}}'
        ),
        (
            '{"discovery_summary":"Достаточная карточка discovery.",'
            '"selector_summary":"Незаконченное предложение карточки"}'
        ),
        (
            '{"discovery_summary":"Достаточная карточка discovery.",'
            '"selector_summary":"Входящий поток и исходящий поток (п."}'
        ),
        (
            '{"discovery_summary":"Достаточная карточка discovery.",'
            '"selector_summary":"Завершенная мысль.!"}'
        ),
    ],
)
async def test_semantic_card_never_publishes_extractive_selector_on_generation_failure(
    provider_result: object,
) -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    complete = AsyncMock()
    if isinstance(provider_result, BaseException):
        complete.side_effect = provider_result
    else:
        complete.return_value = provider_result

    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch("app.services.ai.llm.complete_chat_completion", complete),
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Архитектура",
            text_value="Существенный факт расположен далеко от начала исходного документа.",
        )

    assert projections.discovery_summary.startswith("Архитектура:")
    assert projections.selector_summary == ""
    assert projections.selector_summary_version == 0
    assert projections.model_key == "extractive:v2"
    assert projections.generation_status in {
        "provider_error",
        "invalid_json",
        "missing_fields",
        "selector_too_long",
        "selector_incomplete",
    }


def test_semantic_summary_model_key_is_extractive_when_no_llm_can_be_resolved() -> None:
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=None),
        patch("app.services.ai.semantic_summary.resolve_answer_llm", return_value=None),
    ):
        assert semantic_summary_model_key(SimpleNamespace(), {}, Settings()) == "extractive:v2"
