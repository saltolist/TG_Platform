"""RAG service: markdown text extraction, indexing and retrieval (Phase 2, step 4+).

Architecture:
- markdown_to_index_text(): strip markdown formatting → clean indexable text.
- content_hash(): skip re-embedding unchanged notes.
- index_text_node() / index_note(): upsert rows in note_embeddings.
- retrieve_top_k(): cosine-similarity search over stored vectors.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from typing import Any, Mapping

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.attachment_text import media_meta_index_text
from app.services.ai.embeddings import EmbeddingBackend
from app.services.ai.note_citations import NoteCite

logger = logging.getLogger(__name__)

NODE_NOTE_CHUNK = "note_chunk"
NODE_POST_TEXT = "post_text"
NODE_ATTACHMENT_TEXT = "attachment_text"
NODE_MEDIA_META = "media_meta"
NODE_NOTE_SUMMARY = "note_summary"
NODE_POST_SUMMARY = "post_summary"

TEXT_NODE_TYPES = frozenset(
    {
        NODE_NOTE_CHUNK,
        NODE_POST_TEXT,
        NODE_ATTACHMENT_TEXT,
        NODE_MEDIA_META,
        NODE_NOTE_SUMMARY,
        NODE_POST_SUMMARY,
    }
)
DISCOVERY_NODE_TYPES = frozenset({NODE_NOTE_SUMMARY, NODE_POST_SUMMARY})
CONTEXTUAL_NODE_TYPES = frozenset({NODE_NOTE_CHUNK, NODE_POST_TEXT})

# ──────────────────────────────────────────────────────────────────────────────
# Markdown → plain text
# ──────────────────────────────────────────────────────────────────────────────

# Patterns to strip from markdown (order matters)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ATTACHMENT_URL_RE = re.compile(r"\(attachment:[^)]*\)")
_REFERENCED_ATTACHMENT_RE = re.compile(r"attachment:([\w-]+)")
# ![alt](url) → keep alt text
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
# [text](url) → keep text
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"\*(.+?)\*|_(.+?)_")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")
_TABLE_PIPE_RE = re.compile(r"^\s*\|[-:| ]+\|\s*$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)
_HR_RE = re.compile(r"^---+$", re.MULTILINE)
_ESCAPE_RE = re.compile(r"\\(.)")


def markdown_to_index_text(title: str, body: str) -> str:
    """Convert a note's title + CommonMark body to clean plain text for indexing."""
    text_body = body or ""

    text_body = _CODE_FENCE_RE.sub("", text_body)
    text_body = _INLINE_CODE_RE.sub("", text_body)
    text_body = _HTML_TAG_RE.sub("", text_body)
    text_body = _IMAGE_RE.sub(lambda m: m.group(1), text_body)
    text_body = _ATTACHMENT_URL_RE.sub("", text_body)
    text_body = _LINK_RE.sub(lambda m: m.group(1), text_body)
    text_body = _HEADER_RE.sub("", text_body)
    text_body = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text_body)
    text_body = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text_body)
    text_body = _STRIKETHROUGH_RE.sub(lambda m: m.group(1), text_body)
    text_body = _TABLE_PIPE_RE.sub("", text_body)
    text_body = text_body.replace("|", " ")
    text_body = _BLOCKQUOTE_RE.sub("", text_body)
    text_body = _HR_RE.sub("", text_body)
    text_body = _ESCAPE_RE.sub(lambda m: m.group(1), text_body)
    text_body = "\n".join(line.rstrip() for line in text_body.splitlines())
    text_body = re.sub(r"\n{3,}", "\n\n", text_body).strip()

    if title:
        return f"{title}\n\n{text_body}" if text_body else title
    return text_body


def extract_referenced_attachment_ids(raw_text: str) -> list[str]:
    """Extract attachment ids from raw markdown before index-time stripping."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _REFERENCED_ATTACHMENT_RE.finditer(raw_text or ""):
        file_id = match.group(1).strip()
        if file_id and file_id not in seen:
            seen.add(file_id)
            ordered.append(file_id)
    return ordered


def content_hash(title: str, body: str, model_key: str) -> str:
    """SHA-256 of (title, body, model_key) for change detection."""
    h = hashlib.sha256()
    h.update(title.encode("utf-8"))
    h.update(b"\x00")
    h.update(body.encode("utf-8"))
    h.update(b"\x00")
    h.update(model_key.encode("utf-8"))
    return h.hexdigest()


def plain_content_hash(plain: str, model_key: str) -> str:
    return content_hash("", plain, model_key)


# ──────────────────────────────────────────────────────────────────────────────
# Chunking
# ──────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks of at most max_chars, splitting on paragraph breaks."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\n+", text)
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            remaining = para
            while len(remaining) > max_chars:
                boundary = remaining.rfind(" ", 0, max_chars + 1)
                if boundary < max_chars // 2:
                    boundary = max_chars
                chunks.append(remaining[:boundary].rstrip())
                remaining = remaining[boundary:].lstrip()
            if remaining:
                current = [remaining]
                current_len = len(remaining) + 2
            continue
        if current_len + len(para) + 2 > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para) + 2

    if current:
        chunks.append("\n\n".join(current))
    return [chunk for chunk in chunks if chunk] or [text[:max_chars]]


_KEYWORD_RE = re.compile(r"[\w\-]{3,}", re.UNICODE)


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_discovery_summary(
    title: str,
    text_value: str,
    *,
    max_chars: int = 160,
) -> str:
    """Build a deterministic, bounded object summary for async discovery.

    This is deliberately extractive: it is available even when no chat model
    is configured. A future LLM summary can replace the text while preserving
    the same ``*_summary`` node contract and fallback behavior.
    """
    title_line = _single_line(title)
    body_line = _single_line(text_value)
    if title_line and body_line and body_line.casefold() != title_line.casefold():
        candidate = f"{title_line}: {body_line}"
    else:
        candidate = title_line or body_line
    if len(candidate) <= max_chars:
        return candidate
    clipped = candidate[: max(1, max_chars - 1)].rstrip()
    return f"{clipped}…"


def discovery_keywords(text_value: str, *, limit: int = 10) -> list[str]:
    """Return stable, low-cost terms stored with discovery metadata."""
    seen: set[str] = set()
    result: list[str] = []
    for token in _KEYWORD_RE.findall(_single_line(text_value).casefold()):
        if token in seen or token.isdigit():
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= max(1, limit):
            break
    return result


def contextualize_chunk(
    chunk: str,
    *,
    object_type: str,
    title: str,
    section: str = "",
) -> str:
    """Prefix a source chunk for retrieval without changing citation text."""
    kind = "note" if object_type in {NODE_NOTE_CHUNK, NODE_NOTE_SUMMARY, "note"} else "post"
    context = [f"Document: {kind} {_single_line(title) or 'untitled'}."]
    section_line = _single_line(section)
    if not section_line:
        first_line = _single_line(str(chunk or "").splitlines()[0] if chunk else "")
        if (
            first_line.casefold() != _single_line(title).casefold()
            and len(first_line) <= 120
            and not first_line.endswith((".", "!", "?", ";", ":"))
        ):
            section_line = first_line
    if section_line:
        context.append(f"Section: {section_line}.")
    context.append("This fragment contains source content for the document.")
    return "\n".join(context) + "\n\n" + str(chunk or "").strip()


def object_index_revision(data: Mapping[str, Any] | None, *, fallback: int = 1) -> int:
    """Resolve a monotonic-ish revision for freshness-aware retrieval.

    Workspace objects do not share one revision field yet. Explicit numeric
    revisions win; otherwise a stable 63-bit content fingerprint changes when
    the indexed title/body/status changes and remains serializable in the DB.
    """
    raw = (data or {}).get("revision")
    try:
        if raw is not None and int(raw) > 0:
            return int(raw)
    except (TypeError, ValueError):
        pass
    raw_sync = (data or {}).get("syncRevision")
    try:
        if raw_sync is not None and int(raw_sync) > 0:
            return int(raw_sync)
    except (TypeError, ValueError):
        pass
    fingerprint = json.dumps(
        {
            "id": str((data or {}).get("id") or ""),
            "title": str((data or {}).get("title") or ""),
            "text": str((data or {}).get("text") or (data or {}).get("body") or ""),
            "status": str((data or {}).get("status") or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return int(hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:15], 16) or fallback


# ──────────────────────────────────────────────────────────────────────────────
# Index and retrieval
# ──────────────────────────────────────────────────────────────────────────────

def _vec_to_pg(vec: list[float]) -> str:
    """Encode a float list as pgvector string '[x,y,z,...]'."""
    return "[" + ",".join(str(v) for v in vec) + "]"


async def index_text_node(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    node_type: str,
    note_id: str,
    file_id: str,
    plain_text: str,
    backend: EmbeddingBackend,
    post_id: str | None = None,
    max_chars: int = 4000,
    tenant_key: str = "",
    referenced_ids: list[str] | None = None,
    object_title: str = "",
    object_status: str = "",
    index_revision: int = 1,
    section: str = "",
    keywords: list[str] | None = None,
    summary_version: int = 0,
    summary_model: str = "",
    selector_summary: str | None = None,
    selector_summary_version: int = 0,
    selector_semantic_flags: Mapping[str, Any] | None = None,
) -> int:
    """Embed and store a text node. Returns number of chunks written."""
    if node_type not in TEXT_NODE_TYPES:
        raise ValueError(f"Unsupported node_type: {node_type}")
    if not plain_text.strip():
        return 0

    chunks = _chunk_text(plain_text.strip(), max_chars)
    is_summary = node_type in DISCOVERY_NODE_TYPES
    search_chunks = [
        chunk
        if is_summary
        else contextualize_chunk(
            chunk,
            object_type=node_type,
            title=object_title,
            section=section,
        )
        for chunk in chunks
    ]
    model_key = backend.model_key
    dim = backend.dim
    file_id = file_id or ""
    ref_ids_json = json.dumps(referenced_ids or [])
    keywords_json = json.dumps(
        discovery_keywords(object_title) if keywords is None else keywords,
        ensure_ascii=False,
    )

    await session.execute(
        text(
            "DELETE FROM note_embeddings WHERE user_id = :uid AND tenant_key = :tk "
            "AND scope = :scope AND node_type = :nt AND note_id = :nid "
            "AND file_id = :fid AND model_key = :mk"
        ),
        {
            "uid": str(user_id),
            "tk": tenant_key,
            "scope": scope,
            "nt": node_type,
            "nid": note_id,
            "fid": file_id,
            "mk": model_key,
        },
    )

    vecs = await backend.embed_passages(search_chunks)

    for i, (chunk, search_chunk, vec) in enumerate(zip(chunks, search_chunks, vecs)):
        chash = plain_content_hash(chunk, model_key)
        await session.execute(
            text(
                "INSERT INTO note_embeddings "
                "(user_id, tenant_key, scope, node_type, note_id, file_id, post_id, chunk_index, "
                "model_key, dim, content_hash, chunk_text, search_text, referenced_ids, "
                "object_title, object_status, index_revision, keywords, summary_version, "
                "summary_model, selector_summary, selector_summary_version, "
                "selector_semantic_flags, embedding) "
                "VALUES (:uid, :tk, :scope, :nt, :nid, :fid, :pid, :ci, :mk, :dim, :ch, "
                ":ctxt, :stxt, :rids, :otitle, :ostatus, :irev, :keywords, :sversion, "
                ":smodel, :selector_summary, :selector_summary_version, "
                "CAST(:selector_semantic_flags AS jsonb), :emb) "
                "ON CONFLICT (user_id, tenant_key, scope, node_type, note_id, file_id, "
                "chunk_index, model_key) DO UPDATE "
                "SET dim = EXCLUDED.dim, content_hash = EXCLUDED.content_hash, "
                "chunk_text = EXCLUDED.chunk_text, search_text = EXCLUDED.search_text, "
                "referenced_ids = EXCLUDED.referenced_ids, object_title = EXCLUDED.object_title, "
                "object_status = EXCLUDED.object_status, index_revision = EXCLUDED.index_revision, "
                "keywords = EXCLUDED.keywords, summary_version = EXCLUDED.summary_version, "
                "summary_model = EXCLUDED.summary_model, "
                "selector_summary = EXCLUDED.selector_summary, "
                "selector_summary_version = EXCLUDED.selector_summary_version, "
                "selector_semantic_flags = EXCLUDED.selector_semantic_flags, "
                "post_id = EXCLUDED.post_id, "
                "embedding = EXCLUDED.embedding, updated_at = now()"
            ),
            {
                "uid": str(user_id),
                "tk": tenant_key,
                "scope": scope,
                "nt": node_type,
                "nid": note_id,
                "fid": file_id,
                "pid": post_id,
                "ci": i,
                "mk": model_key,
                "dim": dim,
                "ch": chash,
                "ctxt": chunk,
                "stxt": search_chunk,
                "rids": ref_ids_json,
                "otitle": _single_line(object_title),
                "ostatus": _single_line(object_status),
                "irev": max(1, int(index_revision or 1)),
                "keywords": keywords_json,
                "sversion": max(0, int(summary_version or 0)),
                "smodel": _single_line(summary_model),
                "selector_summary": (
                    _single_line(selector_summary) if selector_summary is not None else None
                ),
                "selector_summary_version": max(0, int(selector_summary_version or 0)),
                "selector_semantic_flags": json.dumps(
                    dict(selector_semantic_flags or {}),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "emb": _vec_to_pg(vec),
            },
        )

    return len(chunks)


async def index_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    title: str,
    body: str,
    backend: EmbeddingBackend,
    post_id: str | None = None,
    max_chars: int = 4000,
    tenant_key: str = "",
    object_status: str = "active",
    index_revision: int | None = None,
    index_summary: bool = True,
    discovery_summary: str | None = None,
    discovery_summary_version: int = 0,
    discovery_summary_model: str = "",
    selector_summary: str | None = None,
    selector_summary_version: int = 0,
    selector_semantic_flags: Mapping[str, Any] | None = None,
) -> int:
    """Embed a note and its discovery summary in the async index."""
    plain = markdown_to_index_text(title, body)
    effective_revision = int(index_revision or object_index_revision({
        "id": note_id,
        "title": title,
        "body": body,
        "status": object_status,
    }))
    summary = str(discovery_summary or "").strip() or build_discovery_summary(title, plain)
    referenced_ids = extract_referenced_attachment_ids(body)
    count = await index_text_node(
        session,
        user_id,
        scope,
        NODE_NOTE_CHUNK,
        note_id,
        "",
        plain,
        backend,
        post_id=post_id,
        max_chars=max_chars,
        tenant_key=tenant_key,
        referenced_ids=referenced_ids,
        object_title=title,
        object_status=object_status,
        index_revision=effective_revision,
        keywords=discovery_keywords(summary),
    )
    if index_summary:
        if summary:
            count += await index_text_node(
                session,
                user_id,
                scope,
                NODE_NOTE_SUMMARY,
                note_id,
                "",
                summary,
                backend,
                post_id=post_id,
                max_chars=max_chars,
                tenant_key=tenant_key,
                object_title=title,
                object_status=object_status,
                index_revision=effective_revision,
                keywords=discovery_keywords(summary),
                summary_version=discovery_summary_version,
                summary_model=discovery_summary_model,
                selector_summary=selector_summary,
                selector_summary_version=selector_summary_version,
                selector_semantic_flags=selector_semantic_flags,
            )
    return count


async def index_discovery_summary(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    node_type: str,
    object_id: str,
    title: str,
    text_value: str,
    backend: EmbeddingBackend,
    *,
    post_id: str | None = None,
    tenant_key: str = "",
    object_status: str = "",
    index_revision: int = 1,
    max_chars: int = 4000,
    keywords: list[str] | None = None,
    summary_text: str | None = None,
    summary_version: int = 0,
    summary_model: str = "",
    selector_summary: str | None = None,
    selector_summary_version: int = 0,
    selector_semantic_flags: Mapping[str, Any] | None = None,
) -> int:
    """Write one object-level discovery node with a deterministic fallback."""
    if node_type not in DISCOVERY_NODE_TYPES:
        raise ValueError(f"Unsupported discovery node_type: {node_type}")
    summary = str(summary_text or "").strip() or build_discovery_summary(title, text_value)
    if not summary:
        await remove_text_node(
            session, user_id, scope, node_type, object_id, tenant_key=tenant_key
        )
        return 0
    return await index_text_node(
        session,
        user_id,
        scope,
        node_type,
        object_id,
        "",
        summary,
        backend,
        post_id=post_id,
        max_chars=max_chars,
        tenant_key=tenant_key,
        object_title=title,
        object_status=object_status,
        index_revision=index_revision,
        keywords=keywords or discovery_keywords(summary),
        summary_version=summary_version,
        summary_model=summary_model,
        selector_summary=selector_summary,
        selector_summary_version=selector_summary_version,
        selector_semantic_flags=selector_semantic_flags,
    )


async def remove_text_node(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    node_type: str,
    note_id: str,
    file_id: str = "",
    model_key: str | None = None,
    tenant_key: str = "",
) -> None:
    """Delete embeddings for one text node (optionally scoped to a model_key)."""
    params: dict[str, Any] = {
        "uid": str(user_id),
        "tk": tenant_key,
        "scope": scope,
        "nt": node_type,
        "nid": note_id,
        "fid": file_id or "",
    }
    if model_key:
        params["mk"] = model_key
        await session.execute(
            text(
                "DELETE FROM note_embeddings WHERE user_id = :uid AND tenant_key = :tk "
                "AND scope = :scope AND node_type = :nt AND note_id = :nid "
                "AND file_id = :fid AND model_key = :mk"
            ),
            params,
        )
    else:
        await session.execute(
            text(
                "DELETE FROM note_embeddings WHERE user_id = :uid AND tenant_key = :tk "
                "AND scope = :scope AND node_type = :nt AND note_id = :nid AND file_id = :fid"
            ),
            params,
        )


async def remove_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    model_key: str | None = None,
    tenant_key: str = "",
) -> None:
    """Delete all embeddings for a note (optionally scoped to a model_key)."""
    for node_type in (NODE_NOTE_CHUNK, NODE_NOTE_SUMMARY):
        await remove_text_node(
            session,
            user_id,
            scope,
            node_type,
            note_id,
            "",
            model_key=model_key,
            tenant_key=tenant_key,
        )


async def remove_file_nodes_for_parent(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    *,
    keep_file_ids: set[str],
    tenant_key: str = "",
) -> None:
    """Remove attachment/media nodes for a note/post parent except listed file ids."""
    rows = (
        await session.execute(
            text(
                "SELECT file_id, node_type FROM note_embeddings "
                "WHERE user_id = :uid AND tenant_key = :tk AND scope = :scope "
                "AND note_id = :nid AND node_type IN (:at, :mm)"
            ),
            {
                "uid": str(user_id),
                "tk": tenant_key,
                "scope": scope,
                "nid": note_id,
                "at": NODE_ATTACHMENT_TEXT,
                "mm": NODE_MEDIA_META,
            },
        )
    ).fetchall()
    stale = {
        (row.file_id, row.node_type)
        for row in rows
        if row.file_id and row.file_id not in keep_file_ids
    }
    for file_id, node_type in stale:
        await remove_text_node(
            session,
            user_id,
            scope,
            node_type,
            note_id,
            file_id,
            tenant_key=tenant_key,
        )


async def upsert_attachment_extraction(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    file_id: str,
    content_hash_value: str,
    mime_type: str,
    extracted_text: str | None,
    tenant_key: str = "",
) -> None:
    await session.execute(
        text(
            "INSERT INTO attachment_extractions "
            "(user_id, tenant_key, scope, note_id, file_id, content_hash, mime_type, extracted_text) "
            "VALUES (:uid, :tk, :scope, :nid, :fid, :ch, :mime, :txt) "
            "ON CONFLICT (user_id, tenant_key, scope, note_id, file_id) DO UPDATE "
            "SET content_hash = EXCLUDED.content_hash, mime_type = EXCLUDED.mime_type, "
            "extracted_text = EXCLUDED.extracted_text, extracted_at = now()"
        ),
        {
            "uid": str(user_id),
            "tk": tenant_key,
            "scope": scope,
            "nid": note_id,
            "fid": file_id,
            "ch": content_hash_value,
            "mime": mime_type,
            "txt": extracted_text,
        },
    )


async def get_attachment_extraction(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    file_id: str,
    tenant_key: str = "",
) -> str | None:
    row = (
        await session.execute(
            text(
                "SELECT extracted_text FROM attachment_extractions "
                "WHERE user_id = :uid AND tenant_key = :tk AND scope = :scope "
                "AND note_id = :nid AND file_id = :fid"
            ),
            {
                "uid": str(user_id),
                "tk": tenant_key,
                "scope": scope,
                "nid": note_id,
                "fid": file_id,
            },
        )
    ).fetchone()
    if row is None:
        return None
    return row.extracted_text


async def get_attachment_extraction_by_hash(
    session: AsyncSession,
    user_id: uuid.UUID,
    content_hash_value: str,
) -> str | None:
    row = (
        await session.execute(
            text(
                "SELECT extracted_text FROM attachment_extractions "
                "WHERE user_id = :uid AND content_hash = :ch "
                "AND extracted_text IS NOT NULL AND extracted_text != '' "
                "AND extracted_text != 'None' AND length(extracted_text) > 10 "
                "ORDER BY extracted_at DESC LIMIT 1"
            ),
            {"uid": str(user_id), "ch": content_hash_value},
        )
    ).fetchone()
    if row is None:
        return None
    return row.extracted_text


async def retrieve_top_k(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    query_vec: list[float],
    model_key: str,
    k: int = 4,
    min_similarity: float = 0.72,
    post_id: str | None = None,
    tenant_key: str | None = None,
    node_types: frozenset[str] | None = None,
    post_id_eq: str | None = None,
    post_id_neq: str | None = None,
    exclude_deleted_posts: bool = True,
    object_ids: frozenset[str] | None = None,
    object_statuses: frozenset[str] | None = None,
    expected_revisions: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return top-k text nodes by cosine similarity."""
    try:
        result = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        if result.scalar_one_or_none() is None:
            return []
    except Exception:
        return []

    query_str = _vec_to_pg(query_vec)
    post_filter = "AND post_id = :pid" if (scope == "post" and post_id) else ""
    if post_id_eq:
        post_filter += " AND post_id = :pid_eq"
    if post_id_neq:
        post_filter += " AND post_id != :pid_neq AND post_id != ''"
    if tenant_key:
        tenant_filter = "AND (tenant_key = :tk OR tenant_key = '')"
    else:
        tenant_filter = "AND tenant_key = ''"

    node_type_filter = ""
    if node_types:
        placeholders = ", ".join(f":nt_{i}" for i in range(len(node_types)))
        node_type_filter = f" AND node_type IN ({placeholders})"

    object_id_filter = ""
    if object_ids:
        placeholders = ", ".join(f":oid_{i}" for i in range(len(object_ids)))
        object_id_filter = f" AND note_id IN ({placeholders})"

    object_status_filter = ""
    if object_statuses:
        placeholders = ", ".join(f":ost_{i}" for i in range(len(object_statuses)))
        object_status_filter = f" AND object_status IN ({placeholders})"

    deleted_filter = ""
    if exclude_deleted_posts:
        deleted_filter = (
            " AND (post_id = '' OR post_id IS NULL OR NOT EXISTS ("
            "SELECT 1 FROM posts p "
            "WHERE p.user_id = :uid "
            "AND p.data->>'id' = note_embeddings.post_id "
            "AND p.data->>'status' = 'deleted'"
            "))"
        )

    sql = text(
        f"SELECT note_id, post_id, chunk_index, tenant_key, node_type, file_id, "
        f"chunk_text, search_text, referenced_ids, scope, object_title, object_status, "
        f"index_revision, keywords, summary_version, summary_model, selector_summary, "
        f"selector_summary_version, selector_semantic_flags, "
        f"1 - (embedding::vector <=> CAST(:qvec AS vector)) AS similarity "
        f"FROM note_embeddings "
        f"WHERE user_id = :uid AND scope = :scope AND model_key = :mk "
        f"{tenant_filter} {post_filter} {node_type_filter} {object_id_filter} "
        f"{object_status_filter} {deleted_filter} "
        f"ORDER BY embedding::vector <=> CAST(:qvec AS vector) "
        f"LIMIT :k"
    )
    params: dict[str, Any] = {
        "qvec": query_str,
        "uid": str(user_id),
        "scope": scope,
        "mk": model_key,
        "k": k * 2,
    }
    if tenant_key:
        params["tk"] = tenant_key
    if scope == "post" and post_id:
        params["pid"] = post_id
    if post_id_eq:
        params["pid_eq"] = post_id_eq
    if post_id_neq:
        params["pid_neq"] = post_id_neq
    if node_types:
        for index, node_type in enumerate(sorted(node_types)):
            params[f"nt_{index}"] = node_type
    if object_ids:
        for index, object_id in enumerate(sorted(object_ids)):
            params[f"oid_{index}"] = object_id
    if object_statuses:
        for index, status in enumerate(sorted(object_statuses)):
            params[f"ost_{index}"] = status

    try:
        rows = (await session.execute(sql, params)).fetchall()
    except Exception as exc:
        logger.warning("RAG retrieval failed: %s", exc)
        return []

    results = [
        {
            "note_id": row.note_id,
            "post_id": row.post_id,
            "chunk_index": row.chunk_index,
            "tenant_key": row.tenant_key or "",
            "node_type": row.node_type or NODE_NOTE_CHUNK,
            "file_id": row.file_id or "",
            "chunk_text": row.chunk_text or "",
            "search_text": getattr(row, "search_text", "") or row.chunk_text or "",
            "referenced_ids": _parse_referenced_ids(row.referenced_ids),
            "scope": getattr(row, "scope", None) or scope,
            "object_title": getattr(row, "object_title", "") or "",
            "object_status": getattr(row, "object_status", "") or "",
            "index_revision": int(getattr(row, "index_revision", 1) or 1),
            "summary_version": int(getattr(row, "summary_version", 0) or 0),
            "summary_model": str(getattr(row, "summary_model", "") or ""),
            "selector_summary": str(getattr(row, "selector_summary", "") or ""),
            "selector_summary_version": int(
                getattr(row, "selector_summary_version", 0) or 0
            ),
            "selector_semantic_flags": _parse_json_object(
                getattr(row, "selector_semantic_flags", None)
            ),
            "keywords": _parse_referenced_ids(getattr(row, "keywords", None)),
            "is_discovery_node": (row.node_type or NODE_NOTE_CHUNK) in DISCOVERY_NODE_TYPES,
            "similarity": float(row.similarity),
        }
        for row in rows
        if float(row.similarity) >= min_similarity
        and (
            not expected_revisions
            or str(row.note_id) not in expected_revisions
            or int(getattr(row, "index_revision", 1) or 1)
            == int(expected_revisions[str(row.note_id)])
        )
    ]
    seen: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
    for r in results:
        key = (
            r["node_type"],
            r["note_id"],
            r["file_id"],
            int(r["chunk_index"]) if object_ids else None,
        )
        if key not in seen or r["similarity"] > seen[key]["similarity"]:
            seen[key] = r
    return sorted(seen.values(), key=lambda x: x["similarity"], reverse=True)[:k]


def _parse_referenced_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _post_title_from_text(text_value: str) -> str:
    line = (text_value.split("\n")[0] or "").strip() or "Пост"
    if len(line) <= 72:
        return line
    return f"{line[:69]}…"


async def _resolve_note_body(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    item_tenant_key: str,
    post_data: Any | None,
) -> tuple[str, str]:
    from app.db.models import GlobalNote
    from app.services.overlay.tenant_notes import get_tenant_note

    title = ""
    body = ""
    if item_tenant_key:
        note_data = await get_tenant_note(session, user_id, item_tenant_key, scope, note_id)
        if note_data:
            title = note_data.get("title", "")
            body = note_data.get("body", "")
    elif scope == "global":
        result = await session.execute(
            select(GlobalNote).where(
                GlobalNote.user_id == user_id,
                GlobalNote.data["id"].astext == note_id,
            )
        )
        note_row = result.scalar_one_or_none()
        if note_row:
            title = note_row.data.get("title", "")
            body = note_row.data.get("body", "")
    elif scope == "post" and post_data:
        for n in (post_data.get("notes") or []):
            if str(n.get("id", "")) == note_id:
                title = n.get("title", "")
                body = n.get("body", "")
                break
    return title, body


async def get_note_data(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    tenant_key: str | None = None,
    post_data: Any | None = None,
    opened_posts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resolve a full note dict (including files[]) from overlay, global, or post scope.

    Search order:
    1. Tenant overlay (if tenant_key)
    2. global_notes table (if scope == "global")
    3. opened_posts in-memory (post_data + opened_posts dict)
    4. DB fallback: scan posts table for a post whose notes[] contains note_id
       — allows OpenNote(note_id) to succeed without a prior OpenPost call.
    """
    from app.db.models import GlobalNote, Post
    from app.services.overlay.tenant_notes import get_tenant_note

    if tenant_key:
        note_data = await get_tenant_note(session, user_id, tenant_key, scope, note_id)
        if note_data:
            return dict(note_data)

    if scope == "global":
        result = await session.execute(
            select(GlobalNote).where(
                GlobalNote.user_id == user_id,
                GlobalNote.data["id"].astext == note_id,
            )
        )
        note_row = result.scalar_one_or_none()
        if note_row is not None:
            return dict(note_row.data)

    posts_to_search: list[dict[str, Any]] = []
    if isinstance(post_data, dict):
        posts_to_search.append(post_data)
    for post in (opened_posts or {}).values():
        if isinstance(post, dict):
            posts_to_search.append(post)

    for post in posts_to_search:
        for note in post.get("notes") or []:
            if isinstance(note, dict) and str(note.get("id", "")) == note_id:
                return dict(note)

    # DB fallback: the note wasn't found in memory — scan posts to locate it.
    # This lets OpenNote(note_id) succeed without a prior OpenPost call, avoiding
    # the planner loop: OpenNote→not_found → OpenPost → (loop without retry).
    try:
        result = await session.execute(
            select(Post).where(
                Post.user_id == user_id,
                Post.data["notes"].as_string().contains(note_id),
            )
        )
        for post_row in result.scalars().all():
            for note in (post_row.data or {}).get("notes") or []:
                if isinstance(note, dict) and str(note.get("id", "")) == note_id:
                    return dict(note)
    except Exception:
        pass  # fallback — non-fatal if the scan fails

    return None


async def list_global_notes(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_key: str | None = None,
) -> list[dict[str, Any]]:
    """List notes not attached to any post (overlay-aware, mirrors get_note_data scoping)."""
    from app.db.models import GlobalNote
    from app.services.overlay.tenant_notes import list_tenant_notes

    if tenant_key:
        return await list_tenant_notes(session, user_id, tenant_key, "global")

    result = await session.execute(
        select(GlobalNote)
        .where(GlobalNote.user_id == user_id)
        .order_by(GlobalNote.created_at.desc())
    )
    return [
        {
            **dict(row.data),
            "id": str(row.id),
            "_created_at": row.created_at.isoformat(),
        }
        for row in result.scalars().all()
    ]


async def resolve_post_data(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_id: str,
) -> dict[str, Any] | None:
    from app.db.resolve import get_owned_post

    try:
        post_row = await get_owned_post(session, user_id, post_id)
    except Exception:
        return None
    return dict(post_row.data)


def _find_note_file(
    note_data: dict[str, Any] | None,
    file_id: str,
) -> dict[str, Any] | None:
    if not note_data:
        return None
    for item in note_data.get("files") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == file_id:
            return item
    return None


def _find_post_media(
    post_data: dict[str, Any] | None,
    file_id: str,
) -> dict[str, Any] | None:
    if not post_data:
        return None
    for index, item in enumerate(post_data.get("media") or []):
        if not isinstance(item, dict):
            continue
        from app.services.ai.attachment_text import post_media_file_id

        if post_media_file_id(item, index) == file_id:
            return item
    return None


async def format_rag_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    results: list[dict[str, Any]],
    scope: str,
    post_data: Any | None = None,
    tenant_key: str | None = None,
) -> tuple[str, list[NoteCite]]:
    """Fetch content for top-k results and format as a context block."""
    if not results:
        return "", []

    lines: list[str] = ["---", "**Контекст из базы знаний:**"]
    cites: list[NoteCite] = []
    cite_index = 0

    for item in results:
        node_type = item.get("node_type") or NODE_NOTE_CHUNK
        # Object summaries are discovery-only candidates. They intentionally
        # never become answer evidence, even if a legacy caller passes raw
        # retrieval rows directly to this formatter.
        if node_type in DISCOVERY_NODE_TYPES:
            continue
        note_id = item["note_id"]
        file_id = item.get("file_id") or ""
        item_scope = str(item.get("scope") or scope)
        item_tenant_key = item.get("tenant_key") or ""
        item_post_id = str(item.get("post_id") or "").strip()
        item_post_data = post_data
        if item_scope == "post" and item_post_id:
            if not isinstance(post_data, dict) or str(post_data.get("id") or "") != item_post_id:
                item_post_data = await resolve_post_data(session, user_id, item_post_id)
        plain = ""
        cite_path = ""
        cite_title = ""

        if node_type == NODE_NOTE_CHUNK:
            title, body = await _resolve_note_body(
                session, user_id, item_scope, note_id, item_tenant_key, item_post_data
            )
            if not body and not title:
                continue
            plain = markdown_to_index_text(title, body)
            cite_title = title.strip() if title else "Заметка"
            post_id_for_ref = item_post_id or (
                str(post_data.get("id") or "") if post_data else ""
            )
            if item_scope == "global":
                cite_path = f"/note/global/{note_id}/"
            elif post_id_for_ref:
                cite_path = f"/note/post/{post_id_for_ref}/{note_id}/"
            else:
                cite_path = f"/note/global/{note_id}/"

        elif node_type == NODE_POST_TEXT:
            resolved_post = await resolve_post_data(session, user_id, note_id)
            if not resolved_post:
                continue
            text_value = str(resolved_post.get("text") or "").strip()
            if not text_value:
                continue
            plain = text_value
            cite_title = _post_title_from_text(text_value)
            cite_path = f"/post/{note_id}/"

        elif node_type == NODE_ATTACHMENT_TEXT:
            extracted = await get_attachment_extraction(
                session,
                user_id,
                item_scope,
                note_id,
                file_id,
                tenant_key=item_tenant_key,
            )
            if not extracted:
                continue
            plain = extracted.strip()
            title, body = await _resolve_note_body(
                session, user_id, item_scope, note_id, item_tenant_key, item_post_data
            )
            note_data = {"title": title, "body": body, "files": []}
            if item_scope == "post" and item_post_data:
                for n in item_post_data.get("notes") or []:
                    if str(n.get("id", "")) == note_id:
                        note_data = n
                        break
            file_item = _find_note_file(note_data if isinstance(note_data, dict) else None, file_id)
            file_name = str((file_item or {}).get("name") or file_id)
            cite_title = file_name
            post_id_for_ref = item_post_id or (
                str(post_data.get("id") or "") if post_data else ""
            )
            if item_scope == "global":
                cite_path = f"/note/global/{note_id}/"
            elif post_id_for_ref:
                cite_path = f"/note/post/{post_id_for_ref}/{note_id}/"
            else:
                cite_path = f"/note/global/{note_id}/"

        elif node_type == NODE_MEDIA_META:
            post_id_for_ref = item.get("post_id") or note_id
            if file_id.startswith("idx-") or item.get("post_id"):
                resolved_post = post_data or await resolve_post_data(
                    session, user_id, post_id_for_ref
                )
                media_item = _find_post_media(resolved_post, file_id)
                if not media_item:
                    continue
                plain = media_meta_index_text(str(media_item.get("name") or file_id))
                cite_title = str(media_item.get("name") or file_id)
                cite_path = f"/post/{post_id_for_ref}/"
            else:
                title, body = await _resolve_note_body(
                    session, user_id, item_scope, note_id, item_tenant_key, item_post_data
                )
                note_data = {"title": title, "body": body, "files": []}
                if item_scope == "post" and item_post_data:
                    for n in item_post_data.get("notes") or []:
                        if str(n.get("id", "")) == note_id:
                            note_data = n
                            break
                file_item = _find_note_file(note_data if isinstance(note_data, dict) else None, file_id)
                if not file_item:
                    continue
                plain = media_meta_index_text(str(file_item.get("name") or file_id))
                cite_title = str(file_item.get("name") or file_id)
                post_id_for_ref = item.get("post_id") or (
                    str(post_data.get("id") or "") if post_data else ""
                )
                if item_scope == "global":
                    cite_path = f"/note/global/{note_id}/"
                elif post_id_for_ref:
                    cite_path = f"/note/post/{post_id_for_ref}/{note_id}/"
                else:
                    cite_path = f"/note/global/{note_id}/"
        else:
            continue

        if not plain:
            continue

        cite_index += 1
        cites.append(NoteCite(path=cite_path, title=cite_title))
        label = f"**{cite_title}**"
        lines.append(
            f"\n[{cite_index}] cite-path: {cite_path} cite-title: {cite_title}\n{label}\n{plain}"
        )

    if len(lines) <= 2:
        return "", []

    lines.append("---")
    return "\n".join(lines), cites
