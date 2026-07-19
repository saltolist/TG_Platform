"""Evidence pack builder for answer model handoff."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.note_citations import NoteCite
from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.trust import wrap_untrusted_block
from app.services.agent.research.evidence_pack import build_verified_evidence_pack
from app.services.agent.research.material_plan import card_eligibility


# Guaranteed minimum footprint per evidence item, in characters. Without a
# floor, greedily filling the budget in evidence_ids order lets a handful of
# long notes early in the list consume the whole max_chars and hard-drop every
# item behind them — even a 263-char fact ("заметка X: files=2, два PNG") that
# would trivially fit. That silent drop is what made the answer model say "0"
# images while research had already verified one image-bearing note (chat
# 63dfb9e4). A floor guarantees every opened object gets *some* representation
# regardless of how large its neighbours are.
_FLOOR_CHARS = 400


def build_evidence_pack(
    *,
    records: dict[str, EvidenceRecord],
    evidence_ids: list[str],
    unresolved: list[str] | None = None,
    max_chars: int = 12000,
) -> tuple[str, list[NoteCite]]:
    seen_paths: set[str] = set()
    ordered: list[tuple[str, str, str]] = []
    for eid in evidence_ids:
        rec = records.get(eid)
        if rec is None:
            continue
        if rec.kind == "semantic_card":
            eligible, _failure = card_eligibility(rec.metadata)
            if not eligible:
                continue
        path = rec.citation_path
        if path in seen_paths:
            continue
        text = rec.content.strip()
        if not text:
            continue
        seen_paths.add(path)
        ordered.append((path, rec.citation_title or path, text))

    blocks: list[str] = []
    cites: list[NoteCite] = []

    if ordered:
        # Pass 1: reserve up to _FLOOR_CHARS per item, in order, never letting
        # the running total exceed max_chars.
        allocated: list[int] = []
        used = 0
        for _, _, text in ordered:
            room = max_chars - used
            floor = min(len(text), _FLOOR_CHARS, max(room, 0))
            allocated.append(floor)
            used += floor

        # Pass 2: spend whatever budget remains extending earlier items toward
        # their full text, in the same order — long notes still get as much
        # room as is left over once every item's floor is covered.
        remaining = max_chars - used
        for i, (_, _, text) in enumerate(ordered):
            if remaining <= 0:
                break
            need = len(text) - allocated[i]
            if need <= 0:
                continue
            grant = min(need, remaining)
            allocated[i] += grant
            remaining -= grant

        for (path, title, text), size in zip(ordered, allocated):
            if size <= 0:
                continue
            cites.append(NoteCite(path=path, title=title))
            body = text if size >= len(text) else text[: size - 1] + "…"
            # Evidence body is user-controlled; fence it as untrusted before it
            # reaches the answer model (agent-runtime-sprints §6).
            blocks.append(wrap_untrusted_block(identifier=path, title=title, body=body))

    if unresolved:
        blocks.append("Отсутствующие данные: " + "; ".join(unresolved))

    return "\n\n---\n\n".join(blocks), cites


def build_verified_pack(
    *,
    records: dict[str, EvidenceRecord],
    evidence_ids: list[str],
    unresolved: list[str] | None = None,
    source_ids: list[str] | None = None,
    schema: str | None = None,
    coverage: str = "complete",
    coverage_by_source: dict | None = None,
    item_annotations: Mapping[str, Mapping[str, Any]] | None = None,
):
    """Public compatibility wrapper for the typed phase-6 pack."""

    return build_verified_evidence_pack(
        records=records,
        evidence_ids=evidence_ids,
        unresolved=unresolved or (),
        source_ids=source_ids or (),
        schema=schema,
        coverage=coverage,
        coverage_by_source=coverage_by_source or {},
        item_annotations=item_annotations,
    )
