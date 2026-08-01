"""Versioned provider transport for the canonical Context Selector."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.agent.research.planner_decision import (
    CandidateReasonCode,
    CandidateRelevance,
    ContextSelectorDecision,
    SelectorResolution,
    SelectorRole,
    SourceDispositionStatus,
)
from app.services.agent.research.trust import neutralize_untrusted
from app.services.ai.rag_json import extract_json_object
from app.services.ai.semantic_summary import (
    SELECTOR_SUMMARY_MAX_CHARS,
    selector_card_has_explicit_absence,
)


LEGACY_SELECTOR_TRANSPORT_SCHEMA = "workspace.context-selector-transport/v1"
LEGACY_SELECTOR_TRANSPORT_VERSION = 1
SELECTOR_TRANSPORT_SCHEMA = "workspace.context-selector-transport/v2"
SELECTOR_TRANSPORT_VERSION = 2
SELECTOR_TRANSPORT_FRAME = "CS2"
MATCHED_EVIDENCE_SCHEMA = "workspace.matched-evidence/v1"
MATCHED_EVIDENCE_MAX_CHARS = 1200
OPENED_EVIDENCE_SCHEMA = "workspace.opened-evidence/v1"
# A verified full read must cover ordinary long notes end to end. The material
# planner already bounds full-text work to this same per-turn budget.
OPENED_EVIDENCE_MAX_CHARS = 12_000

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
    "d": frozenset({"e", "d", "c", "q", "u", "m", "a", "l"}),
    "s": frozenset({"e", "d", "c", "m", "a", "l"}),
    "i": frozenset({"t", "x", "b", "s"}),
}
_PLAIN_FRAME_RE = re.compile(
    r"CS(?P<version>\d+)\|n=(?P<count>\d+)\|r=(?P<nonce>[a-f0-9]{12})"
    r"\|a=(?P<codes>[dsi][tedcqumalxbs][0-9](?:,[dsi][tedcqumalxbs][0-9])*)?"
    r"\|(?P<done>done)",
    re.IGNORECASE,
)
_FORGED_FRAME_TOKEN_RE = re.compile(r"\bCS\d+\|", re.IGNORECASE)
_DRAFT_RECORD_RE = re.compile(
    r"\b(?:draft|proposed|proposal|чернов\w*|предлож\w*|borrador|propuest\w*|"
    r"brouillon|propos\w*|entwurf|vorgeschlag\w*)\b",
    re.IGNORECASE,
)
_FINAL_RECORD_RE = re.compile(
    r"\b(?:final|signed|approved|итогов\w*|финальн\w*|подписан\w*|утвержден\w*|"
    r"firmad\w*|finale?|signe\w*|unterzeichnet\w*|genehmigt\w*)\b",
    re.IGNORECASE,
)
_NAMED_SUBJECT_RE = re.compile(r"\b[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9_-]{2,}\b")
_SUBJECT_STOP_WORDS = frozenset(
    {
        "What", "Which", "Who", "When", "Where", "Why", "How", "Did", "Does", "Can", "The",
        "Что", "Кто", "Когда", "Где", "Почему", "Как", "Какой", "Какая", "Какие", "Можно",
        "Que", "Quelle", "Welche", "Qual", "Quanto", "Combien",
    }
)
_CARD_QUESTION_PREFIX = "Отвечает на вопрос "
_EXPLANATORY_QUERY_RE = re.compile(
    r"(?:^|\b)(?:как|каким\s+образом|почему|зачем|how|why|cómo|por\s+qué|comment|pourquoi|wie|warum)(?:\b|$)",
    re.IGNORECASE,
)
_DESCRIPTIVE_CARD_QUESTION_RE = re.compile(
    r"^(?:что|как(?:ой|ое|ая|ие)|what|which|qué|cuál(?:es)?|quoi|quel(?:le|s)?|was|welche?)\b",
    re.IGNORECASE,
)
_OPERATIONAL_CARD_QUESTION_RE = re.compile(
    r"\b(?:механизм|процесс|способ|причин\w*|работа\w*|использу\w*|наход\w*|ищ\w*|получа\w*|"
    r"mechanism|process|method|reason|cause|work\w*|use\w*|find\w*|search\w*|retriev\w*|"
    r"mecanismo|proceso|método|razón|causa|funciona\w*|usa\w*|busca\w*)\b",
    re.IGNORECASE,
)
_ANSWER_SLOT_QUERY_RE = re.compile(
    r"(?:^|\b)(?:что|кто|ка(?:кой|кая|кие|кое)|сколько|когда|где|почему|зачем|как|"
    r"what|which|who|how\s+(?:many|much)|when|where|why|how|"
    r"que|qué|cual(?:es)?|cuál(?:es)?|quien|quién|cuanto|cuánto|cuando|cuándo|donde|dónde|"
    r"quel(?:le|s)?|qui|combien|quand|où|pourquoi|comment|"
    r"welche?|wer|wie\s+viel|wann|wo|warum|wie|"
    r"quale|chi|quanto|quando|dove|perché|come|"
    r"qual|quem|quanto|quando|onde|por\s+que|como)(?:\b|$)",
    re.IGNORECASE,
)
_NORMATIVE_BOUND_QUERY_RE = re.compile(
    r"\b(?:caps?|limits?|thresholds?|quotas?|minimum|required|approved|лимит\w*|порог\w*|"
    r"квот\w*|миним\w*|требуем\w*|утвержден\w*|limite|umbral|cuota|minimum|"
    r"seuil|quota|grenze|minimum|limite|soglia)\b",
    re.IGNORECASE,
)
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


@dataclass(frozen=True)
class SelectorScopeGuardResult:
    decision: ContextSelectorDecision
    demoted_refs: tuple[str, ...] = ()


def selector_card_has_explicit_answer_slot_absence(card: str) -> bool:
    return selector_card_has_explicit_absence(card)


def selector_candidate_has_explicit_absence(candidate: Mapping[str, Any]) -> bool:
    flags = candidate.get("selector_semantic_flags")
    if isinstance(flags, Mapping) and int(flags.get("v") or 0) >= 1:
        return flags.get("explicit_absence") is True
    return selector_card_has_explicit_answer_slot_absence(
        str(candidate.get("selector_summary") or "")
    )


def _query_obligations(question: str) -> dict[str, Any] | None:
    value = str(question or "")
    if not (_DRAFT_RECORD_RE.search(value) and _FINAL_RECORD_RE.search(value)):
        return None
    return {
        "p": "cross_record_comparison/v2",
        "evidence_slots": [
            {
                "record_role": "draft_or_proposed",
                "requires": "requested_relation_value",
            },
            {
                "record_role": "final_or_signed",
                "requires": "requested_relation_value",
            },
        ],
        "operation": "compare_slot_values",
    }


def _query_subject_anchors(
    question: str,
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    candidate_text = " ".join(
        f"{item.get('title') or ''} {item.get('selector_summary') or ''}"
        for item in candidates
        if isinstance(item, Mapping)
    ).casefold()
    return tuple(
        dict.fromkeys(
            token.casefold()
            for token in _NAMED_SUBJECT_RE.findall(str(question or ""))
            if token not in _SUBJECT_STOP_WORDS and token.casefold() in candidate_text
        )
    )


def apply_selector_question_scope_guard(
    decision: ContextSelectorDecision,
    *,
    question: str,
    candidates: Sequence[Mapping[str, Any]],
    mapping: SelectorTransportMapping,
) -> SelectorScopeGuardResult:
    """Demote provable question-scope and missing-answer mismatches.

    The guard only acts on question-scoped LLM cards. Ambiguous, implicit,
    anaphoric and multi-intent queries remain entirely model-decided.
    """

    query = str(question or "")
    explanatory_query = bool(_EXPLANATORY_QUERY_RE.search(query))
    answer_slot_query = bool(_ANSWER_SLOT_QUERY_RE.search(query))
    comparison_obligations = _query_obligations(query) is not None
    subject_anchors = _query_subject_anchors(query, candidates)
    if (
        not explanatory_query
        and not answer_slot_query
        and not comparison_obligations
        and not subject_anchors
    ):
        return SelectorScopeGuardResult(decision)
    card_by_ref = {
        str(item.get("ref") or ""): str(item.get("selector_summary") or "")
        for item in candidates
        if isinstance(item, Mapping)
    }
    semantic_flags_by_ref = {
        str(item.get("ref") or ""): dict(item.get("selector_semantic_flags") or {})
        for item in candidates
        if isinstance(item, Mapping)
    }
    candidate_by_ref = {
        str(item.get("ref") or ""): item
        for item in candidates
        if isinstance(item, Mapping)
    }
    searchable_by_ref = {
        str(item.get("ref") or ""): (
            f"{item.get('title') or ''} {item.get('selector_summary') or ''}".casefold()
        )
        for item in candidates
        if isinstance(item, Mapping)
    }
    guarded_assessments = []
    demoted_refs: list[str] = []
    for assessment in decision.assessments:
        card = card_by_ref.get(str(assessment.ref), "")
        card_question = ""
        if card.startswith(_CARD_QUESTION_PREFIX) and ": " in card:
            card_question = card[len(_CARD_QUESTION_PREFIX) :].split(": ", 1)[0]
        descriptive_mismatch = (
            explanatory_query
            and assessment.relevance != CandidateRelevance.IRRELEVANT
            and bool(card_question)
            and bool(_DESCRIPTIVE_CARD_QUESTION_RE.search(card_question))
            and not _OPERATIONAL_CARD_QUESTION_RE.search(card_question)
        )
        missing_answer_slot = (
            (answer_slot_query or comparison_obligations)
            and assessment.relevance != CandidateRelevance.IRRELEVANT
            and (
                selector_candidate_has_explicit_absence(
                    candidate_by_ref.get(str(assessment.ref), {})
                )
            )
        )
        observational_bound_mismatch = (
            bool(_NORMATIVE_BOUND_QUERY_RE.search(query))
            and assessment.relevance != CandidateRelevance.IRRELEVANT
            and semantic_flags_by_ref.get(str(assessment.ref), {}).get(
                "observational_value"
            )
            is True
        )
        named_subject_mismatch = (
            bool(subject_anchors)
            and assessment.relevance != CandidateRelevance.IRRELEVANT
            and not any(
                anchor in searchable_by_ref.get(str(assessment.ref), "")
                for anchor in subject_anchors
            )
        )
        should_demote = (
            descriptive_mismatch
            or missing_answer_slot
            or observational_bound_mismatch
            or named_subject_mismatch
        )
        if not should_demote:
            guarded_assessments.append(assessment)
            continue
        demoted_refs.append(str(assessment.ref))
        guarded_assessments.append(
            assessment.model_copy(
                update={
                    "relevance": CandidateRelevance.IRRELEVANT,
                    "role": SelectorRole.NONE,
                    "resolution": SelectorResolution.NONE,
                    "confidence": min(float(assessment.confidence), 0.5),
                    "reason_code": CandidateReasonCode.TOPIC_ONLY,
                }
            )
        )
    if not demoted_refs:
        return SelectorScopeGuardResult(decision)

    selected_refs = {
        str(item.ref)
        for item in guarded_assessments
        if item.relevance != CandidateRelevance.IRRELEVANT
    }
    selected_sources = {
        source_id
        for candidate in mapping.candidates
        if candidate.ref in selected_refs
        for source_id in candidate.source_ids
    }
    guarded_dispositions = tuple(
        disposition.model_copy(
            update={
                "status": (
                    SourceDispositionStatus.SELECTED
                    if disposition.source_id in selected_sources
                    else SourceDispositionStatus.NO_RELEVANT_CANDIDATE
                    if disposition.status == SourceDispositionStatus.SELECTED
                    else disposition.status
                )
            }
        )
        for disposition in decision.source_dispositions
    )
    return SelectorScopeGuardResult(
        ContextSelectorDecision(
            assessments=tuple(guarded_assessments),
            source_dispositions=guarded_dispositions,
        ),
        tuple(sorted(demoted_refs)),
    )


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


class MatchedEvidenceExcerpt(BaseModel):
    """Bounded query-time evidence from an already ranked contextual hit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = MATCHED_EVIDENCE_SCHEMA
    text: str = Field(min_length=1, max_length=MATCHED_EVIDENCE_MAX_CHARS)
    digest: str = Field(pattern=r"^[a-f0-9]{16}$")
    node_type: str = Field(min_length=1, max_length=40)
    source_revision: int = Field(ge=1)
    rank: int = Field(ge=1)
    truncated: bool = False


class OpenedEvidenceExcerpt(BaseModel):
    """Bounded transport view of an ownership-checked full object read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = OPENED_EVIDENCE_SCHEMA
    text: str = Field(min_length=1, max_length=OPENED_EVIDENCE_MAX_CHARS)
    digest: str = Field(pattern=r"^[a-f0-9]{16}$")
    citation_path: str = Field(min_length=1, max_length=500)
    source_revision: int = Field(ge=1)
    owner_verified: bool
    status_verified: bool
    truncated: bool = False


def build_matched_evidence_excerpt(
    source_text: str,
    *,
    node_type: str,
    source_revision: int,
    rank: int,
    max_chars: int = MATCHED_EVIDENCE_MAX_CHARS,
) -> MatchedEvidenceExcerpt | None:
    """Bound a semantic retrieval hit without re-interpreting it lexically."""

    limit = max(80, min(MATCHED_EVIDENCE_MAX_CHARS, int(max_chars)))
    source = " ".join(str(source_text or "").split())
    if not source:
        return None
    truncated = len(source) > limit
    text_value = source[:limit].rstrip()
    if truncated:
        last_space = text_value.rfind(" ")
        if last_space >= limit // 2:
            text_value = text_value[:last_space]
    return MatchedEvidenceExcerpt(
        text=text_value,
        digest=hashlib.sha256(text_value.encode()).hexdigest()[:16],
        node_type=str(node_type or "contextual_chunk"),
        source_revision=max(1, int(source_revision or 1)),
        rank=max(1, int(rank or 1)),
        truncated=truncated,
    )


def build_opened_evidence_excerpt(
    source_text: str,
    *,
    citation_path: str,
    source_revision: int,
    owner_verified: bool,
    status_verified: bool,
    max_chars: int = OPENED_EVIDENCE_MAX_CHARS,
) -> OpenedEvidenceExcerpt | None:
    """Bound a verified full read while preserving its document structure."""

    limit = max(200, min(OPENED_EVIDENCE_MAX_CHARS, int(max_chars)))
    normalized_lines = [
        re.sub(r"[\t\f\v ]+", " ", line).strip()
        for line in str(source_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    lines: list[str] = []
    for line in normalized_lines:
        if line or (lines and lines[-1]):
            lines.append(line)
    source = "\n".join(lines).strip()
    path = str(citation_path or "").strip()
    if not source or not path or not owner_verified or not status_verified:
        return None
    truncated = len(source) > limit
    text_value = source[:limit].rstrip()
    if truncated:
        boundary = max(text_value.rfind("\n"), text_value.rfind(" "))
        if boundary >= limit // 2:
            text_value = text_value[:boundary].rstrip()
    return OpenedEvidenceExcerpt(
        text=text_value,
        digest=hashlib.sha256(text_value.encode()).hexdigest()[:16],
        citation_path=path,
        source_revision=max(1, int(source_revision or 1)),
        owner_verified=True,
        status_verified=True,
        truncated=truncated,
    )


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
        goal = str(source.get("query_goal") or question or "").strip()
        if goal:
            row.append(_neutralize_selector_data(goal[:240]))
        source_rows.append(row)

    parent_ids: dict[str, int] = {}
    parent_rows: list[list[Any]] = []
    candidate_rows: list[list[Any]] = []
    candidate_refs: list[str] = []
    candidate_mappings: list[SelectorCandidateMapping] = []
    include_semantic_flags = any(
        bool(dict(item.get("selector_semantic_flags") or {}).get("explicit_absence"))
        or bool(dict(item.get("selector_semantic_flags") or {}).get("observational_value"))
        or bool(dict(item.get("selector_semantic_flags") or {}).get("record_roles"))
        for item in candidates
        if isinstance(item, Mapping)
    )
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
        summary = str(candidate.get("selector_summary") or "")
        if len(summary) > summary_limit:
            raise ValueError(
                "selector_summary exceeds the transport limit; regenerate the card "
                "instead of truncating it"
            )
        matched_raw = candidate.get("matched_evidence")
        matched = (
            MatchedEvidenceExcerpt.model_validate(matched_raw)
            if isinstance(matched_raw, Mapping)
            else None
        )
        matched_block = ""
        if matched is not None:
            matched_block = (
                "\n<matched_evidence schema=\"v1\" digest=\""
                + matched.digest
                + "\" node=\""
                + _neutralize_selector_data(matched.node_type)
                + "\" revision=\""
                + str(matched.source_revision)
                + "\" rank=\""
                + str(matched.rank)
                + "\" truncated=\""
                + ("1" if matched.truncated else "0")
                + "\">"
                + _neutralize_selector_data(matched.text)
                + "</matched_evidence>"
            )
        opened_raw = candidate.get("opened_evidence")
        opened = (
            OpenedEvidenceExcerpt.model_validate(opened_raw)
            if isinstance(opened_raw, Mapping)
            else None
        )
        opened_block = ""
        if opened is not None:
            opened_block = (
                "\n<opened_evidence schema=\"v1\" digest=\""
                + opened.digest
                + "\" path=\""
                + _neutralize_selector_data(opened.citation_path)
                + "\" revision=\""
                + str(opened.source_revision)
                + "\" owner_verified=\"1\" status_verified=\"1\" truncated=\""
                + ("1" if opened.truncated else "0")
                + "\">"
                + _neutralize_selector_data(opened.text)
                + "</opened_evidence>"
            )
        data = (
            "<workspace_data>"
            + _neutralize_selector_data(title)
            + "\n"
            + _neutralize_selector_data(summary)
            + matched_block
            + opened_block
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
        candidate_row = [
            index,
            _KIND_CODE.get(str(candidate.get("kind") or ""), "u"),
            data,
            _ORIGIN_CODE.get(str(candidate.get("origin") or ""), "u"),
            float(score) if score is not None else None,
            [source_index[item] for item in member_source_ids],
            parent_index,
            [_FIDELITY_CODE.get(str(item), "u") for item in available],
        ]
        if include_semantic_flags:
            flags = dict(candidate.get("selector_semantic_flags") or {})
            roles = set(flags.get("record_roles") or ())
            candidate_row.append(
                "".join(
                    [
                        "a" if flags.get("explicit_absence") is True else "",
                        "d" if "draft_or_proposed" in roles else "",
                        "f" if "final_or_signed" in roles else "",
                        "o" if flags.get("observational_value") is True else "",
                    ]
                )
            )
        candidate_rows.append(candidate_row)

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
        "cc": [
            "i",
            "k",
            "data",
            "o",
            "score",
            "s",
            "p",
            "f",
            *(["x"] if include_semantic_flags else []),
        ],
        "c": candidate_rows,
    }
    obligations = _query_obligations(question)
    if obligations is not None:
        payload["ob"] = obligations
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
                    "pattern": "^(?:d[edcqumal]|s[edcmal]|i[txbs])[0-9]$",
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
        "Each 3-char code is relevance d|s|i, reason t|e|d|c|q|u|m|a|l|x|b|s, confidence 0..9. "
        "Reasons: e explicit, d necessary implication, c comparison; q/u/m/a/l specialized; "
        "irrelevant t subject, x predicate, b absent value, s insufficient/ambiguous. "
        "Assess subject, exact predicate and requested value independently; shared topic is insufficient. "
        "A mandatory rule deciding permission/safety is d without literal yes/no. Fill ob evidence_slots from "
        "cards; operation needs no card. For cross-record ob, c each explicit requested side; with both slots "
        "filled, s is invalid. x hints role but never proves it; x a supplies no value. "
        "A different named referent is i even when predicate/value match, unless q explicitly compares it."
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
        + " No indexes, refs, roles, resolutions, dispositions or prose."
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
        if not isinstance(value, str) or not re.fullmatch(
            r"[dsi][tedcqumalxbs][0-9]", value
        ):
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
    "SelectorScopeGuardResult",
    "SelectorValidationErrorCode",
    "build_opened_evidence_excerpt",
    "apply_selector_question_scope_guard",
    "decode_selector_transport_result",
    "decode_selector_transport_v1_result",
    "decode_selector_transport_v2_result",
    "encode_selector_transport",
    "render_selector_transport_output_requirements",
    "render_selector_transport_result_schema",
    "selector_transport_json_schema",
]
