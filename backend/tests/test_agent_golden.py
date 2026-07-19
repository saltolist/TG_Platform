"""Executable golden scenarios (agent-runtime-sprints §4).

Deterministic merge gate: each scenario runs the FULL `execute_agent_run`
graph with a scripted LLM (`complete_chat_completion` side_effect) — no live
model — and asserts the outcome through `grade_run`, the same deterministic
grader library used everywhere else. This is the executable gate the canon
asks for; `pytest -m golden` is its distinct red/green signal in CI.

Only the 3 critical scenarios are executable here (deixis, notes-with-content,
empty-pack refusal). The other 16 catalog docs remain doc-only — see
`golden_runner.EXECUTABLE_SCENARIOS` and `test_golden_catalog`.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import GlobalChat
from app.services.agent.runtime.executor import execute_agent_run
from app.services.agent.runtime.graders import grade_run
from app.services.agent.runtime.runs import rebuild_runtime_context_for_run, start_run
from app.services.ai.providers import ProviderSpec
from tests.conftest import TestSessionLocal, sample_global_chat


async def _run_golden(
    writer_user,
    *,
    history: list[dict[str, str]],
    user_text: str,
    llm_script: list[str],
    note_data: dict | None = None,
    search_results: list | None = None,
) -> dict:
    """Drive one scripted end-to-end run and return its final graph state.

    Mirrors the wiring of the referent-recall test, parameterised so each
    golden supplies only its own history, prompt, LLM script and tool data.
    """
    chat_id = str(uuid.uuid4())
    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": history},
            )
        )
        await session.commit()
        run, _ = await start_run(
            session,
            user=writer_user,
            thread_id=f"golden-{uuid.uuid4()}",
            scope="global",
            chat_id=chat_id,
        )
        ctx = await rebuild_runtime_context_for_run(session, run, user_text)
        ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
        ctx.reasoner_model = "gpt-4o-mini"
        ctx.reasoner_api_key = "test-key"
        if search_results is not None:
            # SearchNodes embeds the query before retrieve_for_chat runs — avoid
            # loading the real (slow, model-download-dependent) local backend
            # in what's meant to be a fast, deterministic merge gate.
            ctx.embedding_backend = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.ai.llm.complete_chat_completion",
                    new_callable=AsyncMock,
                    side_effect=llm_script,
                )
            )
            if note_data is not None:
                stack.enter_context(
                    patch(
                        "app.services.ai.rag_tools.get_note_data",
                        new_callable=AsyncMock,
                        return_value=note_data,
                    )
                )
            if search_results is not None:
                stack.enter_context(
                    patch(
                        "app.services.ai.rag_tools.retrieve_for_chat",
                        new_callable=AsyncMock,
                        return_value=search_results,
                    )
                )
            final_state = await execute_agent_run(
                session,
                run=run,
                user=writer_user,
                user_text=user_text,
                runtime_context=ctx,
            )
            await session.commit()
    return final_state


@pytest.mark.golden
@pytest.mark.asyncio
async def test_golden_multi_turn_deixis(writer_user) -> None:
    """Scenario 13: a prior turn's note referent, resolved via dialog_context,
    is re-opened and grounds a non-refusal answer. Trajectory must reach
    OpenNote (agent-runtime-sprints §2.2 / DoD)."""
    final_state = await _run_golden(
        writer_user,
        history=[
            {"role": "user", "text": "Открой заметку n1"},
            {"role": "ai", "text": "Открыл заметку note:n1 — там план запуска на июль."},
        ],
        user_text="А что там было по срокам?",
        llm_script=[
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
        ],
        note_data={"id": "n1", "title": "План", "body": "Запуск в июле.", "files": []},
    )

    assert final_state.get("status") == "completed"
    assert "/note/global/n1/" in (final_state.get("evidence_ids") or [])
    report = grade_run(final_state, must_call=["OpenNote"])
    assert report.ok, report.failures


@pytest.mark.golden
@pytest.mark.asyncio
async def test_golden_notes_with_content(writer_user) -> None:
    """Scenario 06: a notes-content question must actually read the note
    (OpenNote in trajectory), and the answer's claims must stay a subset of
    collected evidence (agent-runtime-sprints §1.2/§1.3 + DoD notes-content)."""
    final_state = await _run_golden(
        writer_user,
        history=[],
        user_text="Что написано в заметке n1?",
        llm_script=[
            '{"type": "read"}',
            '{"tool": "OpenNote", "args": {"note_id": "n1"}}',
            (
                '{"tool": "FinishRetrieval", "args": '
                '{"status": "ready", "evidence_ids": ["/note/global/n1/"]}}'
            ),
            (
                '{"answer": "В заметке план запуска на июль.", "claims": '
                '[{"text": "В заметке план запуска на июль.", '
                '"evidence_ids": ["/note/global/n1/"]}]}'
            ),
        ],
        note_data={
            "id": "n1",
            "title": "План",
            "body": "План запуска на июль.",
            "files": [],
        },
    )

    assert final_state.get("status") == "completed"
    assert "/note/global/n1/" in (final_state.get("evidence_ids") or [])
    assert final_state.get("answer_text")
    report = grade_run(final_state, must_call=["OpenNote"])
    assert report.ok, report.failures


@pytest.mark.golden
@pytest.mark.asyncio
async def test_golden_empty_pack_reaches_final_answer(writer_user) -> None:
    """Scenario 11: search finds nothing, the planner's empty FinishRetrieval
    fails verify twice (repair budget=1) and hard-stops into pack with an
    empty evidence set — final generation must still answer without inventing a fact
    (agent-runtime-sprints §1.1/§1.3 exit criterion)."""
    final_state = await _run_golden(
        writer_user,
        history=[],
        user_text="Какой охват у поста про запуск?",
        # Exactly 5 LLM calls: classifier + 3 planner (SearchNodes, then two
        # empty FinishRetrieval — the 2nd only because verify's repair budget
        # is 1), followed by normal final generation with an empty pack. If
        # verifier.max_repair ever rises above 1 this script runs dry and the
        # graph raises StopIteration — add one more FinishRetrieval per extra
        # repair to keep the flow legible.
        llm_script=[
            '{"type": "read"}',
            '{"tool": "SearchNodes", "args": {"query": "охват запуск"}}',
            '{"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": []}}',
            '{"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": []}}',
            (
                '{"answer":"По workspace данных об охвате этого поста не найдено. '
                'Проверьте, опубликован ли он и доступна ли аналитика.","claims":[]}'
            ),
        ],
        search_results=[],
    )

    assert final_state.get("status") == "completed"
    assert final_state.get("stopped_reason") != "empty_evidence_refusal"
    assert final_state.get("evidence_ids") == []
    assert final_state.get("claims") == []
    assert "Проверьте" in str(final_state.get("answer_text") or "")
    report = grade_run(final_state)
    assert report.ok, report.failures
