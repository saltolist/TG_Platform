"""Authoritative typed workspace catalog snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypedDict

from app.services.ai.rag import object_index_revision

CATALOG_SCHEMA_VERSION = "workspace.catalog-snapshot/v1"
DEFAULT_CATALOG_PAGE_SIZE = 100
_INVISIBLE_STATUSES = frozenset({"deleted", "hidden", "inaccessible"})
_MIME_TOKEN = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+\-]*$")


class CatalogParent(TypedDict):
    kind: Literal["post"]
    ref: str


class CatalogMember(TypedDict, total=False):
    ref: str
    kind: Literal["note", "post"]
    id: str
    title: str
    status: str
    visibility: Literal["included"]
    revision: int
    parent: CatalogParent | None
    parent_post_id: str | None
    preview: str
    estimated_full_text_chars: int
    file_count: int | None
    image_count: int | None
    has_files: bool | None
    has_images: bool | None
    notes_count: int | None
    direct_media_count: int | None
    direct_image_count: int | None
    note_files_total: int | None
    note_image_files_total: int | None
    notes_with_files_count: int | None
    notes_with_images_count: int | None
    has_any_images: bool | None


class CatalogSnapshot(TypedDict):
    schema_version: str
    kind: Literal["notes", "posts"]
    source_requirement_id: str
    members: list[CatalogMember]
    members_complete: bool
    total_members: int
    aggregates: dict[str, int | None]
    result_sets: dict[str, list[str] | None]
    result_sets_complete: bool
    provided_properties: list[str]
    omitted_properties: list[str]
    next_cursor: str | None
    page: dict[str, int]


NOTE_PROPERTIES = (
    "notes.file_count",
    "notes.image_count",
    "notes.has_files",
    "notes.has_images",
)
POST_PROPERTIES = (
    "posts.file_count",
    "posts.image_count",
    "posts.has_files",
    "posts.has_images",
    "posts.direct_media_count",
    "posts.direct_image_count",
    "posts.note_files_total",
    "posts.note_image_files_total",
    "posts.notes_with_files_count",
    "posts.notes_with_images_count",
    "posts.has_any_images",
)


def normalized_mime_type(file_data: Mapping[str, Any]) -> str | None:
    """Return a declared MIME type; filenames and extensions are never evidence."""

    raw = file_data.get("mime_type")
    if raw is None:
        raw = file_data.get("mimeType")
    if raw is None:
        raw = file_data.get("type")
    mime = str(raw or "").split(";", 1)[0].strip().lower()
    if mime.count("/") != 1 or mime == "application/octet-stream":
        return None
    major, minor = (part.strip() for part in mime.split("/", 1))
    if not _MIME_TOKEN.fullmatch(major) or not _MIME_TOKEN.fullmatch(minor):
        return None
    return f"{major}/{minor}"


def is_image_file(file_data: Mapping[str, Any]) -> bool | None:
    mime = normalized_mime_type(file_data)
    if mime is None:
        return None
    return mime.startswith("image/")


def is_catalog_visible(data: Mapping[str, Any]) -> bool:
    return str(data.get("status") or "active").strip().lower() not in _INVISIBLE_STATUSES


def _attachment_revision_signature(owner: Mapping[str, Any], field: str) -> Any:
    if field not in owner:
        return None
    raw = owner.get(field)
    if not isinstance(raw, (list, tuple)):
        return "invalid"
    return [
        {
            "id": str(item.get("id") or ""),
            "mime_type": normalized_mime_type(item),
            "declared_type": str(
                item.get("mime_type") or item.get("mimeType") or item.get("type") or ""
            ).strip(),
        }
        if isinstance(item, Mapping)
        else "invalid"
        for item in raw
    ]


def catalog_item_revision(data: Mapping[str, Any], *, kind: Literal["note", "post"]) -> int:
    for field in ("revision", "syncRevision"):
        try:
            if data.get(field) is not None and int(data[field]) > 0:
                return object_index_revision(data)
        except (TypeError, ValueError):
            continue
    signature: dict[str, Any] = {
        "id": str(data.get("id") or ""),
        "title": str(data.get("title") or ""),
        "status": str(data.get("status") or ""),
    }
    if kind == "note":
        signature.update(
            {
                "body": str(data.get("body") or ""),
                "files": _attachment_revision_signature(data, "files"),
            }
        )
    else:
        raw_notes = data.get("notes")
        signature.update(
            {
                "text": str(data.get("text") or ""),
                "media": _attachment_revision_signature(data, "media"),
                "notes": [
                    catalog_item_revision(note, kind="note")
                    if isinstance(note, Mapping)
                    else "invalid"
                    for note in raw_notes
                ]
                if isinstance(raw_notes, (list, tuple))
                else None,
            }
        )
    return object_index_revision(
        {
            "id": signature["id"],
            "status": signature["status"],
            "body": json.dumps(signature, ensure_ascii=False, sort_keys=True),
        }
    )


def _attachment_facts(
    owner: Mapping[str, Any],
    *,
    field: str,
) -> dict[str, int | bool | None]:
    if field not in owner or not isinstance(owner.get(field), (list, tuple)):
        return {
            "file_count": None,
            "image_count": None,
            "has_files": None,
            "has_images": None,
        }
    raw_files = list(owner.get(field) or ())
    if any(not isinstance(item, Mapping) for item in raw_files):
        return {
            "file_count": None,
            "image_count": None,
            "has_files": None,
            "has_images": None,
        }
    classifications = [is_image_file(item) for item in raw_files]
    image_count = (
        sum(value is True for value in classifications)
        if all(value is not None for value in classifications)
        else None
    )
    has_images: bool | None
    if any(value is True for value in classifications):
        has_images = True
    elif any(value is None for value in classifications):
        has_images = None
    else:
        has_images = False
    return {
        "file_count": len(raw_files),
        "image_count": image_count,
        "has_files": bool(raw_files),
        "has_images": has_images,
    }


def _first_line(value: Any, *, fallback: str) -> str:
    return next(
        (line.strip() for line in str(value or "").splitlines() if line.strip()),
        fallback,
    )


def build_note_catalog_item(
    note: Mapping[str, Any],
    *,
    parent_post_id: str | None = None,
) -> CatalogMember | None:
    note_id = str(note.get("id") or "").strip()
    if not note_id or not is_catalog_visible(note):
        return None
    body = str(note.get("body") or "").strip()
    facts = _attachment_facts(note, field="files")
    parent = (
        {"kind": "post", "ref": f"post:{parent_post_id}"}
        if parent_post_id
        else None
    )
    return {
        "ref": f"note:{note_id}",
        "kind": "note",
        "id": note_id,
        "title": _first_line(note.get("title"), fallback=_first_line(body, fallback=note_id)),
        "status": str(note.get("status") or "active").strip().lower(),
        "visibility": "included",
        "revision": catalog_item_revision(note, kind="note"),
        "parent": parent,
        "parent_post_id": parent_post_id,
        "preview": body[:80] + ("…" if len(body) > 80 else ""),
        "estimated_full_text_chars": len(body),
        **facts,
    }


def _known_sum(values: Iterable[int | None]) -> int | None:
    materialized = list(values)
    if any(value is None for value in materialized):
        return None
    return sum(int(value) for value in materialized if value is not None)


def _known_bool_or(values: Iterable[bool | None]) -> bool | None:
    materialized = list(values)
    if any(value is True for value in materialized):
        return True
    if any(value is None for value in materialized):
        return None
    return False


def build_post_catalog_item(post: Mapping[str, Any]) -> CatalogMember | None:
    post_id = str(post.get("id") or "").strip()
    if not post_id or not is_catalog_visible(post):
        return None
    direct = _attachment_facts(post, field="media")
    notes_raw = post.get("notes")
    notes_known = isinstance(notes_raw, (list, tuple)) and all(
        isinstance(item, Mapping) for item in (notes_raw or ())
    )
    note_items = (
        [
            item
            for raw in (notes_raw or ())
            if (item := build_note_catalog_item(raw, parent_post_id=post_id)) is not None
        ]
        if notes_known
        else []
    )
    note_files_total = (
        _known_sum(item.get("file_count") for item in note_items) if notes_known else None
    )
    note_image_files_total = (
        _known_sum(item.get("image_count") for item in note_items) if notes_known else None
    )
    notes_with_files_count = (
        sum(item.get("has_files") is True for item in note_items)
        if notes_known and all(item.get("has_files") is not None for item in note_items)
        else None
    )
    notes_with_images_count = (
        sum(item.get("has_images") is True for item in note_items)
        if notes_known and all(item.get("has_images") is not None for item in note_items)
        else None
    )
    has_note_images = (
        _known_bool_or(item.get("has_images") for item in note_items)
        if notes_known
        else None
    )
    file_count = _known_sum([direct["file_count"], note_files_total])
    image_count = _known_sum([direct["image_count"], note_image_files_total])
    has_files = _known_bool_or(
        [direct["has_files"], *(item.get("has_files") for item in note_items)]
    )
    has_any_images = _known_bool_or([direct["has_images"], has_note_images])
    text_value = str(post.get("text") or "").strip()
    return {
        "ref": f"post:{post_id}",
        "kind": "post",
        "id": post_id,
        "title": _first_line(
            post.get("title"), fallback=_first_line(text_value, fallback=f"Пост {post_id}")
        ),
        "status": str(post.get("status") or "draft").strip().lower(),
        "visibility": "included",
        "revision": catalog_item_revision(post, kind="post"),
        "parent": None,
        "preview": text_value[:80] + ("…" if len(text_value) > 80 else ""),
        "estimated_full_text_chars": len(text_value),
        "notes_count": len(note_items) if notes_known else None,
        "file_count": file_count,
        "image_count": image_count,
        "has_files": has_files,
        "has_images": has_any_images,
        "direct_media_count": direct["file_count"],
        "direct_image_count": direct["image_count"],
        "note_files_total": note_files_total,
        "note_image_files_total": note_image_files_total,
        "notes_with_files_count": notes_with_files_count,
        "notes_with_images_count": notes_with_images_count,
        "has_any_images": has_any_images,
    }


def _page(
    members: list[CatalogMember],
    *,
    cursor: str | int | None,
    page_size: int,
) -> tuple[list[CatalogMember], int, str | None, bool]:
    try:
        offset = max(0, int(cursor or 0))
    except (TypeError, ValueError):
        offset = 0
    size = min(DEFAULT_CATALOG_PAGE_SIZE, max(1, int(page_size)))
    end = min(len(members), offset + size)
    return (
        members[offset:end],
        offset,
        str(end) if end < len(members) else None,
        end >= len(members),
    )


def _property_coverage(
    members: list[CatalogMember],
    properties: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    provided: list[str] = []
    omitted: list[str] = []
    for property_name in properties:
        field = property_name.rsplit(".", 1)[-1]
        (provided if all(item.get(field) is not None for item in members) else omitted).append(
            property_name
        )
    return provided, omitted


def _notes_aggregates(members: list[CatalogMember]) -> dict[str, int | None]:
    has_files_known = all(item.get("has_files") is not None for item in members)
    has_images_known = all(item.get("has_images") is not None for item in members)
    return {
        "total_notes": len(members),
        "notes_with_files": (
            sum(item.get("has_files") is True for item in members) if has_files_known else None
        ),
        "notes_with_images": (
            sum(item.get("has_images") is True for item in members) if has_images_known else None
        ),
        "image_files_total": _known_sum(item.get("image_count") for item in members),
    }


def _posts_aggregates(members: list[CatalogMember]) -> dict[str, int | None]:
    return {
        "total_posts": len(members),
        "direct_media_count": _known_sum(item.get("direct_media_count") for item in members),
        "direct_image_count": _known_sum(item.get("direct_image_count") for item in members),
        "note_files_total": _known_sum(item.get("note_files_total") for item in members),
        "note_image_files_total": _known_sum(
            item.get("note_image_files_total") for item in members
        ),
        "notes_with_files_count": _known_sum(
            item.get("notes_with_files_count") for item in members
        ),
        "notes_with_images_count": _known_sum(
            item.get("notes_with_images_count") for item in members
        ),
        "posts_with_any_images": (
            sum(item.get("has_any_images") is True for item in members)
            if all(item.get("has_any_images") is not None for item in members)
            else None
        ),
    }


def _structural_result_sets(
    members: list[CatalogMember], *, kind: Literal["notes", "posts"]
) -> dict[str, list[str] | None]:
    """Return backend-computed filter membership without collapsing unknown to false."""

    def matching(property_name: str) -> list[str] | None:
        values = [item.get(property_name) for item in members]
        if any(value is None for value in values):
            return None
        return [str(item["ref"]) for item, value in zip(members, values) if value is True]

    if kind == "notes":
        return {
            "notes_with_files": matching("has_files"),
            "notes_with_images": matching("has_images"),
        }
    return {
        "posts_with_direct_images": (
            None
            if any(item.get("direct_image_count") is None for item in members)
            else [str(item["ref"]) for item in members if int(item.get("direct_image_count") or 0) > 0]
        ),
        "posts_with_images_in_notes": (
            None
            if any(item.get("note_image_files_total") is None for item in members)
            else [
                str(item["ref"])
                for item in members
                if int(item.get("note_image_files_total") or 0) > 0
            ]
        ),
        "posts_with_any_images": matching("has_any_images"),
    }


def build_catalog_snapshot(
    raw_members: Iterable[Mapping[str, Any]],
    *,
    kind: Literal["notes", "posts"],
    source_requirement_id: str,
    cursor: str | int | None = None,
    page_size: int = DEFAULT_CATALOG_PAGE_SIZE,
) -> CatalogSnapshot:
    built: list[CatalogMember] = []
    seen_refs: set[str] = set()
    for raw in raw_members:
        item = (
            build_note_catalog_item(
                raw,
                parent_post_id=str(raw.get("_parent_post_id") or "").strip() or None,
            )
            if kind == "notes"
            else build_post_catalog_item(raw)
        )
        if item is None or item["ref"] in seen_refs:
            continue
        seen_refs.add(item["ref"])
        built.append(item)
    properties = NOTE_PROPERTIES if kind == "notes" else POST_PROPERTIES
    provided, omitted = _property_coverage(built, properties)
    page_members, offset, next_cursor, members_complete = _page(
        built, cursor=cursor, page_size=page_size
    )
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "kind": kind,
        "source_requirement_id": str(source_requirement_id or ""),
        "members": page_members,
        "members_complete": members_complete,
        "total_members": len(built),
        "aggregates": (
            _notes_aggregates(built) if kind == "notes" else _posts_aggregates(built)
        ),
        "result_sets": _structural_result_sets(built, kind=kind),
        # Result sets and aggregates are computed over ``built`` before the
        # member projection is paged, so structural queries remain complete.
        "result_sets_complete": True,
        "provided_properties": provided,
        "omitted_properties": omitted,
        "next_cursor": next_cursor,
        "page": {
            "offset": offset,
            "limit": min(DEFAULT_CATALOG_PAGE_SIZE, max(1, int(page_size))),
        },
    }


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "CatalogMember",
    "CatalogSnapshot",
    "DEFAULT_CATALOG_PAGE_SIZE",
    "build_catalog_snapshot",
    "catalog_item_revision",
    "build_note_catalog_item",
    "build_post_catalog_item",
    "is_catalog_visible",
    "is_image_file",
    "normalized_mime_type",
]
