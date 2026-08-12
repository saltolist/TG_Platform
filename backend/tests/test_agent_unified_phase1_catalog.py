"""Unified integrity phase-1 typed catalog and aggregate tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.research.catalog import (
    CATALOG_SCHEMA_VERSION,
    build_catalog_snapshot,
    catalog_item_revision,
    is_image_file,
    normalized_mime_type,
)
from app.services.agent.research.evidence import records_from_agent_state
from app.services.agent.research.graph import _current_post_note_catalog
from app.services.agent.research.material_plan import normalize_candidates
from app.services.ai.rag_tools import (
    AgentState,
    tool_list_all_notes,
    tool_list_global_notes,
    tool_list_posts,
)


def _note(note_id: str, files=(), **extra):
    return {
        "id": note_id,
        "title": f"Note {note_id}",
        "body": "Body",
        "status": "active",
        "files": list(files),
        **extra,
    }


def _state(*, enabled: bool = True, tenant_key: str | None = None) -> AgentState:
    embedding = AsyncMock()
    embedding.model_key = "test"
    return AgentState(
        session=AsyncMock(),
        user_id=uuid4(),
        scope="global",
        tenant_key=tenant_key,
        embedding_backend=embedding,
        settings=Settings(agent_unified_catalog_v1_enabled=enabled),
    )


def test_note_snapshot_schema_explicit_zero_and_two_image_aggregate() -> None:
    snapshot = build_catalog_snapshot(
        [
            _note("empty"),
            _note(
                "images",
                [
                    {"id": "i1", "type": "image/png"},
                    {"id": "i2", "mime_type": "IMAGE/JPEG; charset=binary"},
                ],
            ),
        ],
        kind="notes",
        source_requirement_id="workspace-notes",
    )

    assert snapshot["schema_version"] == CATALOG_SCHEMA_VERSION
    assert set(snapshot) == {
        "schema_version",
        "kind",
        "source_requirement_id",
        "members",
        "members_complete",
        "total_members",
        "aggregates",
        "result_sets",
        "result_sets_complete",
        "provided_properties",
        "omitted_properties",
        "next_cursor",
        "page",
    }
    assert snapshot["source_requirement_id"] == "workspace-notes"
    assert snapshot["members_complete"] is True
    assert snapshot["total_members"] == 2
    assert snapshot["aggregates"] == {
        "total_notes": 2,
        "notes_with_files": 1,
        "notes_with_images": 1,
        "image_files_total": 2,
    }
    empty, images = snapshot["members"]
    assert (empty["file_count"], empty["image_count"]) == (0, 0)
    assert (empty["has_files"], empty["has_images"]) == (False, False)
    assert (images["file_count"], images["image_count"]) == (2, 2)
    assert set(snapshot["provided_properties"]) == {
        "notes.file_count",
        "notes.image_count",
        "notes.has_files",
        "notes.has_images",
    }
    assert snapshot["omitted_properties"] == []
    json.dumps(snapshot)


def test_unknown_attachment_properties_never_become_false_or_zero() -> None:
    snapshot = build_catalog_snapshot(
        [
            {"id": "legacy", "title": "No files field"},
            _note("unknown-mime", [{"id": "f1", "name": "looks-like-image.png"}]),
        ],
        kind="notes",
        source_requirement_id="workspace-notes",
    )

    legacy, unknown_mime = snapshot["members"]
    assert legacy["file_count"] is None
    assert legacy["image_count"] is None
    assert legacy["has_files"] is None
    assert legacy["has_images"] is None
    assert unknown_mime["file_count"] == 1
    assert unknown_mime["has_files"] is True
    assert unknown_mime["image_count"] is None
    assert unknown_mime["has_images"] is None
    assert snapshot["aggregates"] == {
        "total_notes": 2,
        "notes_with_files": None,
        "notes_with_images": None,
        "image_files_total": None,
    }
    assert snapshot["provided_properties"] == []
    assert set(snapshot["omitted_properties"]) == {
        "notes.file_count",
        "notes.image_count",
        "notes.has_files",
        "notes.has_images",
    }


def test_mime_classification_uses_declared_normalized_mime_only() -> None:
    assert normalized_mime_type({"name": "raw", "type": " IMAGE/WEBP ; q=1"}) == (
        "image/webp"
    )
    assert is_image_file({"name": "raw", "type": " IMAGE/WEBP ; q=1"}) is True
    assert is_image_file({"name": "photo.png"}) is None
    assert is_image_file({"name": "photo", "type": "application/pdf"}) is False
    assert is_image_file({"name": "photo.png", "type": "application/octet-stream"}) is None


def test_catalog_revision_changes_when_attachment_structure_changes() -> None:
    empty = _note("revision")
    with_file = _note("revision", [{"id": "f1", "type": "image/png"}])
    assert catalog_item_revision(empty, kind="note") != catalog_item_revision(
        with_file, kind="note"
    )


def test_complete_note_union_deduplicates_global_and_post_owned_ref() -> None:
    snapshot = build_catalog_snapshot(
        [
            _note("global", [{"id": "g", "type": "image/png"}]),
            {**_note("post", []), "_parent_post_id": "post-1"},
            {
                **_note("global", [{"id": "duplicate", "type": "image/png"}]),
                "_parent_post_id": "post-2",
            },
        ],
        kind="notes",
        source_requirement_id="workspace-notes",
    )

    assert [item["ref"] for item in snapshot["members"]] == [
        "note:global",
        "note:post",
    ]
    assert snapshot["aggregates"]["total_notes"] == 2
    assert snapshot["aggregates"]["image_files_total"] == 1
    assert snapshot["members"][1]["parent"] == {
        "kind": "post",
        "ref": "post:post-1",
    }


def test_post_aggregates_keep_direct_and_note_media_separate_and_union_once() -> None:
    snapshot = build_catalog_snapshot(
        [
            {
                "id": "p1",
                "status": "published",
                "text": "Post one",
                "media": [{"id": "direct", "type": "image/jpeg"}],
                "notes": [
                    _note(
                        "n1",
                        [
                            {"id": "nested-image", "type": "image/png"},
                            {"id": "nested-doc", "type": "application/pdf"},
                        ],
                    )
                ],
            },
            {
                "id": "p2",
                "status": "draft",
                "text": "Post two",
                "media": [],
                "notes": [_note("n2", [{"id": "img", "type": "image/webp"}])],
            },
        ],
        kind="posts",
        source_requirement_id="workspace-posts",
    )

    assert snapshot["aggregates"] == {
        "total_posts": 2,
        "draft_posts": 1,
        "scheduled_posts": 0,
        "published_posts": 1,
        "direct_media_count": 1,
        "direct_image_count": 1,
        "note_files_total": 3,
        "note_image_files_total": 2,
        "notes_with_files_count": 2,
        "notes_with_images_count": 2,
        "posts_with_any_images": 2,
    }
    first = snapshot["members"][0]
    assert first["direct_image_count"] == 1
    assert first["note_image_files_total"] == 1
    assert first["image_count"] == 2


def test_catalog_paging_over_one_hundred_is_deterministic() -> None:
    notes = [_note(f"n-{index:03d}") for index in range(101)]
    first = build_catalog_snapshot(
        notes,
        kind="notes",
        source_requirement_id="workspace-notes",
    )
    second = build_catalog_snapshot(
        notes,
        kind="notes",
        source_requirement_id="workspace-notes",
        cursor=first["next_cursor"],
    )

    assert first["total_members"] == 101
    assert len(first["members"]) == 100
    assert first["members_complete"] is False
    assert first["next_cursor"] == "100"
    assert len(second["members"]) == 1
    assert second["members_complete"] is True
    assert second["next_cursor"] is None
    assert second["members"][0]["ref"] == "note:n-100"
    assert first["aggregates"] == second["aggregates"]


def test_catalog_filters_deleted_hidden_and_inaccessible_members() -> None:
    snapshot = build_catalog_snapshot(
        [
            _note("active"),
            _note("deleted", status="deleted"),
            _note("hidden", status="hidden"),
            _note("inaccessible", status="inaccessible"),
        ],
        kind="notes",
        source_requirement_id="workspace-notes",
    )
    assert [item["ref"] for item in snapshot["members"]] == ["note:active"]
    assert snapshot["total_members"] == 1


@pytest.mark.asyncio
async def test_enabled_list_projection_adds_snapshot_without_changing_summary_or_path() -> None:
    row = MagicMock()
    row.data = {
        "id": "p1",
        "status": "draft",
        "text": "Catalog post",
        "media": [],
        "notes": [_note("n1", [{"id": "i1", "type": "image/png"}])],
    }
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    enabled = _state(enabled=True)
    disabled = _state(enabled=False)
    enabled.session.execute = AsyncMock(return_value=result)
    disabled.session.execute = AsyncMock(return_value=result)

    typed = await tool_list_posts(enabled, limit=1)
    legacy = await tool_list_posts(disabled, limit=1)

    assert typed.summary == legacy.summary
    assert typed.catalog_snapshot is not None
    assert legacy.catalog_snapshot is None
    assert typed.catalog_snapshot["total_members"] == 1
    record = records_from_agent_state(enabled)["/posts/"]
    assert record.citation_path == "/posts/"
    assert record.metadata["catalog_snapshot"] == typed.catalog_snapshot
    assert record.metadata["members"] == list(legacy.items)


@pytest.mark.asyncio
async def test_list_posts_display_limit_does_not_change_typed_total_or_page() -> None:
    rows = []
    for index in range(101):
        row = MagicMock()
        row.data = {
            "id": f"p-{index:03d}",
            "status": "draft",
            "text": f"Post {index}",
            "media": [],
            "notes": [],
        }
        rows.append(row)
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    state = _state(enabled=True)
    state.session.execute = AsyncMock(return_value=result)

    outcome = await tool_list_posts(state, limit=8)

    assert "total=101" in outcome.summary
    assert "shown=8" in outcome.summary
    assert outcome.catalog_snapshot["total_members"] == 101
    assert len(outcome.catalog_snapshot["members"]) == 100
    assert outcome.catalog_snapshot["members_complete"] is False
    assert outcome.catalog_snapshot["next_cursor"] == "100"


@pytest.mark.asyncio
async def test_global_notes_are_tenant_scoped_and_status_filtered() -> None:
    state = _state(tenant_key="tenant-a")
    visible = _note("visible")
    hidden = _note("hidden", status="hidden")
    with patch(
        "app.services.ai.rag_tools.list_global_notes",
        new_callable=AsyncMock,
        return_value=[visible, hidden],
    ) as listed:
        outcome = await tool_list_global_notes(state)

    listed.assert_awaited_once_with(
        state.session,
        state.user_id,
        tenant_key="tenant-a",
    )
    assert outcome.catalog_snapshot["total_members"] == 1
    assert outcome.catalog_snapshot["members"][0]["ref"] == "note:visible"
    assert "hidden" not in outcome.summary


@pytest.mark.asyncio
async def test_complete_tenant_inventory_uses_overlay_post_notes_not_base_posts() -> None:
    state = _state(tenant_key="tenant-a")
    overlay_note = {**_note("overlay"), "_parent_post_id": "post-1"}
    with (
        patch(
            "app.services.ai.rag_tools.list_global_notes",
            new_callable=AsyncMock,
            return_value=[_note("global")],
        ),
        patch(
            "app.services.overlay.tenant_notes.list_tenant_notes_with_parents",
            new_callable=AsyncMock,
            return_value=[overlay_note],
        ) as overlay,
    ):
        outcome = await tool_list_all_notes(state)

    overlay.assert_awaited_once_with(
        state.session,
        state.user_id,
        "tenant-a",
        "post",
    )
    assert {item["ref"] for item in outcome.catalog_snapshot["members"]} == {
        "note:global",
        "note:overlay",
    }
    assert outcome.catalog_snapshot["aggregates"]["total_notes"] == 2
    state.session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_bounded_note_catalog_probe_is_not_recorded_as_evidence() -> None:
    state = _state(tenant_key="tenant-a")
    with (
        patch(
            "app.services.ai.rag_tools.list_global_notes",
            new_callable=AsyncMock,
            return_value=[_note(f"n{index}") for index in range(4)],
        ),
        patch(
            "app.services.overlay.tenant_notes.list_tenant_notes_with_parents",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        outcome = await tool_list_all_notes(state, limit=3, record=False)

    assert [item["ref"] for item in outcome.items] == [
        "note:n0",
        "note:n1",
        "note:n2",
    ]
    assert outcome.catalog_snapshot is None
    assert state.context_blocks == []
    assert state.catalog_snapshots == {}
    assert state.visited == set()


def test_typed_ambient_candidate_has_origin_and_nullable_semantic_score() -> None:
    catalog = _current_post_note_catalog(
        {
            "id": "post-1",
            "notes": [_note("ambient", [{"id": "f1", "name": "photo.png"}])],
        },
        typed=True,
    )
    candidate = catalog[0]
    assert candidate["origin"] == "ambient_current_post"
    assert candidate["semantic_score"] is None
    assert "similarity" not in candidate
    assert "score" not in candidate
    assert candidate["image_count"] is None
    assert candidate["has_images"] is None
    normalized = normalize_candidates(catalog)[0]
    assert normalized["origin"] == "ambient_current_post"
    assert normalized["semantic_score"] is None
    assert normalized["score"] is None


def test_semantic_candidate_score_compatibility_is_unchanged() -> None:
    normalized = normalize_candidates(
        [
            {
                "ref": "note:semantic",
                "title": "Semantic",
                "preview": "Card",
                "score": 0.0,
                "similarity": 0.73,
            }
        ]
    )[0]
    assert normalized["origin"] == "semantic_search"
    assert normalized["semantic_score"] == pytest.approx(0.73)
    assert normalized["score"] == pytest.approx(0.73)
