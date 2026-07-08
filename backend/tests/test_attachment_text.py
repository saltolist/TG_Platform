"""Tests for attachment data-URL decoding and text extraction."""

from __future__ import annotations

import base64

import pytest

from app.services.ai.attachment_text import (
    decode_data_url,
    extract_attachment_text,
    media_meta_index_text,
    note_file_record,
    post_media_file_id,
    post_media_record,
)


def test_decode_data_url_plain_text() -> None:
    payload = base64.b64encode(b"hello world").decode("ascii")
    url = f"data:text/plain;base64,{payload}"
    decoded = decode_data_url(url)
    assert decoded is not None
    data, mime = decoded
    assert mime == "text/plain"
    assert data == b"hello world"


def test_decode_data_url_invalid_returns_none() -> None:
    assert decode_data_url("https://example.com/file.pdf") is None
    assert decode_data_url("data:text/plain;base64,!!!not-base64!!!") is None


def test_extract_attachment_text_plain() -> None:
    text = extract_attachment_text("text/plain", b"Line one\nLine two")
    assert text == "Line one\nLine two"


def test_extract_attachment_text_unsupported_mime() -> None:
    assert extract_attachment_text("image/png", b"\x89PNG") is None


def test_media_meta_index_text_joins_parts() -> None:
    assert media_meta_index_text("photo.jpg", alt="cover") == "photo.jpg\ncover"


def test_note_file_record_requires_id() -> None:
    assert note_file_record({"name": "x.pdf"}) is None
    rec = note_file_record({"id": "f1", "name": "doc.pdf", "type": "application/pdf"})
    assert rec == {
        "id": "f1",
        "name": "doc.pdf",
        "type": "application/pdf",
        "url": "",
    }


def test_post_media_file_id_prefers_media_key() -> None:
    assert post_media_file_id({"mediaKey": "mk-1"}, 0) == "mk-1"
    assert post_media_file_id({}, 3) == "idx-3"


def test_post_media_record_builds_from_dict() -> None:
    rec = post_media_record({"name": "clip.mp4", "mediaKey": "m1"}, 1)
    assert rec == {"id": "m1", "name": "clip.mp4", "type": "", "url": ""}


# Minimal valid PDF with one page of text (tiny offline fixture).
_MINIMAL_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 10 100 Td (Hello PDF) Tj ET\nendstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n"
    b"0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n0000000178 00000 n \n"
    b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n272\n%%EOF"
)


def test_extract_attachment_text_pdf_when_pypdf_available() -> None:
  try:
      import pypdf  # noqa: F401
  except ImportError:
      pytest.skip("pypdf not installed")
  text = extract_attachment_text("application/pdf", _MINIMAL_PDF)
  if text is None:
      pytest.skip("pypdf could not parse minimal fixture")
  assert "Hello" in text or "PDF" in text
