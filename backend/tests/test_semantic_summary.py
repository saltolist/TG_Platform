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
    _selector_card_preserves_explicit_negation,
    _selector_card_preserves_record_markers,
    _selector_card_preserves_explicit_absence,
    selector_card_has_explicit_negation,
    selector_card_has_explicit_absence,
    selector_card_record_marker_kinds,
    selector_semantic_flags,
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
                'поддерживает навигацию. Поиск связывает знания с разделами."}'
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


def test_semantic_summary_schema_does_not_force_provider_string_truncation() -> None:
    properties = _SUMMARY_JSON_SCHEMA["properties"]
    assert "maxLength" not in properties["discovery_summary"]
    assert "maxLength" not in properties["selector_summary"]
    assert "pattern" not in properties["selector_summary"]
    assert SELECTOR_SUMMARY_TARGET_MAX_CHARS < SELECTOR_SUMMARY_MAX_CHARS
    assert "Всегда сохраняй явное отрицание" in _SYSTEM
    assert "inventory или списке" in _SYSTEM
    assert "одного-трех коротких утверждений" in _SYSTEM
    assert "только один существенный факт" in _SYSTEM
    assert "не добавляй второй аспект" in _SYSTEM
    assert "разных существенных аспектах" in _SYSTEM
    assert "корневой или вложенный" in _SYSTEM
    assert "Не используй скобки" in _SYSTEM
    assert "Строго различай что или какие от как или почему" in _SYSTEM
    assert "не будет обрезать твой ответ" in _SYSTEM
    assert "сохранит карточку дословно" in _SYSTEM
    assert "Сохраняй lifecycle-роли записей" in _SYSTEM


def test_negation_preservation_accepts_multilingual_equivalents() -> None:
    assert _selector_card_preserves_explicit_negation(
        "Le rapport avance sans donner son echeance.",
        "Le rapport ne donne toujours pas son echeance.",
    )
    assert _selector_card_preserves_explicit_negation(
        "O calendario mudou sem informar a causa.",
        "O calendario nao informa a causa.",
    )
    assert not _selector_card_preserves_explicit_negation(
        "The inventory contains no signed choice.",
        "The inventory lists eu-central.",
    )
    assert selector_card_has_explicit_negation("The inventory contains no signed choice.")


def test_record_marker_preservation_is_model_independent_and_multilingual() -> None:
    assert selector_card_record_marker_kinds(
        "The signed policy retained the value proposed in the draft."
    ) == {"draft_or_proposed", "final_or_signed"}
    assert _selector_card_preserves_record_markers(
        "Подписанный протокол сохранил значение из черновика.",
        "Финальный протокол сохранил значение, предложенное в draft.",
    )
    assert not _selector_card_preserves_record_markers(
        "The signed policy sets eu-central.",
        "The policy sets eu-central.",
    )
    assert selector_semantic_flags(
        "The load test sustained 610 rps rather than an approved cap."
    ) == {
        "v": 2,
        "explicit_absence": False,
        "observational_value": True,
        "record_roles": [],
    }


def test_explicit_absence_preservation_tracks_semantics_not_any_negation() -> None:
    assert selector_card_has_explicit_absence(
        "The inventory offers no indication of a signed decision."
    )
    assert selector_card_has_explicit_absence(
        "No draft or signed recovery-region choice is recorded."
    )
    assert selector_card_has_explicit_absence(
        "Учебный откат завершился за 34 минуты, но утвержденное окно не задано."
    )
    assert not selector_card_has_explicit_absence(
        "The signed policy does not change the region proposed in the draft."
    )
    assert _selector_card_preserves_explicit_absence(
        "Решение не устанавливает владельца.",
        "Владелец в решении отсутствует.",
    )
    assert not _selector_card_preserves_explicit_absence(
        "The inventory contains no signed choice.",
        "The inventory is not a signed policy.",
    )
    for value in (
        "La telemetria no establece el limite de cancelacion.",
        "Le rapport ne donne pas son echeance.",
        "L'agenda ne reserve pas de duree au retour arriere.",
        "L'agenda est publie sans reserver de duree au retour arriere.",
        "La prova non definisce il minimo richiesto.",
        "O calendario nao informa a causa.",
        "La nota nennt keine blockierende Freigabe.",
    ):
        assert selector_card_has_explicit_absence(value), value


@pytest.mark.asyncio
async def test_semantic_summary_regenerates_when_record_role_is_lost() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    lost = (
        '{"discovery_summary":"The policy selects a recovery region.",'
        '"selector_summary":"The policy sets eu-central as the recovery region."}'
    )
    valid = (
        '{"discovery_summary":"The signed policy selects a recovery region.",'
        '"selector_summary":"The signed policy sets eu-central as the recovery region."}'
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=[lost, valid],
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="post",
            title="Signed recovery policy",
            text_value="The signed policy sets eu-central as the recovery region.",
        )

    assert complete.await_count == 2
    assert projections.generation_status == "llm_valid_retry"
    assert projections.selector_summary.startswith("The signed policy")
    assert "code=selector_record_marker_lost" in (
        complete.await_args_list[1].kwargs["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_semantic_summary_one_call_returns_dual_bounded_projection() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    raw = (
        '{"discovery_summary":"Длинная карточка продукта, ограничений и владельцев.",'
        '"selector_summary":"Документ описывает продукт и его ограничения. В нем названы владельцы."}'
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
        '"selector_summary":"Перечислены пять функций: кабинет, AI и поиск. Также названы синхронизация и аналитика."}'
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
        "Перечислены пять функций: кабинет, AI и поиск. "
        "Также названы синхронизация и аналитика."
    )
    assert projections.generation_status == "llm_valid_retry"
    retry_messages = complete.await_args_list[1].kwargs["messages"]
    assert "не обрезай готовую фразу по границе" in retry_messages[-1]["content"]
    assert len(retry_messages) == 3
    assert overlong not in {message["content"] for message in retry_messages}


@pytest.mark.asyncio
async def test_semantic_summary_repair_prompts_progress_across_deterministic_failures() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    overlong = (
        '{"discovery_summary":"Полная discovery карточка.",'
        f'"selector_summary":"{"x" * (SELECTOR_SUMMARY_MAX_CHARS + 1)}"}}'
    )
    complete = AsyncMock(return_value=overlong)
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch("app.services.ai.llm.complete_chat_completion", complete),
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Функции",
            text_value="Подробное перечисление пяти функций.",
        )

    assert projections.selector_summary == ""
    assert projections.generation_status == "selector_too_long"
    assert complete.await_count == 5
    repair_prompts = [
        call.kwargs["messages"][-1]["content"]
        for call in complete.await_args_list[1:]
    ]
    assert len(set(repair_prompts)) == 4
    assert "Repair attempt 2/5" in repair_prompts[0]
    assert "не длиннее 205 Unicode-символов" in repair_prompts[0]
    assert "не более 3 предложений" in repair_prompts[0]
    assert "не более 28 слов всего" in repair_prompts[0]
    assert "Repair attempt 5/5" in repair_prompts[-1]
    assert "не длиннее 175 Unicode-символов" in repair_prompts[-1]
    assert "не более 2 предложений" in repair_prompts[-1]
    assert "не более 16 слов всего" in repair_prompts[-1]


@pytest.mark.asyncio
async def test_semantic_summary_does_not_force_incidental_negation_into_long_card() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    valid = (
        '{"discovery_summary":"The workspace joins channel operations and knowledge.",'
        '"selector_summary":"The workspace has six functional zones for channel work."}'
    )
    source = (
        "The workspace has six functional zones for channel work. "
        + "Detailed operational guidance and examples. " * 80
        + "It is not a standalone search engine. A draft can be edited before publishing."
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value=valid,
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Workspace",
            text_value=source,
        )

    complete.assert_awaited_once()
    assert projections.generation_status == "llm_valid"
    assert projections.selector_summary_version == SELECTOR_SUMMARY_VERSION
    assert projections.selector_semantic_flags == {
        "v": 2,
        "explicit_absence": False,
        "observational_value": False,
        "record_roles": ["draft_or_proposed"],
    }


@pytest.mark.asyncio
async def test_semantic_summary_regenerates_when_explicit_negation_is_lost() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    lost = (
        '{"discovery_summary":"The inventory lists recovery regions.",'
        '"selector_summary":"The inventory lists eu-central among recovery regions."}'
    )
    valid = (
        '{"discovery_summary":"The inventory lists recovery regions.",'
        '"selector_summary":"The inventory contains no draft or signed recovery-region choice."}'
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=[lost, valid],
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="note",
            title="Region inventory",
            text_value=(
                "The inventory lists eu-central but contains no draft or signed choice."
            ),
        )

    assert complete.await_count == 2
    assert projections.generation_status == "llm_valid_retry"
    assert "contains no draft" in projections.selector_summary
    assert "code=selector_record_marker_lost" in (
        complete.await_args_list[1].kwargs["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_semantic_summary_accepts_lossy_card_when_matched_evidence_carries_negation() -> None:
    resolved = (SimpleNamespace(name="OpenAI"), "small", "secret")
    lost = (
        '{"discovery_summary":"The release policy defines permissions.",'
        '"selector_summary":"The release is permitted before approval."}'
    )
    valid = (
        '{"discovery_summary":"The release policy defines permissions.",'
        '"selector_summary":"The release is not permitted before approval."}'
    )
    with (
        patch("app.services.ai.semantic_summary.resolve_orchestrator_llm", return_value=resolved),
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=[lost, valid],
        ) as complete,
    ):
        projections = await build_semantic_summary_projections(
            user=SimpleNamespace(),
            ai_profile={},
            settings=Settings(rag_semantic_summaries_enabled=True),
            object_kind="post",
            title="Release policy",
            text_value="The release is not permitted before approval.",
        )

    assert complete.await_count == 1
    assert projections.selector_summary == "The release is permitted before approval."
    assert projections.generation_status == "llm_valid"


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
                '"selector_summary":"Релиз содержит ключевые изменения. Изменения влияют на продукт."}'
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

    assert projections.selector_summary == (
        "Релиз содержит ключевые изменения. Изменения влияют на продукт."
    )
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
