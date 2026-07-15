"""End-to-end: a listing question is grounded, not refused (§1.4 tail).

The "first-timer" scenarios that motivated this: nobody types "ListPosts" —
they ask "сколько у меня постов про запуск?", "что у меня в работе?", "я не
дублирую посты про доставку?". The listing tool answers those, but until its
output became first-class evidence the answer guard saw an empty pack and
refused despite the data existing. This drives the full execute_agent_run graph
with a scripted planner that cites the listing record, and asserts the answer is
grounded (claims ⊆ evidence, no refusal).
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import GlobalChat, Post
from app.services.agent.runtime.executor import execute_agent_run
from app.services.agent.runtime.graders import grade_run
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run
from app.services.ai.providers import ProviderSpec
from tests.conftest import TestSessionLocal, sample_global_chat, sample_post


@pytest.mark.asyncio
async def test_listing_question_is_grounded_not_refused(writer_user, monkeypatch) -> None:
    monkeypatch.setattr("app.db.session.async_session_factory", TestSessionLocal)
    chat_id = str(uuid.uuid4())
    post_id = str(uuid.uuid4())

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": []},
            )
        )
        session.add(
            Post(
                id=uuid.UUID(post_id),
                user_id=writer_user.id,
                data={**sample_post(post_id, text="Запуск продукта в июле"), "id": post_id},
            )
        )
        await session.commit()

        run, _ = await start_run(
            session, user=writer_user, thread_id=f"listing-{uuid.uuid4()}",
            scope="global", chat_id=chat_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, "Сколько у меня постов про запуск?")
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"

        listing_path = "/posts/q:запуск/"
        script = [
            '{"type": "read"}',
            '{"tool": "ListPosts", "args": {"query": "запуск"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                f'{{"status": "ready", "evidence_ids": ["{listing_path}"]}}}}'
            ),
            (
                '{"answer": "У тебя один пост про запуск.", "claims": '
                f'[{{"text": "У тебя один пост про запуск.", "evidence_ids": ["{listing_path}"]}}]}}'
            ),
        ]
        with ExitStack() as stack:
            stack.enter_context(
                patch("app.services.ai.llm.complete_chat_completion",
                      new_callable=AsyncMock, side_effect=script)
            )
            final_state = await execute_agent_run(
                session, run=run, user=writer_user,
                user_text="Сколько у меня постов про запуск?", runtime_context=ctx,
            )
            await session.commit()

    # The listing grounded the answer: not a refusal, and the cited listing path
    # actually made it into evidence.
    assert final_state.get("status") == "completed"
    assert final_state.get("stopped_reason") != "empty_evidence_refusal"
    assert listing_path in (final_state.get("evidence_ids") or [])
    assert final_state.get("answer_text")
    report = grade_run(final_state, must_call=["ListPosts"])
    assert report.ok, report.failures
