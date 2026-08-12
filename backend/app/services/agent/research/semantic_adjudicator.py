"""Provider-neutral row adjudication over an immutable semantic-card registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping, Sequence

from app.services.agent.research.trust import neutralize_untrusted
from app.services.ai.rag_json import extract_json_object


SEMANTIC_ADJUDICATION_SCHEMA = "workspace.semantic-adjudication/v1"
SEMANTIC_ADJUDICATION_VERSION = 1


class AdjudicationGrade(IntEnum):
    EXCLUDE = 0
    SUPPORTING = 1
    DIRECT = 2


@dataclass(frozen=True)
class AdjudicationCandidate:
    position: int
    ref: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class AdjudicationMapping:
    nonce: str
    signature: str
    obligations: tuple[str, ...]
    candidates: tuple[AdjudicationCandidate, ...]
    payload: Mapping[str, Any]

    def render(self) -> str:
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class RowVerdict:
    position: int
    grade: AdjudicationGrade
    obligations: tuple[int, ...]


@dataclass(frozen=True)
class AdjudicationResult:
    verdicts: tuple[RowVerdict, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class MergedRowVerdict:
    position: int
    grade: AdjudicationGrade | None
    obligations: tuple[int, ...]
    agreement: str


def _source_ids(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(item)
            for item in [
                *(candidate.get("source_requirement_ids") or ()),
                candidate.get("source_requirement_id"),
            ]
            if str(item or "")
        )
    )


def build_adjudication_mapping(
    *,
    question: str,
    obligations: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
    task_profile: str = "",
    selection_mode: str = "",
    source_requirements: Sequence[Mapping[str, Any]] = (),
) -> AdjudicationMapping:
    normalized_obligations = tuple(
        str(item or "").strip()[:400] for item in obligations if str(item or "").strip()
    ) or (str(question or "").strip()[:400],)
    rows: list[list[Any]] = []
    mapped: list[AdjudicationCandidate] = []
    signature_rows: list[list[Any]] = []
    for position, candidate in enumerate(candidates):
        ref = str(candidate.get("ref") or "")
        source_ids = _source_ids(candidate)
        title = str(candidate.get("title") or "").strip()
        card = str(
            candidate.get("selector_summary")
            or candidate.get("discovery_summary")
            or candidate.get("preview")
            or ""
        ).strip()
        status = str(candidate.get("status") or "active").strip().lower()
        parent = candidate.get("parent")
        parent_ref = (
            str(parent.get("ref") or "")
            if isinstance(parent, Mapping)
            else str(candidate.get("parent_post_id") or "")
        )
        windows = [
            [
                str(item.get("source_requirement_id") or ""),
                int(item.get("position") or 0),
                int(item.get("window_size") or 0),
            ]
            for item in candidate.get("catalog_window_memberships") or ()
            if isinstance(item, Mapping)
            and str(item.get("source_requirement_id") or "")
            and int(item.get("position") or 0) > 0
            and int(item.get("window_size") or 0) > 0
        ]
        rows.append(
            [
                position,
                str(candidate.get("kind") or ""),
                "<workspace_data>"
                + neutralize_untrusted(title)
                + "\n"
                + neutralize_untrusted(card)
                + "</workspace_data>",
                list(source_ids),
                status,
                parent_ref or None,
                windows,
            ]
        )
        mapped.append(AdjudicationCandidate(position, ref, source_ids))
        signature_rows.append(
            [
                ref,
                list(source_ids),
                int(candidate.get("source_revision") or 0),
                int(candidate.get("selector_summary_version") or 0),
                hashlib.sha256(card.encode()).hexdigest()[:16],
                status,
                windows,
            ]
        )
    sources = [
        {
            "id": str(source.get("source_id") or ""),
            "kind": str(source.get("kind") or ""),
            "goal": str(source.get("query_goal") or "")[:600],
            "coverage": str(source.get("coverage") or "relevant"),
            "discovery": str(source.get("discovery_mode") or "semantic_relevance"),
            "statuses": [
                str(item)
                for item in (source.get("scope") or {}).get("statuses") or ()
                if str(item)
            ],
            "min": int((source.get("selection_cardinality") or {}).get("min") or 0),
            "max": int((source.get("selection_cardinality") or {}).get("max") or 0),
        }
        for source in source_requirements
        if isinstance(source, Mapping) and str(source.get("source_id") or "")
    ]
    canonical = json.dumps(
        {
            "q": str(question or "")[:1000],
            "o": normalized_obligations,
            "c": signature_rows,
            "task": [str(task_profile or ""), str(selection_mode or "")],
            "sources": sources,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = hashlib.sha256(canonical.encode()).hexdigest()
    nonce = signature[:12]
    payload = {
        "v": SEMANTIC_ADJUDICATION_VERSION,
        "n": len(rows),
        "r": nonce,
        "q": str(question or "")[:1000],
        "task": {
            "profile": str(task_profile or ""),
            "selection": str(selection_mode or ""),
        },
        "obligations": list(normalized_obligations),
        "sources": sources,
        "columns": [
            "position",
            "kind",
            "card",
            "sources",
            "status",
            "parent",
            "windows",
        ],
        "rows": rows,
    }
    return AdjudicationMapping(
        nonce,
        signature,
        normalized_obligations,
        tuple(mapped),
        payload,
    )


def adjudication_json_schema(mapping: AdjudicationMapping) -> dict[str, Any]:
    obligation_indexes = list(range(len(mapping.obligations)))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["v", "n", "r", "rows", "done"],
        "properties": {
            "v": {"type": "integer", "const": SEMANTIC_ADJUDICATION_VERSION},
            "n": {"type": "integer", "const": len(mapping.candidates)},
            "r": {"type": "string", "const": mapping.nonce},
            "rows": {
                "type": "array",
                "minItems": len(mapping.candidates),
                "maxItems": len(mapping.candidates),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["i", "g", "o"],
                    "properties": {
                        "i": {"type": "integer", "minimum": 0},
                        "g": {"type": "integer", "enum": [0, 1, 2]},
                        "o": {
                            "type": "array",
                            "items": {"type": "integer", "enum": obligation_indexes},
                        },
                    },
                },
            },
            "done": {"type": "boolean", "const": True},
        },
    }


def render_adjudication_request(mapping: AdjudicationMapping) -> str:
    """Render the single bounded label request shared by runtime and replay."""

    return (
        "Return exactly one JSON object with keys v,n,r,rows,done. "
        f"Set v={SEMANTIC_ADJUDICATION_VERSION}, n={len(mapping.candidates)}, "
        f"r={json.dumps(mapping.nonce)}, and done=true. "
        "rows must contain every position in ascending order exactly once; "
        "each row has exactly i (position), g (0,1,2), and o (obligation indexes). "
        "For g=0 use o=[]; for g>0 use only supported indexes from "
        f"0..{len(mapping.obligations) - 1}. Do not omit frame fields.\n"
        "Immutable adjudication registry:\n"
        + mapping.render()
    )


def decode_adjudication_result(
    raw: str,
    *,
    mapping: AdjudicationMapping,
) -> AdjudicationResult:
    payload = extract_json_object(str(raw or ""))
    if not isinstance(payload, Mapping):
        return AdjudicationResult(errors=("invalid_json",))
    errors: list[str] = []
    if set(payload) != {"v", "n", "r", "rows", "done"}:
        errors.append("invalid_keys")
    if payload.get("v") != SEMANTIC_ADJUDICATION_VERSION:
        errors.append("wrong_version")
    if payload.get("n") != len(mapping.candidates):
        errors.append("wrong_cardinality")
    if payload.get("r") != mapping.nonce:
        errors.append("wrong_nonce")
    if payload.get("done") is not True:
        errors.append("incomplete")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != len(mapping.candidates):
        errors.append("wrong_cardinality")
        rows = []
    verdicts: list[RowVerdict] = []
    seen: set[int] = set()
    obligation_count = len(mapping.obligations)
    for expected_position, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"i", "g", "o"}:
            errors.append("invalid_row")
            continue
        position = row.get("i")
        grade = row.get("g")
        raw_obligations = row.get("o")
        if type(position) is not int or position != expected_position or position in seen:
            errors.append("invalid_position")
            continue
        seen.add(position)
        if type(grade) is not int or grade not in {0, 1, 2}:
            errors.append("invalid_grade")
            continue
        if not isinstance(raw_obligations, list) or any(
            type(item) is not int or item < 0 or item >= obligation_count
            for item in raw_obligations
        ):
            errors.append("invalid_obligation")
            continue
        # Some strict-output providers populate the only available obligation
        # enum even for an excluded row. Grade 0 is authoritative and carries
        # no semantic edge, so discard that redundant field locally instead of
        # invalidating every other row in the frame.
        obligations = (
            () if grade == 0 else tuple(dict.fromkeys(raw_obligations))
        )
        if grade > 0 and not obligations:
            errors.append("included_without_obligation")
            continue
        verdicts.append(
            RowVerdict(position, AdjudicationGrade(grade), obligations)
        )
    if errors:
        return AdjudicationResult(errors=tuple(dict.fromkeys(errors)))
    return AdjudicationResult(tuple(verdicts))


def merge_adjudication_results(
    left: AdjudicationResult,
    right: AdjudicationResult,
    *,
    tie_breaker: AdjudicationResult | None = None,
) -> tuple[MergedRowVerdict, ...]:
    if not left.valid or not right.valid:
        return ()
    left_by_position = {item.position: item for item in left.verdicts}
    right_by_position = {item.position: item for item in right.verdicts}
    tie_by_position = (
        {item.position: item for item in tie_breaker.verdicts}
        if tie_breaker is not None and tie_breaker.valid
        else {}
    )
    if set(left_by_position) != set(right_by_position):
        return ()
    merged: list[MergedRowVerdict] = []
    for position in sorted(left_by_position):
        first = left_by_position[position]
        second = right_by_position[position]
        first_positive = first.grade > 0
        second_positive = second.grade > 0
        if first_positive == second_positive:
            grade = min(first.grade, second.grade) if first_positive else AdjudicationGrade.EXCLUDE
            obligations = (
                tuple(sorted(set(first.obligations) & set(second.obligations)))
                if first_positive
                else ()
            )
            if first_positive and not obligations:
                tie = tie_by_position.get(position)
                if tie is None:
                    merged.append(
                        MergedRowVerdict(
                            position, None, (), "obligation_disagreement"
                        )
                    )
                else:
                    merged.append(
                        MergedRowVerdict(
                            position,
                            tie.grade,
                            tie.obligations,
                            "tie_breaker",
                        )
                    )
            else:
                merged.append(MergedRowVerdict(position, grade, obligations, "consensus"))
            continue
        tie = tie_by_position.get(position)
        if tie is None:
            merged.append(MergedRowVerdict(position, None, (), "unresolved"))
            continue
        merged.append(
            MergedRowVerdict(position, tie.grade, tie.obligations, "tie_breaker")
        )
    return tuple(merged)


__all__ = [
    "AdjudicationGrade",
    "AdjudicationMapping",
    "AdjudicationResult",
    "MergedRowVerdict",
    "SEMANTIC_ADJUDICATION_SCHEMA",
    "adjudication_json_schema",
    "build_adjudication_mapping",
    "decode_adjudication_result",
    "merge_adjudication_results",
    "render_adjudication_request",
]
