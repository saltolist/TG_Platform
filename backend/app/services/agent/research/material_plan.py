"""Durable candidate assessment and evidence-resolution state."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.ai.semantic_summary import DISCOVERY_SUMMARY_VERSION


MATERIAL_PLAN_SCHEMA = "workspace.material-plan/v1"
MAX_PLANNER_CANDIDATES = 16
FULL_READ_BATCH_SIZE = 3


def canonical_candidate_ref(value: str) -> str:
    raw = str(value or "").strip().strip("/")
    if raw.startswith("note:"):
        return f"note:{raw.split(':')[-1]}"
    if raw.startswith("post:"):
        return f"post:{raw.split(':')[-1]}"
    parts = raw.split("/")
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


def normalize_candidate(
    candidate: Mapping[str, Any],
    *,
    scope: str = "global",
) -> dict[str, Any] | None:
    ref = canonical_candidate_ref(str(candidate.get("ref") or candidate.get("label") or ""))
    kind, _, object_id = ref.partition(":")
    if kind not in {"note", "post"} or not object_id:
        return None
    index_revision = int(candidate.get("index_revision") or 0)
    source_revision = int(candidate.get("source_revision") or 0)
    summary_model = str(candidate.get("summary_model") or "")
    parent_post_id = str(candidate.get("parent_post_id") or "")
    citation_path = str(candidate.get("citation_path") or "")
    if not citation_path and kind == "note" and parent_post_id:
        citation_path = f"/note/post/{parent_post_id}/{object_id}/"
    envelope = {
        "ref": ref,
        "kind": kind,
        "title": str(candidate.get("title") or candidate.get("label") or ref)[:240],
        "card_text": str(
            candidate.get("card_text")
            or candidate.get("preview")
            or candidate.get("chunk_text")
            or ""
        )[:480],
        "score": float(candidate.get("score") or candidate.get("similarity") or 0.0),
        "source_requirement_id": str(candidate.get("source_requirement_id") or ""),
        "index_revision": index_revision,
        "source_revision": source_revision,
        "summary_version": int(candidate.get("summary_version") or 0),
        "summary_model": summary_model,
        "card_origin": card_origin(summary_model),
        "status": str(candidate.get("status") or "active"),
        "parent_post_id": parent_post_id or None,
        "citation_path": citation_path or citation_path_for_ref(ref, scope=scope),
        "has_more": bool(candidate.get("has_more")),
    }
    eligible, failure = card_eligibility(envelope)
    envelope["card_eligible"] = eligible
    envelope["card_eligibility_failure"] = failure
    return envelope


def normalize_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    scope: str = "global",
    limit: int = MAX_PLANNER_CANDIDATES,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = normalize_candidate(raw, scope=scope)
        if candidate is None or candidate["ref"] in seen:
            continue
        seen.add(candidate["ref"])
        normalized.append(candidate)
        if len(normalized) >= limit:
            break
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
        "needs_expansion_assessment": False,
        "coverage": "complete",
        "full_read_batches": [],
        "card_eligibility_failures": {},
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


def next_full_read_batch(plan: Mapping[str, Any], *, size: int = FULL_READ_BATCH_SIZE) -> list[str]:
    pending = set(str(item) for item in plan.get("pending_full_text_ids") or ())
    ordered = [
        *[str(item) for item in plan.get("required_full_text_ids") or ()],
        *[str(item) for item in plan.get("optional_full_text_ids") or ()],
    ]
    return [ref for ref in _unique(ordered) if ref in pending][: max(1, min(size, 3))]


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
    opened_ids = _unique((*result.get("opened_full_text_ids", ()), *opened))
    failed_ids = _unique((*result.get("failed_full_text_ids", ()), *failed))
    resolved = set((*opened_ids, *failed_ids))
    result["opened_full_text_ids"] = opened_ids
    result["failed_full_text_ids"] = failed_ids
    result["pending_full_text_ids"] = [
        str(ref) for ref in result.get("pending_full_text_ids") or () if str(ref) not in resolved
    ]
    result["omitted_ids"] = _unique((*result.get("omitted_ids", ()), *failed_ids))
    if list(batch):
        result["full_read_batches"] = [
            *list(result.get("full_read_batches") or ()),
            _unique(batch),
        ]
    required = set(str(ref) for ref in result.get("required_full_text_ids") or ())
    result["coverage"] = "partial" if required & set(result["omitted_ids"]) else "complete"
    return result


__all__ = [
    "FULL_READ_BATCH_SIZE",
    "MATERIAL_PLAN_SCHEMA",
    "MAX_PLANNER_CANDIDATES",
    "canonical_candidate_ref",
    "card_eligibility",
    "citation_path_for_ref",
    "empty_material_plan",
    "merge_material_plan",
    "next_full_read_batch",
    "normalize_candidate",
    "normalize_candidates",
    "record_full_read_results",
    "saturated_sources",
]
