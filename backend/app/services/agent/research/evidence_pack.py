"""Verified, minimal evidence handoff for the answer model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.material_plan import card_eligibility


EVIDENCE_PACK_SCHEMA = "workspace.evidence-pack/v1"
EVIDENCE_PACK_SCHEMA_V2 = "workspace.evidence-pack/v2"
_DISCOVERY_KINDS = {"search_hit", "note_summary", "post_summary", "summary"}
_ITEM_FLOOR_CHARS = 400


@dataclass(frozen=True)
class EvidencePackItem:
    id: str
    kind: str
    title: str
    citation_path: str
    content: str
    source_ref: str
    fidelity: str = "full_text"
    provenance: dict[str, Any] | None = None
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
) -> VerifiedEvidencePack:
    """Build only from selected, non-empty primary records.

    Discovery summaries are intentionally excluded even if a caller accidentally
    includes their ids. Missing ids are omitted, never fabricated into the pack.
    """

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
        fidelity = "semantic_card" if record.kind == "semantic_card" else "full_text"
        metadata = dict(record.metadata or {})
        if fidelity == "semantic_card":
            eligible, _failure = card_eligibility(metadata)
            if not eligible:
                continue
        provenance = (
            {
                "source_ref": str(metadata.get("ref") or record.source_ref or path),
                "source_revision": int(metadata.get("source_revision") or 0),
                "summary_version": int(metadata.get("summary_version") or 0),
                "summary_model": str(metadata.get("summary_model") or ""),
            }
            if fidelity == "semantic_card"
            else {
                "source_ref": str(record.source_ref or path),
                **(
                    {"source_revision": int(metadata.get("source_revision") or 0)}
                    if metadata.get("source_revision") is not None
                    else {}
                ),
            }
        )
        items.append(
            EvidencePackItem(
                id=eid,
                kind=str(record.kind),
                title=str(record.citation_title or path),
                citation_path=path,
                content=content,
                source_ref=str(record.source_ref or path),
                fidelity=fidelity,
                provenance=provenance,
                allowed_claim_scope="topic_only" if fidelity == "semantic_card" else "content",
            )
        )
    original_items = list(items)
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
    full = allocate([item for item in items if item.fidelity == "full_text"], full_budget)
    by_id = {item.id: item for item in (*cards, *full)}
    items = [by_id[item.id] for item in original_items if item.id in by_id]
    card_chars = sum(len(item.content) for item in items if item.fidelity == "semantic_card")
    full_chars = sum(len(item.content) for item in items if item.fidelity == "full_text")
    truncated_ids = [item.id for item in items if item.truncated]
    omitted_ids = [item.id for item in original_items if item.id not in by_id]
    effective_schema = schema or (
        EVIDENCE_PACK_SCHEMA_V2 if any(item.fidelity == "semantic_card" for item in items) else EVIDENCE_PACK_SCHEMA
    )
    return VerifiedEvidencePack(
        schema=effective_schema,
        evidence_ids=tuple(item.id for item in items),
        items=tuple(items),
        unresolved=tuple(str(item) for item in unresolved if str(item).strip()),
        source_ids=tuple(str(item) for item in source_ids if str(item).strip()),
        coverage="partial" if omitted_ids or coverage == "partial" else "complete",
        coverage_by_source=dict(coverage_by_source or {}),
        context_chars={"card": card_chars, "full_text": full_chars, "total": card_chars + full_chars},
        truncation={"truncated_ids": truncated_ids, "omitted_ids": omitted_ids},
    )
