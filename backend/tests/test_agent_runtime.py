"""Agent runtime API tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import GlobalChat, GlobalNote, Post
from app.db.resolve import get_owned_post
from app.main import app
from app.services.agent.runtime.executor import (
    _persist_turn_memory,
    execute_agent_run,
    resume_agent_graph,
)
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run
from app.services.ai.providers import ProviderSpec
from tests.conftest import TestSessionLocal, sample_global_chat, sample_post


def _finish_post_research(post_id: str) -> str:
    return (
        '{"tool":"FinishRetrieval","args":{"status":"ready","evidence_ids":'
        f'["/post/{post_id}/"]}}}}'
    )


def _scripted_researched_terminal(
    *,
    route_response: str,
    research_response: str,
    terminal_response: str | None,
):
    async def respond(**kwargs):
        system = str((kwargs.get("messages") or [{}])[0].get("content") or "")
        if "единственный WorkspaceAgent" in system:
            return route_response
        if "research-агент workspace" in system or "bounded workspace research planner" in system:
            return research_response
        if terminal_response is not None:
            return terminal_response
        raise AssertionError(f"Unexpected terminal LLM call: {system[:80]}")

    return respond


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
async def test_event_stream_terminates_on_interrupted_run(
    writer_auth_headers: dict[str, str], writer_user, monkeypatch,
) -> None:
    """Regression for chats 2323c4e4 / d8a4b47d: an interrupted run (paused on a
    HITL proposal) must CLOSE the SSE stream. The client only calls refresh()
    — which loads current_interrupt and renders the approval card — after the
    stream closes, so a stream that stays open on "interrupted" leaves the user
    waiting forever despite a valid proposal already sitting in the run."""
    import asyncio

    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/runs/",
            json={"threadId": "sse-interrupt", "scope": "global", "chatId": "gc-sse"},
            headers=writer_auth_headers,
        )
        run_id = created.json()["id"]

        async with TestSessionLocal() as session:
            run = await event_service.get_run(
                session, user_id=writer_user.id, run_id=uuid.UUID(run_id)
            )
            await event_service.update_run_status(
                session, run, status="interrupted",
                current_interrupt={"type": "action_proposal", "proposal": {"command": "edit_post"}},
            )
            await session.commit()

        # Must complete quickly (generator polls every 0.5s, breaks on
        # interrupted). Before the fix this hung until the wait_for timeout.
        async def _read_stream() -> None:
            async with client.stream(
                "GET", f"/api/v1/ai/runs/{run_id}/events/", headers=writer_auth_headers
            ) as resp:
                async for _ in resp.aiter_bytes():
                    pass

        await asyncio.wait_for(_read_stream(), timeout=5.0)


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
async def test_rebuild_runtime_context_targets_latest_created_note(
    writer_user,
) -> None:
    """Regression for chat 67122906: the latest note was indexed before the
    request, but the router used finish and later opened an older semantic hit."""
    chat_id = str(uuid.uuid4())
    note_id = uuid.uuid4()
    history = [
        {"role": "user", "text": "Я создал заметку по этой теме. Что дальше?"},
        {"role": "ai", "text": "Посмотрю."},
        {"role": "user", "text": "Посмотри на эту заметку и скажи конкретно"},
    ]
    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": history},
            )
        )
        session.add(
            GlobalNote(
                id=note_id,
                user_id=writer_user.id,
                data={
                    "id": str(note_id),
                    "title": "Интерактивная пространственная система",
                    "body": "Три слоя системы.",
                },
            )
        )
        await session.commit()
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="recent-note-contract",
            scope="global",
            chat_id=chat_id,
        )

        context = await rebuild_runtime_context_for_run(
            session,
            run,
            "Посмотри на эту заметку и скажи конкретно",
        )

    # The simplified runtime leaves anaphoric wording for the planner; it no
    # longer promotes the latest note to an implicit DB target.
    assert context.turn_contract["corpus"] == "workspace"
    assert not context.turn_contract.get("target_contract", {}).get("targets")
    assert context.turn_contract["target"] is None
    assert context.turn_contract["requires_workspace"] is True


@pytest.mark.asyncio
async def test_completed_run_persists_full_artifact_to_dialog_ledger(
    writer_user,
) -> None:
    from app.services.ai.rag_dialog_ledger import load_ledger

    chat_id = str(uuid.uuid4())
    draft = "Заголовок\n\n" + ("Полный текст поста. " * 80)
    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id="persist-artifact",
            scope="global",
            chat_id=chat_id,
        )
        context = await rebuild_runtime_context_for_run(session, run, "Напиши пост")
        context.turn_contract = {"output": {"kind": "post_draft"}}
        final_state = {
            "user_text": "Напиши пост",
            "answer_text": draft,
            "evidence_ids": [],
            "evidence_records": {},
            "turn_contract": context.turn_contract,
        }
        await _persist_turn_memory(
            session,
            run=run,
            runtime_context=context,
            final_state=final_state,
        )
        # A resume/retry of the same run is idempotent.
        await _persist_turn_memory(
            session,
            run=run,
            runtime_context=context,
            final_state=final_state,
        )
        await session.commit()
        ledger = await load_ledger(
            session,
            user_id=writer_user.id,
            chat_key=context.ledger_key,
        )

    assert len(ledger) == 1
    artifact = next(entity for entity in ledger[0].entities if entity.entity_type == "post_draft")
    assert artifact.content == draft.strip()


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
async def test_rebuild_runtime_context_loads_last_proposed_post_html(
    writer_user,
) -> None:
    """Regression for chat 2b9447dd: dialog_context only carries display text
    ("Предложенное действие отклонено."), dropping what edit_post actually
    proposed — so a follow-up like "сделай ЕЁ через пробел" had nothing to
    resolve against. RuntimeContext.last_proposed_post_html must recover the
    proposed body from history (regardless of approve/reject) separately.
    """
    post_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    post_data = {
        **sample_post(post_id),
        "chats": [
            {
                "id": chat_id,
                "history": [
                    {"role": "user", "text": "Добавь цифру 3 в конце этого поста"},
                    {
                        "role": "ai",
                        "text": "Предложенное действие отклонено.",
                        "proposal": {
                            "id": "p1",
                            "command": "edit_post",
                            "preview": {"patch": {"textHtml": "Текст поста.3"}},
                        },
                        "proposalDecision": "reject",
                    },
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
            thread_id="last-proposed-test",
            scope="post",
            post_id=post_id,
            post_chat_id=chat_id,
        )

        context = await rebuild_runtime_context_for_run(
            session, run, "Сделай ее через пробел"
        )

    assert context.last_proposed_post_html == "Текст поста.3"
    # Display text is what dialog_context carries — the proposed body must
    # NOT already be sitting there under a different key.
    assert "Текст поста.3" not in context.dialog_context


@pytest.mark.asyncio
async def test_rebuild_runtime_context_resolves_legacy_numeric_post_id(
    writer_user,
) -> None:
    """Regression for chat 61af02c7: older posts store data['id'] as a small
    integer ("3") while the DB PK is a UUID. run.post_id carries that legacy
    "3", so the old uuid.UUID(run.post_id)-only lookup raised ValueError and
    left post_data=None — edit_post then produced an empty payload and no
    editable proposal ever reached the user. rebuild must resolve by data['id']
    fallback, matching the mutation executor's get_owned_post."""
    pk = uuid.uuid4()
    legacy_id = "3"
    post_data = {**sample_post(legacy_id, text="Привет 👋"), "id": legacy_id}

    async with TestSessionLocal() as session:
        session.add(Post(id=pk, user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="legacy-post-id",
            scope="post", post_id=legacy_id,
        )
        context = await rebuild_runtime_context_for_run(session, run, "Добавь цифру 2")

    assert context.post_data is not None
    assert context.post_data.get("text") == "Привет 👋"
    assert context.post_data.get("id") == legacy_id


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
    metrics_events = [evt for evt in events if evt.event_type == "run_metrics"]
    assert len(metrics_events) == 1
    metrics = metrics_events[0].payload
    assert metrics["llm_calls"] == 4
    assert metrics["prompt_tokens"] > 0
    assert metrics["completion_tokens"] > 0
    assert metrics["total_tokens"] == metrics["prompt_tokens"] + metrics["completion_tokens"]
    assert metrics["token_method"] == "chars_div_4_estimate"
    assert [call["phase"] for call in metrics["calls"]] == [
        "bootstrap.classifier",
        "research.planner",
        "research.planner",
        "answer.generate",
    ]


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
async def test_execute_agent_run_emits_workspace_step_for_finish(
    writer_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workspace classifier's decision must surface as a "workspace_step"
    event even on the non-research paths (here: "finish"). Without it the
    activity indicator has no step to show and sits on the default label the
    whole run — the "just hangs on Работаю над ответом…" bug."""
    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="workspace-step-test", scope="global",
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Привет, что умеешь?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"

        # Conversational finish now skips workspace discovery.
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response='{"type": "finish"}',
                research_response=(
                    '{"tool":"FinishRetrieval","args":'
                    '{"status":"ready","evidence_ids":[]}}'
                ),
                terminal_response=(
                    '{"answer": "Помогаю с постами и заметками.", "claims": []}'
                ),
            ),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Привет, что умеешь?", runtime_context=ctx,
            )
            await session.commit()

        events = await event_service.list_events(session, run_id=run.id)

    workspace_events = [evt for evt in events if evt.event_type == "workspace_step"]
    assert len(workspace_events) == 1
    assert workspace_events[0].payload["tool"] == "finish"
    assert not [evt for evt in events if evt.event_type == "planner_step"]


@pytest.mark.asyncio
async def test_execute_agent_run_streams_partial_answer_events(
    writer_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """answer_node streams the reply token-by-token; the executor must surface
    growing partial "answer" events (marked partial=True) as the tokens arrive,
    then a terminal "answer" event with the full text + claims. This is what
    makes the chat render the reply progressively instead of all at once."""
    from app.services.agent.runtime import events as event_service

    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    # The answer JSON, chunked into tokens the way a provider streams it.
    answer_tokens = [
        '{"answer":"',
        "Срок ",
        "— ию",
        "ль ме",
        "сяц.",
        '","claims":[]}',
    ]

    async def _fake_stream(**kwargs):
        for tok in answer_tokens:
            yield tok

    async with TestSessionLocal() as session:
        run, _ = await start_run(
            session, user=writer_user, thread_id="stream-answer-test", scope="global",
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Когда запуск?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"

        # Classifier + planner still go through complete_chat_completion; only
        # the answer step streams. Patch the stream directly (overrides the
        # conftest shim) to feed real token chunks.
        with (
            patch(
                "app.services.ai.llm.complete_chat_completion",
                new_callable=AsyncMock,
                side_effect=_scripted_researched_terminal(
                    route_response='{"type": "finish"}',
                    research_response=(
                        '{"tool":"FinishRetrieval","args":'
                        '{"status":"ready","evidence_ids":[]}}'
                    ),
                    terminal_response=None,
                ),
            ),
            patch("app.services.ai.llm.stream_chat_completion_tokens", _fake_stream),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Когда запуск?", runtime_context=ctx,
            )
            await session.commit()

        events = await event_service.list_events(session, run_id=run.id)

    answer_events = [evt for evt in events if evt.event_type == "answer"]
    # At least one partial + the terminal event.
    assert len(answer_events) >= 2
    partials = [e for e in answer_events if e.payload.get("partial")]
    terminal = [e for e in answer_events if not e.payload.get("partial")]
    assert partials, "expected at least one partial answer event"
    assert len(terminal) == 1
    # Partials grow monotonically and are prefixes of the final answer.
    texts = [e.payload["text"] for e in partials]
    assert texts == sorted(texts, key=len)
    final_text = terminal[0].payload["text"]
    assert final_text == "Срок — июль месяц."
    for t in texts:
        assert final_text.startswith(t)


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

        # Three LLM calls now: (1) router classifies as edit_post, (2) bounded
        # research finishes over the opened post, and (3) a dedicated,
        # properly-budgeted call produces the full edited text. The router
        # echoing "<полный новый текст поста>" into a 600-token reply was the
        # original bug (chat 25e2cac3), so the split is the fix, not a crutch.
        route_response = '{"type": "post_proposal", "command": "edit_post", "payload": {}}'
        # The text generator returns the raw post body, not JSON — post bodies
        # are multi-line and JSON-wrapping them broke json.loads (chat 479a2210).
        edit_response = "Запуск июля в часа."
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response=edit_response,
            ),
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
        # post_id is authoritative from ctx.post_data, never the model output.
        assert proposal.get("payload", {}).get("post_id") == post_id
        assert proposal.get("payload", {}).get("patch", {}).get("text") == "Запуск июля в часа."


@pytest.mark.asyncio
async def test_publish_post_request_fills_post_id_when_router_omits_it(
    writer_user, monkeypatch,
) -> None:
    """Regression (chat b0d11b7c): "Опубликуй этот пост" produced an
    action_proposal with payload={} — the router classifier has no reliable
    memory of which post_id it was shown, and unlike edit_post there was no
    deterministic fill-in for publish_post/schedule_post/cancel_schedule/
    delete_post/restore_post. The confirmation card then rendered "Пост
    пустой" (buildProposalPostPreview has nothing to look post_id up from).
    ctx.post_data is the same authoritative source edit_post already trusts
    over the model output."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    post_data = sample_post(post_id, text="Готовый пост.")

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="publish-post-e2e",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Опубликуй этот пост")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        route_response = '{"type": "post_proposal", "command": "publish_post", "payload": {}}'
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response=None,
            ),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Опубликуй этот пост", runtime_context=ctx,
            )
            await session.commit()

        await session.refresh(run)
        assert run.current_interrupt is not None
        proposal = run.current_interrupt.get("proposal") or {}
        assert proposal.get("command") == "publish_post"
        assert proposal.get("payload", {}).get("post_id") == post_id


@pytest.mark.asyncio
async def test_edit_post_generates_multiline_text_without_json_wrapping(
    writer_user, monkeypatch,
) -> None:
    """Regression for chat 479a2210: real post bodies are multi-line (newlines,
    emoji, quotes). The generator used to demand JSON {"text":"..."} and the
    model emitted literal newlines inside the string, so json.loads rejected
    every real post and edit_post reported "не удалось сгенерировать". The
    generator now takes the raw completion as the body — no JSON round-trip."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    original = "Привет 👋\n\nЭто канал о TG.\nСтрочка «в кавычках»."
    post_data = sample_post(post_id, text=original)

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="edit-multiline",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Добавь цифру 2 в конце")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        edited = original + "2"
        route_response = '{"type": "post_proposal", "command": "edit_post", "payload": {}}'
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response=edited,
            ),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Добавь цифру 2 в конце", runtime_context=ctx,
            )
            await session.commit()

        await session.refresh(run)
        assert run.current_interrupt is not None
        proposal = run.current_interrupt.get("proposal") or {}
        assert proposal.get("payload", {}).get("patch", {}).get("text") == edited


@pytest.mark.asyncio
async def test_edit_post_clears_stale_texthtml(writer_user, monkeypatch) -> None:
    """Regression for chat 49a569c8: posts render textHtml in preference to
    text. When the model's HTML response carries no real formatting (plain
    text with no tags), stored_fields_from_platform_html must derive
    textHtml=None so the post doesn't keep showing the old bold wording, and
    the executor must treat that None as "delete the field"."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    post_data = {
        **sample_post(post_id, text="Привет"),
        "textHtml": "<strong>Привет</strong>",
    }

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="edit-clears-html",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Добавь цифру 2")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        route_response = '{"type": "post_proposal", "command": "edit_post", "payload": {}}'
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response="Привет2",
            ),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Добавь цифру 2", runtime_context=ctx,
            )
            await session.commit()

        proposal = run.current_interrupt.get("proposal") or {}
        patch_payload = proposal.get("payload", {}).get("patch", {})
        assert patch_payload.get("text") == "Привет2"
        # textHtml explicitly cleared so the card/post won't show the old bold form.
        assert "textHtml" in patch_payload and patch_payload["textHtml"] is None

        # And the executor actually drops the field (not stores None).
        from app.services.posts.commands import execute_post_command

        await execute_post_command(
            session, user=writer_user, command="edit_post",
            payload=proposal["payload"], resource_version=None,
        )
        refreshed = await get_owned_post(session, writer_user.id, post_id)
        assert refreshed.data.get("text") == "Привет2"
        assert "textHtml" not in refreshed.data


@pytest.mark.asyncio
async def test_edit_post_preserves_formatting_and_custom_emoji(
    writer_user, monkeypatch,
) -> None:
    """The agent is fed the post's existing textHtml (not just plain text) so
    it can preserve inline formatting and Telegram custom emoji through an
    edit, and may apply new formatting of its own. Verifies both: an existing
    <tg-emoji> survives untouched, and the model's own <strong> comes through
    as real formatting in the stored textHtml."""
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)

    post_id = str(uuid.uuid4())
    original_html = 'Привет <tg-emoji emoji-id="5789">⭐</tg-emoji> мир'
    post_data = {
        **sample_post(post_id, text="Привет ⭐ мир"),
        "textHtml": original_html,
    }

    async with TestSessionLocal() as session:
        session.add(Post(id=uuid.UUID(post_id), user_id=writer_user.id, data=post_data))
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id="edit-preserve-formatting",
            scope="post", post_id=post_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Выдели 'мир' жирным")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        monkeypatch.setattr(ctx.settings, "agent_actions_enabled", True)

        # Model echoes the custom emoji verbatim and adds its own <strong>.
        model_html = 'Привет <tg-emoji emoji-id="5789">⭐</tg-emoji> <strong>мир</strong>'
        route_response = '{"type": "post_proposal", "command": "edit_post", "payload": {}}'
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response=model_html,
            ),
        ):
            await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Выдели 'мир' жирным", runtime_context=ctx,
            )
            await session.commit()

        proposal = run.current_interrupt.get("proposal") or {}
        patch_payload = proposal.get("payload", {}).get("patch", {})
        assert patch_payload.get("text") == "Привет ⭐ мир"
        assert 'tg-emoji emoji-id="5789"' in (patch_payload.get("textHtml") or "")
        assert "<strong>мир</strong>" in (patch_payload.get("textHtml") or "")

        from app.services.posts.commands import execute_post_command

        await execute_post_command(
            session, user=writer_user, command="edit_post",
            payload=proposal["payload"], resource_version=None,
        )
        refreshed = await get_owned_post(session, writer_user.id, post_id)
        assert refreshed.data.get("text") == "Привет ⭐ мир"
        assert 'tg-emoji emoji-id="5789"' in refreshed.data.get("textHtml", "")


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

        # Router classifies, research opens the post, then a dedicated call
        # generates the edited text.
        # build_action_proposal_node.
        route_response = '{"type": "post_proposal", "command": "edit_post", "payload": {}}'
        edit_response = "Запуск июля в часа."
        with patch(
            "app.services.ai.llm.complete_chat_completion",
            new_callable=AsyncMock,
            side_effect=_scripted_researched_terminal(
                route_response=route_response,
                research_response=_finish_post_research(post_id),
                terminal_response=edit_response,
            ),
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
