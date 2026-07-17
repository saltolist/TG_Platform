"""Tests for L2 agentic RAG read tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.agent.research.evidence import records_from_agent_state
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_tools import (
    AgentState,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_global_notes,
    tool_list_note_attachments,
    tool_list_post_comments,
    tool_list_post_media,
    tool_list_post_notes,
    tool_list_posts,
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


def test_normalize_node_types_maps_planner_aliases() -> None:
    from app.services.ai.rag_tools import _normalize_node_types

    # The planner says "post"/"note"; the DB stores post_text/note_chunk. Without
    # translation the retrieval filter intersects to ∅ and recall drops to zero.
    assert _normalize_node_types(["post", "note"]) == frozenset(
        {"post_text", "note_chunk"}
    )
    # Real types pass through unchanged.
    assert _normalize_node_types(["note_chunk"]) == frozenset({"note_chunk"})
    # Empty / unknown-only degrade to None = "no filter, search everything",
    # never to an empty set that would silently match nothing.
    assert _normalize_node_types(None) is None
    assert _normalize_node_types([]) is None
    assert _normalize_node_types(["totally_bogus"]) is None


@pytest.mark.asyncio
async def test_tool_search_nodes_translates_node_types_before_retrieval() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.retrieve_for_chat",
        new_callable=AsyncMock,
        return_value=[],
    ) as retrieve:
        await tool_search_nodes(state, query="система", node_types=["post", "note"])

    # The alien planner vocabulary must be translated to real node types, not
    # forwarded verbatim (which zeroed every retrieval pass in chat 63dfb9e4).
    assert retrieve.await_args.kwargs["node_types_filter"] == frozenset(
        {"post_text", "note_chunk"}
    )


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


@pytest.mark.asyncio
async def test_tool_open_post_skips_text_for_current_post_in_post_scope() -> None:
    post = {
        "id": "post-1",
        "text": "Мартовский дайджест",
        "notes": [],
        "media": [],
        "comments": [],
    }
    state = _state(scope="post", base_post_data=post)
    with patch(
        "app.services.ai.rag_tools.resolve_post_data",
        new_callable=AsyncMock,
        return_value=post,
    ):
        outcome = await tool_open_post(state, post_id="post-1")

    assert outcome.error is None
    assert state.opened_posts["post-1"] == post
    assert "post:post-1" in state.visited
    assert state.context_blocks == []
    assert "primer" in outcome.summary


@pytest.mark.asyncio
async def test_tool_open_post_adds_text_for_other_post_in_post_scope() -> None:
    current = {
        "id": "post-1",
        "text": "Текущий пост",
        "notes": [],
        "media": [],
        "comments": [],
    }
    other = {
        "id": "post-2",
        "text": "Другой пост",
        "notes": [],
        "media": [],
        "comments": [],
    }
    state = _state(scope="post", base_post_data=current)
    with patch(
        "app.services.ai.rag_tools.resolve_post_data",
        new_callable=AsyncMock,
        return_value=other,
    ):
        outcome = await tool_open_post(state, post_id="post-2")

    assert outcome.error is None
    assert len(state.context_blocks) == 1
    assert state.context_blocks[0][1] == "Другой пост"
    assert "primer" not in outcome.summary


def test_tool_list_post_notes_from_base_post_data() -> None:
    state = _state()
    outcome = tool_list_post_notes(state, post_id="post-1")
    assert "note:n1" in outcome.summary
    assert "Note 1" in outcome.summary


def test_list_post_notes_surfaces_attachment_markers() -> None:
    # A post note with an image + a doc must expose files=/images= so «заметка с
    # вложениями/картинками» is findable without opening it (chat 9f3d5fdf).
    post = {
        "id": "post-1",
        "text": "T",
        "notes": [
            {
                "id": "n1",
                "title": "Note 1",
                "files": [
                    {"id": "f1", "type": "image/png"},
                    {"id": "f2", "type": "application/pdf"},
                ],
            },
            {"id": "n2", "title": "Note 2", "files": []},
        ],
    }
    state = _state(scope="post", base_post_data=post)
    outcome = tool_list_post_notes(state, post_id="post-1")
    assert "note:n1" in outcome.summary and "files=2" in outcome.summary
    assert "images=1" in outcome.summary
    # A note with no files gets no suffix — no false "files=0".
    n2_line = [ln for ln in outcome.summary.splitlines() if "note:n2" in ln][0]
    assert "files=" not in n2_line


@pytest.mark.asyncio
async def test_list_posts_aggregates_note_attachments() -> None:
    state = _state(scope="global", base_post_data=None)
    row = MagicMock()
    row.data = {
        "id": "1",
        "status": "draft",
        "text": "Пост с картинками в заметке",
        "notes": [
            {"id": "n1", "files": [{"id": "f1", "type": "image/jpeg"}]},
            {"id": "n2", "files": [{"id": "f2", "type": "text/plain"}]},
        ],
    }
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [row]
    state.session.execute = AsyncMock(return_value=mock_result)

    outcome = await tool_list_posts(state, status="all")

    assert "note_files=2" in outcome.summary
    assert "note_images=1" in outcome.summary


@pytest.mark.asyncio
async def test_tool_list_posts_filters_status() -> None:
    state = _state(scope="global", base_post_data=None)
    row_published = MagicMock()
    row_published.data = {
        "id": "1",
        "status": "published",
        "text": "Приветственный пост",
        "notes": [],
    }
    row_draft = MagicMock()
    row_draft.data = {"id": "2", "status": "draft", "text": "Черновик", "notes": []}
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [row_published, row_draft]
    state.session.execute = AsyncMock(return_value=mock_result)

    outcome = await tool_list_posts(state, status="published")

    assert outcome.error is None
    assert "id=1" in outcome.summary
    assert "id=2" not in outcome.summary


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
async def test_tool_open_note_lists_attachments_in_evidence() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={
            "id": "n1",
            "title": "Варианты изображений",
            "body": "Текст заметки",
            "files": [
                {"id": "img1", "name": "shot.png", "type": "image/png"},
                {"id": "img2", "name": "gen.png", "type": "image/png"},
            ],
        },
    ):
        outcome = await tool_open_note(state, note_id="n1", post_id="post-1")

    assert outcome.error is None
    assert "files=2" in outcome.summary
    _, text = state.context_blocks[0]
    # The answer model must see the attachment names/types, not just the body,
    # so it can ground "какая заметка с изображениями?".
    assert "Текст заметки" in text
    assert "Вложения заметки" in text
    assert "shot.png" in text and "image/png" in text


@pytest.mark.asyncio
async def test_tool_open_note_records_note_with_files_but_no_text() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={
            "id": "n1",
            "title": "",
            "body": "",
            "files": [{"id": "img1", "name": "shot.png", "type": "image/png"}],
        },
    ):
        outcome = await tool_open_note(state, note_id="n1", post_id="post-1")

    assert outcome.error is None
    # A body-less, image-only note used to record nothing at all — the answer
    # pack was empty and the run refused despite the images existing.
    assert len(state.context_blocks) == 1
    _, text = state.context_blocks[0]
    assert "shot.png" in text


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
    assert state.listed_image_attachment_refs == []


@pytest.mark.asyncio
async def test_tool_list_note_attachments_populates_image_refs() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={
            "id": "n1",
            "title": "Note 1",
            "body": "",
            "files": [
                {"id": "img1", "name": "a.png", "type": "image/png"},
                {"id": "doc1", "name": "report.pdf", "type": "application/pdf"},
                {"id": "img2", "name": "b.png", "type": "image/png"},
            ],
        },
    ):
        outcome = await tool_list_note_attachments(state, note_id="n1", post_id="post-1")

    assert outcome.error is None
    assert state.listed_image_attachment_refs == [
        "attachment:img1",
        "attachment:img2",
    ]


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
async def test_tool_search_nodes_dedup_considers_node_types_and_k() -> None:
    # Regression: retries that vary node_types/k must NOT be swallowed as
    # duplicates of a same-query call — only the query text was hashed before,
    # so a follow-up SearchNodes(query="x", k=50) after k=10 got no fresh result.
    state = _state()
    with patch(
        "app.services.ai.rag_tools.retrieve_for_chat",
        new_callable=AsyncMock,
        return_value=[],
    ) as mocked:
        first = await tool_search_nodes(state, query="x", node_types=["note"], k=10)
        second = await tool_search_nodes(state, query="x", node_types=["note"], k=50)
        third = await tool_search_nodes(state, query="x", node_types=["note"], k=10)

    assert mocked.await_count == 2
    assert "уже открыт ранее" not in first.summary
    assert "уже открыт ранее" not in second.summary
    assert "уже открыт ранее" in third.summary


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
async def test_tool_hydrate_attachment_retry_after_note_lookup_failure() -> None:
    state = _state()
    note_data = {
        "id": "n1",
        "files": [{"id": "f1", "name": "a.png", "type": "image/png", "url": "http://x/a.png"}],
    }
    with (
        patch(
            "app.services.ai.rag_tools.get_note_data",
            new_callable=AsyncMock,
            side_effect=[None, note_data],
        ),
        patch(
            "app.services.ai.rag_tools.resolve_attachment_bytes",
            new_callable=AsyncMock,
            return_value=(b"png-bytes", "image/png"),
        ),
        patch(
            "app.services.ai.rag_tools.get_attachment_extraction_by_hash",
            new_callable=AsyncMock,
            return_value="cached caption",
        ),
    ):
        first = await tool_hydrate_attachment(
            state, ref="attachment:f1", mode="vision", note_id="n1", post_id="post-1"
        )
        second = await tool_hydrate_attachment(
            state, ref="attachment:f1", mode="vision", note_id="n1", post_id="post-1"
        )

    assert first.error == "note_not_found"
    assert second.error is None
    assert "hydrate:vision:attachment:f1" in state.visited


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


# --- §1.4 tail: listing tools produce first-class citable evidence -----------


def _posts_state():
    state = _state(scope="global", base_post_data=None)
    row_a = MagicMock()
    row_a.data = {"id": "1", "status": "published", "text": "Запуск продукта уже близко", "notes": []}
    row_b = MagicMock()
    row_b.data = {"id": "2", "status": "draft", "text": "Черновик про доставку", "notes": []}
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [row_a, row_b]
    state.session.execute = AsyncMock(return_value=mock_result)
    return state


@pytest.mark.asyncio
async def test_list_posts_records_citable_listing() -> None:
    state = _posts_state()
    outcome = await tool_list_posts(state, query="запуск")
    assert outcome.error is None
    # A citable record exists, keyed by a filter-encoded listing path.
    assert len(state.context_blocks) == 1
    cite, body = state.context_blocks[0]
    assert cite.path == "/posts/q:запуск/"
    assert "id=1" in body
    # records_from_agent_state classifies it as a search_hit, not post_text.
    records = records_from_agent_state(state)
    assert records["/posts/q:запуск/"].kind == "search_hit"


@pytest.mark.asyncio
async def test_list_posts_empty_result_is_still_citable() -> None:
    state = _posts_state()
    outcome = await tool_list_posts(state, query="несуществует")
    # An honest "nothing found" is grounded evidence, not a dead end.
    assert len(state.context_blocks) == 1
    assert "не найдено" in outcome.summary
    assert state.context_blocks[0][0].path == "/posts/q:несуществует/"


@pytest.mark.asyncio
async def test_list_posts_distinct_filters_do_not_collide() -> None:
    state = _posts_state()
    await tool_list_posts(state, query="запуск")
    await tool_list_posts(state)  # all posts — different path
    paths = {cite.path for cite, _ in state.context_blocks}
    assert paths == {"/posts/q:запуск/", "/posts/"}


def test_list_post_notes_records_citable_listing() -> None:
    state = _state()
    outcome = tool_list_post_notes(state, post_id="post-1")
    assert outcome.error is None
    cite, body = state.context_blocks[0]
    assert cite.path == "/post/post-1/notes/"
    assert "note:n1" in body
    assert records_from_agent_state(state)["/post/post-1/notes/"].kind == "search_hit"


def test_list_post_notes_guidance_is_not_citable() -> None:
    # "сначала OpenPost" is control flow, not a fact — must not become evidence.
    state = _state(scope="global", base_post_data=None)
    outcome = tool_list_post_notes(state, post_id="missing")
    assert outcome.error == "post_not_open"
    assert state.context_blocks == []


def test_list_post_notes_precondition_failure_does_not_poison_ref() -> None:
    # Regression: ListPostNotes before OpenPost must NOT mark the ref visited —
    # otherwise the legitimate retry after OpenPost returns "уже открыт ранее"
    # and never lists the notes, burning the agent's whole step budget.
    state = _state(scope="global", base_post_data=None)
    first = tool_list_post_notes(state, post_id="post-1")
    assert first.error == "post_not_open"

    # Simulate OpenPost having populated the post into opened_posts.
    state.opened_posts["post-1"] = {
        "id": "post-1",
        "notes": [{"id": "n1", "title": "Note 1"}],
    }
    second = tool_list_post_notes(state, post_id="post-1")
    assert second.error is None
    assert "note:n1" in second.summary
    assert "уже открыт ранее" not in second.summary


def test_list_post_media_lists_refs_and_flags_images() -> None:
    state = _state()
    state.opened_posts["post-1"] = {
        "id": "post-1",
        "media": [
            {"mediaKey": "mk1", "name": "photo.jpg", "type": "image/jpeg", "kind": "image"},
            {"mediaKey": "mk2", "name": "spec.pdf", "type": "application/pdf", "kind": "document"},
            {"name": "note.ogg", "type": "audio/ogg", "kind": "voice"},
        ],
    }
    outcome = tool_list_post_media(state, post_id="post-1")
    assert outcome.error is None
    cite, body = state.context_blocks[0]
    assert cite.path == "/post/post-1/media/"
    assert "file:mk1" in body
    assert "file:mk2" in body
    assert "file:idx-2" in body  # voice item without mediaKey → positional id
    # Only the image is offered for vision hydration.
    assert state.listed_image_media_refs == ["file:mk1"]
    assert records_from_agent_state(state)["/post/post-1/media/"].kind == "search_hit"


def test_list_post_media_precondition_failure_does_not_poison_ref() -> None:
    state = _state(scope="global", base_post_data=None)
    first = tool_list_post_media(state, post_id="post-1")
    assert first.error == "post_not_open"

    state.opened_posts["post-1"] = {
        "id": "post-1",
        "media": [{"mediaKey": "mk1", "name": "photo.jpg", "type": "image/jpeg"}],
    }
    second = tool_list_post_media(state, post_id="post-1")
    assert second.error is None
    assert "file:mk1" in second.summary
    assert "уже открыт ранее" not in second.summary


def test_list_post_media_empty_is_still_citable() -> None:
    state = _state()
    state.opened_posts["post-1"] = {"id": "post-1", "media": []}
    outcome = tool_list_post_media(state, post_id="post-1")
    assert outcome.error is None
    assert "нет медиа" in outcome.summary
    assert records_from_agent_state(state)["/post/post-1/media/"].kind == "search_hit"


def test_list_post_comments_precondition_failure_does_not_poison_ref() -> None:
    state = _state(scope="global", base_post_data=None)
    first = tool_list_post_comments(state, post_id="post-1")
    assert first.error == "post_not_open"

    state.opened_posts["post-1"] = {
        "id": "post-1",
        "comments": [{"author": "A", "date": "2026-01-01", "text": "hi"}],
    }
    second = tool_list_post_comments(state, post_id="post-1")
    assert second.error is None
    assert "уже открыт ранее" not in second.summary


@pytest.mark.asyncio
async def test_list_note_attachments_records_citable_listing() -> None:
    state = _state()
    with patch(
        "app.services.ai.rag_tools.get_note_data",
        new_callable=AsyncMock,
        return_value={
            "id": "n1", "title": "Note 1", "body": "",
            "files": [{"id": "f1", "name": "report.pdf", "type": "application/pdf"}],
        },
    ):
        outcome = await tool_list_note_attachments(state, note_id="n1", post_id="post-1")
    assert outcome.error is None
    cite, body = state.context_blocks[0]
    assert cite.path == "/note/n1/attachments/"
    assert "report.pdf" in body
    assert records_from_agent_state(state)["/note/n1/attachments/"].kind == "search_hit"


@pytest.mark.asyncio
async def test_tool_list_global_notes_lists_rows() -> None:
    state = _state(scope="global", base_post_data=None)
    with patch(
        "app.services.ai.rag_tools.list_global_notes",
        new_callable=AsyncMock,
        return_value=[{"id": "g1", "title": "Standalone note"}],
    ):
        outcome = await tool_list_global_notes(state)

    assert outcome.error is None
    assert "note:g1" in outcome.summary
    assert "Standalone note" in outcome.summary
    cite, body = state.context_blocks[0]
    assert cite.path == "/global/notes/"
    assert records_from_agent_state(state)["/global/notes/"].kind == "search_hit"


@pytest.mark.asyncio
async def test_tool_list_global_notes_empty_is_still_citable() -> None:
    state = _state(scope="global", base_post_data=None)
    with patch(
        "app.services.ai.rag_tools.list_global_notes",
        new_callable=AsyncMock,
        return_value=[],
    ):
        outcome = await tool_list_global_notes(state)

    assert outcome.error is None
    assert "нет заметок вне постов" in outcome.summary
    assert records_from_agent_state(state)["/global/notes/"].kind == "search_hit"


@pytest.mark.asyncio
async def test_tool_list_global_notes_dedup() -> None:
    state = _state(scope="global", base_post_data=None)
    with patch(
        "app.services.ai.rag_tools.list_global_notes",
        new_callable=AsyncMock,
        return_value=[{"id": "g1", "title": "Standalone note"}],
    ) as mocked:
        await tool_list_global_notes(state)
        outcome = await tool_list_global_notes(state)

    mocked.assert_awaited_once()
    assert "уже открыт ранее" in outcome.summary

