"""Tests for structural-neighbor manifest builder."""

from __future__ import annotations

from app.services.ai.rag_manifest import build_post_manifest


def test_build_post_manifest_full() -> None:
    manifest = build_post_manifest(
        {
            "id": "post-1",
            "notes": [{"id": "n1", "title": "Черновик"}],
            "media": [{"name": "cover.jpg", "mediaKey": "mk-1"}],
            "comments": [{"text": "ok"}, {"text": "nice"}],
        }
    )
    assert manifest == {
        "notes": [{"id": "n1", "title": "Черновик"}],
        "media": [{"id": "mk-1", "name": "cover.jpg"}],
        "comments_count": 2,
    }


def test_build_post_manifest_empty_post() -> None:
    assert build_post_manifest({}) == {
        "notes": [],
        "media": [],
        "comments_count": 0,
    }


def test_build_post_manifest_skips_invalid_entries() -> None:
    manifest = build_post_manifest(
        {
            "notes": ["bad", {"id": "", "title": "X"}, {"id": "n2", "title": ""}],
            "media": [None, {"name": "a.png"}],
            "comments": None,
        }
    )
    assert manifest["notes"] == [{"id": "n2", "title": "n2"}]
    assert manifest["media"] == [{"id": "idx-1", "name": "a.png"}]
    assert manifest["comments_count"] == 0
