"""Research graph result contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.ai.note_citations import NoteCite


@dataclass
class ResearchResult:
    rag_context: str = ""
    cites: list[NoteCite] = field(default_factory=list)
    stopped_reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    step_count: int = 0
