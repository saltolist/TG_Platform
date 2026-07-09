"""Tests for cross-scope retrieval policy."""

from __future__ import annotations

from app.services.ai.rag import NODE_NOTE_CHUNK, NODE_POST_TEXT
from app.services.ai.rag_retrieval_policy import (
    RetrievalPass,
    effective_post_id,
    merge_hits,
    pools_for_chat,
    post_id_aliases,
)


def test_pools_for_global_chat() -> None:
    passes = pools_for_chat("global", None)
    assert len(passes) == 2
    assert passes[0].scope == "global"
    assert passes[0].is_home is True
    assert passes[1].scope == "post"


def test_pools_for_post_chat() -> None:
    passes = pools_for_chat("post", "post-1")
    assert len(passes) == 4
    assert passes[0].post_id == "post-1"
    assert passes[0].is_home is True
    assert passes[3].post_id_neq == "post-1"


def test_effective_post_id_prefers_data_id() -> None:
    assert (
        effective_post_id(
            {"id": "119"},
            "d7ecd734-87f9-40a6-87c8-ef0957dcc56a",
        )
        == "119"
    )


def test_post_id_aliases_include_row_and_data_ids() -> None:
    aliases = post_id_aliases(
        {"id": "119"},
        row_post_id="d7ecd734-87f9-40a6-87c8-ef0957dcc56a",
    )
    assert aliases == frozenset({"119", "d7ecd734-87f9-40a6-87c8-ef0957dcc56a"})


def test_merge_hits_prefers_home_scope_with_bias() -> None:
    home_pass = RetrievalPass(scope="post", post_id="p1", is_home=True)
    other_pass = RetrievalPass(scope="global", is_home=False)
    merged = merge_hits(
        [
            (
                other_pass,
                [
                    {
                        "node_type": NODE_NOTE_CHUNK,
                        "note_id": "g1",
                        "file_id": "",
                        "similarity": 0.50,
                    }
                ],
            ),
            (
                home_pass,
                [
                    {
                        "node_type": NODE_NOTE_CHUNK,
                        "note_id": "p1n",
                        "file_id": "",
                        "similarity": 0.48,
                    }
                ],
            ),
        ],
        scope_bias=0.04,
        k=2,
    )
    assert merged[0]["note_id"] == "p1n"
    assert merged[0]["similarity"] == 0.52


def test_merge_hits_dedup_keeps_best_score() -> None:
    pass_cfg = RetrievalPass(scope="global", is_home=True)
    merged = merge_hits(
        [
            (
                pass_cfg,
                [
                    {
                        "node_type": NODE_POST_TEXT,
                        "note_id": "p1",
                        "file_id": "",
                        "similarity": 0.6,
                    },
                    {
                        "node_type": NODE_POST_TEXT,
                        "note_id": "p1",
                        "file_id": "",
                        "similarity": 0.8,
                    },
                ],
            )
        ],
        scope_bias=0.0,
        k=1,
    )
    assert len(merged) == 1
    assert merged[0]["similarity"] == 0.8
