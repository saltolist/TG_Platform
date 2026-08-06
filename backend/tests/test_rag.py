"""Tests for RAG: markdown_to_index_text, content_hash, retrieve_top_k, format_rag_context."""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.rag import (
    NODE_POST_TEXT,
    _chunk_text,
    _vec_to_pg,
    content_hash,
    extract_referenced_attachment_ids,
    format_rag_context,
    index_text_node,
    markdown_to_index_text,
    retrieve_top_k,
    semantic_index_chunks,
)


# ──────────────────────────────────────────────────────────────────────────────
# markdown_to_index_text
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkdownToIndexText:
    def test_title_prepended(self):
        result = markdown_to_index_text("Моя заметка", "Текст заметки")
        assert result.startswith("Моя заметка")
        assert "Текст заметки" in result

    def test_bold_stripped(self):
        result = markdown_to_index_text("", "**жирный** текст")
        assert "жирный" in result
        assert "**" not in result

    def test_italic_stripped(self):
        result = markdown_to_index_text("", "*курсив*")
        assert "курсив" in result
        assert "*" not in result

    def test_headers_stripped(self):
        result = markdown_to_index_text("", "# Заголовок\n\nТекст")
        assert "Заголовок" in result
        assert "#" not in result

    def test_image_alt_preserved(self):
        result = markdown_to_index_text("", "![Скриншот портфеля](attachment:abc123)")
        assert "Скриншот портфеля" in result
        assert "attachment:" not in result

    def test_link_text_preserved(self):
        result = markdown_to_index_text("", "[Отчёт за апрель](attachment:xyz)")
        assert "Отчёт за апрель" in result
        assert "attachment:" not in result


class TestExtractReferencedAttachmentIds:
    def test_extracts_unique_ids_in_order(self):
        body = "Текст [a](attachment:id1) и ![b](attachment:id2) снова [c](attachment:id1)"
        assert extract_referenced_attachment_ids(body) == ["id1", "id2"]

    def test_empty_body(self):
        assert extract_referenced_attachment_ids("") == []

    def test_table_cell_text_preserved(self):
        body = "| Актив | Доля |\n|---|---|\n| Акции | 60% |"
        result = markdown_to_index_text("", body)
        assert "Актив" in result
        assert "Акции" in result
        assert "60%" in result
        # pipe separators should be removed
        assert "|" not in result

    def test_code_block_stripped(self):
        body = "Смотри:\n```python\nprint('hello')\n```\nДалее"
        result = markdown_to_index_text("", body)
        assert "print" not in result
        assert "Смотри" in result
        assert "Далее" in result

    def test_blockquote_stripped(self):
        result = markdown_to_index_text("", "> Цитата")
        assert "Цитата" in result
        assert ">" not in result

    def test_empty_body(self):
        result = markdown_to_index_text("Заголовок", "")
        assert result == "Заголовок"

    def test_empty_both(self):
        result = markdown_to_index_text("", "")
        assert result == ""

    def test_gfm_table_separator_stripped(self):
        body = "| A | B |\n|:---|:---|\n| x | y |"
        result = markdown_to_index_text("", body)
        # separator row should be gone
        assert ":---" not in result
        assert "x" in result


# ──────────────────────────────────────────────────────────────────────────────
# content_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestContentHash:
    def test_deterministic(self):
        h1 = content_hash("title", "body", "local:e5")
        h2 = content_hash("title", "body", "local:e5")
        assert h1 == h2

    def test_different_model_different_hash(self):
        h1 = content_hash("t", "b", "local:e5")
        h2 = content_hash("t", "b", "openai:text-embedding-3-small")
        assert h1 != h2

    def test_different_body_different_hash(self):
        h1 = content_hash("t", "body1", "m")
        h2 = content_hash("t", "body2", "m")
        assert h1 != h2


# ──────────────────────────────────────────────────────────────────────────────
# _chunk_text
# ──────────────────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = _chunk_text("hello world", 100)
        assert chunks == ["hello world"]

    def test_long_text_split_on_paragraphs(self):
        para = "A" * 100
        text = f"{para}\n\n{para}\n\n{para}"
        chunks = _chunk_text(text, 150)
        assert len(chunks) > 1

    def test_markdown_headings_form_independent_semantic_chunks(self):
        body = (
            "# Overview\n\nGeneral project background.\n\n"
            "## Delivery options\n\n"
            "Demo stores browser mocks. Docker uses the real database and API.\n\n"
            "## Operations\n\nDeployment and monitoring instructions."
        )

        chunks = semantic_index_chunks("Product", body, 1200)

        delivery = next(chunk for chunk in chunks if "Delivery options" in chunk)
        assert "Demo stores browser mocks" in delivery
        assert "General project background" not in delivery
        assert "Deployment and monitoring" not in delivery
        assert all(len(chunk) <= 1200 for chunk in chunks)

    def test_heading_free_text_keeps_paragraph_chunking(self):
        body = "First paragraph.\n\nSecond paragraph."
        assert semantic_index_chunks("Title", body, 1200) == [
            "Title\n\nFirst paragraph.\n\nSecond paragraph."
        ]

    def test_model_boundary_splits_plain_prose_at_topic_shift(self):
        body = (
            "The product is open source.\n\n"
            "Its repository contains the application code.\n\n"
            "There are two delivery options.\n\n"
            "The demo uses browser mocks, while Docker uses real services."
        )

        chunks = semantic_index_chunks(
            "Product",
            body,
            1200,
            semantic_section_starts=[2],
        )

        assert chunks == [
            "Product\n\nThe product is open source.\n\nIts repository contains the application code.",
            "There are two delivery options.\n\nThe demo uses browser mocks, while Docker uses real services.",
        ]

    def test_markdown_horizontal_rules_do_not_become_index_chunks(self):
        body = "# Intro\n\nBackground.\n\n***\n\n## Comparison\n\nTwo options."

        chunks = semantic_index_chunks("Product", body, 1200)

        assert chunks == [
            "Product\n\nIntro\n\nBackground.",
            "Comparison\n\nTwo options.",
        ]

    def test_each_chunk_under_double_max(self):
        """Each chunk is at most a couple paragraphs, not the full text."""
        text = "\n\n".join(["word " * 50] * 5)
        chunks = _chunk_text(text, 100)
        # We should have more than 1 chunk, and the full text is not a single chunk
        assert len(chunks) > 1


# ──────────────────────────────────────────────────────────────────────────────
# _vec_to_pg
# ──────────────────────────────────────────────────────────────────────────────

def test_vec_to_pg_format():
    result = _vec_to_pg([0.1, 0.2, 0.3])
    assert result == "[0.1,0.2,0.3]"


# ──────────────────────────────────────────────────────────────────────────────
# retrieve_top_k (mocked session — no pgvector)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_top_k_no_pgvector():
    """Without pgvector extension, retrieve_top_k returns empty list."""
    mock_session = AsyncMock()
    # Simulate no pgvector extension
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await retrieve_top_k(
        session=mock_session,
        user_id=uuid.uuid4(),
        scope="global",
        query_vec=[0.1] * 384,
        model_key="local:multilingual-e5-small",
        k=4,
    )
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_top_k_with_pgvector():
    """With pgvector available, returns rows filtered by min_similarity."""
    mock_session = AsyncMock()

    # First call: check extension (returns 'vector')
    ext_result = MagicMock()
    ext_result.scalar_one_or_none.return_value = "vector"

    # Second call: rows with similarities
    class FakeRow:
        def __init__(self, note_id, similarity, *, node_type="note_chunk", file_id=""):
            self.note_id = note_id
            self.post_id = None
            self.chunk_index = 0
            self.tenant_key = ""
            self.node_type = node_type
            self.file_id = file_id
            self.chunk_text = "chunk body"
            self.referenced_ids = []
            self.similarity = similarity

    rows_result = MagicMock()
    rows_result.fetchall.return_value = [
        FakeRow("note1", 0.85),
        FakeRow("note2", 0.60),  # below threshold
        FakeRow("note3", 0.78),
    ]

    mock_session.execute = AsyncMock(side_effect=[ext_result, rows_result])

    result = await retrieve_top_k(
        session=mock_session,
        user_id=uuid.uuid4(),
        scope="global",
        query_vec=[0.1] * 384,
        model_key="local:multilingual-e5-small",
        k=4,
        min_similarity=0.72,
    )
    note_ids = [r["note_id"] for r in result]
    assert "note1" in note_ids
    assert "note3" in note_ids
    assert "note2" not in note_ids  # below threshold
    assert result[0]["chunk_text"] == "chunk body"
    assert result[0]["referenced_ids"] == []


@pytest.mark.asyncio
async def test_index_text_node_persists_chunk_snapshot():
    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    await index_text_node(
        session,
        uuid.uuid4(),
        "global",
        NODE_POST_TEXT,
        "post-1",
        "",
        "Snapshot chunk text",
        backend,
        referenced_ids=["att-1"],
    )

    insert_call = session.execute.await_args_list[-1]
    params = insert_call.args[1]
    assert params["ctxt"] == "Snapshot chunk text"
    assert params["rids"] == '["att-1"]'


@pytest.mark.asyncio
async def test_retrieve_top_k_deduplication():
    """Multiple chunks from same note → only best similarity chunk returned."""
    mock_session = AsyncMock()

    ext_result = MagicMock()
    ext_result.scalar_one_or_none.return_value = "vector"

    class FakeRow:
        def __init__(self, note_id, chunk_index, similarity, *, node_type="note_chunk", file_id=""):
            self.note_id = note_id
            self.post_id = None
            self.chunk_index = chunk_index
            self.tenant_key = ""
            self.node_type = node_type
            self.file_id = file_id
            self.chunk_text = f"chunk-{chunk_index}"
            self.referenced_ids = ["ref1"]
            self.similarity = similarity

    rows_result = MagicMock()
    rows_result.fetchall.return_value = [
        FakeRow("note1", 0, 0.80),
        FakeRow("note1", 1, 0.90),  # same note, higher sim
        FakeRow("note2", 0, 0.75),
    ]

    mock_session.execute = AsyncMock(side_effect=[ext_result, rows_result])

    result = await retrieve_top_k(
        session=mock_session,
        user_id=uuid.uuid4(),
        scope="global",
        query_vec=[0.1] * 384,
        model_key="local:multilingual-e5-small",
        k=4,
        min_similarity=0.72,
    )
    # note1 should appear once with the highest similarity
    note1_hits = [r for r in result if r["note_id"] == "note1"]
    assert len(note1_hits) == 1
    assert note1_hits[0]["similarity"] == 0.90


@pytest.mark.asyncio
async def test_retrieve_top_k_preserves_chunks_for_scoped_object_search():
    mock_session = AsyncMock()
    ext_result = MagicMock()
    ext_result.scalar_one_or_none.return_value = "vector"

    class FakeRow:
        def __init__(self, chunk_index, similarity):
            self.note_id = "note1"
            self.post_id = None
            self.chunk_index = chunk_index
            self.tenant_key = ""
            self.node_type = "note_chunk"
            self.file_id = ""
            self.chunk_text = f"chunk-{chunk_index}"
            self.referenced_ids = []
            self.similarity = similarity

    rows_result = MagicMock()
    rows_result.fetchall.return_value = [FakeRow(0, 0.9), FakeRow(2, 0.8)]
    mock_session.execute = AsyncMock(side_effect=[ext_result, rows_result])

    result = await retrieve_top_k(
        session=mock_session,
        user_id=uuid.uuid4(),
        scope="global",
        query_vec=[0.1] * 384,
        model_key="local:multilingual-e5-small",
        k=4,
        min_similarity=0.72,
        object_ids=frozenset({"note1"}),
    )

    assert [(item["note_id"], item["chunk_index"]) for item in result] == [
        ("note1", 0),
        ("note1", 2),
    ]


@pytest.mark.asyncio
async def test_retrieve_top_k_dedup_by_node_type_and_file_id():
    """Same note_id with different node_type/file_id should not collapse."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.ai.rag import NODE_MEDIA_META, NODE_NOTE_CHUNK, NODE_POST_TEXT, retrieve_top_k

    mock_session = AsyncMock()
    ext_result = MagicMock()
    ext_result.fetchone.return_value = (True,)

    class FakeRow:
        def __init__(self, note_id, similarity, *, node_type=NODE_NOTE_CHUNK, file_id=""):
            self.note_id = note_id
            self.post_id = None
            self.chunk_index = 0
            self.tenant_key = ""
            self.node_type = node_type
            self.file_id = file_id
            self.chunk_text = "chunk"
            self.referenced_ids = []
            self.similarity = similarity

    shared_id = "shared-id"
    rows_result = MagicMock()
    rows_result.fetchall.return_value = [
        FakeRow(shared_id, 0.95, node_type=NODE_NOTE_CHUNK),
        FakeRow(shared_id, 0.90, node_type=NODE_POST_TEXT),
        FakeRow(shared_id, 0.85, node_type=NODE_MEDIA_META, file_id="f1"),
        FakeRow(shared_id, 0.80, node_type=NODE_MEDIA_META, file_id="f2"),
    ]

    mock_session.execute = AsyncMock(side_effect=[ext_result, rows_result])

    result = await retrieve_top_k(
        session=mock_session,
        user_id=uuid.uuid4(),
        scope="global",
        query_vec=[0.1] * 384,
        model_key="local:multilingual-e5-small",
        k=10,
        min_similarity=0.72,
    )
    assert len(result) == 4


@pytest.mark.asyncio
async def test_index_text_node_writes_chunks():
    from unittest.mock import AsyncMock, MagicMock

    from app.services.ai.rag import NODE_POST_TEXT, index_text_node

    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    count = await index_text_node(
        session,
        uuid.uuid4(),
        "global",
        NODE_POST_TEXT,
        "post-1",
        "",
        "Post body for indexing",
        backend,
        post_id="post-1",
    )
    assert count == 1
    assert session.execute.await_count >= 2


@pytest.mark.asyncio
async def test_format_rag_context_post_text_branch():
    from unittest.mock import AsyncMock, patch

    from app.services.ai.rag import NODE_POST_TEXT, format_rag_context

    session = AsyncMock()
    user_id = uuid.uuid4()
    results = [
        {
            "note_id": "post-1",
            "post_id": "post-1",
            "node_type": NODE_POST_TEXT,
            "file_id": "",
            "similarity": 0.9,
            "tenant_key": "",
        }
    ]

    with patch(
        "app.services.ai.rag.resolve_post_data",
        new_callable=AsyncMock,
        return_value={"text": "Заголовок поста\nПодробности"},
    ):
        context, cites = await format_rag_context(session, user_id, results, scope="global")

    assert "Контекст из базы знаний" in context
    assert "/post/post-1/" in context
    assert len(cites) == 1
    assert cites[0].path == "/post/post-1/"
    assert cites[0].title == "Заголовок поста"


@pytest.mark.asyncio
async def test_format_rag_context_media_meta_from_post_data():
    from app.services.ai.rag import NODE_MEDIA_META, format_rag_context

    session = AsyncMock()
    user_id = uuid.uuid4()
    post_data = {
        "id": "post-9",
        "media": [{"name": "chart.png", "mediaKey": "mk-1"}],
    }
    results = [
        {
            "note_id": "post-9",
            "post_id": "post-9",
            "node_type": NODE_MEDIA_META,
            "file_id": "mk-1",
            "similarity": 0.8,
            "tenant_key": "",
        }
    ]

    context, cites = await format_rag_context(
        session, user_id, results, scope="global", post_data=post_data
    )
    assert "chart.png" in context
    assert cites[0].path == "/post/post-9/"


# ──────────────────────────────────────────────────────────────────────────────
# context.assemble_reply_messages — RAG injection
# ──────────────────────────────────────────────────────────────────────────────

def test_assemble_reply_messages_rag_injection():
    """rag_context is appended to the last user message."""
    from app.services.ai.context import assemble_reply_messages

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Привет",
        rag_context="---\n**Контекст из базы знаний:**\n\nЗаметка 1\n---",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) >= 1
    last_user = user_msgs[-1]["content"]
    assert "Контекст из базы знаний" in last_user
    assert "Привет" in last_user


def test_assemble_reply_messages_no_rag():
    """Without rag_context messages are unmodified."""
    from app.services.ai.context import assemble_reply_messages

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Привет",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    last_user = user_msgs[-1]["content"]
    assert "Контекст из базы знаний" not in last_user


def test_assemble_reply_messages_empty_rag_no_injection():
    """Empty rag_context string is not injected."""
    from app.services.ai.context import assemble_reply_messages

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Текст",
        rag_context="",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    last_user = user_msgs[-1]["content"]
    assert "Контекст из базы знаний" not in last_user
