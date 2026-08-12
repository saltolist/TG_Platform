"""Extract plain text from note attachment data URLs (PDF, DOCX, plain text)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_DATA_URL_RE = re.compile(r"^data:([^;,]+)?(?:;base64)?,(.*)$", re.DOTALL | re.IGNORECASE)

_PDF_MIMES = frozenset({"application/pdf"})
_DOCX_MIMES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }
)
_TEXT_MIMES = frozenset({"text/plain", "text/markdown", "application/json"})


def bytes_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_data_url(url: str) -> tuple[bytes, str] | None:
    """Parse ``data:<mime>;base64,<payload>`` into raw bytes and mime type."""
    raw = (url or "").strip()
    if not raw.startswith("data:"):
        return None
    match = _DATA_URL_RE.match(raw)
    if match is None:
        return None
    mime = (match.group(1) or "application/octet-stream").strip().lower()
    payload = match.group(2).strip()
    try:
        data = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    return data, mime


def _extract_pdf_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("pypdf not installed — PDF extraction unavailable")
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        joined = "\n\n".join(parts).strip()
        return joined or None
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return None


def _extract_docx_text(data: bytes) -> str | None:
    try:
        from docx import Document  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("python-docx not installed — DOCX extraction unavailable")
        return None
    try:
        document = Document(io.BytesIO(data))
        parts = [para.text.strip() for para in document.paragraphs if para.text.strip()]
        joined = "\n".join(parts).strip()
        return joined or None
    except Exception as exc:
        logger.warning("DOCX text extraction failed: %s", exc)
        return None


def _extract_plain_text(data: bytes, mime_type: str) -> str | None:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding).strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue
    logger.debug("Plain-text decode failed for mime %s", mime_type)
    return None


def extract_attachment_text(mime_type: str, data: bytes) -> str | None:
    """Return extracted plain text, or None if unsupported or extraction failed."""
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime in _PDF_MIMES or mime.endswith("/pdf"):
        return _extract_pdf_text(data)
    if mime in _DOCX_MIMES or mime.endswith("wordprocessingml.document"):
        return _extract_docx_text(data)
    if mime in _TEXT_MIMES or mime.startswith("text/"):
        return _extract_plain_text(data, mime)
    return None


def media_meta_index_text(name: str, *, alt: str = "", caption: str = "") -> str:
    """Build indexable text for a media/file metadata node."""
    parts = [part.strip() for part in (name, alt, caption) if part and part.strip()]
    return "\n".join(parts)


def note_file_record(file_item: dict[str, Any]) -> dict[str, str] | None:
    file_id = str(file_item.get("id") or "").strip()
    if not file_id:
        return None
    return {
        "id": file_id,
        "name": str(file_item.get("name") or file_id).strip() or file_id,
        "type": str(file_item.get("type") or "").strip(),
        "url": str(file_item.get("url") or "").strip(),
    }


def post_media_file_id(media_item: dict[str, Any], index: int) -> str:
    media_key = str(media_item.get("mediaKey") or "").strip()
    if media_key:
        return media_key
    return f"idx-{index}"


def post_media_record(media_item: dict[str, Any], index: int) -> dict[str, str]:
    file_id = post_media_file_id(media_item, index)
    name = str(media_item.get("name") or file_id).strip() or file_id
    return {
        "id": file_id,
        "name": name,
        "type": str(media_item.get("type") or "").strip(),
        "url": str(media_item.get("url") or "").strip(),
    }
