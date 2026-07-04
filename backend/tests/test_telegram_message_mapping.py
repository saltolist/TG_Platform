"""Tests for Telegram message mapping helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.telegram.message_mapping import should_defer_media_fetch


def test_should_defer_media_fetch_only_for_captioned_new_posts() -> None:
    captioned = SimpleNamespace(message="hello", media=object())
    media_only = SimpleNamespace(message="", media=object())
    text_only = SimpleNamespace(message="hello", media=None)

    assert should_defer_media_fetch([captioned], update=False) is True
    assert should_defer_media_fetch([media_only], update=False) is False
    assert should_defer_media_fetch([text_only], update=False) is False
    assert should_defer_media_fetch([captioned], update=True) is False
