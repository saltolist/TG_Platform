"""Verified, minimal evidence handoff for the answer model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.catalog import CATALOG_SCHEMA_VERSION
from app.services.agent.research.material_plan import (
    canonical_candidate_ref,
    card_eligibility,
)


EVIDENCE_PACK_SCHEMA = "workspace.evidence-pack/v1"
EVIDENCE_PACK_SCHEMA_V2 = "workspace.evidence-pack/v2"
_DISCOVERY_KINDS = {"search_hit", "note_summary", "post_summary", "summary"}
_ITEM_FLOOR_CHARS = 400
_FIDELITY_RANK = {
    "metadata": 0,
    "catalog": 0,
    "semantic_card": 1,
    "full_text": 2,
    "analytics": 2,
    "vision": 3,
}
_CATALOG_AGGREGATES = {
    ("notes", "total_notes"): ("total_notes",),
    ("notes", "has_images"): ("notes_with_images",),
    ("notes", "image_count"): ("image_files_total",),
    ("notes", "has_files"): ("notes_with_files",),
    ("posts", "total_posts"): ("total_posts",),
    ("posts", "draft_posts"): ("draft_posts",),
    ("posts", "scheduled_posts"): ("scheduled_posts",),
    ("posts", "published_posts"): ("published_posts",),
    ("posts", "has_any_images"): ("posts_with_any_images",),
    ("posts", "image_count"): ("direct_image_count", "note_image_files_total"),
    ("posts", "has_files"): ("direct_media_count", "note_files_total"),
}


def _record_fidelity(record: EvidenceRecord) -> str:
    if record.kind == "semantic_card":
        return "semantic_card"
    if record.kind == "catalog" or record.kind == "media_meta":
        return "catalog" if record.kind == "catalog" else "metadata"
    if record.kind == "vision":
        return "vision"
    if record.kind == "analytics":
        return "analytics"
    return "full_text"


def _catalog_verification_issues(
    snapshot: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> list[str]:
    source_id = str(source.get("source_id") or "")
    issues: list[str] = []
    if str(snapshot.get("schema_version") or "") != CATALOG_SCHEMA_VERSION:
        issues.append(f"catalog:{source_id}:schema")
    if str(snapshot.get("source_requirement_id") or "") != source_id:
        issues.append(f"catalog:{source_id}:source")
    members = [item for item in snapshot.get("members") or () if isinstance(item, Mapping)]
    structural_projection_complete = bool(snapshot.get("result_sets_complete")) and str(
        source.get("predicate_kind") or ""
    ) == "structural"
    if (
        source.get("coverage") == "complete"
        and not bool(snapshot.get("members_complete"))
        and not structural_projection_complete
    ):
        issues.append(f"catalog:{source_id}:coverage")
    if bool(snapshot.get("members_complete")) and int(snapshot.get("total_members") or 0) != len(members):
        issues.append(f"catalog:{source_id}:membership_count")
    if any(
        str(item.get("status") or "active").lower() in {"deleted", "hidden", "inaccessible"}
        or int(item.get("revision") or 0) <= 0
        for item in members
    ):
        issues.append(f"catalog:{source_id}:member_provenance")
    provided = set(str(item) for item in snapshot.get("provided_properties") or ())
    omitted = set(str(item) for item in snapshot.get("omitted_properties") or ())
    if provided & omitted:
        issues.append(f"catalog:{source_id}:property_coverage")
    aggregates = snapshot.get("aggregates") if isinstance(snapshot.get("aggregates"), Mapping) else {}
    kind = str(snapshot.get("kind") or source.get("kind") or "")
    for requirement in source.get("evidence_requirements") or ():
        if not isinstance(requirement, Mapping):
            continue
        subject = str(requirement.get("subject") or kind)
        property_name = str(requirement.get("property") or "")
        if not property_name or property_name == "grounded_evidence":
            continue
        aggregate_keys = _CATALOG_AGGREGATES.get((subject, property_name), ())
        property_known = property_name.startswith("total_") or f"{subject}.{property_name}" in provided
        if not property_known or not aggregate_keys or any(
            aggregates.get(key) is None for key in aggregate_keys
        ):
            issues.append(f"catalog:{source_id}:property_{subject}.{property_name}")
    total_key = "total_notes" if kind == "notes" else "total_posts" if kind == "posts" else ""
    if total_key and aggregates.get(total_key) != snapshot.get("total_members"):
        issues.append(f"catalog:{source_id}:aggregate_{total_key}")
    if bool(snapshot.get("members_complete")) and kind == "notes":
        if "notes.has_images" in provided:
            expected = sum(item.get("has_images") is True for item in members)
            if aggregates.get("notes_with_images") != expected:
                issues.append(f"catalog:{source_id}:aggregate_notes_with_images")
        if "notes.image_count" in provided:
            expected = sum(int(item.get("image_count") or 0) for item in members)
            if aggregates.get("image_files_total") != expected:
                issues.append(f"catalog:{source_id}:aggregate_image_files_total")
    return issues


@dataclass(frozen=True)
class EvidencePackItem:
    id: str
    kind: str
    title: str
    citation_path: str
    content: str
    source_ref: str
    object_kind: str = "unknown"
    evidence_role: str = "supporting"
    source_requirement_id: str = ""
    fidelity: str = "full_text"
    provenance: dict[str, Any] | None = None
    # Compact discovery/provenance data retained for the durable message
    # manifest. The final-answer renderer does not expose this metadata to the
    # model as an additional instruction or evidence body.
    metadata: dict[str, Any] | None = None
    allowed_claim_scope: str = "content"
    truncated: bool = False


@dataclass(frozen=True)
class VerifiedEvidencePack:
    schema: str
    evidence_ids: tuple[str, ...]
    items: tuple[EvidencePackItem, ...]
    unresolved: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    coverage: str = "complete"
    coverage_by_source: dict[str, Any] | None = None
    context_chars: dict[str, int] | None = None
    truncation: dict[str, Any] | None = None

    @property
    def chars(self) -> int:
        return sum(len(item.content) for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "evidence_ids": list(self.evidence_ids),
            "items": [asdict(item) for item in self.items],
            "unresolved": list(self.unresolved),
            "source_ids": list(self.source_ids),
            "chars": self.chars,
            "coverage": self.coverage,
            "coverage_by_source": dict(self.coverage_by_source or {}),
            "context_chars": dict(self.context_chars or {}),
            "truncation": dict(self.truncation or {}),
        }


def build_verified_evidence_pack(
    *,
    records: Mapping[str, EvidenceRecord],
    evidence_ids: list[str] | tuple[str, ...],
    unresolved: list[str] | tuple[str, ...] = (),
    source_ids: list[str] | tuple[str, ...] = (),
    max_chars: int = 12_000,
    max_card_chars: int = 6_000,
    schema: str | None = None,
    coverage: str = "complete",
    coverage_by_source: Mapping[str, Any] | None = None,
    item_annotations: Mapping[str, Mapping[str, Any]] | None = None,
    material_plan: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
    max_objects: int | None = None,
) -> VerifiedEvidencePack:
    """Build only from selected, non-empty primary records.

    Discovery summaries are intentionally excluded even if a caller accidentally
    includes their ids. Missing ids are omitted, never fabricated into the pack.
    """

    queue_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in (material_plan or {}).get("materialization_queue") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    exact_refs = {
        canonical_candidate_ref(str(item.get("ref") or ""))
        for item in (material_plan or {}).get("candidates") or ()
        if isinstance(item, Mapping) and str(item.get("origin") or "") == "exact_target"
    }
    structural_source_ids = {
        str(item.get("source_id") or "")
        for item in (contract or {}).get("source_requirements") or ()
        if isinstance(item, Mapping)
        and str(item.get("predicate_kind") or "") in {"structural", "mixed"}
    }
    boundary_enabled = material_plan is not None
    verification_issues: list[str] = []
    items: list[EvidencePackItem] = []
    seen_paths: set[str] = set()
    for raw_id in evidence_ids:
        eid = str(raw_id)
        record = records.get(eid)
        if record is None or record.kind in _DISCOVERY_KINDS:
            continue
        content = str(record.content or "").strip()
        path = str(record.citation_path or "").strip()
        if not content or not path or path in seen_paths:
            continue
        seen_paths.add(path)
        metadata = dict(record.metadata or {})
        annotation = dict((item_annotations or {}).get(eid) or {})
        ref = canonical_candidate_ref(str(metadata.get("ref") or record.source_ref or eid))
        queue_item = queue_by_ref.get(ref)
        source_id = str(
            annotation.get("source_requirement_id")
            or (queue_item or {}).get("source_requirement_id")
            or ""
        )
        if boundary_enabled:
            catalog_allowed = record.kind == "catalog" and source_id in structural_source_ids
            if queue_item is None and ref not in exact_refs and not catalog_allowed:
                verification_issues.append(f"membership:{ref or eid}")
                continue
            if catalog_allowed:
                snapshot = metadata.get("catalog_snapshot")
                source = next(
                    (
                        item
                        for item in (contract or {}).get("source_requirements") or ()
                        if isinstance(item, Mapping)
                        and str(item.get("source_id") or "") == source_id
                    ),
                    {},
                )
                if not isinstance(snapshot, Mapping):
                    verification_issues.append(f"catalog:{source_id}:missing_snapshot")
                    continue
                catalog_issues = _catalog_verification_issues(snapshot, source=source)
                if catalog_issues:
                    verification_issues.extend(catalog_issues)
                    continue
                structural_projection = {
                    "schema": "workspace.structural-result/v1",
                    "source_requirement_id": source_id,
                    "kind": snapshot.get("kind"),
                    "total_members": snapshot.get("total_members"),
                    "aggregates": dict(snapshot.get("aggregates") or {}),
                    "result_sets": dict(snapshot.get("result_sets") or {}),
                    "provided_properties": list(snapshot.get("provided_properties") or ()),
                    "omitted_properties": list(snapshot.get("omitted_properties") or ()),
                }
                content = content + "\n\nBackend structural result:\n" + json.dumps(
                    structural_projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
        fidelity = _record_fidelity(record)
        if fidelity == "semantic_card":
            eligible, _failure = card_eligibility(metadata)
            if not eligible:
                verification_issues.append(f"fidelity:{ref}:ineligible_card")
                continue
        required_fidelity = str((queue_item or {}).get("required_fidelity") or fidelity)
        effective_fidelity = str((queue_item or {}).get("effective_fidelity") or required_fidelity)
        if _FIDELITY_RANK.get(fidelity, 2) < _FIDELITY_RANK.get(effective_fidelity, 2):
            verification_issues.append(
                f"fidelity:{ref}:required_{effective_fidelity}:got_{fidelity}"
            )
            continue
        expected_revision = int((queue_item or {}).get("expected_revision") or 0)
        actual_revision = int(metadata.get("source_revision") or 0)
        hydrated_from = str(metadata.get("hydrated_from") or "")
        if expected_revision and actual_revision != expected_revision:
            verification_issues.append(f"revision:{ref}:mismatch")
            continue
        if hydrated_from == "semantic_card":
            if not bool(metadata.get("hydrated")):
                verification_issues.append(f"lineage:{ref}:unverified_hydration")
                continue
        if boundary_enabled and fidelity != "semantic_card" and record.kind != "catalog":
            if not bool(metadata.get("owner_verified")) or not bool(metadata.get("status_verified")):
                verification_issues.append(f"provenance:{ref}:unverified_scope_or_status")
                continue
            if str(metadata.get("status") or "active").lower() in {
                "deleted",
                "hidden",
                "inaccessible",
            }:
                verification_issues.append(f"provenance:{ref}:source_not_visible")
                continue
        provenance = (
            {
                "source_ref": str(metadata.get("ref") or record.source_ref or path),
                "source_revision": int(metadata.get("source_revision") or 0),
                "summary_version": int(metadata.get("summary_version") or 0),
                "summary_model": str(metadata.get("summary_model") or ""),
                # A card can enter a boundary-enabled pack only through the
                # tenant-scoped immutable candidate registry and a matching
                # materialization queue item. Card eligibility also rejects a
                # stale revision or non-visible status.
                "owner_verified": bool(boundary_enabled and queue_item is not None),
                "status_verified": str(metadata.get("status") or "active").lower()
                not in {"deleted", "hidden", "inaccessible"},
                "status": str(metadata.get("status") or "active"),
            }
            if fidelity == "semantic_card"
            else {
                "source_ref": str(record.source_ref or path),
                "producer": str(record.producer or ""),
                "hydrated_from": hydrated_from or None,
                "hydration_verified": bool(metadata.get("hydrated")),
                "owner_verified": bool(metadata.get("owner_verified")),
                "status_verified": bool(metadata.get("status_verified")),
                "status": str(metadata.get("status") or ""),
                "read_scope": str(metadata.get("read_scope") or ""),
                **(
                    {"source_revision": int(metadata.get("source_revision") or 0)}
                    if metadata.get("source_revision") is not None
                    else {}
                ),
                **(
                    {"selection": dict((queue_item or {}).get("provenance") or {})}
                    if queue_item
                    else {}
                ),
                **(
                    {"parent": dict((queue_item or {}).get("parent") or {})}
                    if isinstance((queue_item or {}).get("parent"), Mapping)
                    else {}
                ),
            }
        )
        manifest_metadata = {
            key: metadata[key]
            for key in ("card_text", "preview", "members")
            if key in metadata
        }
        items.append(
            EvidencePackItem(
                id=eid,
                kind=str(record.kind),
                title=str(record.citation_title or path),
                citation_path=path,
                content=content,
                source_ref=str(record.source_ref or path),
                object_kind=str(annotation.get("object_kind") or "unknown"),
                evidence_role=str(annotation.get("evidence_role") or "supporting"),
                source_requirement_id=source_id,
                fidelity=fidelity,
                provenance=provenance,
                metadata=manifest_metadata or None,
                allowed_claim_scope="topic_only" if fidelity == "semantic_card" else "content",
            )
        )
    original_items = list(items)
    if max_objects is not None and len(items) > max(0, int(max_objects)):
        items = items[: max(0, int(max_objects))]
    card_budget = max(0, min(max_card_chars, max_chars))
    full_budget = max(0, max_chars - min(card_budget, sum(
        len(item.content) for item in items if item.fidelity == "semantic_card"
    )))

    def allocate(group: list[EvidencePackItem], budget: int) -> list[EvidencePackItem]:
        if not group or budget <= 0:
            return []
        allocations: list[int] = []
        used = 0
        for item in group:
            size = min(len(item.content), _ITEM_FLOOR_CHARS, max(0, budget - used))
            allocations.append(size)
            used += size
        remaining = max(0, budget - used)
        for index, item in enumerate(group):
            grant = min(max(0, len(item.content) - allocations[index]), remaining)
            allocations[index] += grant
            remaining -= grant
        return [
            EvidencePackItem(
                **{
                    **asdict(item),
                    "content": item.content if size >= len(item.content) else item.content[: max(0, size - 3)] + "...",
                    "truncated": size < len(item.content),
                }
            )
            for item, size in zip(group, allocations)
            if size > 0
        ]

    cards = allocate([item for item in items if item.fidelity == "semantic_card"], card_budget)
    full = allocate([item for item in items if item.fidelity != "semantic_card"], full_budget)
    by_id = {item.id: item for item in (*cards, *full)}
    items = [by_id[item.id] for item in original_items if item.id in by_id]
    card_chars = sum(len(item.content) for item in items if item.fidelity == "semantic_card")
    full_chars = sum(len(item.content) for item in items if item.fidelity != "semantic_card")
    truncated_ids = [item.id for item in items if item.truncated]
    omitted_ids = [item.id for item in original_items if item.id not in by_id]
    queue_refs_packed = {
        canonical_candidate_ref(str(item.source_ref or item.id)) for item in items
    }
    truncated_refs = {
        canonical_candidate_ref(str(item.source_ref or item.id))
        for item in items
        if item.truncated
    }
    planned_refs = set(queue_by_ref)
    planned_omissions = sorted(planned_refs - queue_refs_packed) if boundary_enabled else []
    unresolved_items = list(str(item) for item in unresolved if str(item).strip())
    unresolved_items.extend(verification_issues)
    unresolved_items.extend(f"pack_omission:{ref}" for ref in planned_omissions)
    source_coverage = {key: dict(value) for key, value in (coverage_by_source or {}).items()}
    if boundary_enabled:
        for source_id in set(source_coverage) | {
            str(item.get("source_requirement_id") or "")
            for item in queue_by_ref.values()
            if item.get("source_requirement_id")
        }:
            planned = {
                ref
                for ref, item in queue_by_ref.items()
                if source_id in (item.get("source_requirement_ids") or [item.get("source_requirement_id")])
            }
            packed_refs = planned & queue_refs_packed
            source_truncated = planned & truncated_refs
            source_coverage[source_id] = {
                **source_coverage.get(source_id, {}),
                "planned_count": len(planned),
                "packed_count": len(packed_refs),
                "omitted_refs": sorted(planned - packed_refs),
                "truncated_refs": sorted(source_truncated),
                "coverage": (
                    "complete"
                    if planned == packed_refs and not source_truncated
                    else "partial"
                ),
            }
    effective_schema = schema or (
        EVIDENCE_PACK_SCHEMA_V2 if any(item.fidelity == "semantic_card" for item in items) else EVIDENCE_PACK_SCHEMA
    )
    return VerifiedEvidencePack(
        schema=effective_schema,
        evidence_ids=tuple(item.id for item in items),
        items=tuple(items),
        unresolved=tuple(dict.fromkeys(unresolved_items)),
        source_ids=tuple(str(item) for item in source_ids if str(item).strip()),
        coverage=(
            "partial"
            if omitted_ids
            or truncated_ids
            or planned_omissions
            or verification_issues
            or coverage == "partial"
            else "complete"
        ),
        coverage_by_source=source_coverage,
        context_chars={"card": card_chars, "full_text": full_chars, "total": card_chars + full_chars},
        truncation={
            "truncated_ids": truncated_ids,
            "omitted_ids": omitted_ids,
            "planned_omissions": planned_omissions,
        },
    )
