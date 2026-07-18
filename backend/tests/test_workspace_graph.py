"""Workspace graph and executor tests."""

from __future__ import annotations

import pytest

from app.services.agent.runtime.workspace_graph import build_workspace_graph


def test_build_workspace_graph_compiles() -> None:
    graph = build_workspace_graph()
    compiled = graph.compile()
    assert compiled is not None


@pytest.mark.asyncio
async def test_hybrid_prefetch_merge_dedupes() -> None:
    from app.services.agent.research.prefetch import merge_and_rerank

    vector = [
        {"node_type": "note_chunk", "note_id": "n1", "file_id": "", "post_id": "", "similarity": 0.8},
    ]
    fts = [
        {"node_type": "note_chunk", "note_id": "n1", "file_id": "", "post_id": "", "similarity": 0.6},
        {"node_type": "note_chunk", "note_id": "n2", "file_id": "", "post_id": "", "similarity": 0.5},
    ]
    merged = merge_and_rerank(vector_results=vector, fts_results=fts, top_k=4)
    assert len(merged) == 2
    assert merged[0]["note_id"] == "n1"
    assert "vector" in merged[0]["sources"]
    assert "fts" in merged[0]["sources"]


def test_golden_catalog_has_implemented_ids() -> None:
    from tests.golden_runner import implemented_scenario_ids

    ids = implemented_scenario_ids()
    assert ids == ["06", "11", "13"]
