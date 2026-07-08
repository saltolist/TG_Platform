"""Tests for structural-neighbor manifest builder."""

from __future__ import annotations

from app.services.ai.rag_manifest import build_post_manifest, filter_unopened_neighbors


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


def test_filter_unopened_neighbors_nothing_opened() -> None:
    manifest = {
        "notes": [{"id": "n1", "title": "A"}, {"id": "n2", "title": "B"}],
        "media": [{"id": "m1", "name": "pic.png"}],
        "comments_count": 3,
    }
    filtered = filter_unopened_neighbors(manifest, [])
    assert filtered == manifest


def test_filter_unopened_neighbors_note_already_opened() -> None:
    manifest = {
        "notes": [{"id": "n1", "title": "A"}, {"id": "n2", "title": "B"}],
        "media": [],
        "comments_count": 0,
    }
    results = [{"node_type": "note_chunk", "note_id": "n1", "file_id": ""}]
    filtered = filter_unopened_neighbors(manifest, results)
    assert filtered["notes"] == [{"id": "n2", "title": "B"}]


def test_filter_unopened_neighbors_media_already_opened() -> None:
    manifest = {
        "notes": [],
        "media": [{"id": "m1", "name": "a.png"}, {"id": "m2", "name": "b.png"}],
        "comments_count": 1,
    }
    results = [{"node_type": "media_meta", "note_id": "post-1", "file_id": "m1"}]
    filtered = filter_unopened_neighbors(manifest, results)
    assert filtered["media"] == [{"id": "m2", "name": "b.png"}]
    assert filtered["comments_count"] == 1


def test_filter_unopened_neighbors_empty_manifest() -> None:
    assert filter_unopened_neighbors({}, []) == {
        "notes": [],
        "media": [],
        "comments_count": 0,
    }
