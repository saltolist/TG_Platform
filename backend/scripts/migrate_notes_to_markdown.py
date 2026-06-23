"""Migrate note bodies from legacy embed-token format to CommonMark markdown.

Legacy format: body contains [filename] tokens referencing files by name.
New format:    body contains ![alt](attachment:<id>) or [name](attachment:<id>).

Safe to run multiple times (idempotent): already-converted notes are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Matches legacy embed tokens: [some name] NOT preceded by ! (not already image markdown)
# and NOT followed by ( (not already a markdown link)
_LEGACY_EMBED_RE = re.compile(r"(?<!!)\[([^\]]+)\](?!\()")

# Characters that have special meaning in CommonMark and need escaping in plain text.
# We only escape them when they appear OUTSIDE of the embed tokens we convert.
_MD_ESCAPE_RE = re.compile(r"([\\`*_{}#|>~])")

# Image MIME prefixes
_IMAGE_MIME_PREFIXES = ("image/",)


def _is_image(file_entry: dict[str, Any]) -> bool:
    mime = str(file_entry.get("type", "")).lower()
    return any(mime.startswith(p) for p in _IMAGE_MIME_PREFIXES)


def _ensure_file_ids(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign a stable UUID to each file that lacks one."""
    updated = []
    for f in files:
        if not f.get("id"):
            f = {**f, "id": str(uuid.uuid4())}
        updated.append(f)
    return updated


def _escape_plain_text(text: str) -> str:
    """Escape markdown special characters in plain text segments."""
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _is_already_markdown(body: str) -> bool:
    """Heuristic: body is already markdown if it contains attachment: links."""
    return "attachment:" in body


def migrate_note_body(
    body: str,
    files: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert a single note body from legacy format to markdown.

    Returns (new_body, new_files) where new_files has ids assigned.
    If body is already in markdown format, returns it unchanged.
    """
    if not body:
        return body, files

    if _is_already_markdown(body):
        return body, _ensure_file_ids(files)

    # Has no legacy tokens at all — just escape text and return
    if not _LEGACY_EMBED_RE.search(body):
        return _escape_plain_text(body), _ensure_file_ids(files)

    files = _ensure_file_ids(files)
    name_to_file: dict[str, dict[str, Any]] = {f["name"]: f for f in files if f.get("name")}

    parts: list[str] = []
    last_end = 0

    for m in _LEGACY_EMBED_RE.finditer(body):
        start, end = m.start(), m.end()
        # Escape the plain text before this token
        plain = body[last_end:start]
        parts.append(_escape_plain_text(plain))

        token_name = m.group(1)
        file_entry = name_to_file.get(token_name)
        if file_entry:
            fid = file_entry["id"]
            alt = token_name
            if _is_image(file_entry):
                parts.append(f"![{alt}](attachment:{fid})")
            else:
                parts.append(f"[{alt}](attachment:{fid})")
        else:
            # No matching file — keep as escaped literal text
            parts.append(_escape_plain_text(m.group(0)))

        last_end = end

    # Remaining plain text after last token
    parts.append(_escape_plain_text(body[last_end:]))

    return "".join(parts), files


async def migrate_global_notes(session: AsyncSession) -> int:
    from app.db.models import GlobalNote

    result = await session.execute(select(GlobalNote))
    notes = result.scalars().all()
    changed = 0
    for note in notes:
        data = dict(note.data or {})
        body = data.get("body", "")
        files = list(data.get("files") or [])
        new_body, new_files = migrate_note_body(body, files)
        if new_body != body or new_files != files:
            note.data = {**data, "body": new_body, "files": new_files}
            changed += 1
    return changed


async def migrate_post_notes(session: AsyncSession) -> int:
    from app.db.models import Post

    result = await session.execute(select(Post))
    posts = result.scalars().all()
    changed = 0
    for post in posts:
        data = dict(post.data or {})
        post_notes = list(data.get("notes") or [])
        post_changed = False
        new_notes = []
        for note in post_notes:
            body = note.get("body", "")
            files = list(note.get("files") or [])
            new_body, new_files = migrate_note_body(body, files)
            if new_body != body or new_files != files:
                note = {**note, "body": new_body, "files": new_files}
                post_changed = True
                changed += 1
            new_notes.append(note)
        if post_changed:
            post.data = {**data, "notes": new_notes}
    return changed


async def run(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            gn = await migrate_global_notes(session)
            pn = await migrate_post_notes(session)
            logger.info("Migrated %d global notes, %d post notes to markdown.", gn, pn)
            print(f"Done: {gn} global notes, {pn} post notes migrated.")


if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(level=logging.INFO)
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    asyncio.run(run(url))
