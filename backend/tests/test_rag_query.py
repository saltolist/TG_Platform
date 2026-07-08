"""Tests for RAG query building and rewrite-on-miss orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.ai.rag_escalation import TierAResult, TierASignals
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
async def test_retrieve_rag_for_reply_l0_skips_without_embed() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with patch(
        "app.services.ai.rag_query.retrieve_top_k",
        new_callable=AsyncMock,
    ) as retrieve_mock:
        context, cites = await retrieve_rag_for_reply(
            session=AsyncMock(),
            user_id=uuid4(),
            scope="global",
            user_text="привет",
            history=None,
            embedding_backend=embedding_backend,
            post_data=None,
            tenant_key=None,
            post_id=None,
            top_k=4,
            min_similarity=0.38,
            history_turns=2,
            query_max_chars=2000,
            rewrite_on_miss=False,
            l0_enabled=True,
        )

    assert context == ""
    assert cites == []
    embedding_backend.embed_query.assert_not_awaited()
    retrieve_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_l0_kill_switch_runs_retrieval() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=[],
        ) as retrieve_mock,
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("", []),
        ),
    ):
        await retrieve_rag_for_reply(
            session=AsyncMock(),
            user_id=uuid4(),
            scope="global",
            user_text="привет",
            history=None,
            embedding_backend=embedding_backend,
            post_data=None,
            tenant_key=None,
            post_id=None,
            top_k=4,
            min_similarity=0.38,
            history_turns=2,
            query_max_chars=2000,
            rewrite_on_miss=False,
            l0_enabled=False,
        )

    embedding_backend.embed_query.assert_awaited_once()
    retrieve_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_logs_tier_a_without_changing_output() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    hit_results = [
        {
            "note_id": "n1",
            "post_id": None,
            "chunk_index": 0,
            "tenant_key": "",
            "node_type": "note_chunk",
            "file_id": "",
            "chunk_text": "Длинный текст чанка для Tier A сигналов и проверки.",
            "referenced_ids": [],
            "similarity": 0.9,
        }
    ]

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=hit_results,
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ) as format_mock,
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
        ) as tier_a_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            escalate_min_similarity=0.72,
            escalate_on_miss=True,
        )

    assert context == "--- context ---"
    assert cites == []
    tier_a_mock.assert_called_once()
    format_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_tier_a_on_empty_results_global_scope() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with patch(
        "app.services.ai.rag_query.retrieve_top_k",
        new_callable=AsyncMock,
        return_value=[],
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            escalate_min_similarity=0.72,
            escalate_on_miss=True,
        )

    assert context == ""
    assert cites == []


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


def _hit_results() -> list[dict]:
    return [
        {
            "note_id": "n1",
            "post_id": None,
            "chunk_index": 0,
            "tenant_key": "",
            "node_type": "note_chunk",
            "file_id": "",
            "chunk_text": "Длинный текст чанка для Tier A/B сигналов и проверки.",
            "referenced_ids": [],
            "similarity": 0.9,
        }
    ]


def _tier_a_no_fast_path() -> TierAResult:
    return TierAResult(
        fast_path=None,
        escalate_target=None,
        signals=TierASignals(
            pointer_phrase=False,
            answer_type_mismatch=False,
            chunk_too_short=False,
            is_followup=False,
        ),
        neighbors={"notes": [], "media": [], "comments_count": 0},
    )


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_tier_b_disabled_by_default() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=_tier_a_no_fast_path(),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_b",
            new_callable=AsyncMock,
        ) as tier_b_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert context == "--- context ---"
    assert cites == []
    tier_b_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_tier_b_skipped_on_fast_path() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=TierAResult(
                fast_path="miss",
                escalate_target=None,
                signals=TierASignals(False, False, False, False),
                neighbors={},
            ),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_b",
            new_callable=AsyncMock,
        ) as tier_b_mock,
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
            rewrite_on_miss=False,
            tier_b_enabled=True,
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    tier_b_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_tier_b_skipped_without_reasoner() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=_tier_a_no_fast_path(),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_b",
            new_callable=AsyncMock,
        ) as tier_b_mock,
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
            rewrite_on_miss=False,
            tier_b_enabled=True,
        )

    tier_b_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_tier_b_enabled_logs_without_changing_output() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ) as format_mock,
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=_tier_a_no_fast_path(),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_b",
            new_callable=AsyncMock,
            return_value=type("TierB", (), {"sufficient": False, "open_next": ["note:n2"], "error": None})(),
        ) as tier_b_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            tier_b_enabled=True,
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert context == "--- context ---"
    assert cites == []
    tier_b_mock.assert_awaited_once()
    format_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_off_skips_l2() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- context ---", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=TierAResult(
                fast_path="miss",
                escalate_target=None,
                signals=TierASignals(False, False, False, False),
                neighbors={},
            ),
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
        ) as loop_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rag_mode="off",
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert context == "--- context ---"
    loop_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_flat_skips_l2_on_miss() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=TierAResult(
                fast_path="miss",
                escalate_target=None,
                signals=TierASignals(False, False, False, False),
                neighbors={},
            ),
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
        ) as loop_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rag_mode="flat",
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    assert context == ""
    assert cites == []
    loop_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_agentic_runs_l2() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    agent_result = type(
        "AgentResult",
        (),
        {
            "rag_context": "---\n**Контекст из базы знаний:**\n[1] cite-path: /post/p1/",
            "cites": [],
            "stopped_reason": "sufficient",
        },
    )()

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- l1 ---", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=_tier_a_no_fast_path(),
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
            return_value=agent_result,
        ) as loop_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rag_mode="agentic",
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    loop_mock.assert_awaited_once()
    assert "--- l1 ---" in context
    assert "Контекст из базы знаний" in context


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_auto_miss_bypasses_empty_early_return() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    agent_result = type(
        "AgentResult",
        (),
        {"rag_context": "--- agent ---", "cites": [], "stopped_reason": "budget_exhausted"},
    )()

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=TierAResult(
                fast_path="miss",
                escalate_target=None,
                signals=TierASignals(False, False, False, False),
                neighbors={},
            ),
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
            return_value=agent_result,
        ) as loop_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rag_mode="auto",
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    loop_mock.assert_awaited_once()
    assert context == "--- agent ---"


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_auto_tier_b_insufficient_runs_l2() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    tier_b_result = type(
        "TierB",
        (),
        {"sufficient": False, "open_next": ["note:n2"], "error": None},
    )()
    agent_result = type(
        "AgentResult",
        (),
        {"rag_context": "--- agent ---", "cites": [], "stopped_reason": "sufficient"},
    )()

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=_hit_results(),
        ),
        patch(
            "app.services.ai.rag_query.format_rag_context",
            new_callable=AsyncMock,
            return_value=("--- l1 ---", []),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=_tier_a_no_fast_path(),
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_b",
            new_callable=AsyncMock,
            return_value=tier_b_result,
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
            return_value=agent_result,
        ) as loop_mock,
    ):
        context, _ = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            tier_b_enabled=True,
            rag_mode="auto",
            rewrite_spec=object(),  # type: ignore[arg-type]
            rewrite_model="gpt-test",
            rewrite_api_key="key",
        )

    loop_mock.assert_awaited_once()
    assert "--- l1 ---" in context
    assert "--- agent ---" in context


@pytest.mark.asyncio
async def test_retrieve_rag_for_reply_rag_mode_auto_skips_l2_without_reasoner() -> None:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])

    with (
        patch(
            "app.services.ai.rag_query.retrieve_top_k",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.ai.rag_query.evaluate_tier_a",
            return_value=TierAResult(
                fast_path="miss",
                escalate_target=None,
                signals=TierASignals(False, False, False, False),
                neighbors={},
            ),
        ),
        patch(
            "app.services.ai.rag_query.run_agentic_loop",
            new_callable=AsyncMock,
        ) as loop_mock,
    ):
        context, cites = await retrieve_rag_for_reply(
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
            rewrite_on_miss=False,
            rag_mode="auto",
        )

    assert context == ""
    loop_mock.assert_not_awaited()


def test_seed_and_hints_post_analytics_global() -> None:
    from app.services.ai.rag_query import _seed_and_hints

    seed, hints = _seed_and_hints(
        TierAResult(None, None, TierASignals(False, False, False, False), {}),
        None,
        user_text="Сколько просмотров у поста про скидки?",
        scope="global",
        intent_routing_enabled=True,
    )
    assert seed is None
    assert any("GetPostAnalytics" in hint for hint in hints)


def test_seed_and_hints_comments_hint_names_tool() -> None:
    from app.services.ai.rag_query import _seed_and_hints

    _, hints = _seed_and_hints(
        TierAResult(None, "comments", TierASignals(False, False, False, False), {}),
        None,
    )
    assert any("ListPostComments" in hint for hint in hints)
