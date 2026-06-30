"""Tests for RAG query building and rewrite-on-miss orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.ai.rag_query import (
    build_rag_query_from_history,
    build_rag_rewrite_messages,
    retrieve_rag_for_reply,
    rewrite_rag_query_llm,
)


def test_build_rag_query_without_history_returns_current_message() -> None:
    assert build_rag_query_from_history("Что по дедлайнам?", None) == "Что по дедлайнам?"


def test_build_rag_query_includes_recent_dialogue() -> None:
    history = [
        {"role": "user", "text": "Расскажи про Ивана Петрова"},
        {"role": "ai", "text": "Иван Петров — ключевой контакт по проекту X."},
    ]
    query = build_rag_query_from_history("А что по его дедлайнам?", history, history_turns=2)
    assert "Предыдущий диалог:" in query
    assert "Иван Петров" in query
    assert "Текущий запрос: А что по его дедлайнам?" in query


def test_build_rag_query_excludes_duplicate_current_user_turn() -> None:
    history = [
        {"role": "user", "text": "А что по его дедлайнам?"},
    ]
    query = build_rag_query_from_history("А что по его дедлайнам?", history, history_turns=2)
    assert query == "А что по его дедлайнам?"
    assert "Предыдущий диалог:" not in query


def test_build_rag_query_truncates_to_max_chars() -> None:
    history = [
        {"role": "user", "text": "A" * 500},
        {"role": "ai", "text": "B" * 500},
        {"role": "user", "text": "C" * 500},
        {"role": "ai", "text": "D" * 500},
    ]
    current = "Короткий вопрос"
    query = build_rag_query_from_history(
        current,
        history,
        history_turns=2,
        max_chars=300,
    )
    assert len(query) <= 300
    assert query.endswith(f"Текущий запрос: {current}")


def test_build_rag_rewrite_messages_include_assistant_turns() -> None:
    history = [
        {"role": "user", "text": "Дай три идеи"},
        {"role": "ai", "text": "1. Первая\n2. Вторая\n3. Третья"},
    ]
    messages = build_rag_rewrite_messages("Разверни вторую", history)
    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    assert "Дай три идеи" in user_content
    assert "2. Вторая" in user_content
    assert "Разверни вторую" in user_content


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rewrites_on_miss() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    empty_results: list[dict] = []
    hit_results = [{"note_id": "n1", "post_id": None, "similarity": 0.9}]

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            side_effect=[empty_results, hit_results],
        ) as retrieve_mock,
        patch(
            "app.services.ai.rag_query.rewrite_rag_query_llm",
            new_callable=AsyncMock,
            return_value="Подробнее про вторую идею из списка",
        ) as rewrite_mock,
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ),
    ):
        await retrieve_rag_for_reply(
            session=AsyncMock(),
            user_id=uuid4(),
            scope="global",
            user_text="Разверни вторую",
            history=[
                {"role": "user", "text": "Дай три идеи"},
                {"role": "ai", "text": "1. Первая\n2. Вторая\n3. Третья"},
            ],
            embedding_backend=embedding_backend,
            post_data=None,
            tenant_key=None,
            post_id=None,
            top_k=4,
            min_similarity=0.38,
            history_turns=2,
            query_max_chars=2000,
            rewrite_on_miss=True,
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert retrieve_mock.await_count == 2
    rewrite_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_skips_rewrite_when_first_hit() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    hit_results = [{"note_id": "n1", "post_id": None, "similarity": 0.9}]

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=hit_results,
        ) as retrieve_mock,
        patch(
            "app.services.ai.rag_query.rewrite_rag_query_llm",
            new_callable=AsyncMock,
        ) as rewrite_mock,
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ),
    ):
        await retrieve_rag_for_reply(
            session=AsyncMock(),
            user_id=uuid4(),
            scope="global",
            user_text="Что по дедлайнам?",
            history=None,
            embedding_backend=embedding_backend,
            post_data=None,
            tenant_key=None,
            post_id=None,
            top_k=4,
            min_similarity=0.38,
            history_turns=2,
            query_max_chars=2000,
            rewrite_on_miss=True,
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert retrieve_mock.await_count == 1
    rewrite_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_rag_query_llm_rejects_meta_reply() -> None:
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="Переформулирую последний запрос пользователя в поисковый запрос",
    ):
        result = await rewrite_rag_query_llm(
            "Разверни вторую",
            history=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
        )
    assert result is None
