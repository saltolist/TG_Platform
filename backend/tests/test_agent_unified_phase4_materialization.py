"""Unified integrity phase-4 compiler, hydration and pack-boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.research.catalog import build_catalog_snapshot
from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.evidence_pack import build_verified_evidence_pack
from app.services.agent.research.graph import (
    _hydrate_selected_semantic_cards,
    research_pack_node,
)
from app.services.agent.research.material_plan import (
    MATERIAL_PLAN_SCHEMA_V2,
    compile_material_plan,
    normalize_candidates,
)
from app.services.agent.runtime.message_context import supplied_object_refs
from app.services.ai.semantic_summary import DISCOVERY_SUMMARY_VERSION


def _candidate(
    ref: str,
    *,
    source: str = "workspace-notes",
    origin: str = "semantic_search",
    parent_post_id: str | None = None,
) -> dict:
    return normalize_candidates(
        [
            {
                "ref": ref,
                "title": ref,
                "card_text": f"Card for {ref}",
                "origin": origin,
                "semantic_score": 0.8 if origin == "semantic_search" else None,
                "source_requirement_id": source,
                "index_revision": 5,
                "source_revision": 5,
                "summary_version": DISCOVERY_SUMMARY_VERSION,
                "summary_model": f"llm:test:model:v{DISCOVERY_SUMMARY_VERSION}",
                "status": "active",
                "parent_post_id": parent_post_id,
            }
        ]
    )[0]


def _assessment(
    ref: str,
    *,
    relevance: str = "direct",
    resolution: str = "card",
    confidence: float = 0.9,
) -> dict:
    return {
        "ref": ref,
        "relevance": relevance,
        "role": "answer_evidence" if relevance != "irrelevant" else "none",
        "resolution": resolution if relevance != "irrelevant" else "none",
        "confidence": confidence,
        "reason_code": "topic_only" if resolution == "card" else "exact_fact",
        "selection_source": "context_selector_v2",
    }


def _contract(*, fidelity: str = "full_text", predicate: str = "semantic") -> dict:
    evidence_requirements = (
        [
            {"subject": "notes", "property": "total_notes"},
            {"subject": "notes", "property": "has_images"},
        ]
        if predicate in {"structural", "mixed"}
        else []
    )
    return {
        "version": 3,
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "evidence_obligation": "required",
                "selection_cardinality": {"min": 0, "max": 8},
                "predicate_kind": predicate,
                "required_fidelity": fidelity,
                "evidence_requirements": evidence_requirements,
                "budget": {"candidate_limit": 4},
            }
        ],
    }


def _record(
    ref: str,
    *,
    content: str = "full text",
    kind: str = "note_chunk",
    metadata: dict | None = None,
    producer: str = "rag_tools",
) -> EvidenceRecord:
    object_id = ref.split(":", 1)[-1]
    path = f"/note/global/{object_id}/"
    return EvidenceRecord(
        id=path,
        kind=kind,  # type: ignore[arg-type]
        source_ref=ref,
        content=content,
        citation_path=path,
        citation_title=ref,
        metadata={
            "owner_verified": True,
            "status_verified": True,
            "status": "active",
            "source_revision": 5,
            **(metadata or {}),
        },
        producer=producer,
    )


def test_compiler_consumes_v2_assessments_and_applies_fidelity_floor() -> None:
    direct = _candidate("note:n1", parent_post_id="p1")
    irrelevant = _candidate("note:n2")

    plan = compile_material_plan(
        None,
        candidates=[direct, irrelevant],
        assessments=[
            _assessment("note:n1", resolution="card"),
            _assessment("note:n2", relevance="irrelevant"),
        ],
        source_dispositions=[{"source_id": "workspace-notes", "status": "selected"}],
        contract=_contract(fidelity="full_text"),
    )

    assert plan["schema"] == MATERIAL_PLAN_SCHEMA_V2
    assert [item["ref"] for item in plan["materialization_queue"]] == ["note:n1"]
    item = plan["materialization_queue"][0]
    assert item["effective_fidelity"] == "full_text"
    assert item["parent"] == {"kind": "post", "ref": "post:p1"}
    assert item["provenance"]["selector_schema"] == "workspace.context-selector/v2"
    assert plan["pending_full_text_ids"] == ["note:n1"]
    assert any(event["reason"] == "contract_fidelity_floor" for event in plan["runtime_trace"])


def test_dispositions_never_manufacture_selection_and_search_is_bounded() -> None:
    candidate = _candidate("note:n1")
    plan = compile_material_plan(
        None,
        candidates=[candidate],
        assessments=[_assessment("note:n1", relevance="irrelevant")],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "no_relevant_candidate"},
            {"source_id": "workspace-posts", "status": "search_more"},
            {"source_id": "workspace-media", "status": "ambiguous"},
        ],
        contract=_contract(),
    )

    assert plan["materialization_queue"] == []
    assert plan["discovery_actions"] == [
        {"kind": "bounded_discovery", "source_id": "workspace-media", "max_actions": 1},
        {"kind": "bounded_discovery", "source_id": "workspace-posts", "max_actions": 1},
    ]
    assert {gap["kind"] for gap in plan["gaps"]} == {
        "ambiguous",
        "no_relevant_candidate",
        "search_more",
    }


def test_recall_shortlist_admits_card_negative_candidate_to_full_read_only() -> None:
    first = _candidate("note:first")
    probe = _candidate("note:probe")
    plan = compile_material_plan(
        {
            "precision_full_text_shortlist_refs": ["note:first", "note:probe"],
        },
        candidates=[first, probe],
        assessments=[
            _assessment("note:first", resolution="full_text"),
            _assessment("note:probe", relevance="irrelevant"),
        ],
        source_dispositions=[{"source_id": "workspace-notes", "status": "selected"}],
        contract=_contract(),
    )

    assert plan["pending_full_text_ids"] == ["note:first", "note:probe"]
    assert any(
        event.get("kind") == "recall_cohort_full_read_admission"
        and event.get("ref") == "note:probe"
        for event in plan["runtime_trace"]
    )
    assert next(
        item for item in plan["assessments"] if item["ref"] == "note:probe"
    )["relevance"] == "irrelevant"

    locked = compile_material_plan(
        {
            **plan,
            "membership_locked": True,
            "membership_locked_refs": ["note:first"],
        },
        candidates=[first, probe],
        assessments=[
            _assessment("note:first", resolution="full_text"),
            _assessment("note:probe", relevance="irrelevant"),
        ],
        source_dispositions=[{"source_id": "workspace-notes", "status": "selected"}],
        contract=_contract(),
    )

    assert locked["pending_full_text_ids"] == ["note:first"]
    assert [item["ref"] for item in locked["materialization_queue"]] == [
        "note:first"
    ]


def test_selector_failure_preserves_only_exact_target() -> None:
    exact = _candidate("note:exact", origin="exact_target")
    ambient = _candidate("note:ambient", origin="ambient_current_post")
    previous = {"selector_failure": {"kind": "selector_failed"}}

    plan = compile_material_plan(
        previous,
        candidates=[exact, ambient],
        assessments=[],
        contract=_contract(),
    )

    assert [item["ref"] for item in plan["materialization_queue"]] == ["note:exact"]
    assert plan["coverage"] == "partial"


def test_object_and_char_budgets_omit_before_read_queue() -> None:
    candidates = [_candidate(f"note:n{index}") for index in range(3)]
    plan = compile_material_plan(
        None,
        candidates=candidates,
        assessments=[
            _assessment(item["ref"], resolution="full_text", confidence=1 - index / 10)
            for index, item in enumerate(candidates)
        ],
        contract=_contract(),
        max_objects=2,
        max_full_text_chars=4_000,
    )

    assert plan["pending_full_text_ids"] == ["note:n0", "note:n1"]
    assert set(plan["omitted_ids"]) == {"note:n2"}
    assert plan["budget_usage"] == {
        "objects": 2,
        "full_text_chars_reserved": 2_666,
        "card_chars_reserved": 0,
    }
    assert plan["coverage"] == "partial"


def test_eight_short_full_text_objects_share_twelve_k_budget() -> None:
    candidates = []
    for index in range(8):
        candidate = _candidate(f"note:n{index}")
        candidate["estimated_full_text_chars"] = 900 + index
        candidates.append(candidate)

    plan = compile_material_plan(
        None,
        candidates=candidates,
        assessments=[
            _assessment(item["ref"], resolution="full_text") for item in candidates
        ],
        source_dispositions=[{"source_id": "workspace-notes", "status": "selected"}],
        contract=_contract(),
        max_objects=8,
        max_full_text_chars=12_000,
    )

    assert plan["pending_full_text_ids"] == [f"note:n{index}" for index in range(8)]
    assert plan["omitted_ids"] == []
    assert plan["budget_usage"]["full_text_chars_reserved"] == sum(
        900 + index for index in range(8)
    )
    assert plan["coverage"] == "complete"


def test_required_no_relevant_source_is_partial_without_exhaustive_absence() -> None:
    candidate = _candidate("note:n1")
    plan = compile_material_plan(
        None,
        candidates=[candidate],
        assessments=[_assessment("note:n1", relevance="irrelevant")],
        source_dispositions=[
            {"source_id": "workspace-notes", "status": "no_relevant_candidate"}
        ],
        contract=_contract(),
    )

    assert plan["materialization_queue"] == []
    assert plan["coverage"] == "partial"
    assert next(gap for gap in plan["gaps"] if gap["kind"] == "no_relevant_candidate") == {
        "kind": "no_relevant_candidate",
        "source_id": "workspace-notes",
        "blocks_ready": True,
        "exhaustive_absence": False,
    }


@pytest.mark.asyncio
async def test_hydration_reads_only_compiled_refs_and_records_lineage() -> None:
    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    first = _record("note:n1", kind="semantic_card", metadata={"ref": "note:n1", "source_revision": 5})
    second = _record("note:n2", kind="semantic_card", metadata={"ref": "note:n2", "source_revision": 5})
    ctx = SimpleNamespace(
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        session_factory=lambda: SessionContext(),
    )
    reader = AsyncMock(return_value={"id": "n2", "title": "N2", "body": "hydrated body", "revision": 5})
    with patch("app.services.ai.rag.get_note_data", new=reader), patch(
        "app.services.ai.rag.object_index_revision", return_value=5
    ):
        hydrated, gaps = await _hydrate_selected_semantic_cards(
            records={first.id: first, second.id: second},
            evidence_ids=[first.id, second.id],
            ctx=ctx,
            required_full_text_refs={"note:n2"},
            max_reads=1,
        )

    assert gaps == ()
    reader.assert_awaited_once()
    assert hydrated[first.id].kind == "semantic_card"
    assert hydrated[second.id].kind == "note_chunk"
    assert hydrated[second.id].metadata["hydrated_from"] == "semantic_card"
    assert hydrated[second.id].metadata["hydrated"] is True


def test_pack_verifier_rejects_unselected_and_unverified_promotion() -> None:
    candidate = _candidate("note:n1")
    plan = compile_material_plan(
        None,
        candidates=[candidate],
        assessments=[_assessment("note:n1", resolution="full_text")],
        contract=_contract(),
    )
    selected = _record(
        "note:n1",
        metadata={"source_revision": 5, "hydrated_from": "semantic_card", "hydrated": False},
        producer="final_handoff_hydration",
    )
    unselected = _record("note:n2")

    pack = build_verified_evidence_pack(
        records={selected.id: selected, unselected.id: unselected},
        evidence_ids=[selected.id, unselected.id],
        material_plan=plan,
        contract=_contract(),
        item_annotations={
            selected.id: {"source_requirement_id": "workspace-notes"},
            unselected.id: {"source_requirement_id": "workspace-notes"},
        },
    )

    assert pack.items == ()
    assert pack.coverage == "partial"
    assert "lineage:note:n1:unverified_hydration" in pack.unresolved
    assert "membership:note:n2" in pack.unresolved


def test_verified_hydration_keeps_stable_id_revision_parent_and_provenance() -> None:
    candidate = _candidate("note:n1", parent_post_id="p1")
    plan = compile_material_plan(
        None,
        candidates=[candidate],
        assessments=[_assessment("note:n1", resolution="full_text")],
        contract=_contract(),
    )
    record = _record(
        "note:n1",
        metadata={"source_revision": 5, "hydrated_from": "semantic_card", "hydrated": True},
        producer="final_handoff_hydration",
    )
    pack = build_verified_evidence_pack(
        records={record.id: record},
        evidence_ids=[record.id],
        material_plan=plan,
        contract=_contract(),
        item_annotations={record.id: {"source_requirement_id": "workspace-notes"}},
    )

    assert pack.evidence_ids == (record.id,)
    assert pack.items[0].fidelity == "full_text"
    assert pack.items[0].provenance["source_revision"] == 5
    assert pack.items[0].provenance["hydration_verified"] is True
    assert pack.items[0].provenance["parent"] == {"kind": "post", "ref": "post:p1"}

    stale = EvidenceRecord(
        **{
            **record.to_dict(),
            "metadata": {**record.metadata, "source_revision": 6},
        }
    )
    stale_pack = build_verified_evidence_pack(
        records={stale.id: stale},
        evidence_ids=[stale.id],
        material_plan=plan,
        contract=_contract(),
        item_annotations={stale.id: {"source_requirement_id": "workspace-notes"}},
    )
    assert stale_pack.items == ()
    assert "revision:note:n1:mismatch" in stale_pack.unresolved


def test_vision_fidelity_is_not_flattened_to_full_text() -> None:
    candidate = normalize_candidates(
        [
            {
                "ref": "attachment:f1",
                "origin": "semantic_search",
                "semantic_score": 0.9,
                "source_requirement_id": "workspace-notes",
                "parent_note_id": "n1",
            }
        ]
    )[0]
    plan = compile_material_plan(
        None,
        candidates=[candidate],
        assessments=[_assessment("attachment:f1", resolution="full_text")],
        contract=_contract(fidelity="vision"),
    )
    record = EvidenceRecord(
        id="/attachment/f1/",
        kind="vision",
        source_ref="attachment:f1",
        content="visible text",
        citation_path="/attachment/f1/",
        citation_title="Image",
        metadata={
            "owner_verified": True,
            "status_verified": True,
            "status": "active",
            "fidelity": "vision",
        },
        producer="rag_tools",
    )
    pack = build_verified_evidence_pack(
        records={record.id: record},
        evidence_ids=[record.id],
        material_plan=plan,
        contract=_contract(fidelity="vision"),
        item_annotations={record.id: {"source_requirement_id": "workspace-notes"}},
    )

    assert plan["materialization_queue"][0]["effective_fidelity"] == "vision"
    assert pack.items[0].fidelity == "vision"


def test_pack_truncation_downgrades_coverage_and_reports_source_omissions() -> None:
    candidates = [_candidate("note:n1"), _candidate("note:n2")]
    plan = compile_material_plan(
        None,
        candidates=candidates,
        assessments=[_assessment(item["ref"], resolution="full_text") for item in candidates],
        contract=_contract(),
        max_full_text_chars=8_000,
    )
    records = {
        record.id: record
        for record in (
            _record("note:n1", content="a" * 1_000),
            _record("note:n2", content="b" * 1_000),
        )
    }
    pack = build_verified_evidence_pack(
        records=records,
        evidence_ids=list(records),
        max_chars=500,
        material_plan=plan,
        contract=_contract(),
        item_annotations={
            key: {"source_requirement_id": "workspace-notes"} for key in records
        },
    )

    assert pack.coverage == "partial"
    assert pack.truncation["truncated_ids"]
    assert pack.coverage_by_source["workspace-notes"]["packed_count"] == 2
    assert pack.coverage_by_source["workspace-notes"]["coverage"] == "partial"


def test_mixed_catalog_is_structural_evidence_and_inconsistent_aggregate_is_rejected() -> None:
    snapshot = build_catalog_snapshot(
        [{"id": "n1", "title": "N1", "body": "body", "files": []}],
        kind="notes",
        source_requirement_id="workspace-notes",
    )
    record = EvidenceRecord(
        id="/global/notes/",
        kind="catalog",
        source_ref="/global/notes/",
        content="total_notes=1",
        citation_path="/global/notes/",
        citation_title="Notes",
        metadata={"catalog_snapshot": snapshot},
    )
    plan = {"materialization_queue": [], "candidates": [], "coverage": "complete"}
    contract = _contract(fidelity="catalog", predicate="mixed")
    valid = build_verified_evidence_pack(
        records={record.id: record},
        evidence_ids=[record.id],
        material_plan=plan,
        contract=contract,
        item_annotations={record.id: {"source_requirement_id": "workspace-notes"}},
    )
    assert valid.evidence_ids == (record.id,)

    broken_snapshot = {
        **snapshot,
        "aggregates": {**snapshot["aggregates"], "total_notes": 2},
    }
    broken = EvidenceRecord(
        **{
            **record.to_dict(),
            "metadata": {"catalog_snapshot": broken_snapshot},
        }
    )
    invalid = build_verified_evidence_pack(
        records={broken.id: broken},
        evidence_ids=[broken.id],
        material_plan=plan,
        contract=contract,
        item_annotations={broken.id: {"source_requirement_id": "workspace-notes"}},
    )
    assert invalid.items == ()
    assert "catalog:workspace-notes:aggregate_total_notes" in invalid.unresolved


@pytest.mark.asyncio
async def test_verified_boundary_keeps_structural_catalog_without_member_reads() -> None:
    snapshot = build_catalog_snapshot(
        [
            {
                "id": "n1",
                "title": "N1",
                "body": "body",
                "files": [{"id": "f1", "type": "image/png"}],
            }
        ],
        kind="notes",
        source_requirement_id="workspace-notes",
    )
    catalog = EvidenceRecord(
        id="/global/notes/",
        kind="catalog",
        source_ref="/global/notes/",
        content="notes_with_images=1",
        citation_path="/global/notes/",
        citation_title="Notes",
        metadata={
            "members": [{"kind": "note", "id": "n1", "revision": 5}],
            "catalog_snapshot": snapshot,
        },
    )
    contract = _contract(fidelity="catalog", predicate="structural")
    ctx = SimpleNamespace(
        settings=Settings(
            agent_unified_catalog_v1_enabled=True,
            agent_typed_requirements_v1_enabled=True,
            agent_unified_selector_v1_enabled=True,
            agent_verified_pack_boundary_v1_enabled=True,
        ),
        session_factory=AsyncMock(),
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
    )
    state = {
        "turn_contract": contract,
        "verified_pack_boundary_enabled": True,
        "adaptive_evidence_depth_enabled": True,
        "evidence_records": {catalog.id: catalog.to_dict()},
        "finish_retrieval": {"status": "ready", "evidence_ids": [catalog.id]},
        "material_plan": {
            "schema": MATERIAL_PLAN_SCHEMA_V2,
            "materialization_queue": [],
            "candidates": [],
            "omitted_ids": [],
            "gaps": [],
            "coverage": "complete",
            "budget": {"max_objects": 8},
        },
    }

    with patch("app.services.ai.rag.get_note_data", new=AsyncMock()) as reader:
        result = await research_pack_node(
            state, {"configurable": {"runtime_context": ctx, "turn_contract": contract}}
        )

    reader.assert_not_awaited()
    assert result["evidence_pack"]["evidence_ids"] == [catalog.id]
    assert supplied_object_refs(result["evidence_pack"]) == set()


def test_legacy_pack_builder_remains_compatible_without_material_plan() -> None:
    record = _record("note:n1")
    pack = build_verified_evidence_pack(
        records={record.id: record}, evidence_ids=[record.id]
    )

    assert pack.evidence_ids == (record.id,)
    assert pack.schema == "workspace.evidence-pack/v1"
    assert pack.coverage == "complete"
