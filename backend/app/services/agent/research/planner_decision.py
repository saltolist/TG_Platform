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

    selected_candidate_ids: tuple[str, ...] = Field(default=(), max_length=5)


class PlannerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_code: DecisionCode
    actions: tuple[PlannerAction, ...] = ()
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
        } and not self.actions:
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


def render_planner_schema() -> str:
    """Small prompt fragment kept stable for token/latency measurements."""

    return (
        '{"decision_code":"SEARCH_REQUIRED_SOURCE",'
        '"actions":[{"tool":"SearchNodes","args":{"query":"..."},"intent_id":"source-id"}],'
        '"state_updates":{},"confidence":0.9}'
    )


__all__ = [
    "DecisionCode",
    "PlannerAction",
    "PlannerDecision",
    "PlannerStateUpdates",
    "parse_planner_decision",
    "render_planner_schema",
]
