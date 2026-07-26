"""Versioned provider transport for the canonical Context Selector."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from app.services.agent.research.planner_decision import ContextSelectorDecision
from app.services.agent.research.trust import neutralize_untrusted
from app.services.ai.rag_json import extract_json_object
from app.services.ai.semantic_summary import SELECTOR_SUMMARY_MAX_CHARS


LEGACY_SELECTOR_TRANSPORT_SCHEMA = "workspace.context-selector-transport/v1"
LEGACY_SELECTOR_TRANSPORT_VERSION = 1
SELECTOR_TRANSPORT_SCHEMA = "workspace.context-selector-transport/v2"
SELECTOR_TRANSPORT_VERSION = 2
SELECTOR_TRANSPORT_FRAME = "CS2"

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
_LEGACY_ROLE = {"a": "answer_evidence", "n": "none"}
_LEGACY_RESOLUTION = {
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
_LEGACY_DISPOSITION = {
    "s": "selected",
    "n": "no_relevant_candidate",
    "m": "search_more",
    "a": "ambiguous",
}
_ALLOWED_REASON_BY_RELEVANCE = {
    "d": frozenset({"t", "e", "d", "c", "q", "u", "m", "a", "l"}),
    "s": frozenset({"t", "e", "d", "c", "m", "a", "l"}),
    "i": frozenset({"x", "b", "s"}),
}
_PLAIN_FRAME_RE = re.compile(
    r"CS(?P<version>\d+)\|n=(?P<count>\d+)\|r=(?P<nonce>[a-f0-9]{12})"
    r"\|a=(?P<codes>[dsi][tedcqumalxbs][0-9](?:,[dsi][tedcqumalxbs][0-9])*)?"
    r"\|(?P<done>done)",
    re.IGNORECASE,
)
_FORGED_FRAME_TOKEN_RE = re.compile(r"\bCS\d+\|", re.IGNORECASE)


class SelectorValidationErrorCode(StrEnum):
    MISSING_FRAME = "missing_frame"
    MULTIPLE_FRAMES = "multiple_frames"
    WRONG_VERSION = "wrong_version"
    REGISTRY_MISMATCH = "registry_mismatch"
    MISSING_COMPLETION_MARKER = "missing_completion_marker"
    WRONG_CARDINALITY = "wrong_cardinality"
    INVALID_ASSESSMENT_CODE = "invalid_assessment_code"
    INVALID_RELEVANCE_REASON = "invalid_relevance_reason"
    UNSUPPORTED_FIDELITY = "unsupported_fidelity"
    SOURCE_CARDINALITY_EXCEEDED = "source_cardinality_exceeded"
    INVALID_CANONICAL = "invalid_canonical"


@dataclass(frozen=True)
class SelectorCandidateMapping:
    ref: str
    source_ids: tuple[str, ...]
    available_fidelity: tuple[str, ...]
    required_fidelity: tuple[str, ...]


@dataclass(frozen=True)
class SelectorSourceMapping:
    source_id: str
    maximum: int


@dataclass(frozen=True)
class SelectorTransportMapping:
    candidate_refs: tuple[str, ...]
    source_ids: tuple[str, ...]
    registry_nonce: str = ""
    candidates: tuple[SelectorCandidateMapping, ...] = ()
    sources: tuple[SelectorSourceMapping, ...] = ()


@dataclass(frozen=True)
class SelectorTransport:
    payload: dict[str, Any]
    mapping: SelectorTransportMapping

    def render(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class SelectorDecodeResult:
    decision: ContextSelectorDecision | None
    errors: tuple[SelectorValidationErrorCode, ...] = ()
    assessment_codes: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.decision is not None and not self.errors

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.errors)


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


def _neutralize_selector_data(text: str) -> str:
    fenced = neutralize_untrusted(text)
    return _FORGED_FRAME_TOKEN_RE.sub("[neutralized-frame]|", fenced)


def _registry_nonce(
    *,
    question: str,
    dialog_context: str,
    candidate_refs: Sequence[str],
    source_ids: Sequence[str],
) -> str:
    canonical = json.dumps(
        {
            "q": str(question or "")[:1000],
            "d": str(dialog_context or "")[:3000],
            "c": list(candidate_refs),
            "s": list(source_ids),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def encode_selector_transport(
    *,
    question: str,
    dialog_context: str,
    contract: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    summary_max_chars: int = SELECTOR_SUMMARY_MAX_CHARS,
) -> SelectorTransport:
    summary_limit = max(1, min(480, int(summary_max_chars)))
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
    source_ids = (*source_ids, *sorted(visible_source_ids - set(source_ids)))
    source_index = {source_id: index for index, source_id in enumerate(source_ids)}
    requirements_by_id = {
        str(source.get("source_id") or ""): source for source in requirements
    }

    source_rows: list[list[Any]] = []
    source_mappings: list[SelectorSourceMapping] = []
    for index, source_id in enumerate(source_ids):
        source = requirements_by_id.get(source_id, {})
        cardinality = source.get("selection_cardinality") or {}
        maximum = int(cardinality.get("max") or 16)
        source_mappings.append(SelectorSourceMapping(source_id, maximum))
        row: list[Any] = [
            index,
            _KIND_CODE.get(str(source.get("kind") or ""), "u"),
            "r" if str(source.get("evidence_obligation") or "optional") == "required" else "o",
            int(cardinality.get("min") or 0),
            maximum,
            _FIDELITY_CODE.get(str(source.get("required_fidelity") or "semantic_card"), "s"),
        ]
        goal = str(source.get("query_goal") or "").strip()
        if goal:
            row.append(_neutralize_selector_data(goal[:240]))
        source_rows.append(row)

    parent_ids: dict[str, int] = {}
    parent_rows: list[list[Any]] = []
    candidate_rows: list[list[Any]] = []
    candidate_refs: list[str] = []
    candidate_mappings: list[SelectorCandidateMapping] = []
    for index, candidate in enumerate(candidates):
        ref = str(candidate.get("ref") or "")
        candidate_refs.append(ref)
        member_source_ids = _source_ids(candidate)
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
        summary = str(candidate.get("selector_summary") or "")[:summary_limit]
        data = (
            "<workspace_data>"
            + _neutralize_selector_data(title)
            + "\n"
            + _neutralize_selector_data(summary)
            + "</workspace_data>"
        )
        score = candidate.get("semantic_score")
        available = tuple(str(item) for item in candidate.get("available_fidelity") or ())
        required = tuple(
            str(requirements_by_id.get(source_id, {}).get("required_fidelity") or "semantic_card")
            for source_id in member_source_ids
        )
        candidate_mappings.append(
            SelectorCandidateMapping(ref, member_source_ids, available, required)
        )
        candidate_rows.append(
            [
                index,
                _KIND_CODE.get(str(candidate.get("kind") or ""), "u"),
                data,
                _ORIGIN_CODE.get(str(candidate.get("origin") or ""), "u"),
                float(score) if score is not None else None,
                [source_index[item] for item in member_source_ids],
                parent_index,
                [_FIDELITY_CODE.get(str(item), "u") for item in available],
            ]
        )

    nonce = _registry_nonce(
        question=question,
        dialog_context=dialog_context,
        candidate_refs=candidate_refs,
        source_ids=source_ids,
    )
    payload: dict[str, Any] = {
        "v": SELECTOR_TRANSPORT_VERSION,
        "n": len(candidate_rows),
        "r": nonce,
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
        mapping=SelectorTransportMapping(
            tuple(candidate_refs),
            tuple(source_ids),
            nonce,
            tuple(candidate_mappings),
            tuple(source_mappings),
        ),
    )


def selector_transport_json_schema(mapping: SelectorTransportMapping) -> dict[str, Any]:
    count = len(mapping.candidate_refs)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["v", "n", "r", "a", "done"],
        "properties": {
            "v": {"type": "integer", "const": SELECTOR_TRANSPORT_VERSION},
            "n": {"type": "integer", "const": count},
            "r": {"type": "string", "const": mapping.registry_nonce},
            "a": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "string",
                    "pattern": "^(?:d[tedcqumal]|s[tedcmal]|i[xbs])[0-9]$",
                },
            },
            "done": {"type": "boolean", "const": True},
        },
    }


def render_selector_transport_result_schema() -> str:
    return '{"v":2,"n":2,"r":"nonce-from-request","a":["de9","ix8"],"done":true}'


def render_selector_transport_output_requirements(
    mapping: SelectorTransportMapping,
    *,
    plain_frame: bool = False,
) -> str:
    count = len(mapping.candidate_refs)
    codes = (
        "Each assessment code has exactly three characters: relevance d|s|i, "
        "reason t|e|d|c|q|u|m|a|l|x|b|s, confidence bucket 0..9. "
        "Use x/b/s reasons only with irrelevant; use the remaining semantic reasons "
        "with direct or supporting."
    )
    if plain_frame:
        return (
            f"Return exactly one frame CS2|n={count}|r={mapping.registry_nonce}|"
            f"a=<exactly {count} comma-separated assessment codes>|done. {codes} "
            "Do not return indexes, refs, roles, resolutions, source dispositions, markdown, "
            "or a second frame."
        )
    return (
        "Return one object with exactly v,n,r,a,done. "
        f"Copy v=2, n={count}, r={mapping.registry_nonce}, done=true. "
        f"a must contain exactly {count} assessment strings in candidate position order. "
        + codes
        + " Do not return indexes, refs, roles, resolutions, source dispositions, or prose."
    )


def _error(*codes: SelectorValidationErrorCode) -> SelectorDecodeResult:
    return SelectorDecodeResult(None, tuple(dict.fromkeys(codes)))


def _normalize_v2_payload(
    raw: str,
    *,
    plain_frame: bool,
) -> tuple[Mapping[str, Any] | None, tuple[SelectorValidationErrorCode, ...]]:
    text = str(raw or "")
    if plain_frame:
        frames = list(_PLAIN_FRAME_RE.finditer(text))
        if len(frames) > 1:
            return None, (SelectorValidationErrorCode.MULTIPLE_FRAMES,)
        if not frames:
            prefix = re.search(r"CS(?P<version>\d+)\|", text, re.IGNORECASE)
            if prefix and int(prefix.group("version")) != SELECTOR_TRANSPORT_VERSION:
                return None, (SelectorValidationErrorCode.WRONG_VERSION,)
            if "CS2|" in text and "|done" not in text:
                return None, (SelectorValidationErrorCode.MISSING_COMPLETION_MARKER,)
            return None, (SelectorValidationErrorCode.MISSING_FRAME,)
        match = frames[0]
        codes_text = match.group("codes") or ""
        return {
            "v": int(match.group("version")),
            "n": int(match.group("count")),
            "r": match.group("nonce").lower(),
            "a": codes_text.lower().split(",") if codes_text else [],
            "done": match.group("done").lower() == "done",
        }, ()
    payload = extract_json_object(text)
    if not isinstance(payload, Mapping):
        return None, (SelectorValidationErrorCode.MISSING_FRAME,)
    return payload, ()


def _resolution_for(
    candidate: SelectorCandidateMapping,
    *,
    reason_code: str,
) -> str | None:
    available = set(candidate.available_fidelity)
    required_order = {
        "vision": ("vision",),
        "analytics": ("analytics",),
        "full_text": ("full_text", "text"),
        "text": ("text", "full_text"),
        "semantic_card": ("semantic_card", "card"),
        "card": ("card", "semantic_card"),
        "catalog": ("metadata", "catalog"),
        "metadata": ("metadata", "catalog"),
    }
    resolution = {
        "semantic_card": "card",
        "card": "card",
        "catalog": "metadata",
        "metadata": "metadata",
    }
    for required in candidate.required_fidelity:
        for fidelity in required_order.get(required, (required,)):
            if fidelity in available:
                return resolution.get(fidelity, fidelity)
    preferred = {
        "attachment_or_media": ("vision", "text", "full_text", "semantic_card"),
        "analytics": ("analytics", "full_text", "text", "semantic_card"),
        "topic_only": ("semantic_card", "card", "full_text", "text", "metadata"),
    }.get(reason_code, ("full_text", "text", "semantic_card", "card", "metadata"))
    for fidelity in preferred:
        if fidelity in available:
            return resolution.get(fidelity, fidelity)
    return None


def decode_selector_transport_v2_result(
    raw: str,
    *,
    mapping: SelectorTransportMapping,
    plain_frame: bool = False,
) -> SelectorDecodeResult:
    payload, parse_errors = _normalize_v2_payload(raw, plain_frame=plain_frame)
    if parse_errors:
        return SelectorDecodeResult(None, parse_errors)
    assert payload is not None
    allowed_keys = {"v", "n", "r", "a", "done"}
    if set(payload) != allowed_keys:
        return _error(SelectorValidationErrorCode.INVALID_ASSESSMENT_CODE)
    if payload.get("v") != SELECTOR_TRANSPORT_VERSION:
        return _error(SelectorValidationErrorCode.WRONG_VERSION)
    if payload.get("r") != mapping.registry_nonce:
        return _error(SelectorValidationErrorCode.REGISTRY_MISMATCH)
    if payload.get("done") is not True:
        return _error(SelectorValidationErrorCode.MISSING_COMPLETION_MARKER)
    assessments = payload.get("a")
    if payload.get("n") != len(mapping.candidate_refs):
        return _error(SelectorValidationErrorCode.WRONG_CARDINALITY)
    if not isinstance(assessments, list) or len(assessments) != len(mapping.candidate_refs):
        return _error(SelectorValidationErrorCode.WRONG_CARDINALITY)

    decoded: list[dict[str, Any]] = []
    errors: list[SelectorValidationErrorCode] = []
    codes: list[str] = []
    for index, value in enumerate(assessments):
        if not isinstance(value, str) or not re.fullmatch(r"[dsi][tedcqumalxbs][0-9]", value):
            errors.append(SelectorValidationErrorCode.INVALID_ASSESSMENT_CODE)
            continue
        relevance_code, reason_code, confidence_code = value
        codes.append(value)
        if reason_code not in _ALLOWED_REASON_BY_RELEVANCE[relevance_code]:
            errors.append(SelectorValidationErrorCode.INVALID_RELEVANCE_REASON)
            continue
        irrelevant = relevance_code == "i"
        resolution = "none"
        if not irrelevant:
            candidate = mapping.candidates[index]
            resolution = _resolution_for(candidate, reason_code=_REASON[reason_code]) or ""
            if not resolution:
                errors.append(SelectorValidationErrorCode.UNSUPPORTED_FIDELITY)
                continue
        decoded.append(
            {
                "ref": mapping.candidate_refs[index],
                "relevance": _RELEVANCE[relevance_code],
                "role": "none" if irrelevant else "answer_evidence",
                "resolution": resolution,
                "confidence": int(confidence_code) / 9.0,
                "reason_code": _REASON[reason_code],
            }
        )
    if errors:
        return SelectorDecodeResult(None, tuple(dict.fromkeys(errors)), tuple(codes))

    positive_refs = {
        item["ref"] for item in decoded if item["relevance"] != "irrelevant"
    }
    dispositions: list[dict[str, Any]] = []
    for source in mapping.sources:
        member_indexes = [
            index
            for index, candidate in enumerate(mapping.candidates)
            if source.source_id in candidate.source_ids
        ]
        selected = [
            mapping.candidate_refs[index]
            for index in member_indexes
            if mapping.candidate_refs[index] in positive_refs
        ]
        if len(selected) > source.maximum:
            errors.append(SelectorValidationErrorCode.SOURCE_CARDINALITY_EXCEEDED)
            continue
        member_reasons = {decoded[index]["reason_code"] for index in member_indexes}
        status = (
            "selected"
            if selected
            else "search_more"
            if "search_more" in member_reasons
            else "ambiguous"
            if "ambiguous" in member_reasons
            else "no_relevant_candidate"
        )
        dispositions.append({"source_id": source.source_id, "status": status})
    if errors:
        return SelectorDecodeResult(None, tuple(dict.fromkeys(errors)), tuple(codes))
    try:
        decision = ContextSelectorDecision.model_validate(
            {"assessments": decoded, "source_dispositions": dispositions}
        )
    except (ValidationError, TypeError, ValueError):
        return SelectorDecodeResult(
            None,
            (SelectorValidationErrorCode.INVALID_CANONICAL,),
            tuple(codes),
        )
    return SelectorDecodeResult(decision, (), tuple(codes))


def decode_selector_transport_result(
    raw: str,
    *,
    mapping: SelectorTransportMapping,
    plain_frame: bool = False,
) -> SelectorDecodeResult:
    """Decode the active v2 positional vector into canonical selector v2."""

    return decode_selector_transport_v2_result(
        raw,
        mapping=mapping,
        plain_frame=plain_frame,
    )


def decode_selector_transport_v1_result(
    raw: str,
    *,
    mapping: SelectorTransportMapping,
) -> ContextSelectorDecision | None:
    """Rollback-only decoder for durable v1 responses/checkpoints."""

    payload = extract_json_object(raw or "")
    if not isinstance(payload, Mapping) or set(payload) != {"v", "a", "s"}:
        return None
    if payload.get("v") != LEGACY_SELECTOR_TRANSPORT_VERSION:
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
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= len(mapping.candidate_refs)
            or index in seen_candidates
        ):
            return None
        seen_candidates.add(index)
        decoded_assessments.append(
            {
                "ref": mapping.candidate_refs[index],
                "relevance": _RELEVANCE.get(row[1], row[1]),
                "role": _LEGACY_ROLE.get(row[2], row[2]),
                "resolution": _LEGACY_RESOLUTION.get(row[3], row[3]),
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
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= len(mapping.source_ids)
            or index in seen_sources
        ):
            return None
        seen_sources.add(index)
        decoded_dispositions.append(
            {"source_id": mapping.source_ids[index], "status": _LEGACY_DISPOSITION.get(row[1], row[1])}
        )
    if seen_sources != set(range(len(mapping.source_ids))):
        return None
    try:
        return ContextSelectorDecision.model_validate(
            {"assessments": decoded_assessments, "source_dispositions": decoded_dispositions}
        )
    except (ValidationError, TypeError, ValueError):
        return None


__all__ = [
    "LEGACY_SELECTOR_TRANSPORT_SCHEMA",
    "LEGACY_SELECTOR_TRANSPORT_VERSION",
    "SELECTOR_TRANSPORT_SCHEMA",
    "SELECTOR_TRANSPORT_VERSION",
    "SelectorDecodeResult",
    "SelectorTransport",
    "SelectorTransportMapping",
    "SelectorValidationErrorCode",
    "decode_selector_transport_result",
    "decode_selector_transport_v1_result",
    "decode_selector_transport_v2_result",
    "encode_selector_transport",
    "render_selector_transport_output_requirements",
    "render_selector_transport_result_schema",
    "selector_transport_json_schema",
]
