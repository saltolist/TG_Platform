"""Tests for live-sync content comparison helpers."""

from __future__ import annotations

from app.services.telegram.post_sync import _content_unchanged

def test_content_unchanged_detects_text_html_change() -> None:
    existing = {
        "text": "same text",
        "textHtml": "<strong>same text</strong>",
        "media": [],
        "metrics": {"views": "1", "reposts": 0, "reactions": []},
    }
    incoming = {
        "text": "same text",
        "textHtml": "<em>same text</em>",
        "media": [],
        "metrics": {"views": "1", "reposts": 0, "reactions": []},
    }
    assert _content_unchanged(existing, incoming) is False


def test_content_unchanged_ignores_matching_text_html() -> None:
    payload = {
        "text": "hello",
        "textHtml": "<strong>hello</strong>",
        "media": [],
        "metrics": {"views": "1", "reposts": 0, "reactions": []},
    }
    assert _content_unchanged(payload, dict(payload)) is True


def test_content_unchanged_detects_comment_thread_flag_change() -> None:
    existing = {
        "text": "hello",
        "textHtml": "<strong>hello</strong>",
        "media": [],
        "metrics": {"views": "1", "reposts": 0, "reactions": []},
    }
    incoming = {
        **existing,
        "commentsThreadLiveOptimistic": True,
        "commentsThreadAvailable": True,
    }
    assert _content_unchanged(existing, incoming) is False
