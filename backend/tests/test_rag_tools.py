"""Tests for L2 agentic RAG read tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_tools import (
    AgentState,
    tool_list_note_attachments,
    tool_list_post_notes,
    tool_open_note,
    tool_open_post,
    tool_search_nodes,
)


def _state(**kwargs) -> AgentState:
    embedding_backend = AsyncMock()
    embedding_backend.model_key = "test-model"
    embedding_backend.embed_query = AsyncMock(return_value=[0.1, 0.2])
    defaults = {
        "session": AsyncMock(),
        "user_id": uuid4(),
        "scope": "post",
        "tenant_key": None,
        "embedding_backend": embedding_backend,
        "base_post_data": {
            "id": "post-1",
            "text": "Текст поста",
            "notes": [{"id": "n1", "title": "Note 1", "body": "Body", "files": []}],
            "media": [],
            "comments": [],
        },
    }
    defaults.update(kwargs)
    return AgentState(**defaults)


@pytest.mark.asyncio
async def test_tool_search_nodes_summary_shape() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.retrieve_top_k",
        new_callable=AsyncMock,
        return_value=[
            {
                "node_type": "note_chunk",
                "note_id": "n1",
                "file_id": "",
                "chunk_text": "Длинный текст заметки для превью",
                "similarity": 0.81,
            }
        ],
    ):
        outcome = await tool_search_nodes(state, query="доходность")

    assert outcome.error is None
    assert "note:n1" in outcome.summary
    assert "0.81" in outcome.summary
    assert state.context_blocks == []


@pytest.mark.asyncio
async def test_tool_open_post_caches_and_adds_context() -> None:
    state = _state(base_post_data=None)
    post = {
        "id": "post-1",
        "text": "Мартовский дайджест",
        "notes": [],
        "media": [],
        "comments": [],
    }
    with patch(
        "app.services.ai.rag_tools.resolve_post_data",
        new_callable=AsyncMock,
        return_value=post,
    ):
        outcome = await tool_open_post(state, post_id="post-1")

    assert outcome.error is None
    assert state.opened_posts["post-1"] == post
    assert len(state.context_blocks) == 1
    cite, text = state.context_blocks[0]
    assert isinstance(cite, NoteCite)
    assert cite.path == "/post/post-1/"
    assert "Мартовский" in text


def test_tool_list_post_notes_from_base_post_data() -> None:
    state = _state()
    outcome = tool_list_post_notes(state, post_id="post-1")
    assert "note:n1" in outcome.summary
    assert "Note 1" in outcome.summary


@pytest.mark.asyncio
async def test_tool_open_note_from_post_scope() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={"id": "n1", "title": "Note 1", "body": "Подробности", "files": []},
    ):
        outcome = await tool_open_note(state, note_id="n1", post_id="post-1")

    assert outcome.error is None
    assert len(state.context_blocks) == 1
    cite, text = state.context_blocks[0]
    assert cite.path == "/note/post/post-1/n1/"
    assert "Подробности" in text


@pytest.mark.asyncio
async def test_tool_list_note_attachments_manifest() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={
            "id": "n1",
            "title": "Note 1",
            "body": "",
            "files": [{"id": "f1", "name": "report.pdf", "type": "application/pdf"}],
        },
    ):
        outcome = await tool_list_note_attachments(state, note_id="n1", post_id="post-1")

    assert outcome.error is None
    assert "attachment:f1" in outcome.summary
    assert "report.pdf" in outcome.summary


@pytest.mark.asyncio
async def test_tool_open_post_visited_dedup() -> None:
    state = _state(base_post_data=None)
    with patch(
        "app.services.ai.rag_tools.resolve_post_data",
        new_callable=AsyncMock,
        return_value={"id": "post-1", "text": "x", "notes": [], "media": [], "comments": []},
    ):
        first = await tool_open_post(state, post_id="post-1")
        second = await tool_open_post(state, post_id="post-1")

    assert first.error is None
    assert "уже открыт" in second.summary.lower()


@pytest.mark.asyncio
async def test_tool_search_nodes_fail_soft_on_error() -> None:
    state = _state()
    state.embedding_backend.embed_query = AsyncMock(side_effect=RuntimeError("boom"))
    outcome = await tool_search_nodes(state, query="test")
    assert outcome.error == "boom"
