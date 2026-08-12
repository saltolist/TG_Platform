"""Phase 4: discovery summaries and contextual candidate-first retrieval."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.research.prefetch import retrieve_for_discovery
from app.services.agent.research.search_ledger import canonical_tool_signature
from app.services.ai.rag import (
    NODE_NOTE_SUMMARY,
    NODE_POST_TEXT,
    build_discovery_summary,
    contextualize_chunk,
    discovery_keywords,
    format_rag_context,
    index_text_node,
    object_index_revision,
    retrieve_top_k,
)
from app.services.ai.semantic_summary import DISCOVERY_SUMMARY_VERSION


def _hit(node_type: str, object_id: str, score: float, **extra) -> dict:
    return {
        "node_type": node_type,
        "note_id": object_id,
        "post_id": extra.pop("post_id", ""),
        "file_id": "",
        "similarity": score,
        "blended_score": score,
        **extra,
    }


def test_summary_fallback_is_bounded_and_revision_changes_with_content() -> None:
    summary = build_discovery_summary("Редакционная политика", "слово " * 80)
    assert summary.startswith("Редакционная политика:")
    assert len(summary) <= 160
    assert summary.endswith("…")
    assert object_index_revision({"id": "n1", "body": "old"}) != object_index_revision(
        {"id": "n1", "body": "new"}
    )
    assert object_index_revision({"revision": 7, "body": "ignored"}) == 7
    keywords = discovery_keywords("Политика политика Редакционная запуск сроки аудит")
    assert keywords == ["политика", "редакционная", "запуск", "сроки", "аудит"]


def test_contextual_chunk_keeps_original_source_separate() -> None:
    original = "Первичный текст с важной редкой деталью."
    contextual = contextualize_chunk(
        original,
        object_type="note_chunk",
        title="Политика",
        section="Ограничения",
    )
    assert "Document: note Политика." in contextual
    assert "Section: Ограничения." in contextual
    assert contextual.endswith(original)


@pytest.mark.asyncio
async def test_indexing_embeds_context_but_persists_original_chunk() -> None:
    session = AsyncMock()
    backend = MagicMock(model_key="local:test", dim=2)
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2]])

    await index_text_node(
        session,
        uuid.uuid4(),
        "global",
        NODE_POST_TEXT,
        "p1",
        "",
        "Исходный фрагмент",
        backend,
        object_title="Релиз",
        object_status="published",
        index_revision=4,
    )

    embedded = backend.embed_passages.await_args.args[0][0]
    assert embedded.startswith("Document: post Релиз.")
    insert_params = session.execute.await_args_list[-1].args[1]
    assert insert_params["ctxt"] == "Исходный фрагмент"
    assert insert_params["stxt"] == embedded
    assert insert_params["ostatus"] == "published"
    assert insert_params["irev"] == 4
    assert insert_params["keywords"] == '["релиз"]'


@pytest.mark.asyncio
async def test_candidate_first_fuses_summary_and_context_and_supports_quota_sweep_to_ten() -> None:
    backend = AsyncMock()
    backend.embed_query.return_value = [0.1, 0.2]
    summary = [_hit(NODE_NOTE_SUMMARY, f"n{i}", 1 - i / 20) for i in range(8)]
    contextual = [
        _hit("note_chunk", "n0", 0.99),
        _hit("note_chunk", "rare", 0.80),
    ]
    with patch(
        "app.services.agent.research.prefetch.hybrid_prefetch",
        new_callable=AsyncMock,
        side_effect=[summary, contextual],
    ) as hybrid:
        results = await retrieve_for_discovery(
            session=AsyncMock(),
            user_id=uuid.uuid4(),
            scope="global",
            query_text="редкая деталь",
            embedding_backend=backend,
            tenant_key=None,
            candidate_limit=99,
        )

    assert len(results) == 9
    assert len({item["note_id"] for item in results}) == 9
    assert results[0]["note_id"] == "n0"
    assert "context" in results[0]["sources"]
    assert hybrid.await_count == 2
    backend.embed_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_contextual_discovery_hit_is_promoted_to_existing_llm_card() -> None:
    backend = AsyncMock()
    backend.embed_query.return_value = [0.1, 0.2]
    chunk = _hit(
        "note_chunk",
        "n1",
        0.83,
        chunk_text="Сырой фрагмент заметки",
        index_revision=7,
    )
    card = {
        "ref": "note:n1",
        "label": "note:n1",
        "similarity": 1.0,
        "node_type": NODE_NOTE_SUMMARY,
        "summary_only": True,
        "index_revision": 7,
        "source_revision": 7,
        "summary_version": DISCOVERY_SUMMARY_VERSION,
        "summary_model": f"llm:OpenAI:gpt-4.1-mini:v{DISCOVERY_SUMMARY_VERSION}",
        "title": "Заметка",
        "preview": "Готовая смысловая карточка",
        "status": "active",
        "parent_post_id": None,
        "has_more": False,
        "source_requirement_id": "",
    }
    with (
        patch(
            "app.services.agent.research.prefetch.hybrid_prefetch",
            new_callable=AsyncMock,
            side_effect=[[], [chunk]],
        ),
        patch(
            "app.services.agent.research.prefetch.resolve_current_source_revisions",
            new_callable=AsyncMock,
            return_value={"n1": 7},
        ),
        patch(
            "app.services.agent.research.prefetch.load_discovery_cards_for_objects",
            new_callable=AsyncMock,
            return_value=[card],
        ) as load_cards,
    ):
        results = await retrieve_for_discovery(
            session=AsyncMock(),
            user_id=uuid.uuid4(),
            scope="global",
            query_text="следующая тема",
            embedding_backend=backend,
            tenant_key=None,
        )

    assert results[0]["node_type"] == NODE_NOTE_SUMMARY
    assert results[0]["preview"] == "Готовая смысловая карточка"
    assert results[0]["summary_model"] == (
        f"llm:OpenAI:gpt-4.1-mini:v{DISCOVERY_SUMMARY_VERSION}"
    )
    assert results[0]["similarity"] == 0.83
    load_cards.assert_awaited_once()


@pytest.mark.asyncio
async def test_chunk_search_requires_and_filters_to_selected_objects() -> None:
    backend = AsyncMock()
    backend.embed_query.return_value = [0.1]
    with patch(
        "app.services.agent.research.prefetch.hybrid_prefetch",
        new_callable=AsyncMock,
        return_value=[_hit("note_chunk", "n2", 0.9)],
    ) as hybrid:
        results = await retrieve_for_discovery(
            session=AsyncMock(),
            user_id=uuid.uuid4(),
            scope="global",
            query_text="деталь",
            embedding_backend=backend,
            tenant_key=None,
            selected_object_ids=frozenset({"n1", "n2"}),
        )

    assert [item["note_id"] for item in results] == ["n2"]
    assert hybrid.await_args.kwargs["object_ids"] == frozenset({"n1", "n2"})
    assert hybrid.await_args.kwargs["node_types_filter"] == frozenset(
        {"note_chunk", "post_text"}
    )


@pytest.mark.asyncio
async def test_stale_index_revision_is_filtered_before_return() -> None:
    session = AsyncMock()
    extension = MagicMock()
    extension.scalar_one_or_none.return_value = "vector"

    class Row:
        def __init__(self, object_id: str, revision: int):
            self.note_id = object_id
            self.post_id = None
            self.chunk_index = 0
            self.tenant_key = ""
            self.node_type = NODE_NOTE_SUMMARY
            self.file_id = ""
            self.chunk_text = "summary"
            self.search_text = "summary"
            self.referenced_ids = []
            self.scope = "global"
            self.object_title = "Title"
            self.object_status = "active"
            self.index_revision = revision
            self.similarity = 0.9

    rows = MagicMock()
    rows.fetchall.return_value = [Row("stale", 2), Row("fresh", 3)]
    session.execute.side_effect = [extension, rows]
    results = await retrieve_top_k(
        session,
        uuid.uuid4(),
        "global",
        [0.1],
        "local:test",
        min_similarity=0.1,
        expected_revisions={"stale": 3, "fresh": 3},
    )
    assert [item["note_id"] for item in results] == ["fresh"]


@pytest.mark.asyncio
async def test_summary_nodes_cannot_be_formatted_as_answer_evidence() -> None:
    context, cites = await format_rag_context(
        AsyncMock(),
        uuid.uuid4(),
        [
            {
                "node_type": NODE_NOTE_SUMMARY,
                "note_id": "n1",
                "chunk_text": "discovery only",
            }
        ],
        "global",
    )
    assert context == ""
    assert cites == []


def test_selected_chunk_signature_is_order_independent_and_revision_scoped() -> None:
    contract = {"target_contract": {"revision": 4}, "source_requirements": []}
    first = canonical_tool_signature(
        "SearchObjectChunks",
        {"query": "деталь", "object_ids": ["n2", "n1"]},
        source_requirement_id="unscoped",
        contract=contract,
    )
    second = canonical_tool_signature(
        "SearchObjectChunks",
        {"query": " ДЕТАЛЬ ", "object_ids": ["n1", "n2"]},
        source_requirement_id="unscoped",
        contract=contract,
    )
    assert first == second
