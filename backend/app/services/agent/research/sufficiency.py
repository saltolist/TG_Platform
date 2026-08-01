"""Deterministic evidence sufficiency gate for Workspace Agent phase 5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.services.agent.runtime.turn_contract import (
    covered_source_ids,
    evidence_matches_source,
    missing_required_sources,
    source_discovery_required,
    source_evidence_required,
    source_required_fidelity,
    source_selection_cardinality,
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
    gaps: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "satisfied_requirements": list(self.satisfied_requirements),
            "open_requirements": list(self.open_requirements),
            "exhausted_requirements": list(self.exhausted_requirements),
            "allowed_next_intent_ids": list(self.allowed_next_intent_ids),
            "evidence_ids": list(self.evidence_ids),
            "decision_code": self.decision_code,
            "gaps": [dict(item) for item in self.gaps],
        }


def _gap(
    *,
    kind: str,
    source_id: str,
    required: str,
    evidence_present: str,
    allowed_actions: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema": "workspace.evidence-gap/v1",
        "kind": kind,
        "source_id": source_id,
        "required": required,
        "evidence_present": evidence_present,
        "allowed_actions": list(allowed_actions),
        "blocks_ready": True,
    }


def _catalog_snapshots(
    state: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    snapshots: list[dict[str, Any]] = []
    for raw in (state.get("catalog_snapshots") or {}).values():
        if isinstance(raw, Mapping):
            snapshots.append(dict(raw))
    for record in records.values():
        metadata = record.get("metadata") or {}
        raw = metadata.get("catalog_snapshot") if isinstance(metadata, Mapping) else None
        if isinstance(raw, Mapping):
            snapshots.append(dict(raw))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in snapshots:
        key = (
            str(snapshot.get("source_requirement_id") or ""),
            str(snapshot.get("kind") or ""),
        )
        unique[key] = snapshot
    return tuple(unique.values())


def _snapshot_for_source(
    source: Mapping[str, Any], snapshots: tuple[dict[str, Any], ...]
) -> dict[str, Any] | None:
    source_id = str(source.get("source_id") or "")
    kind = str(source.get("kind") or "")
    return next(
        (
            snapshot
            for snapshot in snapshots
            if str(snapshot.get("source_requirement_id") or "") == source_id
        ),
        next(
            (snapshot for snapshot in snapshots if str(snapshot.get("kind") or "") == kind),
            None,
        ),
    )


_AGGREGATE_REQUIREMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("notes", "total_notes"): ("total_notes",),
    ("notes", "has_images"): ("notes_with_images",),
    ("notes", "image_count"): ("image_files_total",),
    ("notes", "has_files"): ("notes_with_files",),
    ("posts", "total_posts"): ("total_posts",),
    ("posts", "has_any_images"): ("posts_with_any_images",),
    ("posts", "image_count"): ("direct_image_count", "note_image_files_total"),
    ("posts", "has_files"): ("direct_media_count", "note_files_total"),
}


def _typed_contract_gaps(
    *,
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    evidence_ids: tuple[str, ...],
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    snapshots = _catalog_snapshots(state, records)
    gaps: list[dict[str, Any]] = []
    satisfied: list[str] = []
    material_plan = state.get("material_plan") or {}
    baseline_discharged_sources = {
        str(item)
        for item in material_plan.get("baseline_discharged_source_ids") or ()
        if str(item)
    }
    assessment_refs = {
        str(item.get("ref") or "")
        for item in material_plan.get("assessments") or ()
        if isinstance(item, Mapping) and str(item.get("ref") or "")
    }
    coverage_targets = state.get("coverage_targets_by_source") or {}

    for raw_source in contract.get("source_requirements") or ():
        if not isinstance(raw_source, Mapping):
            continue
        source = dict(raw_source)
        source_id = str(source.get("source_id") or "")
        evidence_discharged = source_id in baseline_discharged_sources
        snapshot = _snapshot_for_source(source, snapshots)
        matches = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_matches_source(source, evidence_id=evidence_id, record=records[evidence_id])
        ]
        discovery_source = {
            key: value for key, value in source.items() if key != "required_fidelity"
        }
        discovery_source["evidence_granularity"] = "semantic_card"
        discovery_matches = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_matches_source(
                discovery_source,
                evidence_id=evidence_id,
                record=records[evidence_id],
            )
        ]
        selected_matches = [
            evidence_id
            for evidence_id in matches
            if str(records[evidence_id].get("kind") or "") != "catalog"
        ]
        if source_discovery_required(source) and snapshot is None and not discovery_matches:
            gaps.append(
                _gap(
                    kind="missing_discovery",
                    source_id=source_id,
                    required=f"{source_id}:discovery",
                    evidence_present="no_catalog_or_source_evidence",
                    allowed_actions=("structural_aggregate", "search_source"),
                )
            )
        if source_evidence_required(source) and not evidence_discharged and discovery_matches and not matches:
            gaps.append(
                _gap(
                    kind="fidelity_mismatch",
                    source_id=source_id,
                    required=f"{source_id}:{source_required_fidelity(source)}",
                    evidence_present="source_evidence_below_required_fidelity",
                    allowed_actions=("open_source",),
                )
            )
        if source.get("coverage") == "complete":
            predicate = str(source.get("predicate_kind") or "semantic")
            if predicate in {"semantic", "mixed"}:
                if source_id not in coverage_targets:
                    gaps.append(
                        _gap(
                            kind="incomplete_discovery",
                            source_id=source_id,
                            required=f"{source_id}:complete_catalog",
                            evidence_present="catalog_targets_unknown",
                            allowed_actions=("structural_aggregate", "search_source"),
                        )
                    )
                else:
                    missing_assessments = [
                        str(ref)
                        for ref in coverage_targets.get(source_id) or ()
                        if str(ref) not in assessment_refs
                    ]
                    if missing_assessments:
                        gaps.append(
                            _gap(
                                kind="incomplete_assessment",
                                source_id=source_id,
                                required=f"{source_id}:assessment_coverage",
                                evidence_present=f"{len(missing_assessments)}_refs_unassessed",
                                allowed_actions=("assess_candidates",),
                            )
                        )
            elif (
                snapshot is not None
                and not bool(snapshot.get("members_complete"))
                and not bool(snapshot.get("result_sets_complete"))
            ):
                gaps.append(
                    _gap(
                        kind="incomplete_discovery",
                        source_id=source_id,
                        required=f"{source_id}:complete_catalog",
                        evidence_present="catalog_page_partial",
                        allowed_actions=("structural_aggregate",),
                    )
                )

        minimum, maximum = source_selection_cardinality(source)
        if len(selected_matches) > maximum:
            gaps.append(
                _gap(
                    kind="cardinality_exceeded",
                    source_id=source_id,
                    required=f"selection_max:{maximum}",
                    evidence_present=f"selection_count:{len(selected_matches)}",
                    allowed_actions=("assess_candidates",),
                )
            )
        if source_evidence_required(source) and not evidence_discharged and len(selected_matches) < minimum:
            gaps.append(
                _gap(
                    kind="missing_selection",
                    source_id=source_id,
                    required=f"selection_min:{minimum}",
                    evidence_present=f"selection_count:{len(selected_matches)}",
                    allowed_actions=("search_source", "open_source"),
                )
            )

        for requirement in source.get("evidence_requirements") or ():
            if not isinstance(requirement, Mapping):
                continue
            requirement_id = str(requirement.get("requirement_id") or "")
            property_name = str(requirement.get("property") or "")
            subject = str(requirement.get("subject") or source.get("kind") or "")
            if property_name == "grounded_evidence":
                requirement_met = bool(matches)
                present = "matching_evidence" if matches else "no_matching_evidence"
            else:
                qualified = f"{subject}.{property_name}"
                provided = set(str(item) for item in (snapshot or {}).get("provided_properties") or ())
                aggregates = (snapshot or {}).get("aggregates") or {}
                aggregate_keys = _AGGREGATE_REQUIREMENTS.get((subject, property_name), ())
                property_provided = property_name.startswith("total_") or qualified in provided
                requirement_met = bool(
                    snapshot is not None
                    and property_provided
                    and aggregate_keys
                    and all(aggregates.get(key) is not None for key in aggregate_keys)
                )
                present = (
                    "catalog_without_property"
                    if snapshot is not None and not property_provided
                    else "catalog_without_aggregate"
                    if snapshot is not None
                    else "no_catalog"
                )
            if source_evidence_required(source) and not evidence_discharged and not requirement_met:
                gaps.append(
                    _gap(
                        kind="missing_property" if property_name != "grounded_evidence" else "missing_evidence",
                        source_id=source_id,
                        required=(
                            f"{subject}.{property_name}"
                            if property_name != "grounded_evidence"
                            else requirement_id
                        ),
                        evidence_present=present,
                        allowed_actions=("structural_aggregate", f"open_{subject}"),
                    )
                )
        if not any(item["source_id"] == source_id for item in gaps):
            satisfied.append(source_id)
    deduplicated = tuple(
        dict(item)
        for item in {
            (item["kind"], item["source_id"], item["required"]): item for item in gaps
        }.values()
    )
    return deduplicated, tuple(satisfied)


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
        if source_evidence_required(source)
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

    if int(contract.get("version") or 0) >= 3:
        gaps, satisfied = _typed_contract_gaps(
            state=state,
            contract=contract,
            records=records,
            evidence_ids=evidence_ids,
        )
        typed_gaps = list(gaps)
        typed_gaps.extend(
            dict(item)
            for item in state.get("evidence_gaps") or ()
            if isinstance(item, Mapping) and str(item.get("kind") or "").startswith("selector_")
        )
        for missing_ref in material_missing:
            typed_gaps.append(
                _gap(
                    kind="fidelity_mismatch",
                    source_id="material_plan",
                    required=missing_ref,
                    evidence_present="required_fidelity_not_materialized",
                    allowed_actions=("open_source",),
                )
            )
        remaining_intents = _remaining_intents(list(state.get("search_ledger") or ()), contract)
        required_omitted = {
            ref for ref in required_full if ref in omitted and ref not in opened_full
        }
        if required_omitted:
            for ref in sorted(required_omitted):
                typed_gaps.append(
                    _gap(
                        kind="fidelity_mismatch",
                        source_id="material_plan",
                        required=f"material:{ref}",
                        evidence_present="materialization_omitted",
                        allowed_actions=("open_source",),
                    )
                )
        unique_gaps = tuple(
            dict(item)
            for item in {
                (item["kind"], item["source_id"], item["required"]): item
                for item in typed_gaps
            }.values()
        )
        open_requirements = tuple(str(item["required"]) for item in unique_gaps)
        unresolved = tuple(dict.fromkeys((*open_requirements, *remaining_intents)))
        hard_budget = _budget_exhausted(state, contract) or bool(state.get("deadline_exhausted"))
        if unique_gaps and (requested_status == "partial" or hard_budget or required_omitted):
            return SufficiencyResult(
                "exhausted",
                satisfied,
                unresolved,
                unresolved,
                (),
                evidence_ids,
                (
                    "MATERIAL_COVERAGE_PARTIAL"
                    if required_omitted
                    else "PARTIAL_REQUESTED"
                    if requested_status == "partial"
                    else "BUDGET_EXHAUSTED"
                ),
                unique_gaps,
            )
        if not unique_gaps and not remaining_intents and requested_status != "partial":
            return SufficiencyResult(
                "ready",
                satisfied,
                (),
                (),
                (),
                evidence_ids,
                "ALL_TYPED_REQUIREMENTS_SATISFIED",
                (),
            )
        if requested_status == "partial":
            return SufficiencyResult(
                "exhausted" if unresolved else "ready",
                satisfied,
                unresolved,
                unresolved,
                (),
                evidence_ids,
                "PARTIAL_REQUESTED",
                unique_gaps,
            )
        return SufficiencyResult(
            "follow_up_allowed",
            satisfied,
            open_requirements,
            (),
            unresolved,
            evidence_ids,
            "TYPED_EVIDENCE_GAP" if unique_gaps else "EVIDENCE_GAP",
            unique_gaps,
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

    # A required complete source is a coverage contract, not merely a source
    # presence check. Once the catalog is known, every member must be resolved
    # at the requested fidelity before the run can finish. This is independent
    # of how many candidates semantic retrieval happened to return.
    material_resolved = {
        str(item)
        for item in [
            *list(material_plan.get("card_ids") or ()),
            *list(material_plan.get("opened_full_text_ids") or ()),
        ]
    }
    for source in contract.get("source_requirements") or ():
        if not isinstance(source, Mapping) or not source_evidence_required(source):
            continue
        if source.get("coverage") != "complete":
            continue
        source_id = str(source.get("source_id") or "")
        coverage_targets = state.get("coverage_targets_by_source") or {}
        if source_id not in coverage_targets:
            missing = tuple(dict.fromkeys((*missing, f"coverage:{source_id}:catalog")))
            continue
        targets = tuple(
            str(item)
            for item in coverage_targets.get(source_id) or ()
            if str(item)
        )
        granularity = source_required_fidelity(source)
        if granularity in {"semantic_card", "full_text"}:
            unresolved_targets = [ref for ref in targets if ref not in material_resolved]
            if unresolved_targets:
                missing = tuple(
                    dict.fromkeys(
                        (*missing, *(f"coverage:{source_id}:{ref}" for ref in unresolved_targets))
                    )
                )

    open_requirements = tuple(missing)
    remaining_intents = _remaining_intents(list(state.get("search_ledger") or ()), contract)
    hard_budget = _budget_exhausted(state, contract)
    deadline_exhausted = bool(state.get("deadline_exhausted"))
    source_requirements = tuple(contract.get("source_requirements") or ())
    optional_discovery_complete = bool(source_requirements) and not any(
        source_evidence_required(source)
        for source in source_requirements
        if isinstance(source, Mapping)
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
