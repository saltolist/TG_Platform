"""Durable candidate assessment and evidence-resolution state."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, NotRequired, TypedDict

from app.services.ai.semantic_summary import (
    DISCOVERY_SUMMARY_VERSION,
    SELECTOR_SUMMARY_MAX_CHARS,
    SELECTOR_SUMMARY_VERSION,
)


MATERIAL_PLAN_SCHEMA = "workspace.material-plan/v1"
MATERIAL_PLAN_SCHEMA_V2 = "workspace.material-plan/v2"
MAX_PLANNER_CANDIDATES = 16
MAX_CANDIDATE_REGISTRY = 256
FULL_READ_BATCH_SIZE = 3
DEFAULT_MAX_PACK_OBJECTS = 8
DEFAULT_MAX_FULL_TEXT_CHARS = 12_000
DEFAULT_MAX_CARD_CHARS = 6_000
DEFAULT_FULL_TEXT_RESERVATION_CHARS = 4_000
MIN_FULL_TEXT_RESERVATION_CHARS = 400

_FIDELITY_RANK = {
    "metadata": 0,
    "catalog": 0,
    "semantic_card": 1,
    "card": 1,
    "text": 2,
    "full_text": 2,
    "analytics": 2,
    "vision": 3,
    "none": -1,
}

CANDIDATE_ENVELOPE_SCHEMA = "workspace.candidate-envelope/v1"
_ORIGIN_INCLUSION_PRIORITY = {
    "exact_target": 0,
    "ambient_current_post": 10,
    "dialog_reference": 20,
    "authoritative_catalog": 30,
    "catalog_member": 30,
    "semantic_search": 40,
}


class CandidateEnvelope(TypedDict):
    schema: str
    ref: str
    kind: str
    title: str
    card_text: str
    origin: str
    inclusion_priority: int
    semantic_score: float | None
    semantic_rank_score: NotRequired[float | None]
    search_enriched: NotRequired[bool]
    matched_evidence_rank: NotRequired[int | None]
    source_requirement_ids: list[str]
    source_requirement_id: str
    parent: dict[str, str] | None
    available_fidelity: list[str]
    card_eligible: bool
    card_eligibility_failure: str | None
    index_revision: int
    source_revision: int
    summary_version: int
    summary_model: str
    selector_summary: str
    selector_summary_version: int
    selector_semantic_flags: dict[str, Any]
    selector_summary_fresh: bool
    selector_summary_failure: str | None
    card_origin: str
    status: str
    parent_post_id: str | None
    parent_note_id: str | None
    post_id: str | None
    file_id: str | None
    node_type: str
    citation_path: str
    has_more: bool
    catalog_window_memberships: NotRequired[list[dict[str, Any]]]
    estimated_full_text_chars: NotRequired[int]
    file_count: NotRequired[int | None]
    image_count: NotRequired[int | None]
    has_files: NotRequired[bool | None]
    has_images: NotRequired[bool | None]
    direct_image_count: NotRequired[int | None]
    note_image_files_total: NotRequired[int | None]
    has_any_images: NotRequired[bool | None]
    score: NotRequired[float | None]


def canonical_candidate_ref(value: str) -> str:
    raw = str(value or "").strip().strip("/")
    for prefix in ("note", "post", "file", "attachment", "media", "analytics"):
        if raw.startswith(f"{prefix}:"):
            return f"{prefix}:{raw.split(':', 1)[1]}"
    parts = raw.split("/")
    if "attachment" in parts and parts:
        return f"attachment:{parts[-1]}"
    if "media" in parts and parts:
        return f"file:{parts[-1]}"
    if "note" in parts and parts:
        return f"note:{parts[-1]}"
    if "post" in parts and parts:
        return f"post:{parts[-1]}"
    return raw


def citation_path_for_ref(ref: str, *, scope: str = "global") -> str:
    kind, _, object_id = canonical_candidate_ref(ref).partition(":")
    if kind == "post" and object_id:
        return f"/post/{object_id}/"
    if kind == "note" and object_id:
        return f"/note/{scope or 'global'}/{object_id}/"
    if kind in {"file", "media", "attachment"} and object_id:
        return f"/{kind}/{object_id}/"
    return ""


def card_origin(summary_model: str) -> str:
    model = str(summary_model or "").strip().lower()
    return "llm" if model.startswith("llm:") else "extractive" if model else "missing"


def card_eligibility(candidate: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Validate a card without trusting the planner's eligibility assertion."""

    ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
    if not ref.startswith(("note:", "post:")) or not ref.partition(":")[2]:
        return False, "invalid_ref"
    if not str(candidate.get("card_text") or candidate.get("preview") or "").strip():
        return False, "missing_card"
    status = str(candidate.get("status") or "active").strip().lower()
    if status in {"deleted", "hidden", "inaccessible"}:
        return False, "source_not_visible"
    try:
        summary_version = int(candidate.get("summary_version") or 0)
    except (TypeError, ValueError):
        return False, "invalid_summary_version"
    if summary_version != DISCOVERY_SUMMARY_VERSION:
        return False, "unsupported_summary_version"
    summary_model = str(candidate.get("summary_model") or "")
    if card_origin(summary_model) != "llm":
        return False, "non_llm_card"
    model_parts = summary_model.split(":")
    if len(model_parts) < 4 or model_parts[-1] != f"v{summary_version}":
        return False, "unknown_summary_model"
    try:
        index_revision = int(candidate.get("index_revision") or 0)
        source_revision = int(candidate.get("source_revision") or 0)
    except (TypeError, ValueError):
        return False, "invalid_revision"
    if index_revision <= 0 or source_revision <= 0 or index_revision != source_revision:
        return False, "stale_card"
    if not str(candidate.get("citation_path") or "").strip():
        return False, "invalid_citation"
    return True, None


def selector_summary_freshness(candidate: Mapping[str, Any]) -> tuple[bool, str | None]:
    summary = str(candidate.get("selector_summary") or "").strip()
    if not summary:
        return False, "missing_selector_summary"
    if len(summary) > SELECTOR_SUMMARY_MAX_CHARS:
        return False, "selector_summary_too_long"
    try:
        version = int(candidate.get("selector_summary_version") or 0)
        index_revision = int(candidate.get("index_revision") or 0)
        source_revision = int(candidate.get("source_revision") or 0)
    except (TypeError, ValueError):
        return False, "invalid_selector_summary_freshness"
    if version != SELECTOR_SUMMARY_VERSION:
        return False, "stale_selector_summary_version"
    if index_revision <= 0 or source_revision <= 0 or index_revision != source_revision:
        return False, "stale_selector_summary_revision"
    return True, None


def normalize_candidate(
    candidate: Mapping[str, Any],
    *,
    scope: str = "global",
) -> CandidateEnvelope | None:
    ref = canonical_candidate_ref(str(candidate.get("ref") or candidate.get("label") or ""))
    kind, _, object_id = ref.partition(":")
    if kind not in {"note", "post", "file", "attachment", "media", "analytics"} or not object_id:
        return None
    index_revision = int(candidate.get("index_revision") or 0)
    source_revision = int(candidate.get("source_revision") or 0)
    summary_model = str(candidate.get("summary_model") or "")
    candidate_origin = str(candidate.get("card_origin") or "").strip()
    parent_post_id = str(candidate.get("parent_post_id") or "")
    parent_note_id = str(candidate.get("parent_note_id") or candidate.get("note_id") or "")
    post_id = str(candidate.get("post_id") or "")
    file_id = str(candidate.get("file_id") or object_id) if kind in {"file", "attachment", "media"} else ""
    citation_path = str(candidate.get("citation_path") or "")
    if not citation_path and kind == "note" and parent_post_id:
        citation_path = f"/note/post/{parent_post_id}/{object_id}/"
    origin = str(candidate.get("origin") or "semantic_search").strip() or "semantic_search"
    raw_semantic_score = (
        candidate.get("semantic_score")
        if "semantic_score" in candidate
        else (candidate.get("score") or candidate.get("similarity"))
        if "score" in candidate or "similarity" in candidate
        else None
    )
    try:
        semantic_score = (
            float(raw_semantic_score) if raw_semantic_score is not None else None
        )
    except (TypeError, ValueError):
        semantic_score = None
    if origin != "semantic_search":
        semantic_score = None
    source_requirement_ids = list(
        dict.fromkeys(
            str(item)
            for item in [
                *(candidate.get("source_requirement_ids") or ()),
                candidate.get("source_requirement_id"),
            ]
            if str(item or "")
        )
    )
    catalog_window_memberships: list[dict[str, Any]] = []
    for raw_membership in candidate.get("catalog_window_memberships") or ():
        if not isinstance(raw_membership, Mapping):
            continue
        source_id = str(raw_membership.get("source_requirement_id") or "")
        try:
            position = int(raw_membership.get("position"))
            window_size = int(raw_membership.get("window_size"))
        except (TypeError, ValueError):
            continue
        if source_id and position >= 1 and window_size >= position:
            catalog_window_memberships.append(
                {
                    "source_requirement_id": source_id,
                    "position": position,
                    "window_size": window_size,
                }
            )
    parent = (
        {"kind": "post", "ref": f"post:{parent_post_id}"}
        if parent_post_id
        else {"kind": "note", "ref": f"note:{parent_note_id}"}
        if parent_note_id
        else None
    )
    envelope: CandidateEnvelope = {
        "schema": CANDIDATE_ENVELOPE_SCHEMA,
        "ref": ref,
        "kind": kind,
        "title": str(candidate.get("title") or candidate.get("label") or ref)[:240],
        "card_text": str(
            candidate.get("card_text")
            or candidate.get("preview")
            or candidate.get("chunk_text")
            or ""
        )[:480],
        "origin": origin,
        "inclusion_priority": int(
            candidate.get("inclusion_priority")
            if candidate.get("inclusion_priority") is not None
            else _ORIGIN_INCLUSION_PRIORITY.get(origin, 50)
        ),
        "semantic_score": semantic_score,
        "semantic_rank_score": semantic_score,
        "search_enriched": bool(
            candidate.get("search_enriched")
            or (origin == "semantic_search" and semantic_score is not None)
        ),
        "score": semantic_score,
        "source_requirement_ids": source_requirement_ids,
        "source_requirement_id": source_requirement_ids[0] if source_requirement_ids else "",
        "index_revision": index_revision,
        "source_revision": source_revision,
        "summary_version": int(candidate.get("summary_version") or 0),
        "summary_model": summary_model,
        "selector_summary": str(candidate.get("selector_summary") or ""),
        "selector_summary_version": int(candidate.get("selector_summary_version") or 0),
        "selector_semantic_flags": dict(candidate.get("selector_semantic_flags") or {}),
        "card_origin": candidate_origin or card_origin(summary_model),
        "status": str(candidate.get("status") or "active"),
        "parent_post_id": parent_post_id or None,
        "parent_note_id": parent_note_id or None,
        "parent": parent,
        "post_id": post_id or None,
        "file_id": file_id or None,
        "node_type": str(candidate.get("node_type") or ""),
        "citation_path": citation_path or citation_path_for_ref(ref, scope=scope),
        "has_more": bool(candidate.get("has_more")),
        "available_fidelity": [],
    }
    if catalog_window_memberships:
        envelope["catalog_window_memberships"] = catalog_window_memberships
    if candidate.get("estimated_full_text_chars") is not None:
        try:
            envelope["estimated_full_text_chars"] = max(
                0, int(candidate["estimated_full_text_chars"])
            )
        except (TypeError, ValueError):
            pass
    if candidate.get("matched_evidence_rank") is not None:
        try:
            envelope["matched_evidence_rank"] = max(
                1, int(candidate["matched_evidence_rank"])
            )
        except (TypeError, ValueError):
            pass
    for structural_field in (
        "file_count",
        "image_count",
        "has_files",
        "has_images",
        "direct_image_count",
        "note_image_files_total",
        "has_any_images",
    ):
        if structural_field in candidate:
            envelope[structural_field] = candidate.get(structural_field)  # type: ignore[literal-required]
    eligible, failure = card_eligibility(envelope)
    envelope["card_eligible"] = eligible
    envelope["card_eligibility_failure"] = failure
    selector_fresh, selector_failure = selector_summary_freshness(envelope)
    envelope["selector_summary_fresh"] = selector_fresh
    envelope["selector_summary_failure"] = selector_failure
    if kind in {"note", "post"}:
        envelope["available_fidelity"] = [
            *(["semantic_card"] if eligible else []),
            "full_text",
        ]
    elif kind in {"file", "attachment", "media"}:
        envelope["available_fidelity"] = ["metadata", "text", "vision"]
    elif kind == "analytics":
        envelope["available_fidelity"] = ["analytics"]
    return envelope


def normalize_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    scope: str = "global",
    limit: int = MAX_CANDIDATE_REGISTRY,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    by_ref: dict[str, int] = {}
    for raw in candidates:
        candidate = normalize_candidate(raw, scope=scope)
        if candidate is None:
            continue
        ref = candidate["ref"]
        if ref in by_ref:
            index = by_ref[ref]
            previous = normalized[index]
            source_ids = list(
                dict.fromkeys(
                    [
                        *previous.get("source_requirement_ids", ()),
                        *candidate.get("source_requirement_ids", ()),
                    ]
                )
            )
            preferred = (
                candidate
                if int(candidate["inclusion_priority"]) < int(previous["inclusion_priority"])
                else previous
            )
            normalized[index] = {
                **preferred,
                "source_requirement_ids": source_ids,
                "source_requirement_id": source_ids[0] if source_ids else "",
                "has_more": bool(previous.get("has_more") or candidate.get("has_more")),
                "semantic_rank_score": max(
                    (
                        float(value)
                        for value in (
                            previous.get("semantic_rank_score"),
                            candidate.get("semantic_rank_score"),
                        )
                        if value is not None
                    ),
                    default=None,
                ),
                "search_enriched": bool(
                    previous.get("semantic_score") is not None
                    or candidate.get("semantic_score") is not None
                ),
                "matched_evidence_rank": min(
                    (
                        int(value)
                        for value in (
                            previous.get("matched_evidence_rank"),
                            candidate.get("matched_evidence_rank"),
                        )
                        if value is not None
                    ),
                    default=None,
                ),
                "catalog_window_memberships": [
                    dict(item)
                    for item in dict.fromkeys(
                        tuple(sorted(item.items()))
                        for item in (
                            *previous.get("catalog_window_memberships", ()),
                            *candidate.get("catalog_window_memberships", ()),
                        )
                        if isinstance(item, Mapping)
                    )
                ],
            }
            continue
        if len(normalized) >= limit:
            continue
        by_ref[ref] = len(normalized)
        normalized.append(candidate)
    normalized.sort(
        key=lambda item: (
            int(item["inclusion_priority"])
            if item.get("inclusion_priority") is not None
            else 50,
            -float(item["semantic_score"])
            if item.get("semantic_score") is not None
            else -float(item["semantic_rank_score"])
            if item.get("semantic_rank_score") is not None
            else 0.0,
            str(item.get("ref") or ""),
        )
    )
    return normalized


def empty_material_plan() -> dict[str, Any]:
    return {
        "schema": MATERIAL_PLAN_SCHEMA,
        "assessments": [],
        "candidates": [],
        "card_ids": [],
        "required_full_text_ids": [],
        "optional_full_text_ids": [],
        "pending_full_text_ids": [],
        "opened_full_text_ids": [],
        "failed_full_text_ids": [],
        "promoted_to_full_text_ids": [],
        "omitted_ids": [],
        "has_more_by_source": {},
        "expansion_reason_by_source": {},
        "expansion_pending_sources": [],
        "expanded_sources": [],
        "needs_optional_assessment": False,
        "context_selection_done": False,
        "needs_expansion_assessment": False,
        "coverage": "complete",
        "full_read_batches": [],
        "evidence_escalation_pending_refs": [],
        "evidence_escalation_opened_refs": [],
        "evidence_escalation_failed_refs": [],
        "evidence_escalation_attempted_sources": [],
        "evidence_escalation_reassess_refs": [],
        # A reassessment may establish that an ordinary semantic corpus adds
        # nothing beyond already verified evidence.  This is deliberately
        # separate from discovery: the corpus was still searched and assessed.
        "baseline_discharged_source_ids": [],
        "needs_evidence_reassessment": False,
        "deferred_discovery_actions": [],
        "card_eligibility_failures": {},
        # Phase-4 fields are additive so v1 checkpoints remain readable.
        "materialization_queue": [],
        "discovery_actions": [],
        "gaps": [],
        "runtime_trace": [],
        "budget": {},
        "budget_usage": {},
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _order_full_refs(
    refs: Iterable[str],
    *,
    candidates: Mapping[str, Mapping[str, Any]],
    assessments: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Confidence-first ordering with source diversity as a stable tie-break."""

    queues: dict[str, list[str]] = {}
    for ref in _unique(refs):
        source_id = str(candidates.get(ref, {}).get("source_requirement_id") or "")
        queues.setdefault(source_id, []).append(ref)
    for queue in queues.values():
        queue.sort(
            key=lambda ref: (
                -float(assessments.get(ref, {}).get("confidence") or 0.0),
                ref,
            )
        )
    ordered: list[str] = []
    previous_source = ""
    while any(queues.values()):
        available = [source for source, queue in queues.items() if queue]
        source = min(
            available,
            key=lambda item: (
                -float(assessments.get(queues[item][0], {}).get("confidence") or 0.0),
                item == previous_source and len(available) > 1,
                item,
            ),
        )
        ordered.append(queues[source].pop(0))
        previous_source = source
    return ordered


def merge_material_plan(
    previous: Mapping[str, Any] | None,
    *,
    candidates: Iterable[Mapping[str, Any]],
    assessments: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge assessments by canonical ref and derive deterministic queues."""

    prior = {**empty_material_plan(), **dict(previous or {})}
    candidate_map = {
        str(item.get("ref") or ""): dict(item)
        for item in prior.get("candidates") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    for item in candidates:
        ref = canonical_candidate_ref(str(item.get("ref") or ""))
        if ref:
            candidate_map[ref] = dict(item)

    assessment_map = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in prior.get("assessments") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    for item in assessments:
        ref = canonical_candidate_ref(str(item.get("ref") or ""))
        if ref and ref in candidate_map:
            assessment_map[ref] = {**dict(item), "ref": ref}

    ordered_refs = list(candidate_map)
    ordered_assessments = [assessment_map[ref] for ref in ordered_refs if ref in assessment_map]
    card_ids: list[str] = []
    required_full: list[str] = []
    optional_full: list[str] = []
    promoted = list(prior.get("promoted_to_full_text_ids") or ())
    failures = dict(prior.get("card_eligibility_failures") or {})

    for assessment in ordered_assessments:
        ref = str(assessment["ref"])
        relevance = str(assessment.get("relevance") or "irrelevant")
        if relevance == "irrelevant":
            continue
        resolution = str(assessment.get("resolution") or "full_text")
        candidate = candidate_map[ref]
        if resolution == "card" and str(assessment.get("reason_code") or "") != "topic_only":
            resolution = "full_text"
            assessment["resolution"] = "full_text"
            assessment["runtime_override"] = "claim_scope_requires_primary"
        if resolution == "card" and not bool(candidate.get("card_eligible")):
            resolution = "full_text"
            assessment["resolution"] = "full_text"
            assessment["runtime_override"] = "ineligible_card"
            promoted.append(ref)
            failures[ref] = str(candidate.get("card_eligibility_failure") or "ineligible_card")
        if resolution == "card":
            card_ids.append(ref)
        elif relevance == "direct":
            required_full.append(ref)
        else:
            optional_full.append(ref)

    required_full = _order_full_refs(
        required_full,
        candidates=candidate_map,
        assessments=assessment_map,
    )
    optional_full = _order_full_refs(
        optional_full,
        candidates=candidate_map,
        assessments=assessment_map,
    )
    opened = _unique(prior.get("opened_full_text_ids") or ())
    failed = _unique(prior.get("failed_full_text_ids") or ())
    pending = [ref for ref in _unique((*required_full, *optional_full)) if ref not in opened and ref not in failed]
    omitted = _unique((*prior.get("omitted_ids", ()), *failed))
    has_more: dict[str, bool] = dict(prior.get("has_more_by_source") or {})
    for candidate in candidate_map.values():
        source_id = str(candidate.get("source_requirement_id") or "")
        if source_id:
            has_more[source_id] = has_more.get(source_id, False) or bool(candidate.get("has_more"))

    unresolved_required = [ref for ref in required_full if ref not in opened]
    coverage = "partial" if unresolved_required and any(ref in omitted for ref in unresolved_required) else "complete"
    return {
        **prior,
        "schema": MATERIAL_PLAN_SCHEMA,
        "candidates": list(candidate_map.values()),
        "assessments": ordered_assessments,
        "card_ids": _unique(card_ids),
        "required_full_text_ids": _unique(required_full),
        "optional_full_text_ids": _unique(optional_full),
        "pending_full_text_ids": pending,
        "opened_full_text_ids": opened,
        "failed_full_text_ids": failed,
        "promoted_to_full_text_ids": _unique(promoted),
        "omitted_ids": omitted,
        "has_more_by_source": has_more,
        "coverage": coverage,
        "card_eligibility_failures": failures,
    }


def _effective_fidelity(requested: str, required: str) -> str:
    requested_name = "semantic_card" if requested == "card" else requested
    required_name = "semantic_card" if required == "card" else required
    if _FIDELITY_RANK.get(required_name, 2) > _FIDELITY_RANK.get(requested_name, 2):
        return required_name
    return requested_name


def _candidate_source_ids(candidate: Mapping[str, Any]) -> list[str]:
    return _unique(
        [
            *(candidate.get("source_requirement_ids") or ()),
            str(candidate.get("source_requirement_id") or ""),
        ]
    )


def compile_material_plan(
    previous: Mapping[str, Any] | None,
    *,
    candidates: Iterable[Mapping[str, Any]],
    assessments: Iterable[Mapping[str, Any]],
    source_dispositions: Iterable[Mapping[str, Any]] = (),
    contract: Mapping[str, Any] | None = None,
    max_objects: int = DEFAULT_MAX_PACK_OBJECTS,
    max_full_text_chars: int = DEFAULT_MAX_FULL_TEXT_CHARS,
    max_card_chars: int = DEFAULT_MAX_CARD_CHARS,
) -> dict[str, Any]:
    """Compile the Selector decision into the only DB-readable material queue.

    Relevance is consumed as typed input and is never recomputed here. The
    compiler only applies contract fidelity, provenance and deterministic
    budgets. Its legacy id lists are a compatibility projection of the queue.
    """

    candidate_list = [dict(item) for item in candidates if isinstance(item, Mapping)]
    assessment_list = [dict(item) for item in assessments if isinstance(item, Mapping)]
    plan = merge_material_plan(
        previous,
        candidates=candidate_list,
        assessments=assessment_list,
    )
    candidate_map = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in plan.get("candidates") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    assessment_map = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in plan.get("assessments") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    requirements = {
        str(item.get("source_id") or ""): dict(item)
        for item in (contract or {}).get("source_requirements") or ()
        if isinstance(item, Mapping) and item.get("source_id")
    }
    dispositions = {
        str(item.get("source_id") or ""): str(item.get("status") or "")
        for item in source_dispositions
        if isinstance(item, Mapping) and item.get("source_id")
    }
    discharged_sources = {
        str(item)
        for item in plan.get("baseline_discharged_source_ids") or ()
        if str(item)
    }

    trace = list(plan.get("runtime_trace") or ())
    gaps = [
        dict(item)
        for item in plan.get("gaps") or ()
        if isinstance(item, Mapping)
        and str(item.get("kind") or "") not in {
            "no_relevant_candidate",
            "search_more",
            "material_budget",
        }
    ]
    discovery_actions: list[dict[str, Any]] = []
    for source_id in sorted(dispositions):
        status = dispositions[source_id]
        if status == "no_relevant_candidate":
            requirement = requirements.get(source_id, {})
            required_source = (
                str(requirement.get("evidence_obligation") or "") == "required"
                or bool(requirement.get("required"))
            ) and source_id not in discharged_sources
            source_candidates = [
                candidate
                for candidate in candidate_map.values()
                if source_id in _candidate_source_ids(candidate)
            ]
            exhaustive_absence = (
                str(requirement.get("coverage") or "") == "complete"
                and bool(source_candidates)
                and all(
                    canonical_candidate_ref(str(candidate.get("ref") or ""))
                    in assessment_map
                    for candidate in source_candidates
                )
            )
            gaps.append(
                {
                    "kind": "no_relevant_candidate",
                    "source_id": source_id,
                    "blocks_ready": required_source and not exhaustive_absence,
                    "exhaustive_absence": exhaustive_absence,
                }
            )
        elif status == "search_more":
            discovery_actions.append(
                {
                    "kind": "bounded_discovery",
                    "source_id": source_id,
                    "max_actions": 1,
                }
            )
            gaps.append(
                {"kind": "search_more", "source_id": source_id, "blocks_ready": True}
            )
        elif status == "ambiguous":
            discovery_actions.append(
                {
                    "kind": "bounded_discovery",
                    "source_id": source_id,
                    "max_actions": 1,
                }
            )
            gaps.append(
                {"kind": "ambiguous", "source_id": source_id, "blocks_ready": True}
            )

    selector_failed = bool(plan.get("selector_failure"))
    selected: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for ref, candidate in candidate_map.items():
        assessment = assessment_map.get(ref)
        exact_target = str(candidate.get("origin") or "") == "exact_target"
        if assessment is None:
            if not (selector_failed and exact_target):
                continue
            assessment = {
                "ref": ref,
                "relevance": "direct",
                "resolution": "full_text",
                "reason_code": "exact_target_guarantee",
                "selection_source": "deterministic_exact_target",
                "confidence": 1.0,
            }
            trace.append(
                {"ref": ref, "kind": "exact_target_preserved_after_selector_failure"}
            )
        relevance = str(assessment.get("relevance") or "irrelevant")
        if relevance not in {"direct", "supporting"}:
            continue

        source_ids = _candidate_source_ids(candidate)
        required_fidelities = [
            str(requirements[source_id].get("required_fidelity") or requirements[source_id].get("evidence_granularity") or "full_text")
            for source_id in source_ids
            if source_id in requirements
        ]
        required_fidelity = max(
            required_fidelities or ["metadata"],
            key=lambda value: _FIDELITY_RANK.get(value, 2),
        )
        requested_fidelity = str(assessment.get("resolution") or "full_text")
        effective_fidelity = _effective_fidelity(requested_fidelity, required_fidelity)
        if effective_fidelity == "semantic_card" and not bool(candidate.get("card_eligible")):
            effective_fidelity = "full_text"
            trace.append(
                {
                    "ref": ref,
                    "kind": "fidelity_promotion",
                    "from": "semantic_card",
                    "to": "full_text",
                    "reason": str(candidate.get("card_eligibility_failure") or "ineligible_card"),
                }
            )
        elif _FIDELITY_RANK.get(effective_fidelity, 2) > _FIDELITY_RANK.get(requested_fidelity, 2):
            trace.append(
                {
                    "ref": ref,
                    "kind": "fidelity_promotion",
                    "from": requested_fidelity,
                    "to": effective_fidelity,
                    "reason": "contract_fidelity_floor",
                }
            )

        estimated_chars = (
            len(str(candidate.get("card_text") or ""))
            if effective_fidelity == "semantic_card"
            else None
        )
        full_text_estimate = (
            candidate.get("estimated_full_text_chars") or candidate.get("estimated_chars")
            if effective_fidelity != "semantic_card"
            else None
        )
        required_source = any(
            str(requirements.get(source_id, {}).get("evidence_obligation") or "") == "required"
            or bool(requirements.get(source_id, {}).get("required"))
            for source_id in source_ids
        )
        queue_item = {
            "ref": ref,
            "object_kind": str(candidate.get("kind") or ref.partition(":")[0]),
            "relevance": relevance,
            "role": str(assessment.get("selected_role") or assessment.get("role") or "answer_evidence"),
            "requested_fidelity": requested_fidelity,
            "required_fidelity": required_fidelity,
            "effective_fidelity": effective_fidelity,
            "estimated_chars": estimated_chars,
            "full_text_chars_estimate": full_text_estimate,
            "source_requirement_ids": source_ids,
            "source_requirement_id": source_ids[0] if source_ids else "",
            "parent": dict(candidate.get("parent")) if isinstance(candidate.get("parent"), Mapping) else None,
            "citation_path": str(candidate.get("citation_path") or ""),
            "expected_revision": int(candidate.get("source_revision") or 0),
            "provenance": {
                "candidate_origin": str(candidate.get("origin") or ""),
                "selector_schema": "workspace.context-selector/v2",
                "selection_source": str(assessment.get("selection_source") or "context_selector_v2"),
                "reason_code": str(assessment.get("reason_code") or ""),
                "parent": dict(candidate.get("parent")) if isinstance(candidate.get("parent"), Mapping) else None,
            },
        }
        priority = (
            0 if exact_target else 1 if relevance == "direct" and required_source else 2 if relevance == "direct" else 3,
            int(candidate.get("inclusion_priority") or 50),
            -float(assessment.get("confidence") or 0.0),
            ref,
        )
        selected.append((priority, queue_item))

    selected.sort(key=lambda item: item[0])
    full_text_count = sum(
        item["effective_fidelity"] != "semantic_card" for _priority, item in selected
    )
    fair_full_text_reservation = (
        max(
            1,
            min(
                DEFAULT_FULL_TEXT_RESERVATION_CHARS,
                max(0, int(max_full_text_chars)) // full_text_count,
            ),
        )
        if full_text_count
        else 0
    )
    if max(0, int(max_full_text_chars)) >= full_text_count * MIN_FULL_TEXT_RESERVATION_CHARS:
        fair_full_text_reservation = max(
            MIN_FULL_TEXT_RESERVATION_CHARS, fair_full_text_reservation
        )
    queue: list[dict[str, Any]] = []
    omitted = list(plan.get("omitted_ids") or ())
    used_full = 0
    used_cards = 0
    for _priority, item in selected:
        fidelity = str(item["effective_fidelity"])
        if fidelity == "semantic_card":
            estimate = int(item["estimated_chars"] or 0)
        else:
            raw_estimate = item.get("full_text_chars_estimate")
            try:
                actual_estimate = int(raw_estimate) if raw_estimate is not None else 0
            except (TypeError, ValueError):
                actual_estimate = 0
            estimate = min(
                actual_estimate or fair_full_text_reservation,
                fair_full_text_reservation,
            )
            item["estimated_chars"] = estimate
        reason = ""
        if len(queue) >= max(0, int(max_objects)):
            reason = "object_budget"
        elif fidelity == "semantic_card" and used_cards + estimate > max(0, int(max_card_chars)):
            reason = "card_char_budget"
        elif fidelity != "semantic_card" and used_full + estimate > max(0, int(max_full_text_chars)):
            reason = "full_text_char_budget"
        if reason:
            omitted.append(str(item["ref"]))
            gaps.append(
                {
                    "kind": "material_budget",
                    "source_id": str(item.get("source_requirement_id") or ""),
                    "ref": str(item["ref"]),
                    "reason": reason,
                    "blocks_ready": item["relevance"] == "direct",
                }
            )
            trace.append({"ref": item["ref"], "kind": "budget_omission", "reason": reason})
            continue
        queue.append(item)
        if fidelity == "semantic_card":
            used_cards += estimate
        else:
            used_full += estimate

    card_ids = [item["ref"] for item in queue if item["effective_fidelity"] == "semantic_card"]
    full_ids = [item["ref"] for item in queue if item["effective_fidelity"] != "semantic_card"]
    direct_refs = {item["ref"] for item in queue if item["relevance"] == "direct"}
    opened = _unique(plan.get("opened_full_text_ids") or ())
    failed = _unique(plan.get("failed_full_text_ids") or ())
    pending = [ref for ref in full_ids if ref not in opened and ref not in failed]
    required_full = [ref for ref in full_ids if ref in direct_refs]
    optional_full = [ref for ref in full_ids if ref not in direct_refs]
    omitted = _unique((*omitted, *failed))
    return {
        **plan,
        "schema": MATERIAL_PLAN_SCHEMA_V2,
        "candidates": [
            {
                **candidate_map[ref],
                **(
                    {"selected_resolution": next(item["effective_fidelity"] for item in queue if item["ref"] == ref)}
                    if any(item["ref"] == ref for item in queue)
                    else {}
                ),
            }
            for ref in candidate_map
        ],
        "source_dispositions": [
            {"source_id": source_id, "status": dispositions[source_id]}
            for source_id in sorted(dispositions)
        ],
        "materialization_queue": queue,
        "card_ids": card_ids,
        "required_full_text_ids": required_full,
        "optional_full_text_ids": optional_full,
        "pending_full_text_ids": pending,
        "omitted_ids": omitted,
        "promoted_to_full_text_ids": _unique(
            item["ref"]
            for item in queue
            if item["effective_fidelity"] == "full_text"
            and item["requested_fidelity"] in {"card", "semantic_card"}
        ),
        "discovery_actions": discovery_actions,
        "gaps": gaps,
        "runtime_trace": trace,
        "budget": {
            "max_objects": max(0, int(max_objects)),
            "max_full_text_chars": max(0, int(max_full_text_chars)),
            "max_card_chars": max(0, int(max_card_chars)),
        },
        "budget_usage": {
            "objects": len(queue),
            "full_text_chars_reserved": used_full,
            "card_chars_reserved": used_cards,
        },
        "coverage": "partial" if omitted or selector_failed or any(item.get("blocks_ready") for item in gaps) else "complete",
    }


def next_full_read_batch(plan: Mapping[str, Any], *, size: int = FULL_READ_BATCH_SIZE) -> list[str]:
    pending = set(str(item) for item in plan.get("pending_full_text_ids") or ())
    ordered = [
        *[str(item) for item in plan.get("required_full_text_ids") or ()],
        *[str(item) for item in plan.get("optional_full_text_ids") or ()],
    ]
    return [ref for ref in _unique(ordered) if ref in pending][: max(1, min(size, 3))]


def schedule_matched_evidence_recall_probes(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    deep_reads_remaining: int,
    size: int = FULL_READ_BATCH_SIZE,
) -> dict[str, Any]:
    """Use spare read budget to verify bounded query-conditioned false negatives."""

    result = {**empty_material_plan(), **dict(plan)}
    if deep_reads_remaining <= 0 or result.get("matched_evidence_recall_refs"):
        return result
    positive_refs = {
        canonical_candidate_ref(str(item.get("ref") or ""))
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping)
        and str(item.get("relevance") or "") in {"direct", "supporting"}
    }
    selected_full_refs = set(
        _unique(
            (
                *result.get("required_full_text_ids", ()),
                *result.get("optional_full_text_ids", ()),
            )
        )
    ) & positive_refs
    if len(selected_full_refs) <= 1:
        return result
    required_sources = {
        str(item.get("source_id") or "")
        for item in contract.get("source_requirements") or ()
        if isinstance(item, Mapping)
        and (
            str(item.get("evidence_obligation") or "") == "required"
            or bool(item.get("required"))
        )
    }
    unavailable = {
        canonical_candidate_ref(str(ref))
        for ref in (
            *result.get("opened_full_text_ids", ()),
            *result.get("failed_full_text_ids", ()),
            *result.get("pending_full_text_ids", ()),
        )
        if str(ref)
    }
    ranked: list[dict[str, Any]] = []
    for candidate in result.get("candidates") or ():
        if not isinstance(candidate, Mapping):
            continue
        ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
        if (
            not ref.startswith(("note:", "post:"))
            or ref in unavailable
            or candidate.get("matched_evidence_rank") is None
            or "full_text" not in set(candidate.get("available_fidelity") or ())
            or not (required_sources & set(_candidate_source_ids(candidate)))
        ):
            continue
        ranked.append(dict(candidate))
    ranked.sort(
        key=lambda item: (
            int(item.get("matched_evidence_rank") or 1_000_000),
            int(item.get("inclusion_priority") or 50),
            -float(item.get("semantic_rank_score") or 0.0),
            str(item.get("ref") or ""),
        )
    )
    pending_selected_count = len(
        selected_full_refs
        & {canonical_candidate_ref(str(ref)) for ref in result.get("pending_full_text_ids") or ()}
    )
    capacity = min(size, max(0, deep_reads_remaining - pending_selected_count))
    probe_refs = _unique(
        canonical_candidate_ref(str(candidate.get("ref") or ""))
        for candidate in ranked[:capacity]
    )
    if not probe_refs:
        return result
    result["matched_evidence_recall_refs"] = probe_refs
    result["optional_full_text_ids"] = _unique(
        (*result.get("optional_full_text_ids", ()), *probe_refs)
    )
    result["pending_full_text_ids"] = _unique(
        (*result.get("pending_full_text_ids", ()), *probe_refs)
    )
    result["context_selection_done"] = False
    result["runtime_trace"] = [
        *list(result.get("runtime_trace") or ()),
        {
            "kind": "matched_evidence_recall_scheduled",
            "refs": probe_refs,
            "selected_refs": sorted(selected_full_refs),
        },
    ]
    return result


def schedule_evidence_escalation(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    deep_reads_remaining: int,
    planner_calls_remaining: int,
    size: int = FULL_READ_BATCH_SIZE,
) -> tuple[dict[str, Any], list[str]]:
    """Open the best unread candidate before accepting a required-source miss.

    Required source discovery is not a mandate to spend a full read in every
    corpus.  A verified read can make a second corpus redundant; the existing
    reassessment call is responsible for making that semantic decision.
    """

    result = {**empty_material_plan(), **dict(plan)}
    if deep_reads_remaining <= 0 or planner_calls_remaining <= 0:
        return result, []
    # Full text already selected by the reasoner is stronger evidence than a
    # negative-source probe. Let that read complete before scheduling fallback
    # candidates from another corpus.
    if result.get("pending_full_text_ids"):
        return result, []
    requirements = {
        str(item.get("source_id") or ""): dict(item)
        for item in contract.get("source_requirements") or ()
        if isinstance(item, Mapping) and item.get("source_id")
    }
    discharged_sources = {
        str(item)
        for item in result.get("baseline_discharged_source_ids") or ()
        if str(item)
    }
    disposition_by_source = {
        str(item.get("source_id") or ""): str(item.get("status") or "")
        for item in result.get("source_dispositions") or ()
        if isinstance(item, Mapping) and item.get("source_id")
    }
    unresolved_sources = [
        source_id
        for source_id, status in disposition_by_source.items()
        if status in {"no_relevant_candidate", "search_more", "ambiguous"}
        and (
            str(requirements.get(source_id, {}).get("evidence_obligation") or "")
            == "required"
            or bool(requirements.get(source_id, {}).get("required"))
        )
        and source_id not in discharged_sources
    ]
    attempted_sources = set(
        str(item) for item in result.get("evidence_escalation_attempted_sources") or ()
    )
    unresolved_sources = [
        source_id for source_id in _unique(unresolved_sources) if source_id not in attempted_sources
    ]
    if not unresolved_sources:
        return result, []

    assessment_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    unavailable = set(
        _unique(
            (
                *result.get("opened_full_text_ids", ()),
                *result.get("failed_full_text_ids", ()),
                *result.get("evidence_escalation_pending_refs", ()),
            )
        )
    )
    queues: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in unresolved_sources}
    for candidate in result.get("candidates") or ():
        if not isinstance(candidate, Mapping):
            continue
        ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
        if (
            not ref.startswith(("note:", "post:"))
            or ref in unavailable
            or "full_text" not in set(candidate.get("available_fidelity") or ())
            or str(assessment_by_ref.get(ref, {}).get("relevance") or "irrelevant")
            != "irrelevant"
        ):
            continue
        for source_id in _candidate_source_ids(candidate):
            if source_id in queues:
                queues[source_id].append(dict(candidate))
    for queue in queues.values():
        queue.sort(
            key=lambda item: (
                int(item.get("inclusion_priority") or 50),
                -float(item.get("semantic_rank_score") or 0.0),
                str(item.get("ref") or ""),
            )
        )

    source_order = {
        str(item.get("source_id") or ""): position
        for position, item in enumerate(contract.get("source_requirements") or ())
        if isinstance(item, Mapping) and item.get("source_id")
    }
    decision_input_mode = (
        str(contract.get("task_profile") or "")
        in {"workspace_synthesis", "recommendation"}
    )

    requested_window_rows: list[tuple[dict[str, Any], str, int]] = []
    if decision_input_mode:
        for source_id in unresolved_sources:
            requested_for_source: list[tuple[dict[str, Any], str, int]] = []
            for candidate in queues.get(source_id, ()):
                ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
                if str(assessment_by_ref.get(ref, {}).get("reason_code") or "") != "search_more":
                    continue
                positions = [
                    int(item.get("position") or 0)
                    for item in candidate.get("catalog_window_memberships") or ()
                    if isinstance(item, Mapping)
                    and str(item.get("source_requirement_id") or "") == source_id
                    and int(item.get("position") or 0) > 0
                ]
                requested_for_source.append(
                    (
                        dict(candidate),
                        source_id,
                        min(positions) if positions else 1_000_000,
                    )
                )
            requested_for_source.sort(
                key=lambda item: (
                    item[2],
                    int(item[0].get("matched_evidence_rank") or 1_000_000),
                    int(item[0].get("inclusion_priority") or 50),
                    -float(item[0].get("semantic_rank_score") or 0.0),
                    str(item[0].get("ref") or ""),
                )
            )
            raw_source_limit = (
                requirements.get(source_id, {}).get("budget") or {}
            ).get("deep_reads")
            source_limit = (
                max(0, int(raw_source_limit))
                if raw_source_limit is not None
                else deep_reads_remaining
            )
            requested_window_rows.extend(requested_for_source[:source_limit])

    if requested_window_rows:
        # search_more is the reasoner's explicit request for stronger evidence.
        # Preserve typed-source order, each source's own read budget and any
        # source-local window order;
        # the single opened-evidence reassessment remains the semantic selector.
        requested_window_rows.sort(
            key=lambda item: (
                source_order.get(item[1], 1_000_000),
                item[2],
                int(item[0].get("matched_evidence_rank") or 1_000_000),
                str(item[0].get("ref") or ""),
            )
        )
        ranked = [(candidate, source_id) for candidate, source_id, _ in requested_window_rows]
        target_count = min(deep_reads_remaining, len(ranked))
        escalation_strategy = "reasoner_requested_decision_input_evidence"
    else:
        # An all-negative card pass is not verified absence. Open one bounded
        # global batch so the existing reassessment call can compare full candidates.
        # This never imposes a per-source quota or materializes unselected reads.
        ranked = [
            (candidate, source_id)
            for source_id in unresolved_sources
            for candidate in queues[source_id]
        ]
        ranked.sort(
            key=lambda item: (
                int(item[0].get("matched_evidence_rank") or 1_000_000),
                int(item[0].get("inclusion_priority") or 50),
                -float(item[0].get("semantic_rank_score") or 0.0),
                str(item[0].get("ref") or ""),
            )
        )
        target_count = min(size, deep_reads_remaining)
        escalation_strategy = "ranked_negative_evidence"
    selected: list[str] = []
    selected_sources: list[str] = []
    for candidate, source_id in ranked:
        ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
        if not ref or ref in selected:
            continue
        selected.append(ref)
        selected_sources.append(source_id)
        if len(selected) >= target_count:
            break
    if not selected:
        return result, []

    result["evidence_escalation_pending_refs"] = _unique(
        (*result.get("evidence_escalation_pending_refs", ()), *selected)
    )
    result["evidence_escalation_attempted_sources"] = _unique(
        (*result.get("evidence_escalation_attempted_sources", ()), *selected_sources)
    )
    result["context_selection_done"] = False
    result["needs_evidence_reassessment"] = True
    result["needs_expansion_assessment"] = False
    result["deferred_discovery_actions"] = list(result.get("discovery_actions") or ())
    result["discovery_actions"] = []
    result["runtime_trace"] = [
        *list(result.get("runtime_trace") or ()),
        {
            "kind": "evidence_escalation_scheduled",
            "refs": selected,
            "source_ids": selected_sources,
            "strategy": escalation_strategy,
        },
    ]
    return result, selected


def next_evidence_escalation_batch(
    plan: Mapping[str, Any], *, size: int = FULL_READ_BATCH_SIZE
) -> list[str]:
    pending = _unique(plan.get("evidence_escalation_pending_refs") or ())
    if any(
        isinstance(item, Mapping)
        and item.get("kind") == "evidence_escalation_scheduled"
        and item.get("strategy") == "reasoner_requested_decision_input_evidence"
        for item in reversed(list(plan.get("runtime_trace") or ()))
    ):
        return pending
    return pending[: max(1, min(size, 3))]


def schedule_selected_evidence_reassessment(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    opened: Iterable[str],
) -> dict[str, Any]:
    """Reassess the final verified opened set and fail closed on unread selections."""

    result = {**empty_material_plan(), **dict(plan)}
    if result.get("pending_full_text_ids"):
        return result
    opened_refs = {
        canonical_candidate_ref(str(ref))
        for ref in (*result.get("opened_full_text_ids", ()), *opened)
        if str(ref)
    }
    positive_refs = {
        canonical_candidate_ref(str(item.get("ref") or ""))
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping)
        and str(item.get("relevance") or "") in {"direct", "supporting"}
    }
    failed_selected = positive_refs & {
        canonical_candidate_ref(str(ref))
        for ref in result.get("failed_full_text_ids") or ()
        if str(ref)
    }
    if failed_selected:
        result["assessments"] = [
            (
                {
                    **dict(item),
                    "relevance": "irrelevant",
                    "role": "none",
                    "selected_role": "none",
                    "resolution": "none",
                    "selected_resolution": "none",
                    "confidence": 0.0,
                    "reason_code": "ambiguous",
                }
                if isinstance(item, Mapping)
                and canonical_candidate_ref(str(item.get("ref") or ""))
                in failed_selected
                else dict(item)
            )
            for item in result.get("assessments") or ()
            if isinstance(item, Mapping)
        ]
        positive_refs -= failed_selected
        refs_by_source: dict[str, set[str]] = {}
        for candidate in result.get("candidates") or ():
            if not isinstance(candidate, Mapping):
                continue
            ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
            for source_id in _candidate_source_ids(candidate):
                refs_by_source.setdefault(source_id, set()).add(ref)
        result["source_dispositions"] = [
            {
                **dict(item),
                "status": (
                    "search_more"
                    if str(item.get("status") or "") == "selected"
                    and not (
                        refs_by_source.get(str(item.get("source_id") or ""), set())
                        & positive_refs
                    )
                    else str(item.get("status") or "")
                ),
            }
            for item in result.get("source_dispositions") or ()
            if isinstance(item, Mapping)
        ]
        result["runtime_trace"] = [
            *list(result.get("runtime_trace") or ()),
            {
                "kind": "failed_selected_full_text_demoted",
                "refs": sorted(failed_selected),
            },
        ]
    selected_opened = sorted(opened_refs & positive_refs)
    probe_opened = [
        ref
        for ref in _unique(
            canonical_candidate_ref(str(item))
            for item in result.get("matched_evidence_recall_refs") or ()
            if str(item)
        )
        if ref in opened_refs
    ]
    if not selected_opened and not probe_opened:
        return result

    dispositions = {
        str(item.get("source_id") or ""): str(item.get("status") or "")
        for item in result.get("source_dispositions") or ()
        if isinstance(item, Mapping) and item.get("source_id")
    }
    discharged = {
        str(item)
        for item in result.get("baseline_discharged_source_ids") or ()
        if str(item)
    }
    eligible_negative_sources = []
    for raw_requirement in contract.get("source_requirements") or ():
        if not isinstance(raw_requirement, Mapping):
            continue
        requirement = dict(raw_requirement)
        source_id = str(requirement.get("source_id") or "")
        evidence_required = (
            str(requirement.get("evidence_obligation") or "") == "required"
            or bool(requirement.get("required"))
        )
        if (
            source_id
            and source_id not in discharged
            and dispositions.get(source_id) == "no_relevant_candidate"
            and evidence_required
            and str(requirement.get("coverage") or "") == "relevant"
            and str(requirement.get("predicate_kind") or "semantic") == "semantic"
            and str((requirement.get("scope") or {}).get("mode") or "") == "corpus"
        ):
            eligible_negative_sources.append(source_id)
    result["evidence_escalation_reassess_refs"] = _unique(
        (
            *result.get("evidence_escalation_reassess_refs", ()),
            *selected_opened,
            *probe_opened,
        )
    )
    result["needs_evidence_reassessment"] = True
    result["context_selection_done"] = False
    result["runtime_trace"] = [
        *list(result.get("runtime_trace") or ()),
        {
            "kind": "selected_evidence_reassessment_scheduled",
            "refs": _unique((*selected_opened, *probe_opened)),
            "probe_refs": probe_opened,
            "source_ids": sorted(eligible_negative_sources),
            "reason": "minimal_verified_opened_set",
        },
    ]
    return result


def saturated_sources(plan: Mapping[str, Any]) -> list[str]:
    """Sources whose visible page is entirely direct and advertises more rows."""

    expanded = set(str(item) for item in plan.get("expanded_sources") or ())
    assessments = {
        str(item.get("ref") or ""): str(item.get("relevance") or "")
        for item in plan.get("assessments") or ()
        if isinstance(item, Mapping)
    }
    by_source: dict[str, list[str]] = {}
    for candidate in plan.get("candidates") or ():
        if not isinstance(candidate, Mapping):
            continue
        source_id = str(candidate.get("source_requirement_id") or "")
        ref = str(candidate.get("ref") or "")
        if source_id and ref:
            by_source.setdefault(source_id, []).append(ref)
    return [
        source_id
        for source_id, refs in by_source.items()
        if source_id not in expanded
        and bool((plan.get("has_more_by_source") or {}).get(source_id))
        and refs
        and all(assessments.get(ref) == "direct" for ref in refs)
    ]


def record_full_read_results(
    plan: Mapping[str, Any],
    *,
    opened: Iterable[str] = (),
    failed: Iterable[str] = (),
    batch: Iterable[str] = (),
) -> dict[str, Any]:
    result = {**empty_material_plan(), **dict(plan)}
    batch_ids = set(str(ref) for ref in batch)
    escalation_batch = batch_ids & set(
        str(ref) for ref in result.get("evidence_escalation_pending_refs") or ()
    )
    opened_ids = _unique((*result.get("opened_full_text_ids", ()), *opened))
    failed_ids = _unique(
        (
            *result.get("failed_full_text_ids", ()),
            *(str(ref) for ref in failed if str(ref) not in escalation_batch),
        )
    )
    resolved = set((*opened_ids, *failed_ids))
    result["opened_full_text_ids"] = opened_ids
    result["failed_full_text_ids"] = failed_ids
    result["pending_full_text_ids"] = [
        str(ref) for ref in result.get("pending_full_text_ids") or () if str(ref) not in resolved
    ]
    result["omitted_ids"] = _unique((*result.get("omitted_ids", ()), *failed_ids))
    if escalation_batch:
        escalation_opened = [str(ref) for ref in opened if str(ref) in escalation_batch]
        escalation_failed = [str(ref) for ref in failed if str(ref) in escalation_batch]
        result["evidence_escalation_opened_refs"] = _unique(
            (*result.get("evidence_escalation_opened_refs", ()), *escalation_opened)
        )
        result["evidence_escalation_failed_refs"] = _unique(
            (*result.get("evidence_escalation_failed_refs", ()), *escalation_failed)
        )
        result["evidence_escalation_pending_refs"] = [
            str(ref)
            for ref in result.get("evidence_escalation_pending_refs") or ()
            if str(ref) not in escalation_batch
        ]
        result["evidence_escalation_reassess_refs"] = _unique(
            (*result.get("evidence_escalation_reassess_refs", ()), *escalation_opened)
        )
        result["needs_evidence_reassessment"] = bool(escalation_opened)
        if not escalation_opened:
            result["context_selection_done"] = True
            result["discovery_actions"] = list(
                result.get("deferred_discovery_actions") or ()
            )
        result["deferred_discovery_actions"] = []
    if list(batch):
        result["full_read_batches"] = [
            *list(result.get("full_read_batches") or ()),
            _unique(batch),
        ]
    required = set(str(ref) for ref in result.get("required_full_text_ids") or ())
    v2_partial = (
        str(result.get("schema") or "") == MATERIAL_PLAN_SCHEMA_V2
        and (
            bool(result["omitted_ids"])
            or any(
                bool(item.get("blocks_ready"))
                for item in result.get("gaps") or ()
                if isinstance(item, Mapping)
            )
            or bool(result.get("selector_failure"))
        )
    )
    result["coverage"] = (
        "partial" if required & set(result["omitted_ids"]) or v2_partial else "complete"
    )
    return result


__all__ = [
    "CANDIDATE_ENVELOPE_SCHEMA",
    "CandidateEnvelope",
    "FULL_READ_BATCH_SIZE",
    "MATERIAL_PLAN_SCHEMA",
    "MATERIAL_PLAN_SCHEMA_V2",
    "MAX_CANDIDATE_REGISTRY",
    "MAX_PLANNER_CANDIDATES",
    "canonical_candidate_ref",
    "card_eligibility",
    "citation_path_for_ref",
    "compile_material_plan",
    "empty_material_plan",
    "merge_material_plan",
    "next_evidence_escalation_batch",
    "next_full_read_batch",
    "normalize_candidate",
    "normalize_candidates",
    "record_full_read_results",
    "schedule_evidence_escalation",
    "schedule_matched_evidence_recall_probes",
    "schedule_selected_evidence_reassessment",
    "saturated_sources",
]
