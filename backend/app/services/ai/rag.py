"""RAG service: markdown text extraction, note indexing and retrieval (Phase 2, step 4).

Architecture:
- markdown_to_index_text(): strip markdown formatting → clean indexable text.
- content_hash(): skip re-embedding unchanged notes.
- index_note() / remove_note(): upsert/delete rows in note_embeddings.
- retrieve_top_k(): cosine-similarity search over stored vectors.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import EmbeddingBackend

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Markdown → plain text
# ──────────────────────────────────────────────────────────────────────────────

# Patterns to strip from markdown (order matters)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ATTACHMENT_URL_RE = re.compile(r"\(attachment:[^)]*\)")
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
    """Convert a note's title + CommonMark body to clean plain text for indexing.

    - markdown formatting stripped
    - alt text of images preserved
    - link text preserved; attachment: URLs removed
    - table pipe separators removed; cell text preserved
    - code blocks stripped (code is not useful for semantic note retrieval)
    - title prepended
    """
    text_body = body or ""

    # 1. Remove fenced code blocks
    text_body = _CODE_FENCE_RE.sub("", text_body)
    # 2. Remove inline code
    text_body = _INLINE_CODE_RE.sub("", text_body)
    # 3. Strip HTML tags
    text_body = _HTML_TAG_RE.sub("", text_body)
    # 4. Images: keep alt text
    text_body = _IMAGE_RE.sub(lambda m: m.group(1), text_body)
    # 5. Links: keep link text; remove attachment: urls
    text_body = _ATTACHMENT_URL_RE.sub("", text_body)
    text_body = _LINK_RE.sub(lambda m: m.group(1), text_body)
    # 6. Headers: strip # prefix
    text_body = _HEADER_RE.sub("", text_body)
    # 7. Bold / italic / strikethrough: keep inner text
    text_body = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text_body)
    text_body = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text_body)
    text_body = _STRIKETHROUGH_RE.sub(lambda m: m.group(1), text_body)
    # 8. Table separator rows
    text_body = _TABLE_PIPE_RE.sub("", text_body)
    # 9. Table pipes → spaces (preserve cell content)
    text_body = text_body.replace("|", " ")
    # 10. Blockquote markers
    text_body = _BLOCKQUOTE_RE.sub("", text_body)
    # 11. Horizontal rules
    text_body = _HR_RE.sub("", text_body)
    # 12. Escaped chars
    text_body = _ESCAPE_RE.sub(lambda m: m.group(1), text_body)
    # 13. Normalise whitespace
    text_body = "\n".join(line.rstrip() for line in text_body.splitlines())
    text_body = re.sub(r"\n{3,}", "\n\n", text_body).strip()

    if title:
        return f"{title}\n\n{text_body}" if text_body else title
    return text_body


def content_hash(title: str, body: str, model_key: str) -> str:
    """SHA-256 of (title, body, model_key) for change detection."""
    h = hashlib.sha256()
    h.update(title.encode("utf-8"))
    h.update(b"\x00")
    h.update(body.encode("utf-8"))
    h.update(b"\x00")
    h.update(model_key.encode("utf-8"))
    return h.hexdigest()


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
        if current_len + len(para) + 2 > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para) + 2

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text[:max_chars]]


# ──────────────────────────────────────────────────────────────────────────────
# Index and retrieval
# ──────────────────────────────────────────────────────────────────────────────

def _vec_to_pg(vec: list[float]) -> str:
    """Encode a float list as pgvector string '[x,y,z,...]'."""
    return "[" + ",".join(str(v) for v in vec) + "]"


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
) -> int:
    """Embed and store a note.  Returns number of chunks written."""
    plain = markdown_to_index_text(title, body)
    if not plain:
        return 0

    chunks = _chunk_text(plain, max_chars)
    model_key = backend.model_key
    dim = backend.dim

    # Delete existing chunks for this note+model (handles chunk count changes)
    await session.execute(
        text(
            "DELETE FROM note_embeddings WHERE user_id = :uid AND scope = :scope "
            "AND note_id = :nid AND model_key = :mk"
        ),
        {"uid": str(user_id), "scope": scope, "nid": note_id, "mk": model_key},
    )

    vecs = await backend.embed_passages(chunks)

    for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
        chash = content_hash(title, chunk, model_key)
        await session.execute(
            text(
                "INSERT INTO note_embeddings "
                "(user_id, scope, note_id, post_id, chunk_index, model_key, dim, content_hash, embedding) "
                "VALUES (:uid, :scope, :nid, :pid, :ci, :mk, :dim, :ch, :emb) "
                "ON CONFLICT (user_id, scope, note_id, chunk_index, model_key) DO UPDATE "
                "SET dim = EXCLUDED.dim, content_hash = EXCLUDED.content_hash, "
                "embedding = EXCLUDED.embedding, updated_at = now()"
            ),
            {
                "uid": str(user_id),
                "scope": scope,
                "nid": note_id,
                "pid": post_id,
                "ci": i,
                "mk": model_key,
                "dim": dim,
                "ch": chash,
                "emb": _vec_to_pg(vec),
            },
        )

    return len(chunks)


async def remove_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    note_id: str,
    model_key: str | None = None,
) -> None:
    """Delete all embeddings for a note (optionally scoped to a model_key)."""
    if model_key:
        await session.execute(
            text(
                "DELETE FROM note_embeddings WHERE user_id = :uid AND scope = :scope "
                "AND note_id = :nid AND model_key = :mk"
            ),
            {"uid": str(user_id), "scope": scope, "nid": note_id, "mk": model_key},
        )
    else:
        await session.execute(
            text(
                "DELETE FROM note_embeddings WHERE user_id = :uid AND scope = :scope "
                "AND note_id = :nid"
            ),
            {"uid": str(user_id), "scope": scope, "nid": note_id},
        )


async def retrieve_top_k(
    session: AsyncSession,
    user_id: uuid.UUID,
    scope: str,
    query_vec: list[float],
    model_key: str,
    k: int = 4,
    min_similarity: float = 0.72,
    post_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return top-k notes by cosine similarity.

    Returns list of dicts with keys: note_id, post_id, chunk_index, similarity.
    Returns empty list if pgvector extension is not available.
    """
    # Check if vector extension is available (soft dependency)
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

    sql = text(
        f"SELECT note_id, post_id, chunk_index, "
        f"1 - (embedding::vector <=> CAST(:qvec AS vector)) AS similarity "
        f"FROM note_embeddings "
        f"WHERE user_id = :uid AND scope = :scope AND model_key = :mk {post_filter} "
        f"ORDER BY embedding::vector <=> CAST(:qvec AS vector) "
        f"LIMIT :k"
    )
    params: dict[str, Any] = {
        "qvec": query_str,
        "uid": str(user_id),
        "scope": scope,
        "mk": model_key,
        "k": k * 2,  # over-fetch then filter by similarity threshold
    }
    if scope == "post" and post_id:
        params["pid"] = post_id

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
            "similarity": float(row.similarity),
        }
        for row in rows
        if float(row.similarity) >= min_similarity
    ]
    # Deduplicate by note_id, keep highest-similarity chunk per note
    seen: dict[str, dict[str, Any]] = {}
    for r in results:
        nid = r["note_id"]
        if nid not in seen or r["similarity"] > seen[nid]["similarity"]:
            seen[nid] = r
    return sorted(seen.values(), key=lambda x: x["similarity"], reverse=True)[:k]


# ──────────────────────────────────────────────────────────────────────────────
# Format RAG results for injection into prompt
# ──────────────────────────────────────────────────────────────────────────────

async def format_rag_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    results: list[dict[str, Any]],
    scope: str,
    post_data: Any | None = None,
) -> str:
    """Fetch note content for top-k results and format as a context block.

    Returns markdown-formatted string to append to the last user message.
    """
    if not results:
        return ""

    from app.db.models import GlobalNote, Post

    lines: list[str] = ["---", "**Контекст из заметок:**"]

    cite_index = 0
    for item in results:
        note_id = item["note_id"]
        note_scope = scope
        title = ""
        body = ""

        if note_scope == "global":
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
        elif note_scope == "post" and post_data:
            for n in (post_data.get("notes") or []):
                if str(n.get("id", "")) == note_id:
                    title = n.get("title", "")
                    body = n.get("body", "")
                    break

        if not body and not title:
            continue

        plain = markdown_to_index_text(title, body)
        if plain:
            cite_index += 1
            post_id_for_ref = item.get("post_id") or (
                str(post_data.get("id") or "") if post_data else ""
            )
            if note_scope == "global":
                cite_path = f"/note/global/{note_id}/"
            elif post_id_for_ref:
                cite_path = f"/note/post/{post_id_for_ref}/{note_id}/"
            else:
                cite_path = f"/note/global/{note_id}/"
            cite_title = title.strip() if title else "Заметка"
            label = f"**{cite_title}**"
            lines.append(
                f"\n[{cite_index}] cite-path: {cite_path} cite-title: {cite_title}\n{label}\n{plain}"
            )

    if len(lines) <= 2:
        return ""

    lines.append("---")
    return "\n".join(lines)
