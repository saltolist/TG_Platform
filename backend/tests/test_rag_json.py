"""Tests for shared RAG JSON extraction."""

from __future__ import annotations

from app.services.ai.rag_json import extract_json_object


def test_extract_json_object_clean() -> None:
    assert extract_json_object('{"tool": "Stop"}') == {"tool": "Stop"}


def test_extract_json_object_from_fence() -> None:
    payload = extract_json_object('```\n{"sufficient": true}\n```')
    assert payload == {"sufficient": True}


def test_extract_json_object_garbage() -> None:
    assert extract_json_object("no json here") is None


def test_extract_json_object_nested_steps() -> None:
    raw = (
        '{"goal": "x", "steps": [{"tool": "OpenPost", "args": {"post_id": "3"}}]}'
    )
    assert extract_json_object(raw) == {
        "goal": "x",
        "steps": [{"tool": "OpenPost", "args": {"post_id": "3"}}],
    }
