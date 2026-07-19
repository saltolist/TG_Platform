"""Evidence records for research subgraph."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EvidenceKind = Literal[
    "post_text",
    "note_chunk",
    "attachment_text",
    "media_meta",
    "vision",
    "analytics",
    "comment",
    "catalog",
    "search_hit",
]


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    kind: EvidenceKind
    source_ref: str
    content: str
    citation_path: str
    citation_title: str
    metadata: dict[str, Any] = field(default_factory=dict)
    producer: str = "read_tool"

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvidenceRecord:
        return cls(
            id=str(raw.get("id") or cls.new_id()),
            kind=raw.get("kind", "search_hit"),  # type: ignore[arg-type]
            source_ref=str(raw.get("source_ref") or ""),
            content=str(raw.get("content") or ""),
            citation_path=str(raw.get("citation_path") or ""),
            citation_title=str(raw.get("citation_title") or ""),
            metadata=dict(raw.get("metadata") or {}),
            producer=str(raw.get("producer") or "read_tool"),
        )


def records_from_agent_state(agent_state) -> dict[str, EvidenceRecord]:
    """Build evidence map from legacy AgentState context blocks.

    Records are keyed by their natural, stable citation path (``/post/3/``,
    ``/note/global/n1/``) — the same identifier the planner sees in the pack,
    cites in FinishRetrieval, and the answer model renders. No hash indirection,
    so a planner-returned id can never dangle against the record map
    (agent-runtime-sprints §1.2). First occurrence of a path wins, matching the
    pack's dedup-by-path behaviour.
    """
    from app.services.ai.note_citations import NoteCite

    records: dict[str, EvidenceRecord] = {}
    for cite, plain in agent_state.context_blocks:
        if not isinstance(cite, NoteCite):
            continue
        path = str(cite.path or "")
        if not path or path in records:
            continue
        kind: EvidenceKind = "note_chunk"
        # Listing paths (§1.4 tail) must be classified before the "/post/" rule:
        # "/post/3/notes/" contains "/post/" but is an enumeration, not post body.
        if (
            path.startswith("/posts/")
            or path.endswith("/notes/")
            or path.endswith("/attachments/")
            or path.endswith("/media/")
        ):
            kind = "catalog"
        elif "/attachment/" in path:
            kind = "attachment_text"
        elif path.endswith("/post/") or "/post/" in path and "/note/" not in path:
            kind = "post_text"
        metadata: dict[str, Any] = {"visited": list(agent_state.visited)[-8:]}
        catalog_members = getattr(agent_state, "catalog_members", {})
        if kind == "catalog" and isinstance(catalog_members, dict):
            metadata["members"] = [
                dict(item)
                for item in catalog_members.get(path, ())
                if isinstance(item, dict)
            ]
        records[path] = EvidenceRecord(
            id=path,
            kind=kind,
            source_ref=path,
            content=str(plain or ""),
            citation_path=path,
            citation_title=str(cite.title or ""),
            metadata=metadata,
            producer="rag_tools",
        )
    return records
