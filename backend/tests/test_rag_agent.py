"""Tests for L2 agentic RAG planner loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_agent import (
    build_agent_messages,
    parse_planner_action,
    render_agent_context,
    run_agentic_loop,
)
from app.services.ai.rag_tools import AgentState, ToolOutcome


def _state() -> AgentState:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    return AgentState(
        session=AsyncMock(),
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        embedding_backend=embedding_backend,
        base_post_data=None,
    )


def test_parse_planner_action_clean_json() -> None:
    action = parse_planner_action('{"tool": "Stop", "args": {"reason": "sufficient"}}')
    assert action is not None
    assert action.tool == "Stop"
    assert action.args["reason"] == "sufficient"


def test_parse_planner_action_code_fence() -> None:
    raw = '```json\n{"tool": "OpenPost", "args": {"post_id": "p1"}}\n```'
    action = parse_planner_action(raw)
    assert action is not None
    assert action.tool == "OpenPost"


def test_parse_planner_action_garbage() -> None:
    assert parse_planner_action("not json") is None


def test_build_agent_messages_includes_hints() -> None:
    messages = build_agent_messages(
        "Вопрос",
        transcript=["step 1"],
        hints=["attachment:f1", "media:chart.jpg"],
    )
    user_content = messages[1]["content"]
    assert "attachment:f1" in user_content
    assert "media:chart.jpg" in user_content
    assert "step 1" in user_content


def test_render_agent_context_shape() -> None:
    context, cites = render_agent_context(
        [(NoteCite(path="/note/global/n1/", title="N1"), "Текст заметки")]
    )
    assert "**Контекст из базы знаний:**" in context
    assert "cite-path: /note/global/n1/" in context
    assert cites[0].title == "N1"


@pytest.mark.asyncio
async def test_run_agentic_loop_seed_note_auto_executed() -> None:
    state = _state()
    with (
        patch(
            "app.services.ai.rag_agent.tool_open_note",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="opened note"),
        ) as open_note_mock,
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value='{"tool": "Stop", "args": {"reason": "sufficient"}}',
        ),
    ):
        result = await run_agentic_loop(
            state=state,
            user_text="Вопрос",
            seed_ref="note:n1",
            hints=["attachment:f1"],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=2,
        )

    open_note_mock.assert_awaited_once_with(state, note_id="n1", post_id=None)
    assert result.stopped_reason == "sufficient"


@pytest.mark.asyncio
async def test_run_agentic_loop_budget_exhausted() -> None:
    state = _state()
    with (
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value='{"tool": "SearchNodes", "args": {"query": "test"}}',
        ),
        patch(
            "app.services.ai.rag_agent.tool_search_nodes",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="hits"),
        ),
    ):
        result = await run_agentic_loop(
            state=state,
            user_text="Вопрос",
            seed_ref=None,
            hints=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=1,
        )

    assert result.stopped_reason == "budget_exhausted"


@pytest.mark.asyncio
async def test_run_agentic_loop_parse_failed_fail_soft() -> None:
    state = _state()
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="garbage",
    ):
        result = await run_agentic_loop(
            state=state,
            user_text="Вопрос",
            seed_ref=None,
            hints=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=2,
        )

    assert result.stopped_reason == "parse_failed"
    assert result.rag_context == ""
