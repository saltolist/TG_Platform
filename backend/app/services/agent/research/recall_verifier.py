"""Bounded add-only recall verification for canonical Context Selector misses."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from app.services.agent.research.planner_decision import (
    CandidateReasonCode,
    CandidateRelevance,
    ContextSelectorAssessment,
    ContextSelectorDecision,
    SelectorResolution,
    SelectorRole,
    SourceDispositionStatus,
)
from app.services.agent.research.selector_transport import (
    selector_card_has_explicit_answer_slot_absence,
)
from app.services.agent.research.trust import neutralize_untrusted
from app.services.ai.rag_json import extract_json_object


RECALL_VERIFIER_SCHEMA = "workspace.recall-verifier/v1"
RECALL_VERIFIER_VERSION = 1
MAX_RECALL_VERIFIER_CANDIDATES = 16
_FRAME_RE = re.compile(
    r"RV1\|n=(?P<n>\d+)\|r=(?P<r>[0-9a-f]{12})\|a=(?P<a>[^|]*)\|done",
    re.IGNORECASE,
)
_FORGED_FRAME_TOKEN_RE = re.compile(r"\bRV\d+\|", re.IGNORECASE)
_SECONDARY_RE = re.compile(
    r"\b(?:вторич\w*|последн\w*|secondary|later|final|ultimo|secundari\w*)\b",
    re.IGNORECASE,
)
_SEMANTIC_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SEMANTIC_STOPWORDS = frozenset(
    {
        "about", "after", "again", "also", "been", "before", "being", "does",
        "from", "have", "into", "only", "should", "that", "their", "then", "there",
        "these", "this", "what", "when", "where", "which", "with", "would",
        "будет", "были", "какая", "какие", "какой", "когда", "можно", "после",
        "почему", "этого", "этой", "этот", "como", "cual", "cuando", "donde",
        "quelle", "quand", "comment", "welche", "wann", "come", "quale", "quando",
        "como", "qual", "quando",
    }
)


def _semantic_tokens(value: str) -> frozenset[str]:
    """Return stable content anchors without pretending to solve semantics in code."""

    return frozenset(
        token
        for token in (item.casefold() for item in _SEMANTIC_TOKEN_RE.findall(str(value or "")))
        if len(token) >= 4 and token not in _SEMANTIC_STOPWORDS
    )


def _has_query_card_semantic_anchor(question: str, *, title: str, card: str) -> bool:
    return bool(_semantic_tokens(question) & _semantic_tokens(f"{title} {card}"))
class VerifierVerdict(StrEnum):
    KEEP = "k"
    PROMOTE = "p"
    UNCERTAIN = "u"


class VerifierError(StrEnum):
    INVALID_JSON = "invalid_json"
    INVALID_SHAPE = "invalid_shape"
    WRONG_VERSION = "wrong_version"
    WRONG_CARDINALITY = "wrong_cardinality"
    WRONG_NONCE = "wrong_nonce"
    INVALID_CODE = "invalid_code"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class RecallVerifierCandidate:
    position: int
    ref: str
    source_ids: tuple[str, ...]
    available_fidelity: tuple[str, ...]
    required_fidelity: tuple[str, ...]
    deterministic_keys: tuple[str, ...]


@dataclass(frozen=True)
class RecallVerifierMapping:
    registry_nonce: str
    candidates: tuple[RecallVerifierCandidate, ...]
    signature: str


@dataclass(frozen=True)
class RecallVerifierEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]
    mapping: RecallVerifierMapping | None = None
    payload: Mapping[str, Any] | None = None

    def render(self) -> str:
        return json.dumps(
            self.payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


@dataclass(frozen=True)
class RecallVerifierProposal:
    position: int
    ref: str
    verdict: VerifierVerdict
    confidence_bucket: int


@dataclass(frozen=True)
class RecallVerifierDecodeResult:
    proposals: tuple[RecallVerifierProposal, ...] = ()
    errors: tuple[VerifierError, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RecallVerifierAdmission:
    decision: ContextSelectorDecision
    admitted_refs: tuple[str, ...] = ()
    rejected: tuple[tuple[int, str], ...] = ()


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


def _neutralize_verifier_data(value: str) -> str:
    fenced = neutralize_untrusted(value)
    return _FORGED_FRAME_TOKEN_RE.sub("[neutralized-frame]|", fenced)


def _nonce(
    question: str,
    dialog_context: str,
    candidates: Sequence[Mapping[str, Any]],
    selected_refs: Sequence[str],
) -> tuple[str, str]:
    registry = [
        [
            str(candidate.get("ref") or ""),
            list(_source_ids(candidate)),
            int(candidate.get("index_revision") or 0),
            int(candidate.get("source_revision") or 0),
            int(candidate.get("selector_summary_version") or 0),
            hashlib.sha256(str(candidate.get("selector_summary") or "").encode()).hexdigest()[:16],
        ]
        for candidate in candidates
    ]
    canonical = json.dumps(
        {
            "q": str(question or "")[:1000],
            "d": hashlib.sha256(str(dialog_context or "")[:3000].encode()).hexdigest()[:16],
            "c": registry,
            "s": list(selected_refs),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return digest[:12], digest


def evaluate_recall_verifier_eligibility(
    *,
    question: str,
    dialog_context: str,
    contract: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    decision: ContextSelectorDecision,
    deadline_exhausted: bool = False,
    provider_budget_available: bool = True,
) -> RecallVerifierEligibility:
    """Select omitted semantic candidates using only deterministic risk signals."""

    if deadline_exhausted:
        return RecallVerifierEligibility(False, ("deadline_exhausted",))
    if not provider_budget_available:
        return RecallVerifierEligibility(False, ("provider_budget_exhausted",))
    if not candidates:
        return RecallVerifierEligibility(False, ("empty_registry",))
    if len(candidates) > 100:
        return RecallVerifierEligibility(False, ("candidate_count_forbidden",))
    target_contract = (
        contract.get("target_contract")
        if isinstance(contract.get("target_contract"), Mapping)
        else {}
    )
    if (
        str(contract.get("task_profile") or "")
        in {"exact_lookup", "mutation_proposal"}
        or str(contract.get("corpus") or "") == "exact_note"
        or str(target_contract.get("target_mode") or "") in {"exact", "set"}
    ):
        return RecallVerifierEligibility(False, ("flow_forbidden",))
    sources = [item for item in contract.get("source_requirements") or () if isinstance(item, Mapping)]
    if not sources or any(str(item.get("coverage") or "relevant") != "relevant" for item in sources):
        return RecallVerifierEligibility(False, ("coverage_forbidden",))
    if any(
        str(item.get("predicate_kind") or "semantic") not in {"semantic", "mixed"}
        for item in sources
    ):
        return RecallVerifierEligibility(False, ("predicate_forbidden",))

    selected_refs = tuple(
        str(item.ref)
        for item in decision.assessments
        if item.relevance != CandidateRelevance.IRRELEVANT
    )
    selected_sources = {
        source_id
        for candidate in candidates
        if str(candidate.get("ref") or "") in selected_refs
        for source_id in _source_ids(candidate)
    }
    required_sources = {
        str(item.get("source_id") or "")
        for item in sources
        if str(item.get("evidence_obligation") or "optional") == "required"
    }
    required_gaps = required_sources - selected_sources
    dispositions = {
        str(item.source_id): str(item.status.value) for item in decision.source_dispositions
    }
    omitted: list[RecallVerifierCandidate] = []
    payload_rows: list[list[Any]] = []
    all_refs = tuple(str(item.get("ref") or "") for item in candidates)
    nonce, signature = _nonce(question, dialog_context, candidates, selected_refs)
    visible_source_ids = tuple(
        dict.fromkeys(source_id for candidate in candidates for source_id in _source_ids(candidate))
    )
    source_index = {source_id: index for index, source_id in enumerate(visible_source_ids)}
    parent_ids: dict[str, int] = {}
    for position, candidate in enumerate(candidates):
        ref = str(candidate.get("ref") or "")
        if ref in selected_refs:
            continue
        if (
            candidate.get("selector_summary_fresh") is not True
            or str(candidate.get("card_origin") or "") != "llm"
            or str(candidate.get("status") or "active").casefold()
            in {"deleted", "hidden", "inaccessible"}
        ):
            continue
        member_sources = _source_ids(candidate)
        card = str(candidate.get("selector_summary") or "")
        title = str(candidate.get("title") or "")
        if selector_card_has_explicit_answer_slot_absence(card):
            continue
        risk: list[str] = []
        deterministic: list[str] = []
        if _has_query_card_semantic_anchor(question, title=title, card=card):
            deterministic.append("query_card_semantic_anchor")
        if set(member_sources) & required_gaps:
            risk.append("required_source_gap")
            deterministic.append("required_source_gap")
        if (
            _SECONDARY_RE.search(str(question or ""))
            and str(candidate.get("origin") or "") == "authoritative_catalog"
        ):
            risk.append("secondary_query_authoritative_candidate")
            deterministic.append("secondary_query_authoritative_candidate")
        if _SECONDARY_RE.search(card):
            risk.append("secondary_topic_signal")
            deterministic.append("secondary_topic_signal")
        if not selected_refs:
            risk.append("empty_primary_selection")
        if any(dispositions.get(source_id) in {"ambiguous", "search_more"} for source_id in member_sources):
            risk.append("unresolved_source_disposition")
        if not risk or "query_card_semantic_anchor" not in deterministic:
            continue
        available = tuple(str(item) for item in candidate.get("available_fidelity") or ())
        required = tuple(
            str(source.get("required_fidelity") or "full_text")
            for source in sources
            if str(source.get("source_id") or "") in member_sources
        )
        mapped = RecallVerifierCandidate(
            position,
            ref,
            member_sources,
            available,
            required,
            tuple(dict.fromkeys(deterministic)),
        )
        omitted.append(mapped)
        parent = candidate.get("parent") if isinstance(candidate.get("parent"), Mapping) else None
        parent_ref = str((parent or {}).get("ref") or "")
        parent_position = parent_ids.setdefault(parent_ref, len(parent_ids)) if parent_ref else None
        payload_rows.append(
            [
                position,
                str(candidate.get("kind") or ""),
                "<workspace_data>"
                + _neutralize_verifier_data(title)
                + "\n"
                + _neutralize_verifier_data(card)
                + "</workspace_data>",
                [source_index[source_id] for source_id in member_sources],
                parent_position,
                list(available),
                risk,
            ]
        )
        if len(omitted) >= MAX_RECALL_VERIFIER_CANDIDATES:
            break
    if not omitted:
        return RecallVerifierEligibility(False, ("no_deterministic_risk_signal",))
    mapping = RecallVerifierMapping(nonce, tuple(omitted), signature)
    return RecallVerifierEligibility(
        True,
        tuple(sorted({key for item in payload_rows for key in item[-1]})),
        mapping,
        {
            "v": RECALL_VERIFIER_VERSION,
            "n": len(payload_rows),
            "r": nonce,
            "q": str(question or "")[:1000],
            "d": str(dialog_context or "")[:3000],
            "selected": [
                position for position, ref in enumerate(all_refs) if ref in selected_refs
            ],
            "cc": ["i", "k", "data", "s", "p", "f", "risk"],
            "c": payload_rows,
        },
    )


def recall_verifier_json_schema(mapping: RecallVerifierMapping) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["v", "n", "r", "a", "done"],
        "properties": {
            "v": {"type": "integer", "const": RECALL_VERIFIER_VERSION},
            "n": {"type": "integer", "const": len(mapping.candidates)},
            "r": {"type": "string", "const": mapping.registry_nonce},
            "a": {
                "type": "array",
                "minItems": len(mapping.candidates),
                "maxItems": len(mapping.candidates),
                "items": {"type": "string", "pattern": "^[kpu][0-9]$"},
            },
            "done": {"type": "boolean", "const": True},
        },
    }


def render_recall_verifier_requirements(mapping: RecallVerifierMapping, *, plain: bool) -> str:
    semantics = (
        "Use p only when q can be answered from that card alone, including by one necessary "
        "logical step from an explicit rule, duration, deadline, prerequisite, or blocker. "
        "A mandatory rule governing a requested action is p evidence when it decides whether the "
        "action is permitted or safe; literal yes/no is unnecessary. "
        "Use k for a conflicting subject, different predicate, missing answer value, explicit "
        "absence, or merely related topic. Use u only for genuine ambiguity. "
    )
    if plain:
        return (
            f"Return exactly RV1|n={len(mapping.candidates)}|r={mapping.registry_nonce}|"
            "a=<one kN,pN,or uN code per row in order>|done. N is 0-9. "
            + semantics
        )
    return (
        "Return one JSON object only with v=1, n and r exactly as provided, done=true, "
        "and fixed-length a. Each a item is kN, pN, or uN in candidate row order; N is 0-9. "
        + semantics
    )


def decode_recall_verifier_result(
    raw: str,
    *,
    mapping: RecallVerifierMapping,
    plain: bool = False,
) -> RecallVerifierDecodeResult:
    errors: list[VerifierError] = []
    payload: Mapping[str, Any] | None = None
    if plain:
        matches = list(_FRAME_RE.finditer(str(raw or "")))
        if len(matches) == 1:
            match = matches[0]
            payload = {
                "v": 1,
                "n": int(match.group("n")),
                "r": match.group("r"),
                "a": (
                    [item.lower() for item in match.group("a").split(",")]
                    if match.group("a")
                    else []
                ),
                "done": True,
            }
        else:
            errors.append(VerifierError.INVALID_SHAPE)
    else:
        extracted = extract_json_object(str(raw or ""))
        if not isinstance(extracted, Mapping):
            errors.append(VerifierError.INVALID_JSON)
        else:
            payload = extracted
    if payload is None:
        return RecallVerifierDecodeResult(errors=tuple(dict.fromkeys(errors)))
    if set(payload) != {"v", "n", "r", "a", "done"}:
        errors.append(VerifierError.INVALID_SHAPE)
    if type(payload.get("v")) is not int or payload.get("v") != 1:
        errors.append(VerifierError.WRONG_VERSION)
    if type(payload.get("n")) is not int or payload.get("n") != len(mapping.candidates):
        errors.append(VerifierError.WRONG_CARDINALITY)
    if payload.get("r") != mapping.registry_nonce:
        errors.append(VerifierError.WRONG_NONCE)
    if payload.get("done") is not True:
        errors.append(VerifierError.INCOMPLETE)
    codes = payload.get("a")
    if not isinstance(codes, list) or len(codes) != len(mapping.candidates):
        errors.append(VerifierError.WRONG_CARDINALITY)
        codes = []
    proposals: list[RecallVerifierProposal] = []
    for candidate, code in zip(mapping.candidates, codes, strict=False):
        value = str(code or "")
        if not re.fullmatch(r"[kpu][0-9]", value):
            errors.append(VerifierError.INVALID_CODE)
            continue
        proposals.append(
            RecallVerifierProposal(
                candidate.position,
                candidate.ref,
                VerifierVerdict(value[0]),
                int(value[1]),
            )
        )
    if errors:
        return RecallVerifierDecodeResult(errors=tuple(dict.fromkeys(errors)))
    return RecallVerifierDecodeResult(tuple(proposals))


def _resolution(candidate: RecallVerifierCandidate) -> SelectorResolution | None:
    required = set(candidate.required_fidelity or ("full_text",))
    available = set(candidate.available_fidelity)
    for fidelity, resolution in (
        ("full_text", SelectorResolution.FULL_TEXT),
        ("text", SelectorResolution.TEXT),
        ("vision", SelectorResolution.VISION),
        ("analytics", SelectorResolution.ANALYTICS),
        ("metadata", SelectorResolution.METADATA),
        ("semantic_card", SelectorResolution.CARD),
    ):
        if fidelity in required and fidelity in available:
            return resolution
    return None


def admit_recall_verifier_proposals(
    *,
    primary: ContextSelectorDecision,
    decoded: RecallVerifierDecodeResult,
    mapping: RecallVerifierMapping,
    candidates: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    material_plan: Mapping[str, Any],
    maximum_additions: int = 1,
) -> RecallVerifierAdmission:
    """Apply two-key admission without ever removing primary selections."""

    if not decoded.valid or maximum_additions <= 0:
        return RecallVerifierAdmission(primary)
    by_position = {item.position: item for item in mapping.candidates}
    by_ref = {str(item.get("ref") or ""): item for item in candidates}
    assessments = list(primary.assessments)
    assessment_by_ref = {str(item.ref): item for item in assessments}
    selected_refs = {
        str(item.ref)
        for item in assessments
        if item.relevance != CandidateRelevance.IRRELEVANT
    }
    source_specs = {
        str(item.get("source_id") or ""): item
        for item in contract.get("source_requirements") or ()
        if isinstance(item, Mapping)
    }
    selected_per_source: dict[str, int] = {}
    for candidate in candidates:
        if str(candidate.get("ref") or "") not in selected_refs:
            continue
        for source_id in _source_ids(candidate):
            selected_per_source[source_id] = selected_per_source.get(source_id, 0) + 1
    max_objects = int((material_plan.get("budget") or {}).get("max_objects") or 8)
    rejected: list[tuple[int, str]] = []
    admitted: list[str] = []
    for proposal in decoded.proposals:
        if proposal.verdict != VerifierVerdict.PROMOTE:
            continue
        mapped = by_position.get(proposal.position)
        candidate = by_ref.get(proposal.ref)
        if mapped is None or candidate is None or mapped.ref != proposal.ref:
            rejected.append((proposal.position, "immutable_mapping_mismatch"))
            continue
        if proposal.ref in selected_refs:
            rejected.append((proposal.position, "already_selected"))
            continue
        if "query_card_semantic_anchor" not in mapped.deterministic_keys:
            rejected.append((proposal.position, "missing_deterministic_key"))
            continue
        if (
            candidate.get("selector_summary_fresh") is not True
            or candidate.get("card_eligible") is not True
            or str(candidate.get("status") or "active").casefold()
            in {"deleted", "hidden", "inaccessible"}
        ):
            rejected.append((proposal.position, "security_or_freshness_rejected"))
            continue
        if selector_card_has_explicit_answer_slot_absence(
            str(candidate.get("selector_summary") or "")
        ):
            rejected.append((proposal.position, "explicit_absence_rejected"))
            continue
        resolution = _resolution(mapped)
        if resolution is None:
            rejected.append((proposal.position, "fidelity_rejected"))
            continue
        if len(selected_refs) >= max_objects:
            rejected.append((proposal.position, "pack_budget_rejected"))
            continue
        cardinality_ok = True
        for source_id in mapped.source_ids:
            maximum = int(
                ((source_specs.get(source_id) or {}).get("selection_cardinality") or {}).get(
                    "max"
                )
                or 16
            )
            if selected_per_source.get(source_id, 0) + 1 > maximum:
                cardinality_ok = False
                break
        if not cardinality_ok:
            rejected.append((proposal.position, "source_cardinality_rejected"))
            continue
        original = assessment_by_ref.get(proposal.ref)
        if original is None:
            rejected.append((proposal.position, "missing_primary_assessment"))
            continue
        assessment_by_ref[proposal.ref] = ContextSelectorAssessment(
            ref=proposal.ref,
            relevance=CandidateRelevance.DIRECT,
            role=SelectorRole.ANSWER_EVIDENCE,
            resolution=resolution,
            confidence=proposal.confidence_bucket / 10,
            reason_code=CandidateReasonCode.EXACT_FACT,
        )
        admitted.append(proposal.ref)
        selected_refs.add(proposal.ref)
        for source_id in mapped.source_ids:
            selected_per_source[source_id] = selected_per_source.get(source_id, 0) + 1
        if len(admitted) >= max(0, maximum_additions):
            break
    if not admitted:
        return RecallVerifierAdmission(primary, rejected=tuple(rejected))
    dispositions = tuple(
        item.model_copy(
            update={
                "status": SourceDispositionStatus.SELECTED
                if any(
                    ref in admitted and item.source_id in _source_ids(by_ref[ref])
                    for ref in admitted
                )
                else item.status
            }
        )
        for item in primary.source_dispositions
    )
    return RecallVerifierAdmission(
        ContextSelectorDecision(
            assessments=tuple(assessment_by_ref[str(item.ref)] for item in assessments),
            source_dispositions=dispositions,
        ),
        tuple(admitted),
        tuple(rejected),
    )


__all__ = [
    "RECALL_VERIFIER_SCHEMA",
    "RecallVerifierAdmission",
    "RecallVerifierDecodeResult",
    "RecallVerifierEligibility",
    "RecallVerifierMapping",
    "VerifierError",
    "VerifierVerdict",
    "admit_recall_verifier_proposals",
    "decode_recall_verifier_result",
    "evaluate_recall_verifier_eligibility",
    "recall_verifier_json_schema",
    "render_recall_verifier_requirements",
]
