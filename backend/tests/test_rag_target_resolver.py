"""Tests for LLM target post resolver."""

from __future__ import annotations

from app.services.ai.rag_retrieval_brief import build_retrieval_brief
from app.services.ai.rag_target_resolver import (
    format_catalog_for_planner,
    parse_target_resolution,
)


def test_format_catalog_for_planner() -> None:
    text = format_catalog_for_planner(
        [
            {
                "id": "3",
                "text": "Приветствую 👋",
                "status": "published",
                "notes_count": 0,
            }
        ]
    )
    assert "post_id=3" in text
    assert "Приветствую" in text


def test_parse_target_resolution_validates_catalog_id() -> None:
    resolution = parse_target_resolution(
        '{"post_id": "999", "rationale": "test", "confidence": "high"}',
        catalog_posts=[{"id": "3", "text": "Приветствую 👋"}],
    )
    assert resolution.post_id is None
    assert resolution.confidence == "none"


def test_parse_target_resolution_accepts_catalog_post() -> None:
    resolution = parse_target_resolution(
        '{"post_id": "3", "rationale": "welcome referent", "confidence": "high"}',
        catalog_posts=[{"id": "3", "text": "Приветствую 👋"}],
    )
    assert resolution.post_id == "3"
    assert resolution.is_confident


def test_parse_target_resolution_unknown_confidence_becomes_none_without_post() -> None:
    resolution = parse_target_resolution(
        '{"post_id": null, "rationale": "ambiguous", "confidence": "low"}',
        catalog_posts=[{"id": "3", "text": "Приветствую 👋"}],
    )
    assert resolution.post_id is None
    assert resolution.confidence == "none"


def test_build_retrieval_brief_still_marks_named_post_query() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu постu, которым я приветствую читателей?",
        scope="global",
    )
    assert brief.named_post_query
    assert brief.task == "comparative_visual"
