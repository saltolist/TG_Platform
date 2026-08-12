"""Tests for Telegram message text formatting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.telegram.text_formatting import (
    apply_message_text_fields,
    message_to_text_html,
)

pytest.importorskip("telethon")

from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntitySpoiler,
    MessageEntityStrike,
)


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
    assert ("<s>strike</s>" in html or "<del>strike</del>" in html)


def test_message_to_text_html_spoiler() -> None:
    message = SimpleNamespace(
        message="visible hidden text",
        entities=[MessageEntitySpoiler(offset=8, length=6)],
    )
    html = message_to_text_html(message)
    assert html is not None
    assert '<span class="tg-spoiler">hidden</span>' in html


def test_message_to_text_html_bold_and_spoiler() -> None:
    message = SimpleNamespace(
        message="bold hidden",
        entities=[
            MessageEntityBold(offset=0, length=4),
            MessageEntitySpoiler(offset=5, length=6),
        ],
    )
    html = message_to_text_html(message)
    assert html is not None
    assert "<strong>bold</strong>" in html
    assert '<span class="tg-spoiler">hidden</span>' in html


def test_message_to_text_html_plain_without_entities() -> None:
    message = SimpleNamespace(message="plain text", entities=[])
    assert message_to_text_html(message) is None


def test_message_to_text_html_preserves_line_breaks() -> None:
    message = SimpleNamespace(
        message="first line\nsecond line",
        entities=[MessageEntityBold(offset=0, length=10)],
    )
    html = message_to_text_html(message)
    assert html is not None
    assert "<br>" in html
    assert "first line" in html
    assert "second line" in html


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


def test_normalize_platform_text_html_accepts_bold_markup() -> None:
    from app.services.telegram.text_formatting import (
        apply_platform_text_fields,
        normalize_platform_text_html,
        post_formatting_entities_from_payload,
    )

    text, html, entities = normalize_platform_text_html(
        "bold text", "<strong>bold</strong> text"
    )
    assert text == "bold text"
    assert html is not None
    assert "<strong>bold</strong>" in html
    assert entities

    payload = {"text": "bold text", "textHtml": "<strong>bold</strong> text"}
    apply_platform_text_fields(payload)
    assert payload["textHtml"] == html
    assert post_formatting_entities_from_payload(payload)


def test_normalize_platform_text_html_accepts_custom_emoji() -> None:
    from app.services.telegram.text_formatting import (
        apply_platform_text_fields,
        normalize_platform_text_html,
        post_formatting_entities_from_payload,
    )

    text_html = '<tg-emoji emoji-id="12345">⭐</tg-emoji> nice'
    text, html, entities = normalize_platform_text_html("⭐ nice", text_html)
    assert text == "⭐ nice"
    assert html is not None
    assert "tg-emoji" in html
    assert entities

    payload = {"text": "⭐ nice", "textHtml": text_html}
    apply_platform_text_fields(payload)
    assert payload["textHtml"] == html
    parsed_entities = post_formatting_entities_from_payload(payload)
    assert parsed_entities
    assert any(
        getattr(entity, "document_id", None) == 12345 for entity in parsed_entities
    )


def test_normalize_platform_text_html_rejects_mismatched_plain_text() -> None:
    from app.services.telegram.text_formatting import normalize_platform_text_html

    text, html, entities = normalize_platform_text_html(
        "plain", "<strong>different</strong>"
    )
    assert text == "plain"
    assert html is None
    assert entities is None


# --- stored_fields_from_platform_html: agent-authored Telegram HTML (chat 49a569c8) ---


def test_stored_fields_from_platform_html_derives_text_and_keeps_formatting() -> None:
    from app.services.telegram.text_formatting import stored_fields_from_platform_html

    text, html = stored_fields_from_platform_html("<strong>Заголовок</strong><br>абзац")
    assert text == "Заголовок\nабзац"
    assert html == "<strong>Заголовок</strong><br>абзац"


def test_stored_fields_from_platform_html_preserves_custom_emoji() -> None:
    from app.services.telegram.text_formatting import stored_fields_from_platform_html

    text, html = stored_fields_from_platform_html(
        'Привет <tg-emoji emoji-id="5789">⭐</tg-emoji> мир'
    )
    assert text == "Привет ⭐ мир"
    assert html is not None
    assert 'tg-emoji emoji-id="5789"' in html


def test_stored_fields_from_platform_html_drops_html_without_formatting() -> None:
    from app.services.telegram.text_formatting import stored_fields_from_platform_html

    text, html = stored_fields_from_platform_html("Просто обычный текст без тегов")
    assert text == "Просто обычный текст без тегов"
    assert html is None


def test_stored_fields_from_platform_html_falls_back_on_broken_html() -> None:
    from app.services.telegram.text_formatting import stored_fields_from_platform_html

    # Unclosed tag: Telethon's parser still recovers *some* plain text (it does
    # not raise), so the fallback path is the "no real formatting survives"
    # branch, not the except-Exception branch — both must yield html=None.
    text, html = stored_fields_from_platform_html("<strong>непарный тег")
    assert html is None
    assert "непарный тег" in text


def test_stored_fields_from_platform_html_empty_input() -> None:
    from app.services.telegram.text_formatting import stored_fields_from_platform_html

    assert stored_fields_from_platform_html("") == ("", None)
    assert stored_fields_from_platform_html("   ") == ("", None)
