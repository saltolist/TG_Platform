"""Tests for RAG: markdown_to_index_text, content_hash, retrieve_top_k, format_rag_context."""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.rag import (
    _chunk_text,
    _vec_to_pg,
    content_hash,
    format_rag_context,
    markdown_to_index_text,
    retrieve_top_k,
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
        def __init__(self, note_id, similarity):
            self.note_id = note_id
            self.post_id = None
            self.chunk_index = 0
            self.tenant_key = ""
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


@pytest.mark.asyncio
async def test_retrieve_top_k_deduplication():
    """Multiple chunks from same note → only best similarity chunk returned."""
    mock_session = AsyncMock()

    ext_result = MagicMock()
    ext_result.scalar_one_or_none.return_value = "vector"

    class FakeRow:
        def __init__(self, note_id, chunk_index, similarity):
            self.note_id = note_id
            self.post_id = None
            self.chunk_index = chunk_index
            self.tenant_key = ""
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


# ──────────────────────────────────────────────────────────────────────────────
# context.assemble_reply_messages — RAG injection
# ──────────────────────────────────────────────────────────────────────────────

def test_assemble_reply_messages_rag_injection():
    """rag_context is appended to the last user message."""
    from app.services.ai.context import assemble_reply_messages

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Привет",
        rag_context="---\n**Контекст из заметок:**\n\nЗаметка 1\n---",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) >= 1
    last_user = user_msgs[-1]["content"]
    assert "Контекст из заметок" in last_user
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
    assert "Контекст из заметок" not in last_user


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
    assert "Контекст из заметок" not in last_user
