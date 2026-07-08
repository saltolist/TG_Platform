"""Structural-neighbor manifest for agentic RAG (containment graph)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.attachment_text import post_media_file_id
from app.services.ai.rag import NODE_NOTE_CHUNK


def build_post_manifest(post_data: Mapping[str, Any]) -> dict[str, Any]:
    """Build id/title/name manifest from an already-loaded post JSONB object."""
    notes_out: list[dict[str, str]] = []
    for item in post_data.get("notes") or []:
        if not isinstance(item, Mapping):
            continue
        note_id = str(item.get("id") or "").strip()
        if not note_id:
            continue
        title = str(item.get("title") or note_id).strip() or note_id
        notes_out.append({"id": note_id, "title": title})

    media_out: list[dict[str, str]] = []
    for index, item in enumerate(post_data.get("media") or []):
        if not isinstance(item, Mapping):
            continue
        media_id = post_media_file_id(item, index)
        name = str(item.get("name") or media_id).strip() or media_id
        media_out.append({"id": media_id, "name": name})

    comments = post_data.get("comments") or []
    comments_count = len(comments) if isinstance(comments, list) else 0

    return {
        "notes": notes_out,
        "media": media_out,
        "comments_count": comments_count,
    }


def filter_unopened_neighbors(
    manifest: Mapping[str, Any],
    results: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return manifest entries not already surfaced in L1 retrieval results."""
    opened_note_ids: set[str] = set()
    opened_file_ids: set[str] = set()
    for item in results:
        note_id = str(item.get("note_id") or "").strip()
        file_id = str(item.get("file_id") or "").strip()
        node_type = str(item.get("node_type") or "")
        if node_type == NODE_NOTE_CHUNK and note_id:
            opened_note_ids.add(note_id)
        if file_id:
            opened_file_ids.add(file_id)

    notes_out: list[dict[str, str]] = []
    for item in manifest.get("notes") or []:
        if not isinstance(item, Mapping):
            continue
        note_id = str(item.get("id") or "").strip()
        if note_id and note_id not in opened_note_ids:
            notes_out.append(
                {
                    "id": note_id,
                    "title": str(item.get("title") or note_id).strip() or note_id,
                }
            )

    media_out: list[dict[str, str]] = []
    for item in manifest.get("media") or []:
        if not isinstance(item, Mapping):
            continue
        media_id = str(item.get("id") or "").strip()
        if media_id and media_id not in opened_file_ids:
            media_out.append(
                {
                    "id": media_id,
                    "name": str(item.get("name") or media_id).strip() or media_id,
                }
            )

    comments = manifest.get("comments_count")
    comments_count = int(comments) if isinstance(comments, (int, float)) else 0

    return {
        "notes": notes_out,
        "media": media_out,
        "comments_count": comments_count,
    }
