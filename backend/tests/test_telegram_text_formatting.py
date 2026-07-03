"""Tests for Telegram message text formatting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.telegram.text_formatting import (
    apply_message_text_fields,
    message_to_text_html,
)

pytest.importorskip("telethon")

from telethon.tl.types import MessageEntityBold, MessageEntityItalic, MessageEntityStrike


def test_message_to_text_html_bold_and_strike() -> None:
    message = SimpleNamespace(
        message="bold and strike",
        entities=[
            MessageEntityBold(offset=0, length=4),
            MessageEntityStrike(offset=9, length=6),
        ],
    )
    html = message_to_text_html(message)
    assert html is not None
    assert "<strong>bold</strong>" in html
    assert "<s>strike</s>" in html


def test_message_to_text_html_plain_without_entities() -> None:
    message = SimpleNamespace(message="plain text", entities=[])
    assert message_to_text_html(message) is None


def test_apply_message_text_fields_sets_and_clears_html() -> None:
    message = SimpleNamespace(
        message="hello",
        entities=[MessageEntityItalic(offset=0, length=5)],
    )
    payload: dict[str, str] = {"textHtml": "old"}
    apply_message_text_fields(payload, message)
    assert payload["text"] == "hello"
    assert "textHtml" in payload

    plain = SimpleNamespace(message="plain", entities=[])
    apply_message_text_fields(payload, plain)
    assert payload["text"] == "plain"
    assert "textHtml" not in payload
