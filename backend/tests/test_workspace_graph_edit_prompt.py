"""Regression for chat 2b9447dd: a chain of anaphoric follow-up edits on a
still-rejected proposal ("добавь 3" → "замени на 4, пробел" → "точку после
неё") must layer each edit onto the previous PROPOSED body, not the saved
post — "Отклонить" means "wording isn't right yet", not "start over"."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.workspace_graph import _generate_edited_post_html
from app.services.ai.providers import ProviderSpec


class _FakeSessionCtx:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


def _ctx() -> RuntimeContext:
    ctx = RuntimeContext(
        session_factory=lambda: _FakeSessionCtx(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="post",
        post_data=None,
        ai_profile={},
    )
    ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
    ctx.reasoner_model = "gpt-4o-mini"
    ctx.reasoner_api_key = "test-key"
    return ctx


@pytest.mark.asyncio
async def test_prior_proposal_becomes_edit_base_not_current_html() -> None:
    """The saved post has no digit at all ("Текст поста."). "Добавь после неё
    точку" only makes sense if the model edits the PROPOSED body
    ("Текст поста.3"), not the saved one — else there's nothing for "неё" to
    anchor to and the model silently returns the post unchanged (the actual
    regression observed in chat 2b9447dd turn 3)."""
    ctx = _ctx()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="Текст поста.3.",
    ) as mock_llm:
        result = await _generate_edited_post_html(
            ctx,
            current_html="Текст поста.",
            instruction="Добавь после неё точку",
            last_proposed_post_html="Текст поста.3",
        )

    assert result == "Текст поста.3."
    sent_messages = mock_llm.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in sent_messages if m["role"] == "user")
    # The text handed to the model as "the post to edit" must be the proposed
    # body, not the saved one.
    assert "Текст поста, который нужно отредактировать" in user_content
    edit_section = user_content.split("Текст поста, который нужно отредактировать")[1]
    assert "Текст поста.3" in edit_section.split("Инструкция:")[0]
    # The saved post is still surfaced, but only as background reference.
    assert "Текст поста." in user_content


@pytest.mark.asyncio
async def test_no_prior_proposal_edits_current_html_directly() -> None:
    ctx = _ctx()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="Новый текст",
    ) as mock_llm:
        await _generate_edited_post_html(
            ctx,
            current_html="Текст поста.",
            instruction="Сделай короче",
            last_proposed_post_html=None,
        )

    sent_messages = mock_llm.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "цепочке правок" not in user_content
    edit_section = user_content.split("Текст поста, который нужно отредактировать")[1]
    assert "Текст поста." in edit_section.split("Инструкция:")[0]


@pytest.mark.asyncio
async def test_verified_workspace_context_is_available_to_edit_model() -> None:
    ctx = _ctx()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="Новый текст",
    ) as mock_llm:
        await _generate_edited_post_html(
            ctx,
            current_html="Текст поста.",
            instruction="Уточни анонс по материалам",
            workspace_context="Проверенная заметка: запуск назначен на пятницу.",
        )

    sent_messages = mock_llm.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "Проверенные материалы workspace" in user_content
    assert "запуск назначен на пятницу" in user_content


@pytest.mark.asyncio
async def test_prior_proposal_identical_to_current_edits_current_html() -> None:
    """If the proposed body already matches the saved post (e.g. it was
    approved and applied since), there's no pending draft to continue —
    edit the saved post directly instead of pointlessly repeating it."""
    ctx = _ctx()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="Новый текст",
    ) as mock_llm:
        await _generate_edited_post_html(
            ctx,
            current_html="Текст поста.3",
            instruction="Сделай короче",
            last_proposed_post_html="Текст поста.3",
        )

    sent_messages = mock_llm.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in sent_messages if m["role"] == "user")
    assert "цепочке правок" not in user_content


@pytest.mark.asyncio
async def test_question_mark_followup_after_period_is_deterministic() -> None:
    """Regression for chat 21613326: the router understood the referent, but
    the edit model returned the original period. The prior proposal's only
    delta is '?' so 'after the period' must produce '.?' without an LLM call."""
    ctx = _ctx()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
    ) as mock_llm:
        result = await _generate_edited_post_html(
            ctx,
            current_html="Убери цифру 2 в конце этого поста.",
            instruction="Сделай его после точки",
            last_proposed_post_html="Убери цифру 2 в конце этого поста?",
        )

    assert result == "Убери цифру 2 в конце этого поста.?"
    mock_llm.assert_not_awaited()
