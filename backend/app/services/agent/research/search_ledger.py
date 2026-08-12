"""Run-scoped search intent ledger and canonical read-tool identities.

The ledger is stored as plain JSON in ``AgentGraphState`` so LangGraph
checkpoints preserve dedupe decisions across node/session boundaries.  It owns
control-flow metadata only; evidence remains in ``evidence_records``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.agent.runtime.turn_contract import source_evidence_required

INTENT_STATES = frozenset({"planned", "running", "satisfied", "exhausted"})
TERMINAL_INTENT_STATES = frozenset({"satisfied", "exhausted"})
SEARCH_TOOLS = frozenset({"SearchNodes", "SearchObjectChunks"})

_SPACE_RE = re.compile(r"\s+")
_NODE_TYPE_ALIASES = {
    "note": "note_chunk",
    "notes": "note_chunk",
    "post": "post_text",
    "posts": "post_text",
    "attachment": "attachment_text",
    "attachments": "attachment_text",
    "media": "media_meta",
}


def _normalized_text(value: Any, *, fold_case: bool = False) -> str:
    text = _SPACE_RE.sub(" ", str(value or "").strip())
    return text.casefold() if fold_case else text


def _normalized_args(tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Return the semantic arguments used by signatures and intent keys."""
    raw = {
        str(key): value
        for key, value in args.items()
        if key not in {"source_requirement_id", "evidence_gap", "rewrite_of"}
    }
    if tool in SEARCH_TOOLS:
        raw["query"] = _normalized_text(raw.get("query"), fold_case=True)
        node_types = raw.get("node_types")
        if tool == "SearchNodes" and isinstance(node_types, (list, tuple, set, frozenset)):
            raw["node_types"] = sorted(
                {
                    _NODE_TYPE_ALIASES.get(_normalized_text(item, fold_case=True), _normalized_text(item, fold_case=True))
                    for item in node_types
                    if _normalized_text(item)
                }
            )
        elif tool == "SearchNodes":
            raw.pop("node_types", None)
        if tool == "SearchObjectChunks":
            object_ids = raw.get("object_ids")
            if isinstance(object_ids, (list, tuple, set, frozenset)):
                raw["object_ids"] = sorted(
                    {_normalized_text(item) for item in object_ids if _normalized_text(item)}
                )
            else:
                raw.pop("object_ids", None)
        raw["k"] = max(1, int(raw.get("k") or 4))
    elif tool == "HydrateAttachment":
        raw["ref"] = _normalized_text(raw.get("ref"), fold_case=True)
        raw["mode"] = _normalized_text(raw.get("mode") or "text", fold_case=True)
    elif tool == "GetPostAnalytics":
        raw["post_id"] = _normalized_text(raw.get("post_id"))
        raw["period"] = _normalized_text(raw.get("period") or "7d", fold_case=True)
    else:
        for key, value in list(raw.items()):
            if isinstance(value, str):
                raw[key] = _normalized_text(value, fold_case=key in {"query", "status"})
            elif value is None:
                raw.pop(key)
    return raw


def _source_requirement(
    contract: Mapping[str, Any] | None,
    source_requirement_id: str,
) -> dict[str, Any]:
    for source in (contract or {}).get("source_requirements") or ():
        if str(source.get("source_id") or "") == source_requirement_id:
            return dict(source)
    return {}


def resolve_source_requirement_id(
    contract: Mapping[str, Any] | None,
    *,
    tool: str,
    args: Mapping[str, Any],
) -> str:
    """Bind a tool intent to the narrowest matching SourceRequirement."""
    sources = [dict(item) for item in (contract or {}).get("source_requirements") or ()]
    explicit = _normalized_text(args.get("source_requirement_id"))
    valid_ids = {str(source.get("source_id") or "") for source in sources}
    if explicit and explicit in valid_ids:
        return explicit
    if not sources:
        return "unscoped"

    kind_by_tool = {
        "OpenNote": "notes",
        "ListGlobalNotes": "notes",
        "ListPostNotes": "notes",
        "OpenPost": "posts",
        "ListPosts": "posts",
        "ListPostMedia": "images",
        "ListNoteAttachments": "attachments",
        "HydrateAttachment": "attachments",
        "GetPostAnalytics": "analytics",
    }
    wanted_kind = kind_by_tool.get(tool)
    if tool in SEARCH_TOOLS:
        types = set(_normalized_args(tool, args).get("node_types") or ())
        if types and types <= {"note_chunk"}:
            wanted_kind = "notes"
        elif types and types <= {"post_text"}:
            wanted_kind = "posts"
        elif types and types <= {"attachment_text", "media_meta"}:
            wanted_kind = "attachments"

    object_id = _normalized_text(
        args.get("note_id") or args.get("post_id") or args.get("ref")
        or next(iter(args.get("object_ids") or ()), "")
    )
    if object_id:
        for source in sources:
            target_ids = {
                str(item) for item in (source.get("scope") or {}).get("target_ids") or ()
            }
            if object_id in target_ids:
                return str(source.get("source_id") or "unscoped")
    candidates = [source for source in sources if not wanted_kind or source.get("kind") == wanted_kind]
    if tool == "SearchNodes":
        searchable = [
            source
            for source in candidates
            if int((source.get("budget") or {}).get("search_calls") or 0) > 0
        ]
        if searchable:
            candidates = searchable
    required = [source for source in candidates if source_evidence_required(source)]
    selected = (required or candidates or sources)[0]
    return str(selected.get("source_id") or "unscoped")


def canonical_tool_signature(
    tool: str,
    args: Mapping[str, Any],
    *,
    source_requirement_id: str,
    contract: Mapping[str, Any] | None = None,
) -> str:
    """Hash a read call including source scope and freshness/revision."""
    source = _source_requirement(contract, source_requirement_id)
    payload = {
        "tool": tool,
        "args": _normalized_args(tool, args),
        "source_requirement_id": source_requirement_id,
        "scope": source.get("scope") or {},
        "freshness": source.get("freshness") or {},
        "target_revision": ((contract or {}).get("target_contract") or {}).get("revision"),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return "tool:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def semantic_intent_key(
    tool: str,
    args: Mapping[str, Any],
    *,
    source_requirement_id: str,
    contract: Mapping[str, Any] | None = None,
) -> str:
    signature = canonical_tool_signature(
        tool,
        args,
        source_requirement_id=source_requirement_id,
        contract=contract,
    )
    return "intent:" + signature.removeprefix("tool:")


def _search_family_key(
    tool: str,
    args: Mapping[str, Any],
    *,
    source_requirement_id: str,
    contract: Mapping[str, Any] | None,
) -> str:
    normalized = _normalized_args(tool, args)
    if tool in SEARCH_TOOLS:
        normalized.pop("query", None)
        normalized.pop("k", None)
    payload = {
        "tool": tool,
        "args": normalized,
        "source_requirement_id": source_requirement_id,
        "source": _source_requirement(contract, source_requirement_id),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return "family:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class IntentPreparation:
    ledger: list[dict[str, Any]]
    entry: dict[str, Any]
    execute: bool
    cached: bool = False


def prepare_intent(
    ledger: list[dict[str, Any]] | None,
    *,
    tool: str,
    args: Mapping[str, Any],
    contract: Mapping[str, Any] | None,
    evidence_gap: str = "",
) -> IntentPreparation:
    """Plan/start an intent, or return a cached/blocked terminal entry."""
    current = [dict(item) for item in (ledger or [])]
    source_id = resolve_source_requirement_id(contract, tool=tool, args=args)
    signature = canonical_tool_signature(
        tool, args, source_requirement_id=source_id, contract=contract
    )
    intent_key = semantic_intent_key(
        tool, args, source_requirement_id=source_id, contract=contract
    )
    family_key = _search_family_key(
        tool, args, source_requirement_id=source_id, contract=contract
    )
    for entry in current:
        if entry.get("signature") == signature and entry.get("state") in TERMINAL_INTENT_STATES:
            if (
                entry.get("exhausted_reason") == "rewrite_requires_evidence_gap"
                and _normalized_text(evidence_gap)
            ):
                continue
            return IntentPreparation(current, entry, execute=False, cached=True)

    parent: dict[str, Any] | None = None
    rewrite_count = 0
    if tool in SEARCH_TOOLS:
        family = [entry for entry in current if entry.get("family_key") == family_key]
        if family:
            parent = family[0]
            rewrite_count = max(int(item.get("rewrite_count") or 0) for item in family)
            if not _normalized_text(evidence_gap):
                blocked = {
                    "intent_key": intent_key,
                    "source_requirement_id": source_id,
                    "tool": tool,
                    "args": _normalized_args(tool, args),
                    "signature": signature,
                    "family_key": family_key,
                    "state": "exhausted",
                    "attempts": 0,
                    "rewrite_count": rewrite_count,
                    "exhausted_reason": "rewrite_requires_evidence_gap",
                    "cacheable": True,
                }
                current.append(blocked)
                return IntentPreparation(current, blocked, execute=False)
            if rewrite_count >= 1:
                blocked = {
                    "intent_key": intent_key,
                    "source_requirement_id": source_id,
                    "tool": tool,
                    "args": _normalized_args(tool, args),
                    "signature": signature,
                    "family_key": family_key,
                    "state": "exhausted",
                    "attempts": 0,
                    "rewrite_count": rewrite_count,
                    "parent_intent_key": str(parent.get("intent_key") or ""),
                    "evidence_gap": _normalized_text(evidence_gap),
                    "exhausted_reason": "rewrite_limit_reached",
                    "cacheable": True,
                }
                current.append(blocked)
                return IntentPreparation(current, blocked, execute=False)
            rewrite_count = 1

    entry = {
        "intent_key": intent_key,
        "source_requirement_id": source_id,
        "tool": tool,
        "args": _normalized_args(tool, args),
        "signature": signature,
        "family_key": family_key,
        "state": "running",
        "attempts": 1,
        "rewrite_count": rewrite_count,
    }
    if parent is not None:
        entry["parent_intent_key"] = str(parent.get("intent_key") or "")
        entry["evidence_gap"] = _normalized_text(evidence_gap)
    current.append(entry)
    return IntentPreparation(current, entry, execute=True)


def finish_intent(
    ledger: list[dict[str, Any]],
    *,
    intent_key: str,
    summary: str,
    error: str | None,
    hits: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    record_ids: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Persist a terminal outcome and the data needed for a run-local cache hit."""
    updated = [dict(item) for item in ledger]
    for index in range(len(updated) - 1, -1, -1):
        entry = updated[index]
        if entry.get("intent_key") != intent_key or entry.get("state") != "running":
            continue
        is_empty_search = entry.get("tool") in SEARCH_TOOLS and not hits and not error
        if error:
            state = "exhausted"
            exhausted_reason = f"tool_error:{error}"
        elif is_empty_search:
            state = "exhausted"
            exhausted_reason = "empty_result"
        else:
            state = "satisfied"
            exhausted_reason = ""
        updated[index] = {
            **entry,
            "state": state,
            "summary": str(summary)[:2000],
            "error": error,
            "hits": [dict(item) for item in hits],
            "record_ids": sorted({str(item) for item in record_ids}),
            "cacheable": True,
            **({"exhausted_reason": exhausted_reason} if exhausted_reason else {}),
        }
        break
    return updated


def render_search_ledger_for_planner(ledger: list[dict[str, Any]] | None) -> str:
    if not ledger:
        return ""
    lines = ["SearchIntentLedger (истина runtime; terminal intents не повторяй):"]
    for entry in ledger:
        suffix = ""
        if entry.get("exhausted_reason"):
            suffix = f" exhausted_reason={entry['exhausted_reason']}"
        if entry.get("evidence_gap"):
            suffix += f" gap={entry['evidence_gap']}"
        lines.append(
            f"- {entry.get('intent_key')} source={entry.get('source_requirement_id')} "
            f"tool={entry.get('tool')} state={entry.get('state')} "
            f"attempts={entry.get('attempts', 0)} rewrites={entry.get('rewrite_count', 0)}{suffix}"
        )
    return "\n".join(lines)


def annotate_additive_search(
    ledger: list[dict[str, Any]],
    *,
    source_requirement_id: str,
    authoritative_refs: list[str] | tuple[str, ...],
    hits: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    """Trace that semantic ranking enriched, but did not replace, a complete corpus."""

    authoritative = tuple(dict.fromkeys(str(ref) for ref in authoritative_refs if str(ref)))
    hit_refs = tuple(
        dict.fromkeys(str(hit.get("ref") or "") for hit in hits if str(hit.get("ref") or ""))
    )
    updated = [dict(item) for item in ledger]
    for index in range(len(updated) - 1, -1, -1):
        item = updated[index]
        if (
            str(item.get("source_requirement_id") or "") == source_requirement_id
            and str(item.get("tool") or "") in SEARCH_TOOLS
        ):
            updated[index] = {
                **item,
                "search_relation": "additive_to_authoritative_catalog",
                "authoritative_ref_count": len(authoritative),
                "semantic_hit_count": len(hit_refs),
                "ranked_authoritative_ref_count": len(set(authoritative).intersection(hit_refs)),
                "related_candidate_count": len(set(hit_refs).difference(authoritative)),
                "discovery_ref_count_before": len(authoritative),
                "discovery_ref_count_after": len(authoritative),
            }
            break
    return updated


def cached_outcome(entry: Mapping[str, Any]) -> tuple[str, str | None, tuple[dict[str, Any], ...]]:
    return (
        str(entry.get("summary") or f"Intent {entry.get('intent_key')} already terminal."),
        str(entry.get("error")) if entry.get("error") else None,
        tuple(dict(item) for item in entry.get("hits") or ()),
    )
