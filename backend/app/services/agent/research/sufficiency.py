"""Deterministic evidence sufficiency gate for Workspace Agent phase 5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.services.agent.runtime.turn_contract import (
    covered_source_ids,
    missing_required_sources,
)
from app.services.agent.research.material_plan import canonical_candidate_ref

SufficiencyStatus = Literal["ready", "follow_up_allowed", "exhausted", "invalid"]


@dataclass(frozen=True)
class SufficiencyResult:
    status: SufficiencyStatus
    satisfied_requirements: tuple[str, ...]
    open_requirements: tuple[str, ...]
    exhausted_requirements: tuple[str, ...]
    allowed_next_intent_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    decision_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "satisfied_requirements": list(self.satisfied_requirements),
            "open_requirements": list(self.open_requirements),
            "exhausted_requirements": list(self.exhausted_requirements),
            "allowed_next_intent_ids": list(self.allowed_next_intent_ids),
            "evidence_ids": list(self.evidence_ids),
            "decision_code": self.decision_code,
        }


def _budget_exhausted(state: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    budgets = contract.get("budgets") or {}
    checks = (
        ("planner_calls_used", "planner_calls"),
        ("search_calls_used", "search_calls"),
        ("deep_reads_used", "deep_reads"),
        ("tool_calls_used", "tool_calls"),
    )
    return any(
        int(state.get(used) or 0) >= int(budgets.get(limit) or 0)
        for used, limit in checks
        if limit in budgets
    )


def _remaining_intents(
    ledger: list[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[str, ...]:
    required_sources = {
        str(source.get("source_id") or "")
        for source in contract.get("source_requirements") or ()
        if source.get("required")
    }
    remaining: list[str] = []
    for entry in ledger:
        if str(entry.get("state") or "") not in {"planned", "running"}:
            continue
        source_id = str(entry.get("source_requirement_id") or "")
        if not required_sources or source_id in required_sources:
            remaining.append(str(entry.get("intent_key") or source_id))
    return tuple(dict.fromkeys(item for item in remaining if item))


def evaluate_sufficiency(
    *,
    state: Mapping[str, Any],
    contract: Mapping[str, Any] | None = None,
    requested_status: str | None = None,
) -> SufficiencyResult:
    """Evaluate evidence after every seed/tool result without an LLM call."""

    contract = dict(contract or state.get("turn_contract") or {})
    raw_records = state.get("evidence_records") or {}
    if any(not isinstance(value, Mapping) for value in raw_records.values()):
        return SufficiencyResult(
            "invalid",
            (),
            ("malformed_evidence_record",),
            (),
            (),
            (),
            "INVALID_EVIDENCE_RECORD",
        )
    records = {str(key): dict(value) for key, value in raw_records.items() if isinstance(value, Mapping)}
    evidence_ids = tuple(
        str(key)
        for key, record in records.items()
        if str(record.get("content") or "").strip()
        and str(record.get("kind") or "") not in {"note_summary", "post_summary"}
    )
    material_plan = dict(state.get("material_plan") or {})
    required_full = tuple(
        str(item) for item in material_plan.get("required_full_text_ids") or () if str(item)
    )
    opened_full = set(
        str(item) for item in material_plan.get("opened_full_text_ids") or () if str(item)
    )
    omitted = set(str(item) for item in material_plan.get("omitted_ids") or () if str(item))
    card_ids = tuple(str(item) for item in material_plan.get("card_ids") or () if str(item))
    available_refs = {
        canonical_candidate_ref(str(record.get("source_ref") or key))
        for key, record in records.items()
        if key in evidence_ids
    }
    material_missing = [
        f"material:{ref}"
        for ref in required_full
        if ref not in opened_full or ref not in available_refs
    ]
    material_missing.extend(
        f"material:{ref}" for ref in card_ids if ref not in available_refs
    )

    if contract.get("source_requirements"):
        covered = covered_source_ids(contract, {key: records[key] for key in evidence_ids})
        missing = missing_required_sources(contract, covered)
        satisfied = tuple(
            str(source.get("source_id") or "")
            for source in contract.get("source_requirements") or ()
            if str(source.get("source_id") or "") in covered
        )
    else:
        missing = () if evidence_ids else ("evidence",)
        satisfied = ("evidence",) if evidence_ids else ()

    selected_candidates = (
        ()
        if state.get("adaptive_evidence_depth_enabled")
        else tuple(
            str(item) for item in state.get("selected_candidate_ids") or () if str(item)
        )
    )
    unread_candidates = tuple(
        candidate_id
        for candidate_id in selected_candidates
        if not any(f"/{candidate_id}/" in evidence_id for evidence_id in evidence_ids)
    )
    if unread_candidates:
        missing = tuple(
            dict.fromkeys((*missing, *(f"candidate:{item}" for item in unread_candidates)))
        )
    if material_missing:
        missing = tuple(dict.fromkeys((*missing, *material_missing)))

    open_requirements = tuple(missing)
    remaining_intents = _remaining_intents(list(state.get("search_ledger") or ()), contract)
    hard_budget = _budget_exhausted(state, contract)
    deadline_exhausted = bool(state.get("deadline_exhausted"))
    source_requirements = tuple(contract.get("source_requirements") or ())
    optional_discovery_complete = bool(source_requirements) and not any(
        bool(source.get("required")) for source in source_requirements
    ) and not bool(state.get("prefetch_hits"))
    required_omitted = {
        ref for ref in required_full if ref in omitted and ref not in opened_full
    }
    if required_omitted:
        unresolved = tuple(
            dict.fromkeys((*missing, *(f"material:{ref}" for ref in sorted(required_omitted))))
        )
        return SufficiencyResult(
            "exhausted",
            satisfied,
            unresolved,
            unresolved,
            (),
            evidence_ids,
            "MATERIAL_COVERAGE_PARTIAL",
        )
    if material_plan.get("coverage") == "partial" and any(
        str(item).endswith(":unseen_candidates")
        for item in material_plan.get("omitted_ids") or ()
    ):
        unresolved = tuple(
            dict.fromkeys(
                (*missing, *[str(item) for item in material_plan.get("omitted_ids") or ()])
            )
        )
        return SufficiencyResult(
            "exhausted",
            satisfied,
            unresolved,
            unresolved,
            (),
            evidence_ids,
            "DISCOVERY_COVERAGE_PARTIAL",
        )
    if requested_status == "ready" and evidence_ids and not missing:
        return SufficiencyResult(
            "ready", satisfied, (), (), (), evidence_ids, "ALL_REQUIRED_EVIDENCE_PRESENT"
        )
    if evidence_ids and not missing and not remaining_intents and requested_status != "partial":
        return SufficiencyResult(
            "ready", satisfied, (), (), (), evidence_ids, "ALL_REQUIRED_EVIDENCE_PRESENT"
        )
    if (
        optional_discovery_complete
        and not missing
        and not remaining_intents
        and requested_status != "partial"
    ):
        return SufficiencyResult(
            "ready", satisfied, (), (), (), (), "OPTIONAL_DISCOVERY_COMPLETE"
        )
    if requested_status == "partial":
        unresolved = tuple(dict.fromkeys((*missing, *remaining_intents)))
        return SufficiencyResult(
            "exhausted" if unresolved or not evidence_ids else "ready",
            satisfied,
            unresolved,
            unresolved,
            (),
            evidence_ids,
            "PARTIAL_REQUESTED",
        )
    if hard_budget or deadline_exhausted:
        unresolved = tuple(dict.fromkeys((*missing, *remaining_intents)))
        return SufficiencyResult(
            "exhausted" if unresolved else "ready",
            satisfied,
            unresolved,
            unresolved,
            (),
            evidence_ids,
            "BUDGET_EXHAUSTED",
        )
    allowed = tuple(dict.fromkeys((*missing, *remaining_intents)))
    return SufficiencyResult(
        "follow_up_allowed",
        satisfied,
        open_requirements,
        (),
        allowed,
        evidence_ids,
        "REQUIRED_EVIDENCE_MISSING" if missing else "EVIDENCE_GAP",
    )


__all__ = ["SufficiencyResult", "evaluate_sufficiency"]
