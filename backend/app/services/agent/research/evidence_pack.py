"""Verified, minimal evidence handoff for the answer model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.services.agent.research.evidence import EvidenceRecord


EVIDENCE_PACK_SCHEMA = "workspace.evidence-pack/v1"
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


@dataclass(frozen=True)
class VerifiedEvidencePack:
    schema: str
    evidence_ids: tuple[str, ...]
    items: tuple[EvidencePackItem, ...]
    unresolved: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

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
        }


def build_verified_evidence_pack(
    *,
    records: Mapping[str, EvidenceRecord],
    evidence_ids: list[str] | tuple[str, ...],
    unresolved: list[str] | tuple[str, ...] = (),
    source_ids: list[str] | tuple[str, ...] = (),
    max_chars: int = 12_000,
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
        items.append(
            EvidencePackItem(
                id=eid,
                kind=str(record.kind),
                title=str(record.citation_title or path),
                citation_path=path,
                content=content,
                source_ref=str(record.source_ref or path),
            )
        )
    if items:
        allocations: list[int] = []
        used = 0
        for item in items:
            size = min(len(item.content), _ITEM_FLOOR_CHARS, max(0, max_chars - used))
            allocations.append(size)
            used += size
        remaining = max(0, max_chars - used)
        for index, item in enumerate(items):
            grant = min(max(0, len(item.content) - allocations[index]), remaining)
            allocations[index] += grant
            remaining -= grant
        items = [
            EvidencePackItem(
                **{
                    **asdict(item),
                    "content": (
                        item.content
                        if allocations[index] >= len(item.content)
                        else item.content[: max(0, allocations[index] - 1)] + "..."
                    ),
                }
            )
            for index, item in enumerate(items)
            if allocations[index] > 0
        ]
    return VerifiedEvidencePack(
        schema=EVIDENCE_PACK_SCHEMA,
        evidence_ids=tuple(item.id for item in items),
        items=tuple(items),
        unresolved=tuple(str(item) for item in unresolved if str(item).strip()),
        source_ids=tuple(str(item) for item in source_ids if str(item).strip()),
    )
