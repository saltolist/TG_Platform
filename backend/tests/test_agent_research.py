"""Research subgraph unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.graph import parse_tool_action, run_research_graph
from app.services.agent.research.pack import build_evidence_pack
from app.services.agent.research.verifier import verify_evidence
from app.services.agent.runtime.context import RuntimeContext
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_tools import AgentState


def test_parse_tool_action_finish() -> None:
    action = parse_tool_action('{"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": []}}')
    assert action is not None
    assert action.tool == "FinishRetrieval"


def test_verify_evidence_ready() -> None:
    rec = EvidenceRecord(
        id="e1",
        kind="note_chunk",
        source_ref="note:n1",
        content="hello",
        citation_path="/note/global/n1/",
        citation_title="n1",
    )
    result = verify_evidence(
        finish={"status": "ready", "evidence_ids": ["e1"]},
        records={"e1": rec},
    )
    assert result.ok is True


def test_build_evidence_pack_dedup() -> None:
    rec = EvidenceRecord(
        id="e1",
        kind="note_chunk",
        source_ref="note:n1",
        content="alpha beta",
        citation_path="/note/global/n1/",
        citation_title="Note",
    )
    ctx, cites = build_evidence_pack(records={"e1": rec}, evidence_ids=["e1"])
    assert "alpha" in ctx
    assert len(cites) == 1
    assert isinstance(cites[0], NoteCite)


def test_verify_evidence_empty_ids_fails() -> None:
    """agent-runtime-sprints §1.3: an empty citation set is never a valid finish."""
    rec = EvidenceRecord(
        id="/note/global/n1/",
        kind="note_chunk",
        source_ref="/note/global/n1/",
        content="content",
        citation_path="/note/global/n1/",
        citation_title="n1",
    )
    result = verify_evidence(
        finish={"status": "ready", "evidence_ids": []},
        records={"/note/global/n1/": rec},
    )
    assert result.ok is False
    assert "no_evidence_ids" in result.errors


def test_verify_evidence_partial_rejects_empty_content() -> None:
    """agent-runtime-sprints §1.3: partial still must ground on non-empty content."""
    rec = EvidenceRecord(
        id="/post/3/",
        kind="post_text",
        source_ref="/post/3/",
        content="   ",
        citation_path="/post/3/",
        citation_title="Post 3",
    )
    result = verify_evidence(
        finish={"status": "partial", "evidence_ids": ["/post/3/"]},
        records={"/post/3/": rec},
    )
    assert result.ok is False
    assert "empty_evidence_content" in result.errors


def test_records_from_agent_state_uses_natural_ids() -> None:
    """agent-runtime-sprints §1.2: records key on citation path, no hash indirection."""
    from types import SimpleNamespace

    from app.services.agent.research.evidence import records_from_agent_state

    cite = NoteCite(path="/post/3/", title="Post 3")
    agent_state = SimpleNamespace(
        context_blocks=[(cite, "post body")],
        visited=[],
    )
    records = records_from_agent_state(agent_state)
    assert set(records) == {"/post/3/"}
    assert records["/post/3/"].content == "post body"
    assert records["/post/3/"].kind == "post_text"


@pytest.mark.asyncio
async def test_answer_node_refuses_on_empty_evidence() -> None:
    """agent-runtime-sprints §1.1: research with no grounded evidence refuses."""
    from app.services.agent.runtime.workspace_graph import REFUSAL_TEXT, answer_node

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
    )
    state = {
        "user_text": "какой охват у поста 3?",
        "tool_call": {"type": "read"},
        "evidence_ids": [],
        "rag_context": "",
    }
    result = await answer_node(state, {"configurable": {"runtime_context": ctx}})
    assert result["answer_text"] == REFUSAL_TEXT
    assert result["claims"] == []
    assert result["stopped_reason"] == "empty_evidence_refusal"


def _reasoner_ctx() -> RuntimeContext:
    from app.services.ai.providers import ProviderSpec

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
    )
    ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
    ctx.reasoner_model = "gpt-4o-mini"
    ctx.reasoner_api_key = "test-key"
    return ctx


@pytest.mark.asyncio
async def test_workspace_agent_node_forwards_dialog_context_to_classifier_prompt() -> None:
    """agent-runtime-sprints §2.1: classifier must see dialog_context, not just
    the current turn, so it can route stylistic follow-ups to "finish" instead
    of a doomed re-search."""
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    state = {"user_text": "Покороче можешь?"}
    config = {
        "configurable": {
            "runtime_context": ctx,
            "dialog_context": "Пользователь: Какой охват у поста 3?\nАссистент: Охват 1200 просмотров.",
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"type": "finish"}',
    ) as mock_llm:
        result = await workspace_agent_node(state, config)

    assert result["current_tool"] == "finish"
    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Охват 1200 просмотров" in user_content
    assert "Покороче можешь?" in user_content


@pytest.mark.asyncio
async def test_answer_node_forwards_dialog_context_on_finish_path() -> None:
    """agent-runtime-sprints §2.1: a "finish" turn (no research pack) must still
    let the model answer from dialog_context — e.g. "покороче" needs the prior
    answer's text, not the empty-evidence refusal."""
    from app.services.agent.runtime.workspace_graph import REFUSAL_TEXT, answer_node

    ctx = _reasoner_ctx()
    state = {
        "user_text": "Покороче можешь?",
        "tool_call": {"type": "finish"},
        "evidence_ids": [],
        "rag_context": "",
    }
    config = {
        "configurable": {
            "runtime_context": ctx,
            "dialog_context": "Пользователь: Какой охват у поста 3?\nАссистент: Охват 1200 просмотров.",
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"answer": "1200.", "claims": []}',
    ) as mock_llm:
        result = await answer_node(state, config)

    # No research pack was produced, but the finish path never hits the
    # empty-evidence guard — that guard only fires when tool_call == "read".
    assert result["answer_text"] != REFUSAL_TEXT
    assert result["answer_text"] == "1200."
    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Охват 1200 просмотров" in user_content


@pytest.mark.asyncio
async def test_run_research_graph_without_llm_uses_context_blocks() -> None:
    session = AsyncMock()
    session.commit = AsyncMock()

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    agent_state = AgentState(
        session=session,
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        embedding_backend=AsyncMock(),
    )
    cite = NoteCite(path="/note/global/n1/", title="n1")
    agent_state.context_blocks.append((cite, "seeded content"))

    ctx = RuntimeContext(
        session_factory=_Factory(),
        user_id=agent_state.user_id,
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=agent_state.embedding_backend,
        scope="global",
        post_data=None,
        ai_profile={},
        agent_tool_state=agent_state,
    )

    with patch("app.services.ai.llm.complete_chat_completion", new_callable=AsyncMock):
        result = await run_research_graph(
            ctx,
            user_text="test",
            max_steps=1,
            spec=None,
            model="",
            api_key="",
        )

    assert "seeded content" in result.rag_context or result.stopped_reason

    # Deterministic graders must pass on real graph output, not just fixtures
    # (agent-runtime-sprints Фаза 0): no dangling citation, no claim on empty pack.
    from app.services.agent.runtime.graders import grade_run

    report = grade_run(
        {
            "rag_context": result.rag_context,
            "evidence_ids": list(result.evidence_ids or []),
            "evidence_records": {eid: {} for eid in (result.evidence_ids or [])},
            "claims": [],
            "answer_text": result.rag_context,
            "stopped_reason": result.stopped_reason,
        }
    )
    assert report.ok, report.failures
