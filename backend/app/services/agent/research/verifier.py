"""Deterministic evidence verification."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.agent.research.evidence import EvidenceRecord


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    missing_ids: tuple[str, ...]
    dangling_refs: tuple[str, ...]
    errors: tuple[str, ...]
    repair_allowed: bool


def verify_evidence(
    *,
    finish: dict | None,
    records: dict[str, EvidenceRecord],
    max_repair: int = 1,
    repair_count: int = 0,
) -> VerifyResult:
    if finish is None:
        return VerifyResult(
            ok=False,
            missing_ids=(),
            dangling_refs=(),
            errors=("finish_retrieval_missing",),
            repair_allowed=repair_count < max_repair,
        )

    status = str(finish.get("status") or "").strip()
    if status not in {"ready", "partial"}:
        return VerifyResult(
            ok=False,
            missing_ids=(),
            dangling_refs=(),
            errors=(f"invalid_finish_status:{status}",),
            repair_allowed=repair_count < max_repair,
        )

    requested = [str(item) for item in (finish.get("evidence_ids") or [])]
    missing = [eid for eid in requested if eid not in records]
    dangling = [eid for eid in requested if eid in records and not records[eid].content.strip()]

    errors: list[str] = []
    # An empty citation set is never a valid finish: the planner claimed it was
    # done but selected nothing to ground the answer on (agent-runtime-sprints §1.3).
    if not requested:
        errors.append("no_evidence_ids")
    if missing:
        errors.append("missing_evidence_ids")
    if dangling:
        errors.append("empty_evidence_content")

    ownership_errors = [
        eid
        for eid in (finish.get("evidence_ids") or [])
        if eid in records and not str(records[eid].citation_path or "").startswith("/")
    ]
    if ownership_errors:
        errors.append("invalid_citation_paths")

    # Both ready and partial must have at least one resolvable, non-empty cite.
    # partial only relaxes the "everything requested resolved" bar, not the
    # dangling/empty-content bar (agent-runtime-sprints §1.3).
    ok = bool(requested) and not dangling
    if status == "ready":
        ok = ok and not missing

    return VerifyResult(
        ok=ok,
        missing_ids=tuple(missing),
        dangling_refs=tuple(dangling),
        errors=tuple(errors),
        repair_allowed=repair_count < max_repair and bool(errors),
    )
