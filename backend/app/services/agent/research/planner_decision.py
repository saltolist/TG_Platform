"""Compact, bounded planner protocol for Workspace Agent phase 5.

The planner selects the next application action. Durable observations,
requirements and evidence stay in graph state; they are never required to be
echoed by the model.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.ai.rag_json import extract_json_object


class DecisionCode(StrEnum):
    USE_FAST_PATH = "USE_FAST_PATH"
    SEARCH_REQUIRED_SOURCE = "SEARCH_REQUIRED_SOURCE"
    READ_EXPLICIT_TARGET = "READ_EXPLICIT_TARGET"
    READ_TOP_CANDIDATES = "READ_TOP_CANDIDATES"
    HYDRATE_EVIDENCE_GAP = "HYDRATE_EVIDENCE_GAP"
    RESOLVE_AMBIGUITY = "RESOLVE_AMBIGUITY"
    PROPOSE_MUTATION = "PROPOSE_MUTATION"
    FINISH_READY = "FINISH_READY"
    FINISH_PARTIAL = "FINISH_PARTIAL"


class CandidateRelevance(StrEnum):
    DIRECT = "direct"
    SUPPORTING = "supporting"
    IRRELEVANT = "irrelevant"


class CandidateResolution(StrEnum):
    CARD = "card"
    FULL_TEXT = "full_text"


class ContextRole(StrEnum):
    TARGET = "target"
    SUPPORTING = "supporting"


class ContextResolution(StrEnum):
    CARD = "card"
    FULL_TEXT = "full_text"
    METADATA = "metadata"
    TEXT = "text"
    VISION = "vision"
    ANALYTICS = "analytics"


class ContextSelection(BaseModel):
    """ID-only selector output; content is always materialized by runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=3, max_length=240)
    role: ContextRole
    resolution: ContextResolution


class LegacyContextSelectorDecision(BaseModel):
    """Rollback-only positive-selection projection used by the v1 path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selections: tuple[ContextSelection, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> "LegacyContextSelectorDecision":
        refs = [item.ref for item in self.selections]
        if len(refs) != len(set(refs)):
            raise ValueError("selector contains duplicate refs")
        return self


class CandidateReasonCode(StrEnum):
    TOPIC_ONLY = "topic_only"
    EXACT_FACT = "exact_fact"
    DETAILED_SUMMARY = "detailed_summary"
    COMPARISON = "comparison"
    QUOTE = "quote"
    EDIT_SOURCE = "edit_source"
    ATTACHMENT_OR_MEDIA = "attachment_or_media"
    ANALYTICS = "analytics"
    LOW_CARD_QUALITY = "low_card_quality"
    UNRELATED_TOPIC = "unrelated_topic"
    AMBIGUOUS = "ambiguous"
    SEARCH_MORE = "search_more"


class SelectorRole(StrEnum):
    ANSWER_EVIDENCE = "answer_evidence"
    NONE = "none"


class SelectorResolution(StrEnum):
    NONE = "none"
    CARD = "card"
    FULL_TEXT = "full_text"
    METADATA = "metadata"
    TEXT = "text"
    VISION = "vision"
    ANALYTICS = "analytics"


class SourceDispositionStatus(StrEnum):
    SELECTED = "selected"
    NO_RELEVANT_CANDIDATE = "no_relevant_candidate"
    SEARCH_MORE = "search_more"
    AMBIGUOUS = "ambiguous"


class ContextSelectorAssessment(BaseModel):
    """The selector's complete semantic assessment of one visible ref."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=3, max_length=240)
    relevance: CandidateRelevance
    role: SelectorRole
    resolution: SelectorResolution
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: CandidateReasonCode

    @model_validator(mode="after")
    def validate_semantics(self) -> "ContextSelectorAssessment":
        if self.relevance == CandidateRelevance.IRRELEVANT:
            if self.role != SelectorRole.NONE or self.resolution != SelectorResolution.NONE:
                raise ValueError("irrelevant assessment requires role=none and resolution=none")
        elif self.role != SelectorRole.ANSWER_EVIDENCE or self.resolution == SelectorResolution.NONE:
            raise ValueError(
                "direct/supporting assessment requires role=answer_evidence and a resolution"
            )
        return self


class SourceDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=160)
    status: SourceDispositionStatus


class ContextSelectorDecision(BaseModel):
    """Canonical v2 selector output: every visible ref and source is explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessments: tuple[ContextSelectorAssessment, ...] = Field(max_length=16)
    source_dispositions: tuple[SourceDisposition, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "ContextSelectorDecision":
        refs = [item.ref for item in self.assessments]
        if len(refs) != len(set(refs)):
            raise ValueError("selector contains duplicate assessment refs")
        source_ids = [item.source_id for item in self.source_dispositions]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("selector contains duplicate source dispositions")
        return self


class CandidateAssessment(BaseModel):
    """One bounded semantic decision for one visible discovery candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=3, max_length=160)
    relevance: CandidateRelevance
    resolution: CandidateResolution
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_code: CandidateReasonCode


_READ_TOOLS = frozenset(
    {
        "SearchNodes",
        "SearchObjectChunks",
        "OpenPost",
        "OpenNote",
        "ListPosts",
        "ListPostNotes",
        "ListGlobalNotes",
        "ListNoteAttachments",
        "ListPostMedia",
        "HydrateAttachment",
        "GetPostAnalytics",
        "ResolveObjects",
        "SearchObjects",
        "OpenObjects",
        "HydrateAttachments",
        "ReadAnalytics",
    }
)


class PlannerAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str = Field(min_length=1, max_length=48)
    args: dict[str, Any] = Field(default_factory=dict)
    intent_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_tool(self) -> "PlannerAction":
        if self.tool not in _READ_TOOLS:
            raise ValueError(f"unsupported planner tool: {self.tool}")
        return self


class PlannerStateUpdates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Compatibility projection for phase-5 checkpoints. Adaptive evidence depth
    # persists the richer assessment list in ``material_plan`` instead.
    selected_candidate_ids: tuple[str, ...] = Field(default=(), max_length=16)
    candidate_assessments: tuple[CandidateAssessment, ...] = Field(
        default=(), max_length=16
    )


class PlannerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_code: DecisionCode
    actions: tuple[PlannerAction, ...] = ()
    assessments: tuple[CandidateAssessment, ...] = Field(default=(), max_length=16)
    # Alternate explicit name accepted for replay/checkpoint producers.
    candidate_assessments: tuple[CandidateAssessment, ...] = Field(
        default=(), max_length=16
    )
    state_updates: PlannerStateUpdates = Field(default_factory=PlannerStateUpdates)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_shape(self) -> "PlannerDecision":
        if len(self.actions) > 3:
            raise ValueError("planner decision may contain at most three actions")
        signatures = {
            json.dumps({"tool": item.tool, "args": item.args}, sort_keys=True, default=str)
            for item in self.actions
        }
        if len(signatures) != len(self.actions):
            raise ValueError("planner decision contains duplicate actions")
        if self.decision_code in {
            DecisionCode.FINISH_READY,
            DecisionCode.FINISH_PARTIAL,
            DecisionCode.USE_FAST_PATH,
            DecisionCode.RESOLVE_AMBIGUITY,
        } and self.actions:
            raise ValueError(f"{self.decision_code} cannot contain actions")
        if self.decision_code not in {
            DecisionCode.FINISH_READY,
            DecisionCode.FINISH_PARTIAL,
            DecisionCode.USE_FAST_PATH,
            DecisionCode.RESOLVE_AMBIGUITY,
        } and not self.actions and not (
            self.assessments
            or self.candidate_assessments
            or self.state_updates.candidate_assessments
        ):
            raise ValueError(f"{self.decision_code} requires an action")
        return self


def parse_planner_decision(raw: str) -> PlannerDecision | None:
    """Parse exactly one compact decision; malformed output is rejected once."""

    payload = extract_json_object(raw or "")
    if not isinstance(payload, Mapping):
        return None
    try:
        return PlannerDecision.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return None


def parse_context_selector_decision(raw: str) -> ContextSelectorDecision | None:
    payload = extract_json_object(raw or "")
    if not isinstance(payload, Mapping):
        return None
    try:
        return ContextSelectorDecision.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return None


def parse_legacy_context_selector_decision(raw: str) -> LegacyContextSelectorDecision | None:
    payload = extract_json_object(raw or "")
    if not isinstance(payload, Mapping):
        return None
    try:
        return LegacyContextSelectorDecision.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return None


def render_context_selector_schema() -> str:
    return (
        '{"assessments":[{"ref":"post:ID","relevance":"direct",'
        '"role":"answer_evidence","resolution":"card","confidence":0.94,'
        '"reason_code":"topic_only"},{"ref":"note:ID","relevance":"irrelevant",'
        '"role":"none","resolution":"none","confidence":0.97,'
        '"reason_code":"unrelated_topic"}],"source_dispositions":['
        '{"source_id":"workspace-posts","status":"selected"},'
        '{"source_id":"workspace-notes","status":"no_relevant_candidate"}]}'
    )


def render_legacy_context_selector_schema() -> str:
    return (
        '{"selections":[{"ref":"post:ID","role":"target",'
        '"resolution":"card"},{"ref":"note:ID","role":"supporting",'
        '"resolution":"full_text"}]}'
    )


def render_planner_schema() -> str:
    """Small prompt fragment kept stable for token/latency measurements."""

    return (
        '{"decision_code":"SEARCH_REQUIRED_SOURCE",'
        '"actions":[{"tool":"SearchNodes","args":{"query":"..."},"intent_id":"source-id"}],'
        '"assessments":[{"ref":"note:ID","relevance":"direct",'
        '"resolution":"card","confidence":0.9,"reason_code":"topic_only"}],'
        '"state_updates":{},"confidence":0.9}'
    )


__all__ = [
    "DecisionCode",
    "CandidateAssessment",
    "CandidateReasonCode",
    "CandidateRelevance",
    "CandidateResolution",
    "ContextResolution",
    "ContextRole",
    "ContextSelection",
    "ContextSelectorDecision",
    "ContextSelectorAssessment",
    "LegacyContextSelectorDecision",
    "SelectorResolution",
    "SelectorRole",
    "SourceDisposition",
    "SourceDispositionStatus",
    "PlannerAction",
    "PlannerDecision",
    "PlannerStateUpdates",
    "parse_planner_decision",
    "parse_context_selector_decision",
    "parse_legacy_context_selector_decision",
    "render_context_selector_schema",
    "render_legacy_context_selector_schema",
    "render_planner_schema",
]
