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
    raw_semantic_rank_score = candidate.get("semantic_rank_score")
    try:
        semantic_rank_score = (
            float(raw_semantic_rank_score)
            if raw_semantic_rank_score is not None
            else semantic_score
        )
    except (TypeError, ValueError):
        semantic_rank_score = semantic_score
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
        # Retrieval provenance survives later authoritative-card hydration.
        # `semantic_score` describes this input row's origin, while the rank
        # score is an immutable recall feature of the candidate identity.
        "semantic_rank_score": semantic_rank_score,
        "search_enriched": bool(
            candidate.get("search_enriched")
            or semantic_rank_score is not None
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
                    previous.get("search_enriched")
                    or candidate.get("search_enriched")
                    or previous.get("semantic_rank_score") is not None
                    or candidate.get("semantic_rank_score") is not None
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
        "finite_source_recovery_refs": [],
        "semantic_card_recovery_refs": [],
        "precision_full_text_shortlist_refs": [],
        "precision_shortlist_verification_refs": [],
        "precision_shortlist_recovery_refs": [],
        # Once the post-read owner has produced validated edges and the
        # deterministic assembler has committed membership, later planner or
        # materialization passes may not add a new evidence ref implicitly.
        "membership_locked_refs": [],
        "membership_locked": False,
        "membership_boundary_violations": [],
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
    locked_refs = {
        canonical_candidate_ref(str(ref))
        for ref in prior.get("membership_locked_refs") or ()
        if str(ref)
    }
    membership_locked = bool(prior.get("membership_locked"))
    boundary_violations = list(prior.get("membership_boundary_violations") or ())
    for item in assessments:
        ref = canonical_candidate_ref(str(item.get("ref") or ""))
        if ref and ref in candidate_map:
            normalized = {**dict(item), "ref": ref}
            if (
                membership_locked
                and ref not in locked_refs
                and str(normalized.get("relevance") or "irrelevant")
                != "irrelevant"
            ):
                boundary_violations.append(ref)
                normalized.update(
                    {
                        "relevance": "irrelevant",
                        "role": "none",
                        "resolution": "none",
                        "reason_code": "membership_locked",
                        "runtime_override": "post_read_membership_boundary",
                    }
                )
            elif (
                membership_locked
                and ref in locked_refs
                and str(normalized.get("relevance") or "irrelevant")
                == "irrelevant"
                and str((assessment_map.get(ref) or {}).get("relevance") or "")
                in {"direct", "supporting"}
            ):
                boundary_violations.append(ref)
                normalized = {
                    **assessment_map[ref],
                    "runtime_override": "post_read_membership_boundary",
                }
            assessment_map[ref] = normalized

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
        "membership_locked_refs": sorted(locked_refs),
        "membership_locked": membership_locked,
        "membership_boundary_violations": _unique(boundary_violations),
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
    # `max_objects` is the final pack cardinality. A finite comparison may
    # request a larger immutable read cohort so post-read can choose the one
    # self-contained record without making retrieval itself one-shot.
    contract_selection_mode = str((contract or {}).get("selection_mode") or "")
    configured_read_max = max(
        0, int((contract or {}).get("read_cohort_max_objects") or 0)
    )
    deep_read_capacity = max(
        0,
        int(((contract or {}).get("budgets") or {}).get("deep_reads") or 0),
    )
    # Composition answers need a recall cohort larger than their final pack:
    # lossy cards cannot be allowed to decide which full-text rows are never
    # opened. The cohort is still bounded by the existing deep-read budget;
    # membership remains constrained by max_objects below the post-read owner.
    if contract_selection_mode in {
        "composition",
        "cross_record_comparison",
        "cross_record_inventory",
    }:
        configured_read_max = max(configured_read_max, deep_read_capacity)
    read_max_objects = max(max(0, int(max_objects)), configured_read_max)
    source_order = {
        str(source.get("source_id") or ""): position
        for position, source in enumerate(contract.get("source_requirements") or ())
        if isinstance(source, Mapping) and str(source.get("source_id") or "")
    }
    source_deep_read_limits = {
        source_id: max(0, int((requirement.get("budget") or {}).get("deep_reads")))
        for source_id, requirement in requirements.items()
        if (requirement.get("budget") or {}).get("deep_reads") is not None
    }
    # Recall cohorts are admission decisions, not final membership. Once a
    # candidate is in this immutable full-text cohort, a per-source planner
    # allowance must not evict it before reading. The shared object/character
    # budgets remain authoritative and still bound the cohort.
    recall_full_text_refs = {
        canonical_candidate_ref(str(ref))
        for ref in plan.get("precision_full_text_shortlist_refs") or ()
        if str(ref)
    }
    protected_full_text_refs = {
        canonical_candidate_ref(str(ref))
        for ref in (
            *(plan.get("precision_full_text_shortlist_refs") or ()),
            *(plan.get("required_full_text_ids") or ()),
        )
        if str(ref)
    }
    for ref, candidate in candidate_map.items():
        assessment = assessment_map.get(ref)
        exact_target = str(candidate.get("origin") or "") == "exact_target"
        recall_admission = bool(
            not plan.get("membership_locked")
            and ref in recall_full_text_refs
        )
        if recall_admission and (
            assessment is None
            or str(assessment.get("relevance") or "irrelevant")
            not in {"direct", "supporting"}
        ):
            # The card stage owns only bounded recall. Admit its shortlist to
            # the read queue even when the card classifier was negative; the
            # post-read owner will decide final membership from opened text.
            assessment = {
                "ref": ref,
                "relevance": "supporting",
                "resolution": "full_text",
                "reason_code": "recall_cohort_full_read",
                "selection_source": "deterministic_recall_cohort",
                "confidence": 1.0,
            }
            trace.append(
                {"ref": ref, "kind": "recall_cohort_full_read_admission"}
            )
        elif assessment is None:
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
        catalog_positions = [
            (
                source_order.get(source_id, 1_000_000),
                int(membership.get("position") or 0),
            )
            for membership in candidate.get("catalog_window_memberships") or ()
            if isinstance(membership, Mapping)
            for source_id in [str(membership.get("source_requirement_id") or "")]
            if str(requirements.get(source_id, {}).get("discovery_mode") or "")
            == "catalog_window"
            and int(membership.get("position") or 0) > 0
        ]
        ordered_observation = min(catalog_positions) if catalog_positions else None
        priority = (
            0
            if exact_target
            else 1
            if ordered_observation is not None
            else 2
            if relevance == "direct" and required_source
            else 3
            if relevance == "direct"
            else 4,
            ordered_observation[0] if ordered_observation is not None else 1_000_000,
            ordered_observation[1] if ordered_observation is not None else 1_000_000,
            int(candidate.get("inclusion_priority") or 50),
            -float(assessment.get("confidence") or 0.0),
            ref,
        )
        if ordered_observation is not None:
            queue_item["ordered_observation_priority"] = True
        selected.append((priority, queue_item))

    selected.sort(key=lambda item: item[0])
    full_text_count = sum(
        item["effective_fidelity"] != "semantic_card" for _priority, item in selected
    )
    # Reserve against the bounded cohort capacity, not only the candidates
    # currently visible to the compiler. Otherwise an early long row consumes
    # the budget that a later short recall candidate needs before post-read can
    # classify it. This remains a reservation cap; actual short rows use their
    # smaller estimate and the total character budget stays authoritative.
    reservation_count = max(full_text_count, read_max_objects)
    fair_full_text_reservation = (
        max(
            1,
            min(
                DEFAULT_FULL_TEXT_RESERVATION_CHARS,
                max(0, int(max_full_text_chars)) // reservation_count,
            ),
        )
        if reservation_count
        else 0
    )
    if max(0, int(max_full_text_chars)) >= reservation_count * MIN_FULL_TEXT_RESERVATION_CHARS:
        fair_full_text_reservation = max(
            MIN_FULL_TEXT_RESERVATION_CHARS, fair_full_text_reservation
        )
    queue: list[dict[str, Any]] = []
    omitted = list(plan.get("omitted_ids") or ())
    used_full = 0
    used_cards = 0
    source_deep_reads_used = {source_id: 0 for source_id in source_deep_read_limits}
    for _priority, item in selected:
        fidelity = str(item["effective_fidelity"])
        read_budget_source_id = ""
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
        if fidelity != "semantic_card":
            bounded_source_ids = sorted(
                (
                    source_id
                    for source_id in item.get("source_requirement_ids") or ()
                    if source_id in source_deep_read_limits
                ),
                key=lambda source_id: (source_order.get(source_id, 1_000_000), source_id),
            )
            unbounded_source_ids = [
                source_id
                for source_id in item.get("source_requirement_ids") or ()
                if source_id not in source_deep_read_limits
            ]
            if bounded_source_ids and not unbounded_source_ids and str(item["ref"]) not in protected_full_text_refs:
                read_budget_source_id = next(
                    (
                        source_id
                        for source_id in bounded_source_ids
                        if source_deep_reads_used[source_id]
                        < source_deep_read_limits[source_id]
                    ),
                    "",
                )
                if not read_budget_source_id:
                    reason = "source_deep_read_budget"
            if read_budget_source_id:
                item["read_budget_source_id"] = read_budget_source_id
        if not reason and len(queue) >= read_max_objects:
            reason = "object_budget"
        elif not reason and fidelity == "semantic_card" and used_cards + estimate > max(0, int(max_card_chars)):
            reason = "card_char_budget"
        elif not reason and fidelity != "semantic_card" and used_full + estimate > max(0, int(max_full_text_chars)):
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
            if read_budget_source_id:
                source_deep_reads_used[read_budget_source_id] += 1

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
            "read_max_objects": read_max_objects,
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


def _is_decision_input_task(contract: Mapping[str, Any]) -> bool:
    profile = str(contract.get("task_profile") or "")
    answer_shape = contract.get("answer_shape") or {}
    finite_inventory = (
        isinstance(answer_shape, Mapping)
        and str(answer_shape.get("kind") or "") == "inventory"
        and type(answer_shape.get("expected_member_count")) is int
        and int(answer_shape["expected_member_count"]) > 0
    )
    if finite_inventory:
        return False
    if profile == "recommendation":
        return True
    if any(
        isinstance(source, Mapping)
        and str(source.get("discovery_mode") or "") == "catalog_window"
        for source in contract.get("source_requirements") or ()
    ):
        return True
    return bool(
        str(contract.get("selection_mode") or "")
        in {"composition", "cross_record_comparison"}
        and isinstance(answer_shape, Mapping)
        and str(answer_shape.get("kind") or "") == "freeform"
        and len(contract.get("answer_obligations") or ()) > 1
    )


def schedule_matched_evidence_recall_probes(
    plan: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    deep_reads_remaining: int,
    size: int = FULL_READ_BATCH_SIZE,
) -> dict[str, Any]:
    """Use spare read budget to verify bounded query-conditioned false negatives."""

    result = {**empty_material_plan(), **dict(plan)}
    if (
        deep_reads_remaining <= 0
        or result.get("matched_evidence_recall_refs")
        or result.get("finite_source_recovery_refs")
        or result.get("finite_topical_recall_refs")
        or result.get("semantic_card_recovery_refs")
    ):
        return result
    positive_refs = {
        canonical_candidate_ref(str(item.get("ref") or ""))
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping)
        and str(item.get("relevance") or "") in {"direct", "supporting"}
    }
    selected_material_refs = _unique(
        (
            *result.get("required_full_text_ids", ()),
            *result.get("optional_full_text_ids", ()),
            *(
                result.get("card_ids", ())
                if result.get("precision_full_text_shortlist_refs")
                else ()
            ),
        )
    )
    selected_full_refs = set(selected_material_refs) & positive_refs
    answer_shape = contract.get("answer_shape") or {}
    finite_inventory = (
        isinstance(answer_shape, Mapping)
        and str(answer_shape.get("kind") or "") == "inventory"
        and type(answer_shape.get("expected_member_count")) is int
        and int(answer_shape["expected_member_count"]) > 0
    )
    if not selected_full_refs:
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
    disposition_by_source = {
        str(item.get("source_id") or ""): str(item.get("status") or "")
        for item in result.get("source_dispositions") or ()
        if isinstance(item, Mapping) and item.get("source_id")
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
    pending_count = len(
        {
            canonical_candidate_ref(str(ref))
            for ref in result.get("pending_full_text_ids") or ()
        if str(ref)
        }
    )
    decision_profile = _is_decision_input_task(contract)
    raw_answer_requirements = [
        item
        for item in contract.get("evidence_requirements") or ()
        if isinstance(item, Mapping)
    ]
    if not raw_answer_requirements:
        raw_answer_requirements = [
            item
            for source in contract.get("source_requirements") or ()
            if isinstance(source, Mapping)
            for item in source.get("evidence_requirements") or ()
            if isinstance(item, Mapping)
        ]
    answer_requirement_ids = {
        str(item.get("requirement_id") or "")
        for item in raw_answer_requirements
        if str(item.get("requirement_id") or "")
    }
    answer_shape = contract.get("answer_shape") or {}
    finite_topical_profile = (
        str(contract.get("task_profile") or "") == "topical_answer"
        and not (
            isinstance(answer_shape, Mapping)
            and str(answer_shape.get("kind") or "") == "inventory"
        )
        and len(answer_requirement_ids) > 1
    )
    available_reads = max(0, deep_reads_remaining - pending_count)
    capacity = available_reads if decision_profile else min(size, available_reads)
    if capacity <= 0:
        return result

    assessment_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    candidates = [
        dict(candidate)
        for candidate in result.get("candidates") or ()
        if isinstance(candidate, Mapping)
        and canonical_candidate_ref(str(candidate.get("ref") or "")).startswith(
            ("note:", "post:")
        )
        and "full_text" in set(candidate.get("available_fidelity") or ())
    ]

    # Card precision may identify several plausible rows for the same atomic
    # obligation even though the deterministic assembler selects only one card.
    # Open the bounded runner-up cohort as probes; only the later opened-evidence
    # reassessment can admit them into the final materialization queue.
    source_limits = {
        str(source.get("source_id") or ""): max(
            0, int((source.get("budget") or {}).get("deep_reads"))
        )
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
        and source.get("source_id")
        and (source.get("budget") or {}).get("deep_reads") is not None
    }
    candidate_by_ref = {
        canonical_candidate_ref(str(candidate.get("ref") or "")): candidate
        for candidate in candidates
    }
    source_reserved = {source_id: 0 for source_id in source_limits}
    for ref in unavailable:
        candidate = candidate_by_ref.get(ref)
        if candidate is None:
            continue
        for source_id in _candidate_source_ids(candidate):
            if source_id in source_reserved:
                source_reserved[source_id] += 1
    precision_verification_refs: list[str] = []
    precision_recovery_refs: list[str] = []
    precision_shortlist_refs = _unique(
        canonical_candidate_ref(str(raw_ref))
        for raw_ref in result.get("precision_full_text_shortlist_refs") or ()
        if str(raw_ref)
    )
    for ref in precision_shortlist_refs:
        if len(precision_verification_refs) >= capacity:
            break
        candidate = candidate_by_ref.get(ref)
        if candidate is None or ref in unavailable:
            continue
        bounded_sources = [
            source_id
            for source_id in _candidate_source_ids(candidate)
            if source_id in source_limits
        ]
        if bounded_sources and all(
            source_reserved[source_id] >= source_limits[source_id]
            for source_id in bounded_sources
        ):
            continue
        precision_verification_refs.append(ref)
        if ref not in positive_refs:
            precision_recovery_refs.append(ref)
        unavailable.add(ref)
        for source_id in bounded_sources:
            if source_reserved[source_id] < source_limits[source_id]:
                source_reserved[source_id] += 1
                break
    capacity -= len(precision_verification_refs)

    # A valid card-recall adjudication owns the bounded read cohort. Generic
    # recovery heuristics below must not spend spare budget on rows that this
    # recall pass explicitly rejected; only the post-read classifier may make
    # the final membership decision for the shortlisted full texts.
    if precision_shortlist_refs:
        capacity = 0

    # A finite topical comparison can expose an unranked catalog card whose
    # lossy projection is insufficient but whose query-conditioned chunk is a
    # strong navigation hit. Spend only spare global reads on a bounded pair of
    # those rows, then let full-text reassessment decide final inclusion.
    finite_topical_recovery_refs: list[str] = []
    if finite_topical_profile and capacity > 0 and len(selected_full_refs) > 1:
        topical_rows: list[tuple[int, float, int, str]] = []
        for candidate_position, candidate in enumerate(candidates):
            ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
            assessment = assessment_by_ref.get(ref, {})
            if (
                ref in unavailable
                or str(candidate.get("origin") or "") != "authoritative_catalog"
                or str(assessment.get("relevance") or "") != "irrelevant"
                or str(assessment.get("reason_code") or "") != "search_more"
                or candidate.get("matched_evidence_rank") is None
            ):
                continue
            topical_rows.append(
                (
                    int(candidate.get("inclusion_priority") or 50),
                    -float(candidate.get("semantic_rank_score") or 0.0),
                    candidate_position,
                    ref,
                )
            )
        topical_rows.sort()
        finite_topical_recovery_refs = _unique(
            row[-1] for row in topical_rows[: min(2, capacity)]
        )
        capacity -= len(finite_topical_recovery_refs)
        unavailable.update(finite_topical_recovery_refs)

    # A complete decision-source catalog that fits its own typed read budget
    # is a bounded false-negative cohort. Use only otherwise spare global reads
    # to let the existing batched reassessment compare its rejected cards in
    # full; opening a row never selects it for final context.
    finite_recovery_rows: list[tuple[int, int, int, int, float, str]] = []
    for source_position, requirement in enumerate(
        contract.get("source_requirements") or ()
    ):
        if not isinstance(requirement, Mapping):
            continue
        source_id = str(requirement.get("source_id") or "")
        raw_source_limit = (requirement.get("budget") or {}).get("deep_reads")
        evidence_required = (
            str(requirement.get("evidence_obligation") or "") == "required"
            or bool(requirement.get("required"))
        )
        bounded_catalog_window = (
            str(requirement.get("discovery_mode") or "") == "catalog_window"
            and disposition_by_source.get(source_id) in {"selected", "search_more"}
        )
        requested_window_reassessment = (
            bounded_catalog_window
            and disposition_by_source.get(source_id) == "search_more"
        )
        selected_window_reassessment = (
            bounded_catalog_window
            and disposition_by_source.get(source_id) == "selected"
        )
        requested_semantic_reassessment = (
            str(requirement.get("discovery_mode") or "")
            == "semantic_relevance"
            and any(
                str(assessment_by_ref.get(ref, {}).get("reason_code") or "")
                == "search_more"
                for ref in {
                    canonical_candidate_ref(str(candidate.get("ref") or ""))
                    for candidate in candidates
                    if source_id in _candidate_source_ids(candidate)
                }
            )
        )
        if (
            not decision_profile
            or not source_id
            or not evidence_required
            or (
                str(requirement.get("coverage") or "") != "complete"
                and not bounded_catalog_window
                and not requested_semantic_reassessment
            )
            or raw_source_limit is None
        ):
            continue
        try:
            source_limit = max(0, int(raw_source_limit))
        except (TypeError, ValueError):
            continue
        source_candidates = [
            candidate
            for candidate in candidates
            if source_id in _candidate_source_ids(candidate)
        ]
        source_refs = {
            canonical_candidate_ref(str(candidate.get("ref") or ""))
            for candidate in source_candidates
        }
        source_selected_count = len(source_refs & selected_full_refs)
        source_spare = max(0, source_limit - source_selected_count)
        if requested_semantic_reassessment:
            source_spare = min(source_spare, 1)
        if (
            not source_candidates
            or (
                not requested_semantic_reassessment
                and len(source_candidates) > source_limit
            )
            or (
                not (source_refs & selected_full_refs)
                and not requested_window_reassessment
            )
            or source_spare <= 0
        ):
            continue
        source_recovery_rows: list[tuple[int, int, int, int, float, str]] = []
        for candidate in source_candidates:
            ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
            if (
                ref in unavailable
                or str(assessment_by_ref.get(ref, {}).get("relevance") or "")
                != "irrelevant"
                or (
                    (
                        requested_window_reassessment
                        or requested_semantic_reassessment
                        or (
                            bounded_catalog_window
                            and not selected_window_reassessment
                            and str(requirement.get("coverage") or "")
                            != "complete"
                        )
                    )
                    and str(
                        assessment_by_ref.get(ref, {}).get("reason_code") or ""
                    )
                    != "search_more"
                )
            ):
                continue
            catalog_positions = [
                int(item.get("position") or 0)
                for item in candidate.get("catalog_window_memberships") or ()
                if isinstance(item, Mapping)
                and str(item.get("source_requirement_id") or "") == source_id
                and int(item.get("position") or 0) > 0
            ]
            source_recovery_rows.append(
                (
                    source_position,
                    min(catalog_positions) if catalog_positions else 1_000_000,
                    int(candidate.get("matched_evidence_rank") or 1_000_000),
                    int(candidate.get("inclusion_priority") or 50),
                    -float(candidate.get("semantic_rank_score") or 0.0),
                    ref,
                )
            )
        source_recovery_rows.sort()
        finite_recovery_rows.extend(source_recovery_rows[:source_spare])
    finite_recovery_rows.sort()
    finite_recovery_refs = _unique(
        row[-1] for row in finite_recovery_rows[:capacity]
    )
    capacity -= len(finite_recovery_refs)
    unavailable.update(finite_recovery_refs)

    unresolved_decision_sources = {
        source_id
        for source_id in required_sources
        if disposition_by_source.get(source_id)
        in {"no_relevant_candidate", "search_more", "ambiguous"}
        and not any(
            source_id in _candidate_source_ids(candidate)
            and canonical_candidate_ref(str(candidate.get("ref") or ""))
            in selected_full_refs
            for candidate in candidates
        )
    }
    selected_source_ids = {
        source_id
        for candidate in candidates
        if canonical_candidate_ref(str(candidate.get("ref") or ""))
        in selected_full_refs
        for source_id in _candidate_source_ids(candidate)
    }

    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
        candidate_source_ids = set(_candidate_source_ids(candidate))
        if (
            not ref.startswith(("note:", "post:"))
            or ref in unavailable
            or candidate.get("matched_evidence_rank") is None
            or "full_text" not in set(candidate.get("available_fidelity") or ())
            or not (required_sources & candidate_source_ids)
            or (
                finite_inventory
                and not (selected_source_ids & candidate_source_ids)
            )
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
    probe_refs = (
        _unique(
            canonical_candidate_ref(str(candidate.get("ref") or ""))
            for candidate in ranked[:capacity]
        )
        if (finite_inventory or not unresolved_decision_sources)
        and (len(selected_full_refs) > 1 or finite_inventory)
        else []
    )
    capacity -= len(probe_refs)
    unavailable.update(probe_refs)

    # Full-text verification can overturn a card-level false positive only for
    # rows that were opened. When several primary selections leave spare read
    # budget, admit one strongest rejected semantic card into that same batched
    # reassessment. Opening is not selection: the reasoner still has to prove
    # the row from full text, and a single primary selection never expands.
    semantic_recovery_rows: list[tuple[int, float, str]] = []
    if capacity > 0 and len(selected_full_refs) > 1:
        for candidate in candidates:
            ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
            semantic_score = candidate.get("semantic_rank_score")
            if semantic_score is None:
                semantic_score = candidate.get("semantic_score")
            if (
                ref in unavailable
                or str(assessment_by_ref.get(ref, {}).get("relevance") or "")
                != "irrelevant"
                or (
                    candidate.get("matched_evidence_rank") is None
                    and semantic_score is None
                )
            ):
                continue
            semantic_recovery_rows.append(
                (
                    int(candidate.get("matched_evidence_rank") or 1_000_000),
                    -float(semantic_score or 0.0),
                    ref,
                )
            )
    semantic_recovery_rows.sort()
    semantic_card_recovery_refs = _unique(
        row[-1] for row in semantic_recovery_rows[: min(1, capacity)]
    )
    scheduled_refs = _unique(
        (
            *precision_verification_refs,
            *precision_recovery_refs,
            *finite_topical_recovery_refs,
            *finite_recovery_refs,
            *probe_refs,
            *semantic_card_recovery_refs,
        )
    )
    if not scheduled_refs:
        return result
    result["finite_source_recovery_refs"] = finite_recovery_refs
    result["finite_topical_recall_refs"] = finite_topical_recovery_refs
    result["matched_evidence_recall_refs"] = probe_refs
    result["semantic_card_recovery_refs"] = semantic_card_recovery_refs
    result["precision_shortlist_verification_refs"] = precision_verification_refs
    result["precision_shortlist_recovery_refs"] = precision_recovery_refs
    result["optional_full_text_ids"] = _unique(
        (*result.get("optional_full_text_ids", ()), *scheduled_refs)
    )
    result["pending_full_text_ids"] = _unique(
        (*result.get("pending_full_text_ids", ()), *scheduled_refs)
    )
    result["context_selection_done"] = False
    result["runtime_trace"] = [
        *list(result.get("runtime_trace") or ()),
        {
            "kind": "matched_evidence_recall_scheduled",
            "refs": scheduled_refs,
            "selected_refs": sorted(selected_full_refs),
            "finite_source_recovery_refs": finite_recovery_refs,
            "matched_evidence_recall_refs": probe_refs,
            "semantic_card_recovery_refs": semantic_card_recovery_refs,
            "precision_shortlist_verification_refs": precision_verification_refs,
            "precision_shortlist_recovery_refs": precision_recovery_refs,
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
    decision_input_mode = _is_decision_input_task(contract)
    pending_full_text_count = len(
        {
            canonical_candidate_ref(str(ref))
            for ref in result.get("pending_full_text_ids") or ()
            if str(ref)
        }
    )
    # Ordinary factual retrieval should finish selected full text before
    # probing another corpus. A decision-input task instead needs one joint
    # read batch so the single reassessment can compare selected premises with
    # reasoner-requested rows from every unresolved required source.
    if pending_full_text_count and not decision_input_mode:
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
    assessment_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in result.get("assessments") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    candidate_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in result.get("candidates") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    queue_by_ref = {
        canonical_candidate_ref(str(item.get("ref") or "")): dict(item)
        for item in result.get("materialization_queue") or ()
        if isinstance(item, Mapping) and item.get("ref")
    }
    positive_source_ids = {
        source_id
        for candidate in result.get("candidates") or ()
        if isinstance(candidate, Mapping)
        and str(
            assessment_by_ref.get(
                canonical_candidate_ref(str(candidate.get("ref") or "")), {}
            ).get("relevance")
            or ""
        )
        in {"direct", "supporting"}
        for source_id in _candidate_source_ids(candidate)
    }
    unresolved_sources = [
        source_id
        for source_id, status in disposition_by_source.items()
        if (
            status in {"no_relevant_candidate", "search_more", "ambiguous"}
            or (status == "selected" and source_id not in positive_source_ids)
        )
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
    source_read_limits = {
        source_id: max(0, int((requirement.get("budget") or {}).get("deep_reads")))
        for source_id, requirement in requirements.items()
        if (requirement.get("budget") or {}).get("deep_reads") is not None
    }
    source_reads_reserved = {source_id: 0 for source_id in source_read_limits}
    selected_input_refs: list[str] = []
    if decision_input_mode:
        recall_priority_refs = (
            result.get("precision_full_text_shortlist_refs") or ()
            if int(
                result.get("precision_full_text_shortlist_obligation_count") or 0
            )
            >= 4
            else ()
        )
        ordered_positive_refs = _unique(
            (
                *(
                    canonical_candidate_ref(str(ref))
                    for ref in recall_priority_refs
                    if str(ref)
                ),
                *(
                    canonical_candidate_ref(str(item.get("ref") or ""))
                    for item in result.get("queue") or ()
                    if isinstance(item, Mapping) and item.get("ref")
                ),
                *(
                    canonical_candidate_ref(str(item.get("ref") or ""))
                    for item in result.get("candidates") or ()
                    if isinstance(item, Mapping) and item.get("ref")
                ),
            )
        )
        opened_or_failed = {
            canonical_candidate_ref(str(ref))
            for ref in (
                *result.get("opened_full_text_ids", ()),
                *result.get("failed_full_text_ids", ()),
            )
            if str(ref)
        }
        for ref in ordered_positive_refs:
            candidate = candidate_by_ref.get(ref, {})
            if (
                len(selected_input_refs) >= deep_reads_remaining
                or ref in opened_or_failed
                or not ref.startswith(("note:", "post:"))
                or str(queue_by_ref.get(ref, {}).get("effective_fidelity") or "")
                == "semantic_card"
                or "full_text" not in set(candidate.get("available_fidelity") or ())
                or str(assessment_by_ref.get(ref, {}).get("relevance") or "")
                not in {"direct", "supporting"}
            ):
                continue
            bounded_sources = [
                source_id
                for source_id in _candidate_source_ids(candidate)
                if source_id in source_read_limits
            ]
            reserved_source = next(
                (
                    source_id
                    for source_id in bounded_sources
                    if source_reads_reserved[source_id] < source_read_limits[source_id]
                ),
                "",
            )
            if bounded_sources and not reserved_source:
                continue
            selected_input_refs.append(ref)
            if reserved_source:
                source_reads_reserved[reserved_source] += 1

    available_reads = max(0, deep_reads_remaining - len(selected_input_refs))
    if not unresolved_sources and not selected_input_refs:
        return result, []

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
    decision_input_rows: list[tuple[dict[str, Any], str, int]] = []
    used_source_probe = False
    if decision_input_mode:
        for source_id in unresolved_sources:
            ranked_for_source: list[tuple[dict[str, Any], str, int]] = []
            requested_refs = {
                canonical_candidate_ref(str(candidate.get("ref") or ""))
                for candidate in queues.get(source_id, ())
                if str(
                    assessment_by_ref.get(
                        canonical_candidate_ref(str(candidate.get("ref") or "")),
                        {},
                    ).get("reason_code")
                    or ""
                )
                == "search_more"
            }
            if not requested_refs:
                used_source_probe = True
            for candidate in queues.get(source_id, ()):
                ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
                if requested_refs and ref not in requested_refs:
                    continue
                positions = [
                    int(item.get("position") or 0)
                    for item in candidate.get("catalog_window_memberships") or ()
                    if isinstance(item, Mapping)
                    and str(item.get("source_requirement_id") or "") == source_id
                    and int(item.get("position") or 0) > 0
                ]
                ranked_for_source.append(
                    (
                        dict(candidate),
                        source_id,
                        min(positions) if positions else 1_000_000,
                    )
                )
            ranked_for_source.sort(
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
            source_limit = max(
                0,
                source_limit - source_reads_reserved.get(source_id, 0),
            )
            decision_input_rows.extend(ranked_for_source[:source_limit])

    if decision_input_rows:
        # Preserve typed-source order, each source's own read budget and any
        # source-local window order. search_more rows take precedence within a
        # source; an all-negative card pass still needs one bounded source-local
        # evidence batch before absence is verified. The single opened-evidence
        # reassessment remains the semantic selector.
        decision_input_rows.sort(
            key=lambda item: (
                source_order.get(item[1], 1_000_000),
                item[2],
                int(item[0].get("matched_evidence_rank") or 1_000_000),
                str(item[0].get("ref") or ""),
            )
        )
        ranked = [(candidate, source_id) for candidate, source_id, _ in decision_input_rows]
        target_count = min(available_reads, len(ranked))
        escalation_strategy = (
            "bounded_per_source_decision_input_evidence"
            if used_source_probe
            else "reasoner_requested_decision_input_evidence"
        )
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
        target_count = min(size, available_reads)
        escalation_strategy = (
            "selected_decision_input_evidence"
            if selected_input_refs and not ranked
            else "ranked_negative_evidence"
        )
    selected: list[str] = list(selected_input_refs)
    selected_sources: list[str] = []
    recovery_count = 0
    for candidate, source_id in ranked:
        if recovery_count >= target_count:
            break
        ref = canonical_candidate_ref(str(candidate.get("ref") or ""))
        if not ref or ref in selected:
            continue
        selected.append(ref)
        selected_sources.append(source_id)
        recovery_count += 1
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
            "selected_input_refs": selected_input_refs,
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
        and item.get("strategy")
        in {
            "reasoner_requested_decision_input_evidence",
            "bounded_per_source_decision_input_evidence",
            "selected_decision_input_evidence",
        }
        for item in reversed(list(plan.get("runtime_trace") or ()))
    ):
        return _unique((*plan.get("pending_full_text_ids", ()), *pending))
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
            for item in (
                *result.get("finite_source_recovery_refs", ()),
                *result.get("matched_evidence_recall_refs", ()),
                *result.get("semantic_card_recovery_refs", ()),
                *result.get("precision_shortlist_recovery_refs", ()),
            )
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
