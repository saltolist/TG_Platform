"""Agent runtime API tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import GlobalChat, Post
from app.main import app
from app.services.agent.runtime.executor import execute_agent_run, resume_agent_graph
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run
from app.services.ai.providers import ProviderSpec
from tests.conftest import TestSessionLocal, sample_global_chat, sample_post


@pytest.mark.asyncio
async def test_create_and_get_agent_run(writer_auth_headers: dict[str, str]) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"threadId": "gc-test", "scope": "global", "chatId": "gc1"},
            headers=writer_auth_headers,
        )
        assert created.status_code == 201
        run_id = created.json()["id"]

        fetched = await client.get(f"/api/v1/ai/runs/{run_id}/", headers=writer_auth_headers)
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "running"
        assert body["thread_id"] == "gc-test"


@pytest.mark.asyncio
async def test_agent_run_not_found(writer_auth_headers: dict[str, str]) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/ai/runs/{uuid.uuid4()}/", headers=writer_auth_headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_executes_with_postgres_checkpoint(
    writer_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The API writes the run to the test DB, so the durable executor must read
    # from the same session factory. Without this it silently uses the prod
    # factory, never finds the run, and returns early leaving status="running".
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr("app.tasks.agent_runs.async_session_factory", TestSessionLocal)
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={
                "threadId": "durable-test",
                "scope": "global",
                "chatId": "gc1",
            },
            headers=writer_auth_headers,
        )
        assert created.status_code == 201
        run_id = created.json()["id"]

        from app.tasks.agent_runs import _execute_agent_run

        await _execute_agent_run(uuid.UUID(run_id), "Собери доступный контекст")

        fetched = await client.get(
            f"/api/v1/ai/runs/{run_id}/",
            headers=writer_auth_headers,
        )
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["status"] == "completed"
        assert body["snapshot"]["run_id"] == run_id


@pytest.mark.asyncio
async def test_rebuild_runtime_context_loads_dialog_context_from_chat_history(
    writer_user,
) -> None:
    """Cross-turn deixis (agent-runtime-sprints §2.1): a run's RuntimeContext
    carries prior chat turns as dialog_context, sourced the same way the
    legacy reply path does (GlobalChat.data.history).
    """
    chat_id = str(uuid.uuid4())
    seeded_history = [
        {"role": "user", "text": "Расскажи про пост про скидки"},
        {"role": "ai", "text": "Пост про скидки собрал 500 просмотров"},
    ]

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": seeded_history},
            )
        )
        await session.commit()

        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="dialog-ctx-test",
            scope="global",
            chat_id=chat_id,
        )

        context = await rebuild_runtime_context_for_run(
            session, run, "А что по второму посту?"
        )

    assert "Пост про скидки собрал 500 просмотров" in context.dialog_context
    assert "Расскажи про пост про скидки" in context.dialog_context


@pytest.mark.asyncio
async def test_rebuild_runtime_context_empty_dialog_context_without_chat(
    writer_user,
) -> None:
    """No chat_id / unknown chat → empty dialog_context, not an error (memory
    is best-effort, never a hard dependency for the run)."""
    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="dialog-ctx-empty-test",
            scope="global",
        )

        context = await rebuild_runtime_context_for_run(session, run, "Привет")

    assert context.dialog_context == ""


@pytest.mark.asyncio
async def test_rebuild_runtime_context_post_scope_uses_post_chat_id(
    writer_user,
) -> None:
    """post_chat_id (mirrors AiReplyRequest.post_chat_id) disambiguates which
    of a post's embedded chats a run belongs to — a plain chat_id match or
    "last chat" fallback would silently pick the wrong one when a post has
    more than one chat (agent-runtime-sprints §2.1 open question, resolved).
    """
    post_id = str(uuid.uuid4())
    wrong_chat_id = str(uuid.uuid4())
    right_chat_id = str(uuid.uuid4())
    post_data = {
        **sample_post(post_id),
        "chats": [
            {
                "id": wrong_chat_id,
                "history": [
                    {"role": "user", "text": "Что по картинке?"},
                    {"role": "ai", "text": "Про другой чат поста"},
                ],
            },
            {
                "id": right_chat_id,
                "history": [
                    {"role": "user", "text": "Что по тексту?"},
                    {"role": "ai", "text": "Нужный чат поста про текст"},
                ],
            },
        ],
    }

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="post-chat-id-test",
            scope="post",
            post_id=post_id,
            post_chat_id=right_chat_id,
        )

        context = await rebuild_runtime_context_for_run(session, run, "Что там было?")

    assert "Нужный чат поста про текст" in context.dialog_context
    assert "другой чат" not in context.dialog_context


@pytest.mark.asyncio
async def test_agent_referent_recall_reopens_note_via_dialog_context(
    writer_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 2 §2.2 (no ledger/resolver for the agent path — see
    agent-runtime-remaining.md §2): the planner sees a prior turn's note id
    as plain text in dialog_context and re-calls OpenNote with that same
    natural id, exactly like any other tool-loop step. No live LLM was
    reachable in this session (AgentRouter outage), so the LLM is scripted —
    this still exercises every real wiring hop end-to-end: dialog_context ->
    planner prompt -> tool re-call -> evidence -> grounded, non-refusal
    answer (agent-runtime-sprints §2.1/§2.2 exit criteria).
    """
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    chat_id = str(uuid.uuid4())
    seeded_history = [
        {"role": "user", "text": "Открой заметку n1"},
        {"role": "ai", "text": "Открыл заметку note:n1 — там план запуска на июль."},
    ]

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": seeded_history},
            )
        )
        await session.commit()

        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="referent-recall-test",
            scope="global",
            chat_id=chat_id,
        )

        runtime_context = await rebuild_runtime_context_for_run(
            session, run, "А что там было по срокам?"
        )
        # Sanity check before wiring the scripted LLM: the referent text from
        # the prior turn must have actually reached dialog_context.
        assert "план запуска" in runtime_context.dialog_context

        runtime_context.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        runtime_context.reasoner_model = "gpt-4o-mini"
        runtime_context.reasoner_api_key = "test-key"

        llm_responses = [
            '{"type": "read"}',
            '{"tool": "OpenNote", "args": {"note_id": "n1"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            (
                '{"answer": "Срок — июль.", "claims": '
                '[{"text": "Срок — июль.", "evidence_ids": ["/note/global/n1/"]}]}'
            ),
        ]

        with (
            patch(
                "app.services.ai.llm.complete_chat_completion",
                new_callable=AsyncMock,
                side_effect=llm_responses,
            ) as mock_llm,
            patch(
                "app.services.ai.rag_tools.get_note_data",
                new_callable=AsyncMock,
                return_value={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []},
            ),
        ):
            final_state = await execute_agent_run(
                session,
                run=run,
                user=writer_user,
                user_text="А что там было по срокам?",
                runtime_context=runtime_context,
            )
            await session.commit()

    assert final_state.get("status") == "completed"
    assert "/note/global/n1/" in (final_state.get("evidence_ids") or [])
    assert "июл" in str(final_state.get("answer_text") or "").lower()

    # The re-call was possible only because the planner's own prompt (not
    # just RuntimeContext) carried the referent text — verify it reached the
    # LLM call that decided to re-open note n1.
    planner_call = mock_llm.await_args_list[1]
    planner_messages = planner_call.kwargs.get("messages") or planner_call.args[0]
    prompt_text = " ".join(str(m.get("content", "")) for m in planner_messages)
    assert "план запуска" in prompt_text


@pytest.mark.asyncio
async def test_execute_agent_run_emits_planner_step_events(
    writer_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agent-runtime-sprints §3.3: every research_planner_node call must
    surface as a "planner_step" agent_event with the full decision shape,
    so the UI can render steps 1..N as the run streams."""
    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="planner-step-sse-test",
            scope="global",
        )
        runtime_context = await rebuild_runtime_context_for_run(
            session, run, "Что в заметке n1?"
        )
        runtime_context.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        runtime_context.reasoner_model = "gpt-4o-mini"
        runtime_context.reasoner_api_key = "test-key"

        llm_responses = [
            '{"type": "read"}',
            (
                '{"observations": [], "reasoning": "нужно найти заметку n1",'
                ' "gap": "note content missing", "tool": "OpenNote",'
                ' "args": {"note_id": "n1"}}'
            ),
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            '{"answer": "Есть данные.", "claims": []}',
        ]
        with (
            patch(
                "app.services.ai.llm.complete_chat_completion",
                new_callable=AsyncMock,
                side_effect=llm_responses,
            ),
            patch(
                "app.services.ai.rag_tools.get_note_data",
                new_callable=AsyncMock,
                return_value={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []},
            ),
        ):
            await execute_agent_run(
                session,
                run=run,
                user=writer_user,
                user_text="Что в заметке n1?",
                runtime_context=runtime_context,
            )
            await session.commit()

        events = await event_service.list_events(session, run_id=run.id)

    # Two research_planner_node calls happen: step 1 decides OpenNote, step 2
    # (after fetching the note) decides FinishRetrieval — each must surface as
    # its own planner_step event, in step order.
    planner_events = [evt for evt in events if evt.event_type == "planner_step"]
    assert len(planner_events) == 2
    first, second = planner_events[0].payload, planner_events[1].payload
    assert first["reasoning"] == "нужно найти заметку n1"
    assert first["gap"] == "note content missing"
    assert first["tool"] == "OpenNote"
    assert first["args"] == {"note_id": "n1"}
    assert first["observations"] == []
    assert second["tool"] == "FinishRetrieval"


@pytest.mark.asyncio
async def test_execute_agent_run_emits_tool_result_events(writer_user, monkeypatch) -> None:
    """Спринт 5: each tool execution must surface as a "tool_result" event
    carrying what the tool returned (summary, error, produced record_ids), so
    the log shows not just the decision but the observation that followed it."""
    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="tool-result-test", scope="global",
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Что в заметке n1?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"

        llm_responses = [
            '{"type": "read"}',
            '{"tool": "OpenNote", "args": {"note_id": "n1"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            '{"answer": "Есть данные.", "claims": []}',
        ]
        with (
            patch("app.services.ai.llm.complete_chat_completion",
                  new_callable=AsyncMock, side_effect=llm_responses),
            patch("app.services.ai.rag_tools.get_note_data", new_callable=AsyncMock,
                  return_value={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []}),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Что в заметке n1?", runtime_context=ctx,
            )
            await session.commit()

        events = await event_service.list_events(session, run_id=run.id)

    # Exactly one real tool call (OpenNote); FinishRetrieval is a planner
    # terminal, not a tool-node execution.
    tool_events = [evt for evt in events if evt.event_type == "tool_result"]
    assert len(tool_events) == 1
    payload = tool_events[0].payload
    assert payload["tool"] == "OpenNote"
    assert payload["error"] is None
    assert "/note/global/n1/" in payload["record_ids"]
    assert payload["step"] >= 0


@pytest.mark.asyncio
async def test_execute_agent_run_marks_deadline_exceeded(writer_user, monkeypatch) -> None:
    """A spent wall-clock budget must terminate the run as failed with an
    explicit deadline_exceeded reason, not a generic crash — and must not
    dial the provider (agent-runtime-sprints §6)."""
    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="deadline-test", scope="global"
        )
        runtime_context = await rebuild_runtime_context_for_run(session, run, "Что там?")
        runtime_context.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        runtime_context.reasoner_model = "gpt-4o-mini"
        runtime_context.reasoner_api_key = "test-key"
        # Zero budget: the very first LLM call (classifier) trips the deadline.
        # settings is a cached singleton — monkeypatch so the negative value is
        # restored and cannot leak into other tests' deadlines.
        monkeypatch.setattr(runtime_context.settings, "rag_agent_deadline_s", -1.0)

        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
        ) as mock_llm:
            with pytest.raises(Exception):
                await execute_agent_run(
                    session,
                    run=run,
                    user=writer_user,
                    user_text="Что там?",
                    runtime_context=runtime_context,
                )
            await session.commit()

        assert mock_llm.await_count == 0, "provider dialed despite spent budget"
        events = await event_service.list_events(session, run_id=run.id)

    failed = [evt for evt in events if evt.event_type == "run_failed"]
    assert failed, "no run_failed event emitted"
    assert failed[-1].payload.get("stopped_reason") == "deadline_exceeded"
    assert run.status == "failed"


def test_record_run_metrics_counts_empty_pack_and_reason() -> None:
    """Спринт 5: run-level counters — empty pack (grounding gap) and terminal
    stopped_reason — move when a run finishes with no evidence."""
    from app.services.agent.runtime.executor import _record_run_metrics
    from app.services.agent.runtime.observability import (
        AGENT_EMPTY_PACK,
        AGENT_STOPPED_REASON,
    )

    empty_before = AGENT_EMPTY_PACK._value.get()
    reason_before = AGENT_STOPPED_REASON.labels("empty_evidence_refusal")._value.get()

    _record_run_metrics(
        {"step_count": 3, "evidence_ids": [], "stopped_reason": "empty_evidence_refusal"}
    )

    assert AGENT_EMPTY_PACK._value.get() == empty_before + 1
    assert (
        AGENT_STOPPED_REASON.labels("empty_evidence_refusal")._value.get()
        == reason_before + 1
    )


def test_record_run_metrics_non_empty_pack_does_not_count_empty() -> None:
    from app.services.agent.runtime.executor import _record_run_metrics
    from app.services.agent.runtime.observability import AGENT_EMPTY_PACK

    empty_before = AGENT_EMPTY_PACK._value.get()
    _record_run_metrics(
        {"step_count": 2, "evidence_ids": ["/note/global/n1/"], "stopped_reason": "ready"}
    )
    assert AGENT_EMPTY_PACK._value.get() == empty_before  # не инкрементился


@pytest.mark.asyncio
async def test_execute_agent_run_logs_trace_when_ai_context_log_enabled(
    writer_user, monkeypatch, caplog,
) -> None:
    """Спринт 5 tracing hail: unlike the legacy AI_CONTEXT_LOG path (process-
    local ContextVar buffer, dead in the Celery worker), this renders from the
    durable agent_events chain — so it works from execute_agent_run directly."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="trace-log-test", scope="global",
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Что в заметке n1?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "ai_context_log", True)

        llm_responses = [
            '{"type": "read"}',
            '{"tool": "OpenNote", "args": {"note_id": "n1"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            '{"answer": "Есть данные.", "claims": []}',
        ]
        with (
            patch("app.services.ai.llm.complete_chat_completion",
                  new_callable=AsyncMock, side_effect=llm_responses),
            patch("app.services.ai.rag_tools.get_note_data", new_callable=AsyncMock,
                  return_value={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []}),
            caplog.at_level("INFO", logger="agent.runtime"),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Что в заметке n1?", runtime_context=ctx,
            )
            await session.commit()

    assert any("AGENT RUN" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_execute_agent_run_skips_trace_log_when_flag_off(
    writer_user, monkeypatch, caplog,
) -> None:
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="trace-log-off-test", scope="global",
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Что в заметке n1?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        assert ctx.settings.ai_context_log is False  # default

        llm_responses = [
            '{"type": "read"}',
            '{"tool": "OpenNote", "args": {"note_id": "n1"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            '{"answer": "Есть данные.", "claims": []}',
        ]
        with (
            patch("app.services.ai.llm.complete_chat_completion",
                  new_callable=AsyncMock, side_effect=llm_responses),
            patch("app.services.ai.rag_tools.get_note_data", new_callable=AsyncMock,
                  return_value={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []}),
            caplog.at_level("INFO", logger="agent.runtime"),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Что в заметке n1?", runtime_context=ctx,
            )
            await session.commit()

    assert not any("AGENT RUN" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_edit_post_request_produces_action_proposal_end_to_end(
    writer_user, monkeypatch,
) -> None:
    """Bug fix regression: "убери цифру 2" in a post chat must produce an
    edit_post ActionProposal (HITL card), not silently fall through to a
    plain text answer — which is what happened when the classifier never saw
    the post's text (agent-runtime-remaining.md tracing/bugfix pass)."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    post_data = sample_post(post_id, text="Запуск 2 июля в 2 часа.")

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="edit-post-e2e",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "убери цифру 2 из текста")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        assert ctx.post_data is not None and ctx.post_data.get("text") == "Запуск 2 июля в 2 часа."

        llm_response = (
            '{"type": "post_proposal", "command": "edit_post", '
            f'"payload": {{"post_id": "{post_id}", '
            '"patch": {"text": "Запуск июля в часа."}}}}'
        )
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock, return_value=llm_response,
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="убери цифру 2 из текста", runtime_context=ctx,
            )
            await session.commit()

        await session.refresh(run)
        assert run.current_interrupt is not None
        assert run.current_interrupt.get("type") == "action_proposal"
        proposal = run.current_interrupt.get("proposal") or {}
        assert proposal.get("command") == "edit_post"
        assert proposal.get("payload", {}).get("patch", {}).get("text") == "Запуск июля в часа."


@pytest.mark.asyncio
async def test_resume_agent_graph_after_action_proposal_completes(
    writer_user, monkeypatch,
) -> None:
    """Regression for the v1->v2 stream migration: resume_agent_graph must
    reach status="completed" after an approve, using the same version="v2"
    "interrupts" field executor.py now reads from (agent-runtime-remaining.md
    v1/v2 follow-up). No prior test exercised this path at all."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    post_data = sample_post(post_id, text="Запуск 2 июля в 2 часа.")

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="edit-post-resume",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "убери цифру 2 из текста")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        llm_response = (
            '{"type": "post_proposal", "command": "edit_post", '
            f'"payload": {{"post_id": "{post_id}", '
            '"patch": {"text": "Запуск июля в часа."}}}}'
        )
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock, return_value=llm_response,
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="убери цифру 2 из текста", runtime_context=ctx,
            )
            await session.commit()

        await session.refresh(run)
        proposal = run.current_interrupt.get("proposal") or {}
        assert run.status == "interrupted"

        await resume_agent_graph(
            session,
            run=run,
            resume_value={
                "decision": "approve",
                "proposal_id": proposal.get("id"),
                "payload_hash": proposal.get("payload_hash"),
                "applied": {"post_id": post_id, "status": "published"},
            },
            runtime_context=ctx,
        )
        await session.commit()

        await session.refresh(run)
        assert run.status == "completed"
        assert run.current_interrupt is None
        assert "статус: published" in (run.snapshot.get("answer_text") or "")
