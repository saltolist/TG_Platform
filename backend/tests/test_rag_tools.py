"""Tests for L2 agentic RAG read tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_tools import (
    AgentState,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_note_attachments,
    tool_list_post_comments,
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
        "app.services.ai.rag_tools.retrieve_for_chat",
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


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_cache_hit() -> None:
    state = _state()
    with (
        patch(
            "app.services.ai.rag_tools.get_note_data",
            new_callable=AsyncMock,
            return_value={
                "id": "n1",
                "title": "Note 1",
                "body": "",
                "files": [
                    {
                        "id": "f1",
                        "name": "report.pdf",
                        "type": "application/pdf",
                        "url": "data:application/pdf;base64,AA==",
                    }
                ],
            },
        ),
        patch(
            "app.services.ai.rag_tools.get_attachment_extraction",
            new_callable=AsyncMock,
            return_value="Cached PDF text",
        ),
    ):
        outcome = await tool_hydrate_attachment(
            state,
            ref="attachment:f1",
            mode="text",
            note_id="n1",
            post_id="post-1",
        )

    assert outcome.error is None
    assert len(state.context_blocks) == 1
    _, text = state.context_blocks[0]
    assert text == "Cached PDF text"


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_lazy_extract_and_cache() -> None:
    state = _state()
    pdf_bytes = b"%PDF-1.4 minimal"
    import base64

    data_url = f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode()}"
    with (
        patch(
            "app.services.ai.rag_tools.get_note_data",
            new_callable=AsyncMock,
            return_value={
                "id": "n1",
                "title": "Note 1",
                "body": "",
                "files": [{"id": "f1", "name": "report.pdf", "type": "application/pdf", "url": data_url}],
            },
        ),
        patch(
            "app.services.ai.rag_tools.get_attachment_extraction",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.ai.rag_tools.extract_attachment_text",
            return_value="Extracted text",
        ),
        patch(
            "app.services.ai.rag_tools.upsert_attachment_extraction",
            new_callable=AsyncMock,
        ) as mock_upsert,
        patch(
            "app.services.ai.rag_worker.enqueue_note_job",
            new_callable=AsyncMock,
        ),
    ):
        outcome = await tool_hydrate_attachment(
            state,
            ref="attachment:f1",
            mode="text",
            note_id="n1",
            post_id="post-1",
        )

    assert outcome.error is None
    mock_upsert.assert_awaited_once()
    assert state.context_blocks[0][1] == "Extracted text"


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_unsupported_mime() -> None:
    state = _state()
    with (
        patch(
            "app.services.ai.rag_tools.get_note_data",
            new_callable=AsyncMock,
            return_value={
                "id": "n1",
                "title": "Note 1",
                "body": "",
                "files": [
                    {
                        "id": "f1",
                        "name": "chart.png",
                        "type": "image/png",
                        "url": "data:image/png;base64,AA==",
                    }
                ],
            },
        ),
        patch(
            "app.services.ai.rag_tools.get_attachment_extraction",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.ai.rag_tools.resolve_attachment_bytes",
            new_callable=AsyncMock,
            return_value=(b"\x89PNG", "image/png"),
        ),
        patch(
            "app.services.ai.rag_tools.extract_attachment_text",
            return_value=None,
        ),
    ):
        outcome = await tool_hydrate_attachment(
            state,
            ref="attachment:f1",
            mode="text",
            note_id="n1",
            post_id="post-1",
        )

    assert outcome.error == "no_text"
    assert "vision" in outcome.summary.lower()


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_visited_dedup() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value=None,
    ):
        first = await tool_hydrate_attachment(
            state, ref="attachment:f1", mode="text", note_id="n1", post_id="post-1"
        )
        second = await tool_hydrate_attachment(
            state, ref="attachment:f1", mode="text", note_id="n1", post_id="post-1"
        )

    assert first.error == "note_not_found"
    assert "уже" in second.summary.lower()


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_vision_budget_exhausted() -> None:
    from app.core.config import Settings

    state = _state(settings=Settings(rag_agent_max_vision=0), vision_calls_used=0)
    outcome = await tool_hydrate_attachment(
        state, ref="attachment:f1", mode="vision", note_id="n1", post_id="post-1"
    )
    assert outcome.error == "vision_budget_exhausted"


@pytest.mark.asyncio
async def test_tool_hydrate_attachment_vision_no_model() -> None:
    state = _state(user=None)
    with (
        patch(
            "app.services.ai.rag_tools.get_note_data",
            new_callable=AsyncMock,
            return_value={
                "id": "n1",
                "title": "Note 1",
                "body": "",
                "files": [
                    {
                        "id": "f1",
                        "name": "chart.png",
                        "type": "image/png",
                        "url": "data:image/png;base64,AA==",
                    }
                ],
            },
        ),
        patch(
            "app.services.ai.rag_tools.resolve_attachment_bytes",
            new_callable=AsyncMock,
            return_value=(b"\x89PNG", "image/png"),
        ),
        patch(
            "app.services.ai.rag_tools.get_attachment_extraction_by_hash",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        outcome = await tool_hydrate_attachment(
            state,
            ref="attachment:f1",
            mode="vision",
            note_id="n1",
            post_id="post-1",
        )

    assert outcome.error == "no_vision_model"


def test_tool_list_post_comments_adds_context() -> None:
    state = _state(
        base_post_data={
            "id": "post-1",
            "text": "Post",
            "notes": [],
            "media": [],
            "comments": [
                {
                    "id": "c1",
                    "author": "Alice",
                    "text": "Отличный пост",
                    "date": "2026-01-02T10:00:00Z",
                },
                {
                    "id": "c2",
                    "author": "Bob",
                    "text": "Согласен",
                    "date": "2026-01-01T10:00:00Z",
                },
            ],
        }
    )
    outcome = tool_list_post_comments(state, post_id="post-1")
    assert outcome.error is None
    assert "2 из 2" in outcome.summary
    assert len(state.context_blocks) == 1
    cite, body = state.context_blocks[0]
    assert cite.path == "/post/post-1/comments/"
    assert "Alice" in body
    assert "Bob" in body


def test_tool_list_post_comments_post_not_open() -> None:
    state = _state(base_post_data=None)
    outcome = tool_list_post_comments(state, post_id="post-1")
    assert outcome.error == "post_not_open"


def test_tool_list_post_comments_empty() -> None:
    state = _state()
    outcome = tool_list_post_comments(state, post_id="post-1")
    assert "нет комментариев" in outcome.summary.lower()


@pytest.mark.asyncio
async def test_tool_get_post_analytics_happy_path() -> None:
    state = _state()
    trend_body = "Период: 30d\nПросмотры: 100"
    with patch(
        "app.services.ai.rag_tools._load_post_trend_body",
        new_callable=AsyncMock,
        return_value=(trend_body, NoteCite(path="/post/post-1/", title="Аналитика поста"), None),
    ):
        outcome = await tool_get_post_analytics(state, post_id="post-1", period="30d")

    assert outcome.error is None
    assert len(state.context_blocks) == 1
    assert "Просмотры" in state.context_blocks[0][1]


@pytest.mark.asyncio
async def test_tool_get_post_analytics_unpublished() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools._load_post_trend_body",
        new_callable=AsyncMock,
        return_value=("", NoteCite(path="/post/post-1/", title="Аналитика поста"), "unpublished"),
    ):
        outcome = await tool_get_post_analytics(state, post_id="post-1", period="30d")

    assert outcome.error == "unpublished"

