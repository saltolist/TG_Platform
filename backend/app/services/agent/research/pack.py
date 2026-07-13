"""Evidence pack builder for answer model handoff."""

from __future__ import annotations

from app.services.ai.note_citations import NoteCite
from app.services.agent.research.evidence import EvidenceRecord


def build_evidence_pack(
    *,
    records: dict[str, EvidenceRecord],
    evidence_ids: list[str],
    unresolved: list[str] | None = None,
    max_chars: int = 12000,
) -> tuple[str, list[NoteCite]]:
    cites: list[NoteCite] = []
    blocks: list[str] = []
    used = 0
    seen_paths: set[str] = set()

    for eid in evidence_ids:
        rec = records.get(eid)
        if rec is None:
            continue
        path = rec.citation_path
        if path in seen_paths:
            continue
        seen_paths.add(path)
        text = rec.content.strip()
        if not text:
            continue
        if used + len(text) > max_chars:
            remaining = max_chars - used
            if remaining <= 80:
                break
            text = text[: remaining - 1] + "…"
        cites.append(NoteCite(path=path, title=rec.citation_title or path))
        blocks.append(f"[{rec.citation_title or path}]\n{text}")
        used += len(text)

    if unresolved:
        blocks.append("Отсутствующие данные: " + "; ".join(unresolved))

    return "\n\n---\n\n".join(blocks), cites
