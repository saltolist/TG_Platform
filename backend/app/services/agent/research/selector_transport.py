"""Compact, versioned provider transport for the canonical Context Selector."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from app.services.agent.research.planner_decision import ContextSelectorDecision
from app.services.agent.research.trust import neutralize_untrusted
from app.services.ai.rag_json import extract_json_object
from app.services.ai.semantic_summary import SELECTOR_SUMMARY_MAX_CHARS


SELECTOR_TRANSPORT_SCHEMA = "workspace.context-selector-transport/v1"
SELECTOR_TRANSPORT_VERSION = 1

_KIND_CODE = {
    "note": "n",
    "notes": "n",
    "post": "p",
    "posts": "p",
    "file": "f",
    "attachment": "a",
    "media": "m",
    "analytics": "x",
}
_FIDELITY_CODE = {
    "metadata": "m",
    "catalog": "c",
    "semantic_card": "s",
    "card": "s",
    "text": "t",
    "full_text": "f",
    "vision": "v",
    "analytics": "a",
}
_ORIGIN_CODE = {
    "exact_target": "x",
    "ambient_current_post": "a",
    "dialog_reference": "d",
    "authoritative_catalog": "c",
    "catalog_member": "c",
    "semantic_search": "s",
}
_RELEVANCE = {"d": "direct", "s": "supporting", "i": "irrelevant"}
_ROLE = {"a": "answer_evidence", "n": "none"}
_RESOLUTION = {
    "n": "none",
    "c": "card",
    "f": "full_text",
    "m": "metadata",
    "t": "text",
    "v": "vision",
    "a": "analytics",
}
_REASON = {
    "t": "topic_only",
    "e": "exact_fact",
    "d": "detailed_summary",
    "c": "comparison",
    "q": "quote",
    "u": "edit_source",
    "m": "attachment_or_media",
    "a": "analytics",
    "l": "low_card_quality",
    "x": "unrelated_topic",
    "b": "ambiguous",
    "s": "search_more",
}
_DISPOSITION = {
    "s": "selected",
    "n": "no_relevant_candidate",
    "m": "search_more",
    "a": "ambiguous",
}


@dataclass(frozen=True)
class SelectorTransportMapping:
    candidate_refs: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SelectorTransport:
    payload: dict[str, Any]
    mapping: SelectorTransportMapping

    def render(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


def _source_ids(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value)
            for value in [
                *(candidate.get("source_requirement_ids") or ()),
                candidate.get("source_requirement_id"),
            ]
            if str(value or "")
        )
    )


def encode_selector_transport(
    *,
    question: str,
    dialog_context: str,
    contract: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> SelectorTransport:
    visible_source_ids = {
        source_id for candidate in candidates for source_id in _source_ids(candidate)
    }
    requirements = [
        dict(source)
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
        and str(source.get("source_id") or "") in visible_source_ids
    ]
    source_ids = tuple(str(source.get("source_id") or "") for source in requirements)
    missing_sources = sorted(visible_source_ids - set(source_ids))
    source_ids = (*source_ids, *missing_sources)
    source_index = {source_id: index for index, source_id in enumerate(source_ids)}
    requirements_by_id = {
        str(source.get("source_id") or ""): source for source in requirements
    }

    source_rows: list[list[Any]] = []
    for index, source_id in enumerate(source_ids):
        source = requirements_by_id.get(source_id, {})
        cardinality = source.get("selection_cardinality") or {}
        row: list[Any] = [
            index,
            _KIND_CODE.get(str(source.get("kind") or ""), "u"),
            "r" if str(source.get("evidence_obligation") or "optional") == "required" else "o",
            int(cardinality.get("min") or 0),
            int(cardinality.get("max") or 16),
            _FIDELITY_CODE.get(str(source.get("required_fidelity") or "semantic_card"), "s"),
        ]
        goal = str(source.get("query_goal") or "").strip()
        if goal:
            row.append(goal[:240])
        source_rows.append(row)

    parent_ids: dict[str, int] = {}
    parent_rows: list[list[Any]] = []
    candidate_rows: list[list[Any]] = []
    candidate_refs: list[str] = []
    for index, candidate in enumerate(candidates):
        ref = str(candidate.get("ref") or "")
        candidate_refs.append(ref)
        parent = candidate.get("parent") if isinstance(candidate.get("parent"), Mapping) else None
        parent_index: int | None = None
        if parent:
            parent_ref = str(parent.get("ref") or "")
            if parent_ref:
                parent_index = parent_ids.setdefault(parent_ref, len(parent_ids))
                if parent_index == len(parent_rows):
                    parent_rows.append(
                        [parent_index, _KIND_CODE.get(str(parent.get("kind") or ""), "u")]
                    )
        title = str(candidate.get("title") or "")
        summary = str(candidate.get("selector_summary") or "")[:SELECTOR_SUMMARY_MAX_CHARS]
        data = (
            "<workspace_data>"
            + neutralize_untrusted(title)
            + "\n"
            + neutralize_untrusted(summary)
            + "</workspace_data>"
        )
        score = candidate.get("semantic_score")
        candidate_rows.append(
            [
                index,
                _KIND_CODE.get(str(candidate.get("kind") or ""), "u"),
                data,
                _ORIGIN_CODE.get(str(candidate.get("origin") or ""), "u"),
                float(score) if score is not None else None,
                [source_index[item] for item in _source_ids(candidate)],
                parent_index,
                [
                    _FIDELITY_CODE.get(str(item), "u")
                    for item in candidate.get("available_fidelity") or ()
                ],
            ]
        )

    payload: dict[str, Any] = {
        "v": SELECTOR_TRANSPORT_VERSION,
        "q": str(question or "")[:1000],
        "d": str(dialog_context or "")[:3000],
        "sc": ["i", "k", "e", "min", "max", "f", "g"],
        "s": source_rows,
        "cc": ["i", "k", "data", "o", "score", "s", "p", "f"],
        "c": candidate_rows,
    }
    if parent_rows:
        payload["p"] = parent_rows
    return SelectorTransport(
        payload=payload,
        mapping=SelectorTransportMapping(tuple(candidate_refs), tuple(source_ids)),
    )


def render_selector_transport_result_schema() -> str:
    return (
        '{"v":1,"a":[[0,"d","a","c",0.94,"t"],'
        '[1,"i","n","n",0.97,"x"]],"s":[[0,"s"],[1,"n"]]}'
    )


def render_selector_transport_output_requirements(
    mapping: SelectorTransportMapping,
) -> str:
    candidate_count = len(mapping.candidate_refs)
    source_count = len(mapping.source_ids)
    candidate_range = f"0..{candidate_count - 1}" if candidate_count else "empty"
    source_range = f"0..{source_count - 1}" if source_count else "empty"
    return (
        "Output cardinality for this registry: "
        f"a MUST contain exactly {candidate_count} rows, one for every candidate index "
        f"{candidate_range}, in ascending index order; "
        f"s MUST contain exactly {source_count} rows, one for every source index "
        f"{source_range}, in ascending index order. "
        "For each a row, relevance i MUST use role n and resolution n; relevance d or s "
        "MUST use role a and a resolution code present in that candidate row's final fidelity "
        "array. For each source, the number of d or s member candidates MUST NOT exceed its "
        "sc max; disposition s is allowed exactly when at least one member candidate is d or s. "
        "The system example illustrates codes only; do not copy its row count."
    )


def decode_selector_transport_result(
    raw: str,
    *,
    mapping: SelectorTransportMapping,
) -> ContextSelectorDecision | None:
    payload = extract_json_object(raw or "")
    if not isinstance(payload, Mapping) or set(payload) != {"v", "a", "s"}:
        return None
    if payload.get("v") != SELECTOR_TRANSPORT_VERSION:
        return None
    assessments = payload.get("a")
    dispositions = payload.get("s")
    if not isinstance(assessments, list) or not isinstance(dispositions, list):
        return None

    decoded_assessments: list[dict[str, Any]] = []
    seen_candidates: set[int] = set()
    for row in assessments:
        if not isinstance(row, list) or len(row) != 6:
            return None
        index = row[0]
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        if index < 0 or index >= len(mapping.candidate_refs) or index in seen_candidates:
            return None
        seen_candidates.add(index)
        decoded_assessments.append(
            {
                "ref": mapping.candidate_refs[index],
                "relevance": _RELEVANCE.get(row[1], row[1]),
                "role": _ROLE.get(row[2], row[2]),
                "resolution": _RESOLUTION.get(row[3], row[3]),
                "confidence": row[4],
                "reason_code": _REASON.get(row[5], row[5]),
            }
        )
    if seen_candidates != set(range(len(mapping.candidate_refs))):
        return None

    decoded_dispositions: list[dict[str, Any]] = []
    seen_sources: set[int] = set()
    for row in dispositions:
        if not isinstance(row, list) or len(row) != 2:
            return None
        index = row[0]
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        if index < 0 or index >= len(mapping.source_ids) or index in seen_sources:
            return None
        seen_sources.add(index)
        decoded_dispositions.append(
            {
                "source_id": mapping.source_ids[index],
                "status": _DISPOSITION.get(row[1], row[1]),
            }
        )
    if seen_sources != set(range(len(mapping.source_ids))):
        return None
    try:
        return ContextSelectorDecision.model_validate(
            {
                "assessments": decoded_assessments,
                "source_dispositions": decoded_dispositions,
            }
        )
    except (ValidationError, TypeError, ValueError):
        return None


__all__ = [
    "SELECTOR_TRANSPORT_SCHEMA",
    "SELECTOR_TRANSPORT_VERSION",
    "SelectorTransport",
    "SelectorTransportMapping",
    "decode_selector_transport_result",
    "encode_selector_transport",
    "render_selector_transport_output_requirements",
    "render_selector_transport_result_schema",
]
