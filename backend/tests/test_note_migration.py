"""Tests for note body migration: legacy [name] tokens → CommonMark markdown."""

import pytest

from scripts.migrate_notes_to_markdown import migrate_note_body


FILES = [
    {"id": "img1", "name": "photo.jpg", "type": "image/jpeg", "url": "http://x/photo.jpg"},
    {"id": "doc1", "name": "report.pdf", "type": "application/pdf", "url": "http://x/report.pdf"},
]


def test_plain_text_no_tokens():
    body = "Hello world, no embeds here."
    new_body, new_files = migrate_note_body(body, [])
    assert new_body == body


def test_already_markdown_skipped():
    body = "![photo](attachment:img1)"
    new_body, new_files = migrate_note_body(body, FILES)
    assert new_body == body


def test_image_token_converted():
    body = "See [photo.jpg] for details."
    new_body, _ = migrate_note_body(body, FILES)
    assert "![photo.jpg](attachment:img1)" in new_body
    assert "[photo.jpg]" not in new_body.replace("![photo.jpg](attachment:img1)", "")


def test_file_token_converted():
    body = "Download [report.pdf] here."
    new_body, _ = migrate_note_body(body, FILES)
    assert "[report.pdf](attachment:doc1)" in new_body
    # must NOT have ! prefix (not an image)
    assert "![report.pdf]" not in new_body


def test_unknown_token_kept_escaped():
    body = "Missing [unknown.png] file."
    new_body, _ = migrate_note_body(body, FILES)
    # token with no matching file → escaped literal
    assert "attachment:" not in new_body
    assert "unknown.png" in new_body


def test_markdown_special_chars_escaped_in_plain_text():
    body = "Price: *100* | #tag"
    new_body, _ = migrate_note_body(body, [])
    assert "\\*100\\*" in new_body
    assert "\\#tag" in new_body
    assert "\\|" in new_body


def test_file_id_assigned_if_missing():
    files = [{"name": "photo.jpg", "type": "image/jpeg", "url": "http://x/photo.jpg"}]
    body = "[photo.jpg]"
    _, new_files = migrate_note_body(body, files)
    assert new_files[0].get("id")


def test_existing_file_id_preserved():
    body = "[photo.jpg]"
    new_body, new_files = migrate_note_body(body, FILES)
    assert new_files[0]["id"] == "img1"


def test_multiple_tokens():
    body = "[photo.jpg] and [report.pdf]"
    new_body, _ = migrate_note_body(body, FILES)
    assert "![photo.jpg](attachment:img1)" in new_body
    assert "[report.pdf](attachment:doc1)" in new_body


def test_image_row_preserved_as_adjacent_lines():
    """Adjacent image tokens on separate lines → adjacent markdown image lines."""
    body = "[photo.jpg]\n[photo.jpg]"
    new_body, _ = migrate_note_body(body, FILES)
    lines = new_body.strip().splitlines()
    assert all("attachment:img1" in line for line in lines)


def test_empty_body():
    new_body, _ = migrate_note_body("", [])
    assert new_body == ""


def test_none_files_treated_as_empty():
    body = "Hello"
    new_body, new_files = migrate_note_body(body, [])
    assert new_body == "Hello"
    assert new_files == []


def test_idempotent_already_converted():
    """Running migration twice must not double-escape or re-convert."""
    body = "[photo.jpg] text"
    new_body1, files1 = migrate_note_body(body, FILES)
    new_body2, files2 = migrate_note_body(new_body1, files1)
    assert new_body1 == new_body2
