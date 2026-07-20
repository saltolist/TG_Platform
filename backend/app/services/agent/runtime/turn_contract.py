"""Deterministic per-turn goal and referent contract.

The LLM still decides how to phrase an answer, but it must not decide which
object words such as "this note" or "their posts" refer to from scratch in
every node.  This module extracts the stable parts once and threads them
through classifier, research and answer generation.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.ai.chat_history import linearize_for_llm

_POST_IDEA_RE = re.compile(
    r"\bпост(?:ом|а|у|е)?\s*(\d+)\s*[—-]\s*[«\"]?([^»\"\n,.]+(?:[,:][^»\"\n]+)?)",
    re.IGNORECASE,
)
_POST_REFERENT_RE = re.compile(r"\b(эт\w*|этому|этого|этот|он|его)\s+пост|\bэтому\s*$", re.I)
_NOTE_REFERENT_RE = re.compile(
    r"\b(эт\w*\s+заметк\w*|эту\s+заметк\w*|про\s+заметк\w*|"
    r"создал\w*\s+заметк\w*|добавил\w*\s+(?:ее|её)|прочитай\w*\s+(?:ее|её)|"
    r"посмотри\w*\s+на\s+(?:эту|нее|неё)|что\s+там|пример\w*\s+.*\s+там)\b",
    re.I,
)

SUPPORTED_CAPABILITIES = (
    "read posts, notes, attachments, comments and post analytics",
    "create, edit, schedule, publish, delete and restore posts via approval",
    "generate and attach media via approval",
)

TURN_CONTRACT_SCHEMA = "workspace.turn/v2"
TARGET_CONTRACT_SCHEMA = "workspace.target/v2"
REFERENT_RESOLUTION_SCHEMA = "workspace.referent-resolution/v1"

TargetRole = Literal["subject", "source", "comparison", "style_reference", "context"]
TargetMode = Literal["exact", "set", "corpus", "mixed", "ambiguous"]
ExecutionMode = Literal["fast", "compact", "deep", "batch"]
SourceKind = Literal["notes", "posts", "analytics", "comments", "attachments", "images", "dialog"]
SourceRole = Literal["source", "comparison", "style_reference", "context"]


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TargetRef(_ContractModel):
    kind: Literal["note", "post", "dialog_artifact"]
    id: str = Field(min_length=1)
    role: TargetRole = "subject"
    authoritative: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    resolved_by: Literal[
        "explicit_id",
        "explicit_link",
        "open_object",
        "recent_object",
        "dialog_ledger",
        "dialog_artifact",
        "semantic_resolver",
    ]
    source_turn_id: str | None = None
    source_user_text: str | None = None
    title: str | None = None
    parent_post_id: str | None = None
    content: str | None = None


class CorpusRef(_ContractModel):
    kind: Literal["workspace", "feed_posts"]
    role: TargetRole
    scope: Literal["current_user"] = "current_user"


class TargetAmbiguity(_ContractModel):
    kind: Literal["note", "post"]
    candidate_ids: tuple[str, ...] = Field(min_length=2)
    reason: str = Field(min_length=1)
    question: str = Field(min_length=1)


class ResolutionEvent(_ContractModel):
    target_id: str
    target_kind: Literal["note", "post", "dialog_artifact"]
    resolved_by: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_turn_id: str | None = None


class ReferentReference(_ContractModel):
    mention: str = Field(min_length=1)
    target_type: Literal["entity", "entity_set", "artifact"]
    source_set_ref: str | None = None
    target_ids: tuple[str, ...] = ()
    selection_mode: Literal[
        "all", "explicit_subset", "predicate", "complement", "ambiguous"
    ]
    interpretation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ReferentResolution(_ContractModel):
    resolution_schema: Literal["workspace.referent-resolution/v1"] = Field(
        default=REFERENT_RESOLUTION_SCHEMA, alias="schema"
    )
    references: tuple[ReferentReference, ...] = ()
    unresolved: tuple[str, ...] = ()
    ambiguity: dict[str, Any] | None = None


class TargetContract(_ContractModel):
    contract_schema: Literal["workspace.target/v2"] = Field(
        default=TARGET_CONTRACT_SCHEMA, alias="schema"
    )
    revision: int = Field(ge=1)
    contract_id: str = Field(min_length=1)
    target_mode: TargetMode
    targets: tuple[TargetRef, ...] = ()
    corpora: tuple[CorpusRef, ...] = ()
    ambiguities: tuple[TargetAmbiguity, ...] = ()
    resolution_events: tuple[ResolutionEvent, ...] = ()
    referent_resolution: ReferentResolution = Field(default_factory=ReferentResolution)

    @model_validator(mode="after")
    def validate_mode(self) -> "TargetContract":
        keys = [(item.kind, item.id) for item in self.targets]
        if len(keys) != len(set(keys)):
            raise ValueError("target ids must be unique per kind")
        if self.target_mode == "exact" and (len(self.targets) != 1 or self.corpora):
            raise ValueError("exact mode requires one target and no corpora")
        if self.target_mode == "set" and (len(self.targets) < 2 or self.corpora):
            raise ValueError("set mode requires multiple targets and no corpora")
        if self.target_mode == "corpus" and (self.targets or not self.corpora):
            raise ValueError("corpus mode requires corpora and no targets")
        if self.target_mode == "mixed" and (not self.targets or not self.corpora):
            raise ValueError("mixed mode requires targets and corpora")
        if self.target_mode == "ambiguous" and not self.ambiguities:
            raise ValueError("ambiguous mode requires ambiguity details")
        event_keys = {(item.target_kind, item.target_id) for item in self.resolution_events}
        if any((item.kind, item.id) not in event_keys for item in self.targets):
            raise ValueError("every target requires a resolution event")
        return self


class SourceScope(_ContractModel):
    mode: Literal["targets", "corpus"]
    target_ids: tuple[str, ...] = ()
    corpus: Literal["workspace", "feed_posts"] | None = None
    owner: Literal["current_user"] = "current_user"
    statuses: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> "SourceScope":
        if self.mode == "targets" and (not self.target_ids or self.corpus is not None):
            raise ValueError("target scope requires target_ids only")
        if self.mode == "corpus" and (self.target_ids or self.corpus is None):
            raise ValueError("corpus scope requires corpus only")
        return self


class Freshness(_ContractModel):
    mode: Literal["exact_revision", "latest_available", "max_age", "historical_snapshot"]
    revision: int | None = Field(default=None, ge=1)
    max_age_seconds: int | None = Field(default=None, ge=0)
    snapshot_at: str | None = None

    @model_validator(mode="after")
    def validate_freshness(self) -> "Freshness":
        if self.mode == "exact_revision" and self.revision is None:
            raise ValueError("exact_revision requires revision")
        if self.mode == "max_age" and self.max_age_seconds is None:
            raise ValueError("max_age requires max_age_seconds")
        if self.mode == "historical_snapshot" and not self.snapshot_at:
            raise ValueError("historical_snapshot requires snapshot_at")
        return self


class SourceBudget(_ContractModel):
    search_calls: int = Field(ge=0)
    rewrite_calls: int = Field(ge=0)
    candidate_limit: int = Field(ge=1)
    deep_reads: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_rewrites(self) -> "SourceBudget":
        if self.rewrite_calls > self.search_calls:
            raise ValueError("rewrite_calls cannot exceed search_calls")
        return self


class SourceRequirement(_ContractModel):
    source_id: str = Field(min_length=1)
    kind: SourceKind
    role: SourceRole
    required: bool
    query_goal: str = Field(min_length=1)
    min_evidence: int = Field(default=1, ge=1, le=8)
    coverage: Literal["relevant", "complete"] = "relevant"
    evidence_granularity: Literal["catalog", "semantic_card", "full_text"] = "full_text"
    scope: SourceScope
    freshness: Freshness
    budget: SourceBudget


class RunBudget(_ContractModel):
    soft_deadline_ms: int = Field(gt=0)
    hard_deadline_ms: int = Field(gt=0)
    planner_calls: int = Field(ge=0)
    search_calls: int = Field(ge=0)
    search_rewrites_per_intent: int = Field(ge=0)
    deep_reads: int = Field(ge=0)
    tool_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_deadlines(self) -> "RunBudget":
        if self.soft_deadline_ms > self.hard_deadline_ms:
            raise ValueError("soft deadline cannot exceed hard deadline")
        return self


class TurnContractV2(_ContractModel):
    contract_schema: Literal["workspace.turn/v2"] = Field(
        default=TURN_CONTRACT_SCHEMA, alias="schema"
    )
    version: Literal[2] = 2
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    goal: str = Field(min_length=1)
    task_profile: Literal[
        "exact_lookup",
        "topical_answer",
        "workspace_synthesis",
        "recommendation",
        "comparison",
        "exhaustive_inventory",
        "artifact_revision",
        "channel_profile_draft",
        "mutation_proposal",
    ]
    target_contract_ref: str
    target_contract: TargetContract
    source_requirements: tuple[SourceRequirement, ...]
    evidence_requirements: tuple[str, ...]
    answer_requires: tuple[str, ...]
    output_schema: str
    execution_mode: ExecutionMode
    budgets: RunBudget
    # Compatibility fields consumed by the current graph during the phased rollout.
    intent: str
    scope: str
    corpus: str
    target: dict[str, Any] | None
    output: dict[str, Any]
    requires_workspace: bool
    required_evidence_kinds: tuple[str, ...]
    search_query: str
    max_steps: int
    success_criteria: tuple[str, ...]
    supported_capabilities: tuple[str, ...]
    prohibited_recommendations: tuple[str, ...]
    answerability_without_evidence: bool

    @model_validator(mode="after")
    def validate_source_budgets(self) -> "TurnContractV2":
        source_ids = [source.source_id for source in self.source_requirements]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id must be unique")
        if sum(source.budget.search_calls for source in self.source_requirements) > self.budgets.search_calls:
            raise ValueError("local search budgets exceed run budget")
        if sum(source.budget.deep_reads for source in self.source_requirements) > self.budgets.deep_reads:
            raise ValueError("local deep-read budgets exceed run budget")
        if any(
            source.budget.rewrite_calls > self.budgets.search_rewrites_per_intent
            for source in self.source_requirements
        ):
            raise ValueError("local rewrite budget exceeds per-intent run budget")
        if self.execution_mode == "fast" and self.budgets.planner_calls != 0:
            raise ValueError("fast mode cannot spend planner calls")
        return self


def _dialog_pairs(history: list[Mapping[str, Any]] | None) -> list[tuple[str, str]]:
    # Preserve a leading assistant artifact as well: imported/branched histories
    # can legitimately start at a generated draft even though the conversational
    # prompt later filters roles for alternation.
    return linearize_for_llm(history or [])


def _last_text(pairs: list[tuple[str, str]], role: str) -> str:
    for item_role, text in reversed(pairs):
        if item_role == role and text.strip():
            return text.strip()
    return ""


def _working_post_artifact(
    pairs: list[tuple[str, str]],
    *,
    prefer_longest: bool = False,
) -> str:
    """Return the latest full draft-like assistant artifact, without truncation."""
    candidates: list[str] = []
    for role, text in reversed(pairs):
        if role != "assistant":
            continue
        stripped = text.strip()
        if len(stripped) >= 500 and stripped.count("\n\n") >= 2:
            if not prefer_longest:
                return stripped[:12000]
            candidates.append(stripped[:12000])
    return max(candidates, key=len, default="")


def _ledger_artifact(
    dialog_ledger: tuple[Any, ...],
    *,
    post_draft_only: bool = False,
    prefer_longest: bool = False,
) -> str:
    """Return the latest full assistant artifact kept outside clipped history."""
    candidates: list[str] = []
    for turn in reversed(dialog_ledger):
        for entity in reversed(tuple(getattr(turn, "entities", ()) or ())):
            entity_type = str(getattr(entity, "entity_type", "") or "")
            if post_draft_only and entity_type != "post_draft":
                continue
            content = str(getattr(entity, "content", "") or "").strip()
            if content:
                if not prefer_longest:
                    return content[:12000]
                candidates.append(content[:12000])
    return max(candidates, key=len, default="")


def _ledger_artifact_context(
    dialog_ledger: tuple[Any, ...],
    *,
    content: str,
) -> tuple[str | None, str | None]:
    """Return the turn and user goal that produced a ledger artifact."""

    wanted = str(content or "").strip()
    if not wanted:
        return None, None
    for turn in reversed(dialog_ledger):
        for entity in reversed(tuple(getattr(turn, "entities", ()) or ())):
            if str(getattr(entity, "content", "") or "").strip() != wanted:
                continue
            return (
                str(getattr(turn, "turn_id", "") or "").strip() or None,
                str(getattr(turn, "user_text", "") or "").strip() or None,
            )
    return None, None


def _history_artifact_user_text(
    pairs: list[tuple[str, str]],
    *,
    content: str,
) -> str | None:
    """Return the user message immediately governing an assistant artifact."""

    wanted = str(content or "").strip()
    for index in range(len(pairs) - 1, -1, -1):
        role, text = pairs[index]
        if role != "assistant" or text.strip() != wanted:
            continue
        for prior in range(index - 1, -1, -1):
            prior_role, prior_text = pairs[prior]
            if prior_role == "user" and prior_text.strip():
                return prior_text.strip()
    return None


def _post_idea_label(text: str) -> str:
    match = _POST_IDEA_RE.search(text or "")
    if not match:
        return ""
    title = " ".join(match.group(2).strip(" «»\"").split())
    return f"Пост {match.group(1)} — {title}" if title else f"Пост {match.group(1)}"


def _clean_note_title(value: Any) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    # BlockNote imports can repeat the document heading several times.  A
    # repeated title is one title, not five separate semantic signals.
    return lines[0]


def _recent_note_target(
    *,
    user_text: str,
    pairs: list[tuple[str, str]],
    recent_note: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not recent_note:
        return None
    recent_users = "\n".join(text for role, text in pairs[-8:] if role == "user")
    creation_context = f"{recent_users}\n{user_text}"
    has_creation_context = bool(
        re.search(r"\b(создал|добавил)\w*\s+(?:эту\s+)?заметк", creation_context, re.I)
    )
    title = _clean_note_title(recent_note.get("title"))
    title_tokens = {
        token[:6]
        for token in re.findall(r"[\w-]+", title.lower())
        if len(token) >= 5
    }
    context_tokens = {
        token[:6]
        for token in re.findall(r"[\w-]+", f"{recent_users}\n{user_text}".lower())
        if len(token) >= 5
    }
    has_named_note_context = bool(
        title_tokens
        and len(title_tokens & context_tokens) >= min(2, len(title_tokens))
    )
    if not (
        _NOTE_REFERENT_RE.search(user_text)
        and (has_creation_context or has_named_note_context)
    ):
        return None
    note_id = str(recent_note.get("id") or "").strip()
    if not note_id:
        return None
    return {
        "kind": "recent_note",
        "id": note_id,
        "title": title or note_id,
        "created_at": str(recent_note.get("created_at") or ""),
        "authoritative": True,
    }


def _ledger_note_target(
    *,
    user_text: str,
    dialog_ledger: tuple[Any, ...],
) -> dict[str, Any] | None:
    if not _NOTE_REFERENT_RE.search(user_text or ""):
        return None
    for turn in reversed(dialog_ledger):
        for entity in reversed(tuple(getattr(turn, "entities", ()) or ())):
            if str(getattr(entity, "entity_type", "")) != "note":
                continue
            note_id = str(getattr(entity, "note_id", "") or "").strip()
            if not note_id:
                continue
            return {
                "kind": "ledger_note",
                "id": note_id,
                "title": str(getattr(entity, "title", "") or note_id),
                "authoritative": True,
            }
    return None


_EXPLICIT_POST_LINK_RE = re.compile(r"(?:https?://[^\s)]+)?(/post/([\w-]+)/?)", re.I)
_EXPLICIT_NOTE_LINK_RE = re.compile(
    r"(?:https?://[^\s)]+)?/note/(?:post/([\w-]+)/|global/)([\w-]+)/?", re.I
)
_EXPLICIT_ID_RE = re.compile(
    r"\b(?P<label>пост(?:а|у|ом|е)?|post|заметк(?:а|у|е|ой)?|note)\s*[#№:]?\s*(?P<id>[A-Za-z0-9][A-Za-z0-9_-]{1,127})\b",
    re.I,
)


def _stable_artifact_id(content: str) -> str:
    return f"artifact:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:24]}"


def _post_title_from_text(text: str) -> str:
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line[:160]


def _explicit_targets(user_text: str) -> list[dict[str, Any]]:
    """Extract only high-confidence links/IDs; semantic hits never enter here."""
    text = user_text or ""
    found: list[tuple[int, dict[str, Any]]] = []
    occupied: list[tuple[int, int]] = []
    for match in _EXPLICIT_NOTE_LINK_RE.finditer(text):
        post_id, note_id = match.group(1), match.group(2)
        found.append((match.start(), {
            "kind": "note", "id": note_id, "role": "subject", "authoritative": True,
            "confidence": 1.0, "resolved_by": "explicit_link", "parent_post_id": post_id,
        }))
        occupied.append((match.start(), match.end()))
    for match in _EXPLICIT_POST_LINK_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        found.append((match.start(), {
            "kind": "post", "id": match.group(2), "role": "subject", "authoritative": True,
            "confidence": 1.0, "resolved_by": "explicit_link",
        }))
        occupied.append((match.start(), match.end()))
    for match in _EXPLICIT_ID_RE.finditer(text):
        label = match.group("label").lower()
        identifier = match.group("id")
        # Bare short tokens ("заметка n1") are often titles/labels in prose,
        # not authoritative IDs. Explicit links, UUIDs, numeric Telegram IDs and
        # longer opaque IDs are high-confidence; short tokens remain planner
        # candidates and must be opened before becoming evidence.
        if not (identifier.isdigit() or len(identifier) >= 8 or "-" in identifier):
            continue
        kind = "post" if label.startswith(("пост", "post")) else "note"
        item = {
            "kind": kind, "id": identifier, "role": "subject", "authoritative": True,
            "confidence": 1.0, "resolved_by": "explicit_id",
        }
        if not any(existing[1]["kind"] == kind and existing[1]["id"] == item["id"] for existing in found):
            found.append((match.start(), item))
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for _position, item in sorted(found, key=lambda pair: pair[0]):
        unique.setdefault((item["kind"], item["id"]), item)
    return list(unique.values())


def _is_referential_text(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    return bool(
        _POST_REFERENT_RE.search(lowered)
        or _NOTE_REFERENT_RE.search(lowered)
        or any(
            marker in lowered
            for marker in ("это", "эти", "них", "ней", "неё", "предыдущ", "в этом пост")
        )
    )


def _ledger_targets(*, user_text: str, dialog_ledger: tuple[Any, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve referential turns to durable entities, preserving multi-targets."""
    if not _is_referential_text(user_text):
        return [], []
    plural = bool(re.search(r"\b(эти|этих|них|обоих|обеих|все|нескольк|посты|заметки)\b", user_text.lower()))
    for turn in reversed(dialog_ledger):
        candidates: list[dict[str, Any]] = []
        for entity in tuple(getattr(turn, "entities", ()) or ()):
            kind = str(getattr(entity, "entity_type", "") or "")
            if kind == "entity_set":
                for raw_member in tuple(getattr(entity, "members", ()) or ()):
                    if not isinstance(raw_member, Mapping):
                        continue
                    member_kind = str(raw_member.get("kind") or "")
                    member_id = str(raw_member.get("id") or "").strip()
                    if member_kind not in {"note", "post"} or not member_id:
                        continue
                    candidates.append({
                        "kind": member_kind,
                        "id": member_id,
                        "role": "subject",
                        "authoritative": True,
                        "confidence": 1.0,
                        "resolved_by": "dialog_ledger",
                        "source_turn_id": str(getattr(turn, "turn_id", "") or "") or None,
                        "title": str(raw_member.get("title") or "") or None,
                    })
                continue
            if kind not in {"note", "post"}:
                continue
            entity_id = str(getattr(entity, f"{kind}_id", "") or "").strip()
            if not entity_id:
                continue
            candidates.append({
                "kind": kind, "id": entity_id, "role": "subject", "authoritative": True,
                "confidence": 0.98, "resolved_by": "dialog_ledger",
                "source_turn_id": str(getattr(turn, "turn_id", "") or "") or None,
                "title": str(getattr(entity, "title", "") or "") or None,
            })
        prior_turn_contract = getattr(turn, "turn_contract", None)
        if isinstance(prior_turn_contract, Mapping):
            prior_targets = (prior_turn_contract.get("target_contract") or {}).get("targets") or []
            for raw in prior_targets:
                kind = str(raw.get("kind") or "")
                entity_id = str(raw.get("id") or "").strip()
                if kind not in {"note", "post"} or not entity_id:
                    continue
                if any(item["kind"] == kind and item["id"] == entity_id for item in candidates):
                    continue
                candidates.append({
                    "kind": kind, "id": entity_id, "role": str(raw.get("role") or "subject"),
                    "authoritative": True, "confidence": 0.98, "resolved_by": "dialog_ledger",
                    "source_turn_id": str(getattr(turn, "turn_id", "") or "") or None,
                    "title": raw.get("title"), "parent_post_id": raw.get("parent_post_id"),
                })
        if not candidates:
            continue
        if plural or len(candidates) == 1:
            return candidates, []
        return [], [{
            "kind": candidates[0]["kind"], "candidate_ids": [item["id"] for item in candidates],
            "reason": "несколько равноправных объектов в последнем контексте",
            "question": "Какой именно объект использовать?",
        }]
    return [], []


def _target_contract_for(*, legacy: Mapping[str, Any], user_text: str, scope: str,
                         open_post: Mapping[str, Any] | None, dialog_ledger: tuple[Any, ...],
                         prior_contract: Mapping[str, Any] | None,
                         message_manifests: tuple[Mapping[str, Any], ...] = (),
                         semantic_referent_enabled: bool = True) -> TargetContract:
    from app.services.agent.runtime.referent_resolution import (
        candidate_envelope,
        previous_selection,
        resolve_from_candidates,
    )

    explicit = _explicit_targets(user_text)
    ambiguities_raw: list[dict[str, Any]] = []
    targets = explicit
    referent_resolution_raw: dict[str, Any] = {
        "schema": REFERENT_RESOLUTION_SCHEMA,
        "references": [],
        "unresolved": [],
        "ambiguity": None,
    }
    plural_referent = bool(
        re.search(
            r"\b(эти|этих|них|обоих|обеих|все|нескольк|посты|заметки)\b",
            user_text.lower(),
        )
    )
    if (
        not targets
        and scope == "post"
        and open_post
        and not _NOTE_REFERENT_RE.search(user_text)
        and not plural_referent
    ):
        post_id = str(open_post.get("id") or "").strip()
        if post_id:
            targets = [{
                "kind": "post", "id": post_id, "role": "subject", "authoritative": True,
                "confidence": 1.0, "resolved_by": "open_object",
                "title": _post_title_from_text(str(open_post.get("text") or "")) or None,
            }]
    legacy_target = dict(legacy.get("target") or {})
    if (
        not targets
        and legacy_target.get("kind") == "dialog_artifact"
        and legacy_target.get("authoritative", True)
    ):
        content = str(legacy_target.get("content") or "").strip()
        target_id = str(legacy_target.get("id") or "").strip() or _stable_artifact_id(content)
        targets = [{
            "kind": "dialog_artifact",
            "id": target_id,
            "role": "subject",
            "authoritative": True,
            "confidence": 0.95,
            "resolved_by": "dialog_artifact",
            "source_turn_id": legacy_target.get("source_turn_id"),
            "source_user_text": legacy_target.get("source_user_text"),
            "title": legacy_target.get("title") or legacy_target.get("label"),
            "content": content,
        }]
    if not targets:
        targets, ambiguities_raw = _ledger_targets(user_text=user_text, dialog_ledger=dialog_ledger)
    # Position/complement/implicit follow-ups are resolved against the bounded
    # ledger graph. No workspace search is performed here and no ID can be
    # introduced outside that graph.
    if (
        not targets
        and not ambiguities_raw
        and (dialog_ledger or message_manifests)
        and semantic_referent_enabled
    ):
        envelope = candidate_envelope(
            dialog_ledger=dialog_ledger,
            manifests=message_manifests,
            open_object=open_post,
        )
        artifact_followup = bool(
            re.search(
                r"\b(сократ\w*|короче|перепиш\w*|переформулир\w*|его|ответ)\b",
                user_text.casefold(),
            )
        )
        predicate_followup = bool(
            re.search(
                r"\b(?:посты|заметки)\s+(?:про|об|на\s+тему)\b",
                user_text.casefold(),
            )
        )
        resolution_envelope = (
            [item for item in envelope if item.get("kind") == "artifact"]
            if artifact_followup and any(item.get("kind") == "artifact" for item in envelope)
            else envelope
        )
        if resolution_envelope and (
            re.search(r"\b(перв\w*|втор\w*|трет\w*|четверт\w*|пят\w*|остальн\w*|кроме|эти|они|них|кажд\w*)\b", user_text.casefold())
            or artifact_followup
            or predicate_followup
            or len(resolution_envelope) == 1
        ):
            referent_resolution_raw = resolve_from_candidates(
                user_text,
                resolution_envelope,
                previous_selected_refs=previous_selection(dialog_ledger),
            )
            reference = next(iter(referent_resolution_raw.get("references") or ()), None)
            if isinstance(reference, Mapping) and reference.get("target_ids"):
                by_ref = {str(item.get("ref")): item for item in resolution_envelope}
                targets = []
                for target_ref in reference.get("target_ids") or ():
                    candidate = by_ref.get(str(target_ref))
                    if not candidate:
                        continue
                    candidate_kind = str(candidate.get("kind") or "")
                    kind, identifier = (
                        ("dialog_artifact", str(target_ref))
                        if candidate_kind == "artifact"
                        else str(target_ref).split(":", 1)
                    )
                    targets.append({
                        "kind": kind,
                        "id": identifier,
                        "role": "subject",
                        "authoritative": True,
                        "confidence": float(reference.get("confidence") or 0.0),
                        "resolved_by": "semantic_resolver",
                        "source_turn_id": candidate.get("source_turn_id"),
                        "title": candidate.get("title"),
                    })
            elif referent_resolution_raw.get("ambiguity"):
                ambiguity = referent_resolution_raw["ambiguity"]
                candidate_ids = [str(item) for item in ambiguity.get("candidate_ids") or ()]
                if len(candidate_ids) >= 2:
                    ambiguities_raw = [{
                        "kind": "post" if candidate_ids[0].startswith("post:") else "note",
                        "candidate_ids": [item.split(":", 1)[-1] for item in candidate_ids],
                        "reason": "semantic referent resolution is ambiguous",
                        "question": str(ambiguity.get("question") or "Уточните объект."),
                    }]
    if not targets and legacy.get("target"):
        raw = dict(legacy["target"])
        kind = "note" if raw.get("kind") in {"recent_note", "ledger_note"} else "dialog_artifact"
        target_id = str(raw.get("id") or "").strip() or _stable_artifact_id(str(raw.get("content") or ""))
        targets = [{
            "kind": kind, "id": target_id, "role": "subject" if kind != "dialog_artifact" else "context",
            "authoritative": bool(raw.get("authoritative", True)),
            "confidence": 1.0 if kind != "dialog_artifact" else 0.95,
            "resolved_by": "dialog_artifact" if kind == "dialog_artifact" else (
                "recent_object" if raw.get("kind") == "recent_note" else "dialog_ledger"
            ),
            "source_turn_id": raw.get("source_turn_id"), "title": raw.get("title") or raw.get("label"),
            "source_user_text": raw.get("source_user_text"),
            "content": raw.get("content"),
        }]
    corpora: list[CorpusRef] = []
    if legacy.get("corpus") == "feed_posts":
        corpora.append(CorpusRef(kind="feed_posts", role="comparison"))
    elif not targets and legacy.get("requires_workspace"):
        corpora.append(CorpusRef(kind="workspace", role="context"))
    ambiguities = tuple(TargetAmbiguity.model_validate(item) for item in ambiguities_raw)
    if ambiguities:
        target_mode: TargetMode = "ambiguous"
    elif targets and corpora:
        target_mode = "mixed"
    elif len(targets) == 1:
        target_mode = "exact"
    elif len(targets) > 1:
        target_mode = "set"
    else:
        target_mode = "corpus"
        if not corpora:
            corpora.append(CorpusRef(kind="workspace", role="context"))
    revision = int((prior_contract or {}).get("revision") or 0) + 1
    contract_id = f"turn:{uuid.uuid5(uuid.NAMESPACE_URL, f'{revision}:{user_text}:{scope}')}"
    refs = tuple(TargetRef.model_validate(item) for item in targets)
    events = tuple(ResolutionEvent(target_id=item.id, target_kind=item.kind,
                                   resolved_by=item.resolved_by, confidence=item.confidence,
                                   source_turn_id=item.source_turn_id) for item in refs)
    return TargetContract(
        revision=revision, contract_id=contract_id, target_mode=target_mode, targets=refs,
        corpora=tuple(corpora), ambiguities=ambiguities, resolution_events=events,
        referent_resolution=ReferentResolution.model_validate(referent_resolution_raw),
    )


def _is_exhaustive_request(value: str) -> bool:
    lowered = value.casefold()
    return any(
        marker in lowered
        for marker in (
            "проанализируй всё",
            "проанализируй все",
            "анализ всех",
            "инвентаризац",
            "перечисли всё",
            "перечисли все",
            "весь workspace",
            "всего workspace",
            "analyze all",
            "analyse all",
            "entire workspace",
            "exhaustive inventory",
        )
    )


def _task_profile(
    legacy: Mapping[str, Any],
    target_contract: TargetContract,
    *,
    batch_enabled: bool,
) -> str:
    intent = str(legacy.get("intent") or "answer")
    if batch_enabled and _is_exhaustive_request(str(legacy.get("search_query") or "")):
        return "exhaustive_inventory"
    if intent == "edit_post":
        return "mutation_proposal"
    if intent == "write_post":
        return "artifact_revision" if target_contract.targets else "workspace_synthesis"
    if intent == "compare_with_feed_posts":
        return "comparison"
    if target_contract.target_mode in {"exact", "set"}:
        return "exact_lookup"
    return "topical_answer"


def _source_requirements(
    legacy: Mapping[str, Any],
    target_contract: TargetContract,
    *,
    profile: str,
) -> tuple[SourceRequirement, ...]:
    sources: list[SourceRequirement] = []
    if profile == "exhaustive_inventory":
        return tuple(
            SourceRequirement(
                source_id=f"batch-workspace-{kind}",
                kind=kind,
                role="source",
                required=True,
                query_goal=f"materialize every current-user {kind} object",
                scope=SourceScope(mode="corpus", corpus="workspace"),
                freshness=Freshness(mode="latest_available"),
                budget=SourceBudget(
                    search_calls=0,
                    rewrite_calls=0,
                    candidate_limit=1,
                    deep_reads=0,
                ),
            )
            for kind in ("notes", "posts")
        )
    for index, target in enumerate(target_contract.targets, start=1):
        if target.kind not in {"note", "post"}:
            continue
        kind: SourceKind = "notes" if target.kind == "note" else "posts"
        sources.append(SourceRequirement(
            source_id=f"target-{target.kind}-{index}", kind=kind, role="source", required=True,
            query_goal=f"read the authoritative {target.kind} {target.id}",
            scope=SourceScope(mode="targets", target_ids=(target.id,)),
            freshness=Freshness(mode="latest_available"),
            budget=SourceBudget(search_calls=0, rewrite_calls=0, candidate_limit=1, deep_reads=1),
        ))
    corpus_kinds = {item.kind for item in target_contract.corpora}
    if "feed_posts" in corpus_kinds:
        role: SourceRole = "style_reference" if bool((legacy.get("output") or {}).get("match_reference_style")) else "comparison"
        sources.append(SourceRequirement(
            source_id="corpus-feed-posts", kind="posts", role=role, required=True,
            query_goal="find published feed posts relevant to the current goal",
            scope=SourceScope(mode="corpus", corpus="feed_posts", statuses=("published",)),
            freshness=Freshness(mode="latest_available"),
            budget=SourceBudget(search_calls=2, rewrite_calls=1, candidate_limit=5, deep_reads=2),
        ))
    if "workspace" in corpus_kinds:
        # Every ordinary answer turn gets bounded, source-separated discovery
        # over both primary workspace corpora. These requirements are optional
        # until the semantic classifier marks a source as factual/required;
        # discovery can therefore enrich a normal answer without turning an
        # empty workspace into a refusal.
        for kind in ("notes", "posts"):
            sources.append(SourceRequirement(
                source_id=f"workspace-{kind}", kind=kind, role="context",
                required=False,
                query_goal=f"find {kind} relevant to the current goal, if any",
                scope=SourceScope(mode="corpus", corpus="workspace"),
                freshness=Freshness(mode="latest_available"),
                budget=SourceBudget(
                    search_calls=1,
                    rewrite_calls=0,
                    candidate_limit=6,
                    deep_reads=3,
                ),
            ))
    return tuple(sources)


def _run_budget(*, profile: str, target_contract: TargetContract,
                sources: tuple[SourceRequirement, ...]) -> tuple[ExecutionMode, RunBudget]:
    if profile == "exhaustive_inventory":
        return "batch", RunBudget(
            soft_deadline_ms=30_000,
            hard_deadline_ms=60_000,
            planner_calls=0,
            search_calls=0,
            search_rewrites_per_intent=0,
            deep_reads=0,
            tool_calls=0,
        )
    exact_reads = sum(source.budget.deep_reads for source in sources)
    if profile == "exact_lookup" and target_contract.target_mode in {"exact", "set"}:
        return "fast", RunBudget(
            soft_deadline_ms=10_000, hard_deadline_ms=30_000, planner_calls=0,
            search_calls=0, search_rewrites_per_intent=0, deep_reads=max(1, exact_reads),
            tool_calls=max(2, exact_reads + 1),
        )
    local_search = sum(source.budget.search_calls for source in sources)
    local_reads = sum(source.budget.deep_reads for source in sources)
    return "compact", RunBudget(
        soft_deadline_ms=30_000, hard_deadline_ms=60_000, planner_calls=2,
        search_calls=max(3, local_search), search_rewrites_per_intent=1,
        deep_reads=max(3, local_reads), tool_calls=max(8, local_search + local_reads + 2),
    )


def _upgrade_contract_v2(*, legacy: dict[str, Any], user_text: str, scope: str,
                         open_post: Mapping[str, Any] | None, dialog_ledger: tuple[Any, ...],
                         prior_contract: Mapping[str, Any] | None,
                         batch_enabled: bool,
                         message_manifests: tuple[Mapping[str, Any], ...] = (),
                         semantic_referent_enabled: bool = True) -> dict[str, Any]:
    prior_target = dict((prior_contract or {}).get("target_contract") or {})
    target_contract = _target_contract_for(
        legacy=legacy, user_text=user_text, scope=scope, open_post=open_post,
        dialog_ledger=dialog_ledger, prior_contract=prior_target,
        message_manifests=message_manifests,
        semantic_referent_enabled=semantic_referent_enabled,
    )
    profile = _task_profile(legacy, target_contract, batch_enabled=batch_enabled)
    sources = _source_requirements(legacy, target_contract, profile=profile)
    execution_mode, budgets = _run_budget(profile=profile, target_contract=target_contract, sources=sources)
    revision = target_contract.revision
    prior_revision = int((prior_contract or {}).get("revision") or 0) or None
    goal = user_text.strip()
    if prior_contract and _is_referential_text(user_text) and len(goal) < 80:
        prior_goal = str(prior_contract.get("goal") or "").strip()
        if prior_goal:
            goal = f"{prior_goal}; follow-up: {goal}"
    compatibility = {**legacy, "version": 2}
    model = TurnContractV2(
        revision=revision, parent_revision=prior_revision, goal=goal or "respond to the current turn",
        task_profile=profile, target_contract_ref=target_contract.contract_id,
        target_contract=target_contract, source_requirements=sources,
        evidence_requirements=tuple(
            f"{source.source_id}:grounded_evidence" for source in sources if source.required
        ),
        answer_requires=tuple(str(item) for item in legacy.get("success_criteria") or ()),
        output_schema=(
            "exhaustive_inventory.v1"
            if profile == "exhaustive_inventory"
            else f"{(legacy.get('output') or {}).get('kind', 'answer')}.v1"
        ),
        answerability_without_evidence=not any(source.required for source in sources),
        execution_mode=execution_mode, budgets=budgets,
        **compatibility,
    )
    return model.model_dump(mode="json", by_alias=True)


def build_turn_contract(
    *,
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    scope: str,
    recent_note: Mapping[str, Any] | None = None,
    dialog_ledger: tuple[Any, ...] = (),
    open_post: Mapping[str, Any] | None = None,
    prior_contract: Mapping[str, Any] | None = None,
    message_manifests: tuple[Mapping[str, Any], ...] = (),
    semantic_referent_enabled: bool = True,
    v2_enabled: bool = True,
    batch_enabled: bool = True,
) -> dict[str, Any]:
    current = (user_text or "").strip()
    lowered = current.lower()
    pairs = _dialog_pairs(history)
    history_assistant = _last_text(pairs, "assistant")
    ledger_assistant = _ledger_artifact(dialog_ledger)
    last_assistant = ledger_assistant or history_assistant
    prefer_longest_artifact = any(
        marker in lowered
        for marker in ("размер уменьш", "слишком корот", "слишком маленьк")
    )
    working_artifact = (
        _working_post_artifact(pairs, prefer_longest=prefer_longest_artifact)
        or _ledger_artifact(
            dialog_ledger,
            post_draft_only=True,
            prefer_longest=prefer_longest_artifact,
        )
    )

    compare_posts = "пересека" in lowered and "пост" in lowered
    style_request = any(
        marker in lowered
        for marker in (
            "в их стиле",
            "в стиле моих пост",
            "именно в стиле",
            "как мои обычные",
            "как мои полные",
            "их верст",
            "их вёрст",
        )
    )
    feed_corpus = bool(
        compare_posts
        or style_request
        or ("пост" in lowered and any(m in lowered for m in ("имеющ", "из лент", "в лент", "которые у меня уже")))
    )
    write_post = bool(
        any(marker in lowered for marker in ("напиши текст", "напиши пост", "текст этого пост"))
        or ("напиши" in lowered and ("пост" in lowered or working_artifact))
    )
    inspect_note = "замет" in lowered and any(
        marker in lowered for marker in ("прочитай", "посмотри", "что написано", "что дальше", "добавил", "создал")
    )

    if style_request or write_post:
        intent = "write_post"
    elif compare_posts:
        intent = "compare_with_feed_posts"
    elif inspect_note:
        intent = "inspect_note"
    elif scope == "post" and any(
        marker in lowered
        for marker in (
            "добав", "убер", "удал", "сделай", "измени", "выдел", "жирн",
            "опубли", "заплан", "расплан", "отмен", "восстанов", "переформулир",
            "сократ", "перепиш", "исправ", "замен", "поменя", "оформ",
        )
    ):
        intent = "edit_post"
    else:
        intent = "answer"

    target = _recent_note_target(
        user_text=current,
        pairs=pairs,
        recent_note=recent_note,
    )
    if target is None:
        target = _ledger_note_target(
            user_text=current,
            dialog_ledger=dialog_ledger,
        )
    explicit_targets = _explicit_targets(current)
    if target is None and len(explicit_targets) == 1 and explicit_targets[0]["kind"] == "note":
        explicit = explicit_targets[0]
        target = {
            "kind": "recent_note",
            "id": explicit["id"],
            "title": explicit["id"],
            "authoritative": True,
        }
    if target is None and last_assistant and (
        _POST_REFERENT_RE.search(lowered) or "этого поста" in lowered or "этому посту" in lowered
    ):
        referent_content = working_artifact if write_post and working_artifact else last_assistant
        source_turn_id, source_user_text = _ledger_artifact_context(
            dialog_ledger,
            content=referent_content,
        )
        source_user_text = source_user_text or _history_artifact_user_text(
            pairs,
            content=referent_content,
        )
        label = _post_idea_label(referent_content)
        if not label and source_user_text and re.search(
            r"следующ\w*\s+пост|про\s+что\s+написать",
            source_user_text.casefold(),
        ):
            label = "рекомендованный следующий пост"
        target = {
            "kind": "dialog_artifact",
            "role": "assistant",
            "label": label or "предмет предыдущего ответа ассистента",
            "content": referent_content[:12000],
            "authoritative": True,
            "source_turn_id": source_turn_id,
            "source_user_text": source_user_text,
        }

    output: dict[str, Any] = {"kind": "answer"}
    if intent == "write_post":
        output = {
            "kind": "post_draft",
            "match_reference_style": style_request,
            "match_sentence_length": style_request,
            "preserve_paragraph_layout": style_request or "абзац" in lowered,
            "require_section_headings": "заголов" in lowered or style_request,
            "min_paragraphs": 5 if style_request or "абзац" in lowered else 2,
            "min_section_headings": 2 if "заголов" in lowered or style_request else 0,
        }
        if working_artifact:
            output["min_chars"] = max(400, int(len(working_artifact) * 0.9))
            output["working_artifact"] = working_artifact

    corpus = "feed_posts" if feed_corpus else "workspace"
    if target and target.get("kind") in {"recent_note", "ledger_note"}:
        corpus = "exact_note"

    # V2 always performs bounded workspace enrichment. Whether evidence is
    # mandatory for the answer is decided semantically by the classifier and
    # stored separately as answerability_without_evidence.
    requires_workspace = True if v2_enabled else bool(feed_corpus or target or inspect_note)
    if corpus in {"feed_posts", "exact_note"}:
        max_steps = 4
    elif target:
        max_steps = 6
    else:
        # Broad inventory questions may legitimately need the configured ten
        # steps. The no-progress guard, not a smaller blanket cap, stops loops.
        max_steps = 10

    success_criteria = ["answer the current user request, not a neighboring semantic topic"]
    if corpus == "feed_posts":
        success_criteria.append("use actual feed posts as evidence; planning notes are out of scope")
    if target:
        success_criteria.append("use only the authoritative referent as the target object")
    if output.get("kind") == "post_draft":
        success_criteria.append("satisfy the requested length, headings and paragraph layout")

    search_query = current
    if target and target.get("kind") == "dialog_artifact":
        search_query = f"{current}. Целевой материал: {target.get('label')}. {target.get('content', '')[:800]}"
    elif target and target.get("kind") in {"recent_note", "ledger_note"}:
        search_query = f"Открыть конкретную заметку {target.get('title')} ({target.get('id')})"

    legacy = {
        "version": 1,
        "intent": intent,
        "scope": scope,
        "corpus": corpus,
        "target": target,
        "output": output,
        "requires_workspace": requires_workspace,
        "required_evidence_kinds": ["post_text"] if corpus == "feed_posts" else [],
        "search_query": search_query,
        "max_steps": max_steps,
        "success_criteria": success_criteria,
        "supported_capabilities": list(SUPPORTED_CAPABILITIES),
        "prohibited_recommendations": [
            "link a note to posts or files",
            "claim a workspace mutation exists when it is not in supported_capabilities",
        ],
    }
    if not v2_enabled:
        return legacy
    return _upgrade_contract_v2(
        legacy=legacy,
        user_text=current,
        scope=scope,
        open_post=open_post,
        dialog_ledger=dialog_ledger,
        prior_contract=prior_contract,
        batch_enabled=batch_enabled,
        message_manifests=message_manifests,
        semantic_referent_enabled=semantic_referent_enabled,
    )


def render_turn_contract(contract: Mapping[str, Any] | None) -> str:
    if not contract:
        return "(контракт хода отсутствует)"
    return json.dumps(dict(contract), ensure_ascii=False, sort_keys=True)


def missing_required_sources(
    contract: Mapping[str, Any],
    satisfied_source_ids: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Return only required source gaps; optional sources never block ready."""
    return tuple(
        str(source.get("source_id") or "")
        for source in contract.get("source_requirements") or []
        if source.get("required")
        and str(source.get("source_id") or "") not in satisfied_source_ids
    )


_SOURCE_RECORD_KINDS: dict[str, frozenset[str]] = {
    "notes": frozenset({"note_chunk", "semantic_card"}),
    "posts": frozenset({"post_text", "semantic_card"}),
    "analytics": frozenset({"analytics"}),
    "comments": frozenset({"comment"}),
    "attachments": frozenset({"attachment_text", "media_meta"}),
    "images": frozenset({"vision", "media_meta"}),
    "dialog": frozenset(),
}


def _semantic_card_object_kind(evidence_id: str, record: Mapping[str, Any]) -> str:
    """Resolve the workspace object represented by a generic semantic card."""

    metadata = record.get("metadata") or {}
    explicit = str(record.get("object_kind") or metadata.get("object_kind") or "").strip()
    if explicit in {"note", "notes"}:
        return "notes"
    if explicit in {"post", "posts"}:
        return "posts"

    source_ref = str(record.get("source_ref") or metadata.get("ref") or "").strip("/")
    if source_ref.startswith("note:"):
        return "notes"
    if source_ref.startswith("post:"):
        return "posts"

    normalized_id = f"/{str(evidence_id).strip('/')}/"
    if normalized_id.startswith("/note/"):
        return "notes"
    if normalized_id.startswith("/post/"):
        return "posts"
    return ""


def evidence_matches_source(
    source: Mapping[str, Any],
    *,
    evidence_id: str,
    record: Mapping[str, Any],
) -> bool:
    """Revalidate source kind, immutable scope and freshness at evidence use."""
    source_kind = str(source.get("kind") or "")
    record_kind = str(record.get("kind") or "")
    granularity = str(source.get("evidence_granularity") or "full_text")
    if record_kind == "semantic_card":
        card_object_kind = _semantic_card_object_kind(evidence_id, record)
        if card_object_kind != source_kind:
            return False
    catalog_match = False
    if source_kind == "posts":
        catalog_match = record_kind == "catalog" and evidence_id.startswith("/posts/")
    elif source_kind == "notes":
        catalog_match = record_kind == "catalog" and (
            evidence_id == "/global/notes/" or evidence_id.endswith("/notes/")
        )
    if granularity == "catalog":
        if not catalog_match:
            return False
    else:
        allowed_kinds = _SOURCE_RECORD_KINDS.get(source_kind, frozenset())
        if not catalog_match and (not allowed_kinds or record_kind not in allowed_kinds):
            return False

    scope = source.get("scope") or {}
    if scope.get("mode") == "targets":
        target_ids = [str(item) for item in scope.get("target_ids") or []]
        if not any(f"/{target_id}/" in evidence_id for target_id in target_ids):
            return False
    elif scope.get("mode") == "corpus":
        corpus = str(scope.get("corpus") or "")
        if corpus == "feed_posts" and record_kind != "post_text":
            return False
    else:
        return False

    metadata = record.get("metadata") or {}
    statuses = {str(item) for item in scope.get("statuses") or []}
    record_status = str(metadata.get("status") or "")
    if statuses and record_status and record_status not in statuses:
        return False

    freshness = source.get("freshness") or {}
    mode = str(freshness.get("mode") or "latest_available")
    if mode == "exact_revision":
        return metadata.get("revision") == freshness.get("revision")
    if mode == "max_age":
        age = metadata.get("age_seconds")
        return isinstance(age, (int, float)) and age <= int(freshness.get("max_age_seconds") or 0)
    if mode == "historical_snapshot":
        return str(metadata.get("snapshot_at") or "") == str(freshness.get("snapshot_at") or "")
    return mode == "latest_available"


def covered_source_ids(
    contract: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
) -> frozenset[str]:
    covered: set[str] = set()
    for source in contract.get("source_requirements") or []:
        source_id = str(source.get("source_id") or "")
        matches = sum(
            1
            for evidence_id, record in records.items()
            if evidence_matches_source(source, evidence_id=evidence_id, record=record)
        )
        if source_id and matches >= int(source.get("min_evidence") or 1):
            covered.add(source_id)
    return frozenset(covered)
