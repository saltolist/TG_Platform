"""migrate note bodies from legacy embed-token format to CommonMark markdown

Revision ID: 004_notes_markdown_migration
Revises: 003_summary_catalog
Create Date: 2026-06-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_notes_markdown_migration"
down_revision: Union[str, None] = "003_summary_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Run note body migration inline using the migration script logic."""
    import json
    import re
    import uuid

    bind = op.get_bind()

    _LEGACY_EMBED_RE = re.compile(r"(?<!!)\[([^\]]+)\](?!\()")
    _MD_ESCAPE_RE = re.compile(r"([\\`*_{}#|>~])")
    _IMAGE_MIME_PREFIXES = ("image/",)

    def _is_image(f):
        return str(f.get("type", "")).lower().startswith(_IMAGE_MIME_PREFIXES)

    def _ensure_ids(files):
        return [{**f, "id": f.get("id") or str(uuid.uuid4())} for f in files]

    def _escape(text):
        return _MD_ESCAPE_RE.sub(r"\\\1", text)

    def _convert(body, files):
        if not body or "attachment:" in body:
            return body, _ensure_ids(files)
        if not _LEGACY_EMBED_RE.search(body):
            return _escape(body), _ensure_ids(files)
        files = _ensure_ids(files)
        name_to = {f["name"]: f for f in files if f.get("name")}
        parts, last = [], 0
        for m in _LEGACY_EMBED_RE.finditer(body):
            parts.append(_escape(body[last:m.start()]))
            fe = name_to.get(m.group(1))
            if fe:
                fid, alt = fe["id"], m.group(1)
                parts.append(f"![{alt}](attachment:{fid})" if _is_image(fe) else f"[{alt}](attachment:{fid})")
            else:
                parts.append(_escape(m.group(0)))
            last = m.end()
        parts.append(_escape(body[last:]))
        return "".join(parts), files

    # Migrate global notes
    rows = bind.execute(sa.text("SELECT id, data FROM global_notes")).fetchall()
    for row in rows:
        data = row.data if not isinstance(row.data, str) else json.loads(row.data)
        body = data.get("body", "")
        files = list(data.get("files") or [])
        new_body, new_files = _convert(body, files)
        if new_body != body or new_files != files:
            data = {**data, "body": new_body, "files": new_files}
            bind.execute(
                sa.text("UPDATE global_notes SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"data": json.dumps(data, ensure_ascii=False), "id": str(row.id)},
            )

    # Migrate post notes (nested inside posts.data.notes[])
    rows = bind.execute(sa.text("SELECT id, data FROM posts")).fetchall()
    for row in rows:
        data = row.data if not isinstance(row.data, str) else json.loads(row.data)
        post_notes = list(data.get("notes") or [])
        changed = False
        new_notes = []
        for note in post_notes:
            body = note.get("body", "")
            files = list(note.get("files") or [])
            new_body, new_files = _convert(body, files)
            if new_body != body or new_files != files:
                note = {**note, "body": new_body, "files": new_files}
                changed = True
            new_notes.append(note)
        if changed:
            data = {**data, "notes": new_notes}
            bind.execute(
                sa.text("UPDATE posts SET data = CAST(:data AS jsonb) WHERE id = :id"),
                {"data": json.dumps(data, ensure_ascii=False), "id": str(row.id)},
            )


def downgrade() -> None:
    # Downgrade is a no-op: reverting markdown back to legacy tokens is
    # lossy (we no longer have the original row layout info) and not needed
    # since the legacy format is being replaced.
    pass
