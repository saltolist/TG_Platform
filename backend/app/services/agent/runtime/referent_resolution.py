"""Bounded referent candidate graph and deterministic selection paths.

This module never searches the workspace.  It can only select IDs that were
placed in the candidate envelope by manifests, the dialog ledger, a previous
target contract, or the currently open object.  Ambiguous semantic cases stay
terminal and can be handed to the existing classifier for one structured
interpretation.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

SCHEMA = "workspace.referent-resolution/v1"

_ORDINALS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четверт": 4,
    "четв": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}
_COUNT_WORDS = {"два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}


def _entity_ref(kind: str, identifier: str) -> str:
    return f"{kind}:{identifier}"


def candidate_envelope(
    *,
    dialog_ledger: Sequence[Any] = (),
    manifests: Sequence[Mapping[str, Any]] = (),
    open_object: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a compact, ordered, deduplicated candidate envelope."""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: Mapping[str, Any]) -> None:
        kind = str(item.get("kind") or "")
        ref = str(item.get("ref") or "")
        if kind not in {"post", "note", "artifact"} or not ref:
            return
        key = (kind, ref, str(item.get("source_set_ref") or ""))
        if key in seen:
            return
        seen.add(key)
        candidates.append(dict(item))

    for manifest in manifests:
        turn_id = str(manifest.get("source_turn_id") or manifest.get("run_id") or "")
        for index, raw in enumerate(manifest.get("context_refs") or (), start=1):
            if not isinstance(raw, Mapping):
                continue
            add({
                "ref": str(raw.get("ref") or ""), "kind": str(raw.get("kind") or ""),
                "title": raw.get("title"), "summary": raw.get("summary"), "position": index,
                "provenance": str(raw.get("provenance") or "exact"),
                "source_turn_id": turn_id, "revision": raw.get("revision"),
                "source_set_ref": None,
            })
        for raw_set in manifest.get("reference_sets") or ():
            if not isinstance(raw_set, Mapping):
                continue
            set_ref = str(raw_set.get("ref") or "")
            kind = str(raw_set.get("kind") or "")
            for index, ref in enumerate(raw_set.get("ordered_members") or (), start=1):
                add({
                    "ref": str(ref), "kind": kind, "position": index,
                    "provenance": "exact", "source_turn_id": turn_id,
                    "source_set_ref": set_ref,
                })
        for index, raw in enumerate(manifest.get("artifacts") or (), start=1):
            if not isinstance(raw, Mapping):
                continue
            add({
                "ref": str(raw.get("ref") or ""),
                "kind": "artifact",
                "title": raw.get("title"),
                "position": index,
                "provenance": "exact",
                "source_turn_id": turn_id,
                "revision": None,
                "source_set_ref": f"set:{turn_id}:artifacts",
            })

    for turn in reversed(tuple(dialog_ledger)):
        turn_id = str(getattr(turn, "turn_id", "") or "")
        for entity in tuple(getattr(turn, "entities", ()) or ()):
            entity_type = str(getattr(entity, "entity_type", "") or "")
            if entity_type == "entity_set":
                set_ref = str(getattr(entity, "ref", "") or f"set:{turn_id}:entities")
                for index, member in enumerate(tuple(getattr(entity, "members", ()) or ()), start=1):
                    if not isinstance(member, Mapping):
                        continue
                    kind = str(member.get("kind") or "")
                    identifier = str(member.get("id") or "")
                    add({
                        "ref": _entity_ref(kind, identifier), "kind": kind,
                        "title": member.get("title"), "position": index,
                        "provenance": "exact", "source_turn_id": turn_id,
                        "source_set_ref": set_ref,
                    })
            elif entity_type in {"post", "note"}:
                identifier = str(getattr(entity, f"{entity_type}_id", "") or "")
                add({
                    "ref": _entity_ref(entity_type, identifier), "kind": entity_type,
                    "title": getattr(entity, "title", None), "position": 1,
                    "provenance": "exact", "source_turn_id": turn_id,
                    "source_set_ref": f"set:{turn_id}:{entity_type}",
                })
        prior = getattr(turn, "turn_contract", None)
        for index, target in enumerate(((prior or {}).get("target_contract") or {}).get("targets") or (), start=1):
            if not isinstance(target, Mapping):
                continue
            kind = str(target.get("kind") or "")
            identifier = str(target.get("id") or "")
            add({
                "ref": _entity_ref(kind, identifier), "kind": kind,
                "title": target.get("title"), "position": index,
                "provenance": "exact", "source_turn_id": turn_id,
                "source_set_ref": f"set:{turn_id}:{kind}",
            })

    if open_object:
        kind = str(open_object.get("kind") or "post")
        identifier = str(open_object.get("id") or "")
        add({
            "ref": _entity_ref(kind, identifier), "kind": kind,
            "title": open_object.get("title"), "position": 1,
            "provenance": "exact", "source_turn_id": None,
            "source_set_ref": "current:open-object",
        })
    return candidates


def _latest_set(candidates: Sequence[Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for candidate in candidates:
        set_ref = str(candidate.get("source_set_ref") or "")
        if not set_ref:
            continue
        if set_ref not in groups:
            groups[set_ref] = []
            order.append(set_ref)
        groups[set_ref].append(dict(candidate))
    if not order:
        return "", []
    # Preserve the authoritative source set across subset turns. Newer
    # manifests may also contain singleton target sets; choosing the largest
    # bounded set keeps "остальные" anchored to the original catalog.
    set_ref = max(order, key=lambda ref: len(groups[ref]))
    return set_ref, sorted(groups[set_ref], key=lambda item: int(item.get("position") or 0))


def _selected_positions(text: str, size: int) -> list[int]:
    lowered = text.casefold()
    first_count = re.search(r"\bпервые?\s+(\d+)\b", lowered)
    if first_count:
        return list(range(1, min(size, int(first_count.group(1))) + 1))
    first_word = re.search(r"\bпервые?\s+(два|две|три|четыре|пять)\b", lowered)
    if first_word:
        count = _COUNT_WORDS[first_word.group(1)]
        return list(range(1, min(size, count) + 1))
    positions: list[int] = []
    for stem, position in _ORDINALS.items():
        if re.search(rf"\b{stem}\w*\b", lowered):
            positions.append(position)
    return sorted(set(position for position in positions if 1 <= position <= size))


def validate_resolution(
    resolution: Mapping[str, Any], *, candidate_refs: set[str]
) -> list[str]:
    issues: list[str] = []
    if str(resolution.get("schema") or "") != SCHEMA:
        issues.append("unsupported_resolution_schema")
    for reference in resolution.get("references") or ():
        if not isinstance(reference, Mapping):
            issues.append("malformed_reference")
            continue
        for ref in reference.get("target_ids") or ():
            if str(ref) not in candidate_refs:
                issues.append(f"invented_target:{ref}")
    return issues


def resolve_from_candidates(
    user_text: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    previous_selected_refs: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve explicit set operations without adding a search/LLM call."""
    text = (user_text or "").strip()
    lowered = text.casefold()
    set_ref, members = _latest_set(candidates)
    if not members:
        return {"schema": SCHEMA, "references": [], "unresolved": [], "ambiguity": None}
    refs = [str(item.get("ref") or "") for item in members]
    selected: list[str] = []
    mode = "ambiguous"
    interpretation = ""
    confidence = 0.0

    positions: list[int] = []
    predicate_match = re.search(r"\b(?:про|об|на\s+тему)\s+([\w-]{2,})", lowered)
    if predicate_match and predicate_match.group(1) not in {"что", "них", "это"}:
        term = predicate_match.group(1)
        selected = [
            str(item.get("ref") or "")
            for item in members
            if term in f"{item.get('title') or ''} {item.get('summary') or ''}".casefold()
        ]
        if not selected:
            return {
                "schema": SCHEMA,
                "references": [],
                "unresolved": [text],
                "ambiguity": {
                    "candidate_set_refs": [set_ref],
                    "candidate_ids": refs,
                    "question": "Уточните, какие объекты из набора соответствуют этому критерию.",
                },
            }
        mode = "predicate"
        interpretation = f"объекты исходного набора по критерию: {term}"
        confidence = 0.86
    else:
        positions = _selected_positions(text, len(members))
    if mode == "predicate":
        pass
    elif positions:
        selected = [refs[position - 1] for position in positions]
        mode = "explicit_subset"
        interpretation = "позиционное подмножество предыдущего набора"
        confidence = 0.99
    elif any(marker in lowered for marker in ("остальн", "кроме", "за исключением")):
        excluded = set(str(item) for item in previous_selected_refs)
        if "кроме" in lowered or "за исключением" in lowered:
            title_matches = [
                str(item.get("ref")) for item in members
                if str(item.get("title") or "").casefold()
                and any(
                    token in lowered
                    for token in re.findall(r"[\w-]{5,}", str(item.get("title") or "").casefold())
                )
            ]
            excluded.update(title_matches)
        selected = [ref for ref in refs if ref not in excluded]
        if not excluded:
            return {
                "schema": SCHEMA,
                "references": [],
                "unresolved": [text] if text else [],
                "ambiguity": {
                    "candidate_set_refs": [set_ref],
                    "candidate_ids": refs,
                    "question": "Уточните, какие объекты были выбраны ранее.",
                },
            }
        mode = "complement"
        interpretation = "дополнение исходного набора"
        confidence = 0.96 if excluded else 0.65
    elif len(members) == 1:
        selected = refs
        mode = "all"
        interpretation = "единственный допустимый объект"
        confidence = 0.99
    elif re.search(r"\b(все|кажд\w*|эти|тех|они|их|них|посты|заметки)\b", lowered):
        selected = refs
        mode = "all"
        interpretation = "весь предыдущий упорядоченный набор"
        confidence = 0.95
    else:
        return {
            "schema": SCHEMA,
            "references": [],
            "unresolved": [text] if text else [],
            "ambiguity": {
                "candidate_set_refs": [set_ref],
                "candidate_ids": refs,
                "question": "Уточните, какие именно объекты из предыдущего набора использовать.",
            },
        }

    result = {
        "schema": SCHEMA,
        "references": [{
            "mention": text,
            "target_type": (
                "artifact"
                if all(item.get("kind") == "artifact" for item in members if str(item.get("ref")) in selected)
                else "entity" if len(selected) == 1 else "entity_set"
            ),
            "source_set_ref": set_ref,
            "target_ids": selected,
            "selection_mode": mode,
            "interpretation": interpretation,
            "confidence": confidence,
        }],
        "unresolved": [],
        "ambiguity": None,
    }
    issues = validate_resolution(result, candidate_refs=set(refs))
    if issues:
        return {"schema": SCHEMA, "references": [], "unresolved": issues, "ambiguity": None}
    return result


def previous_selection(dialog_ledger: Sequence[Any]) -> tuple[str, ...]:
    for turn in reversed(tuple(dialog_ledger)):
        contract = getattr(turn, "turn_contract", None)
        resolution = ((contract or {}).get("target_contract") or {}).get("referent_resolution") or {}
        for reference in reversed(resolution.get("references") or ()):
            if isinstance(reference, Mapping) and reference.get("target_ids"):
                return tuple(str(item) for item in reference.get("target_ids") or ())
    return ()


__all__ = [
    "SCHEMA", "candidate_envelope", "previous_selection", "resolve_from_candidates",
    "validate_resolution",
]
