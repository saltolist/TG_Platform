"""Tests for L2 agentic RAG planner loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_agent import (
    _finalize_plan_phase,
    _is_valid_hydrate_ref,
    build_agent_messages,
    format_planner_trace_lines,
    parse_planner_action,
    render_agent_context,
    run_agentic_loop,
)
from app.services.ai.rag_retrieval_plan import (
    L2PlanContext,
    RetrievalPlan,
    RetrievalPlanStep,
    StructuredPlanDecision,
)
from app.services.ai.rag_stop_evaluator import StopVerdict
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


def test_format_planner_trace_lines_includes_raw_and_parsed() -> None:
    raw = '{"tool": "OpenPost", "args": {"post_id": "3"}}'
    action = parse_planner_action(raw)
    lines = format_planner_trace_lines(
        step_index=2,
        max_steps=4,
        raw=raw,
        action=action,
    )
    assert lines[0] == "step=2/4"
    assert "OpenPost" in lines[1]
    assert lines[2] == "parsed_tool=OpenPost"
    assert "'post_id': '3'" in lines[3]


def test_format_planner_trace_lines_truncates_long_raw() -> None:
    raw = '{"tool": "SearchNodes", "args": {"query": "' + ("x" * 900) + '"}}'
    lines = format_planner_trace_lines(step_index=1, max_steps=4, raw=raw, action=None)
    assert lines[1].startswith("raw: ")
    assert lines[1].endswith("…")
    assert len(lines[1]) < 900


@pytest.mark.asyncio
async def test_run_agentic_loop_traces_planner_raw() -> None:
    state = _state()
    planner_raw = '{"tool": "SearchNodes", "args": {"query": "приветственный пост"}}'
    with (
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            return_value=planner_raw,
        ),
        patch(
            "app.services.ai.rag_agent.tool_search_nodes",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="hits"),
        ),
        patch("app.services.ai.rag_agent.trace_step") as trace_mock,
    ):
        await run_agentic_loop(
            state=state,
            user_text="Вопрос",
            seed_ref=None,
            hints=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=1,
        )

    planner_calls = [
        call
        for call in trace_mock.call_args_list
        if call.args[0] == "7. rag.L2.planner"
    ]
    assert len(planner_calls) == 1
    body = planner_calls[0].args[1]
    assert isinstance(body, list)
    assert any("приветственный пост" in line for line in body)
    assert any(line.startswith("parsed_tool=SearchNodes") for line in body)


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


def test_is_valid_hydrate_ref_rejects_placeholder() -> None:
    assert not _is_valid_hydrate_ref("attachment:<id>")
    assert not _is_valid_hydrate_ref("")
    assert _is_valid_hydrate_ref("attachment:704a2ddd-f969-46d1-8a04-04efd02abfde")
    assert _is_valid_hydrate_ref("file:media-1")


@pytest.mark.asyncio
async def test_finalize_plan_phase_rejects_comparative_stop_until_all_images() -> None:
    state = _state()
    state.settings = Settings(rag_agent_max_vision=2)
    state.listed_image_attachment_refs = [
        "attachment:img1",
        "attachment:img2",
    ]
    state.visited.add("hydrate:vision:attachment:img1")
    state.context_blocks.append(
        (NoteCite(path="/note/global/n1/attachment/img1/", title="A"), "caption a")
    )
    query = (
        "Как считаешь, какое изображение подойдет моему посту про "
        "больше никаких переключений между сервисами?"
    )
    stopped_reason, should_break = await _finalize_plan_phase(
        user_text=query,
        state=state,
        transcript=[],
        stopped_reason="plan_complete",
    )
    assert not should_break
    assert stopped_reason == "plan_complete"


@pytest.mark.asyncio
async def test_run_agentic_loop_seed_note_auto_executed() -> None:
    state = _state()
    async def _open_note_side_effect(state: AgentState, *, note_id: str, post_id: str | None = None):
        state.visited.add(f"note:{note_id}")
        state.context_blocks.append(
            (NoteCite(path=f"/note/global/{note_id}/", title="N"), "Текст заметки")
        )
        return ToolOutcome(summary="opened note")

    with (
        patch(
            "app.services.ai.rag_agent.tool_open_note",
            new_callable=AsyncMock,
            side_effect=_open_note_side_effect,
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


@pytest.mark.asyncio
async def test_dispatch_hydrate_attachment_text() -> None:
    from app.services.ai.rag_agent import _dispatch_tool, PlannerAction

    state = _state()
    with patch(
        "app.services.ai.rag_agent.tool_hydrate_attachment",
        new_callable=AsyncMock,
        return_value=ToolOutcome(summary="hydrated"),
    ) as hydrate_mock:
        outcome = await _dispatch_tool(
            state,
            PlannerAction(
                tool="HydrateAttachment",
                args={"ref": "attachment:f1", "mode": "text", "note_id": "n1"},
            ),
        )

    assert outcome.summary == "hydrated"
    hydrate_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_list_post_comments() -> None:
    from app.services.ai.rag_agent import _dispatch_tool, PlannerAction

    state = _state()
    with patch(
        "app.services.ai.rag_agent.tool_list_post_comments",
        return_value=ToolOutcome(summary="comments"),
    ) as comments_mock:
        outcome = await _dispatch_tool(
            state,
            PlannerAction(tool="ListPostComments", args={"post_id": "post-1"}),
        )

    assert outcome.summary == "comments"
    comments_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_get_post_analytics() -> None:
    from app.services.ai.rag_agent import _dispatch_tool, PlannerAction

    state = _state()
    with patch(
        "app.services.ai.rag_agent.tool_get_post_analytics",
        new_callable=AsyncMock,
        return_value=ToolOutcome(summary="analytics"),
    ) as analytics_mock:
        outcome = await _dispatch_tool(
            state,
            PlannerAction(
                tool="GetPostAnalytics",
                args={"post_id": "post-1", "period": "7d"},
            ),
        )

    assert outcome.summary == "analytics"
    analytics_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agentic_loop_keeps_context_after_hydration_failure() -> None:
    state = _state()
    state.context_blocks.append((NoteCite(path="/post/p1/", title="Post"), "Existing context"))
    with (
        patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=[
                '{"tool": "HydrateAttachment", "args": {"ref": "attachment:f1", "mode": "text", "note_id": "n1"}}',
                '{"tool": "Stop", "args": {"reason": "sufficient"}}',
            ],
        ),
        patch(
            "app.services.ai.rag_agent.tool_hydrate_attachment",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="failed", error="fetch_failed"),
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
            max_steps=3,
        )

    assert "Existing context" in result.rag_context
    assert result.stopped_reason == "sufficient"


@pytest.mark.asyncio
async def test_run_agentic_loop_replans_after_discovery() -> None:
    state = _state()
    initial_plan = RetrievalPlan(
        goal="discover posts",
        steps=[
            RetrievalPlanStep(
                tool="ListPosts",
                args={"status": "all"},
                purpose="каталог",
            ),
        ],
    )
    replan_plan = RetrievalPlan(
        goal="open welcome post",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "3"},
                purpose="прочитать пост",
            ),
        ],
    )

    async def _compose_side_effect(**kwargs: object) -> tuple[RetrievalPlan, str]:
        if kwargs.get("transcript"):
            return replan_plan, '{"goal": "open welcome post"}'
        return initial_plan, '{"goal": "discover posts"}'

    with (
        patch(
            "app.services.ai.rag_agent.decide_structured_plan",
            return_value=StructuredPlanDecision(use_plan=True, reason="test"),
        ),
        patch(
            "app.services.ai.rag_agent.compose_retrieval_plan",
            side_effect=_compose_side_effect,
        ),
        patch(
            "app.services.ai.rag_agent.tool_list_posts",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="id=3 status=published"),
        ),
        patch(
            "app.services.ai.rag_agent.tool_open_post",
            new_callable=AsyncMock,
            return_value=ToolOutcome(summary="opened post 3"),
        ) as open_mock,
        patch(
            "app.services.ai.rag_stop_evaluator.evaluate_stop",
            return_value=StopVerdict(allowed=True, reason="context_present"),
        ),
        patch("app.services.ai.llm.complete_chat_completion", new_callable=AsyncMock) as llm_mock,
    ):
        result = await run_agentic_loop(
            state=state,
            user_text="есть приветственный пост?",
            seed_ref=None,
            hints=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=4,
            plan_context=L2PlanContext(planning_mode="auto", l1_results=[]),
        )

    open_mock.assert_awaited_once_with(state, post_id="3")
    llm_mock.assert_not_awaited()
    assert result.stopped_reason == "plan_complete"


@pytest.mark.asyncio
async def test_run_agentic_loop_replans_on_plan_alignment() -> None:
    from app.services.ai.rag import NODE_NOTE_CHUNK

    state = _state()
    l1_results = [
        {
            "node_type": NODE_NOTE_CHUNK,
            "post_id": "721c63fe",
            "note_id": "n1",
            "chunk_text": "Варианты изображений",
            "similarity": 0.55,
        }
    ]
    misaligned_plan = RetrievalPlan(
        goal="найти приветственный пост",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe"},
                purpose="из L1 note",
            ),
        ],
    )
    aligned_plan = RetrievalPlan(
        goal="найти приветственный пост",
        steps=[
            RetrievalPlanStep(
                tool="SearchNodes",
                args={"query": "приветственный пост", "node_types": ["post_text"]},
                purpose="discovery",
            ),
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "3"},
                purpose="открыть welcome",
            ),
        ],
    )

    async def _compose_side_effect(**kwargs: object) -> tuple[RetrievalPlan, str]:
        if kwargs.get("transcript"):
            return aligned_plan, '{"goal": "aligned"}'
        return misaligned_plan, '{"goal": "misaligned"}'

    open_mock = AsyncMock(return_value=ToolOutcome(summary="opened post 3"))
    search_mock = AsyncMock(return_value=ToolOutcome(summary="found post 3"))

    with (
        patch(
            "app.services.ai.rag_agent.decide_structured_plan",
            return_value=StructuredPlanDecision(use_plan=True, reason="test"),
        ),
        patch(
            "app.services.ai.rag_agent.compose_retrieval_plan",
            side_effect=_compose_side_effect,
        ),
        patch(
            "app.services.ai.rag_agent.tool_open_post",
            open_mock,
        ),
        patch(
            "app.services.ai.rag_agent.tool_search_nodes",
            search_mock,
        ),
        patch(
            "app.services.ai.rag_stop_evaluator.evaluate_stop",
            return_value=StopVerdict(allowed=True, reason="target_post_bound"),
        ),
        patch("app.services.ai.llm.complete_chat_completion", new_callable=AsyncMock) as llm_mock,
        patch("app.services.ai.rag_agent.trace_step") as trace_mock,
    ):
        result = await run_agentic_loop(
            state=state,
            user_text="есть приветственный пост в серии?",
            seed_ref=None,
            hints=[],
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
            max_steps=4,
            plan_context=L2PlanContext(planning_mode="auto", l1_results=l1_results),
        )

    open_mock.assert_awaited_once_with(state, post_id="3")
    assert search_mock.await_count >= 1
    llm_mock.assert_not_awaited()
    assert result.stopped_reason == "plan_complete"
    assert state.resolved_target_post_id == "3"
    align_calls = [
        call for call in trace_mock.call_args_list if call.args[0] == "7. rag.L2.plan_align"
    ]
    assert align_calls
    assert any("aligned=False" in str(call.args[1]) for call in align_calls)

