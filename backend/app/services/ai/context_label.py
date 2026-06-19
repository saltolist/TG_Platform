"""Message context labels: format 1-2-3 (head-attached-turn)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.services.ai.chat_history import clamp_active_branch_index

_LABEL_RE = re.compile(r"^(?P<head>\d+)-(?P<attached>\d+)-(?P<turn>.+)$")
_TURN_SEGMENT_RE = re.compile(r"^\d+(?:\.\d+)?")


def format_context_label(
    head: int,
    attached: int,
    turn: str,
) -> str:
    if attached > 0 and attached <= head:
        attached = 0
    return f"{head}-{attached}-{turn}"


def normalize_context_label_parts(
    head: int,
    attached: int,
    turn: str,
) -> tuple[int, int, str]:
    if attached > 0 and attached <= head:
        attached = 0
    return head, attached, turn


def parse_turn_label(raw: str) -> str | None:
    """Parse nested turn path: 3, 3.2, 3.2(4), 3.2(4.2(5))."""
    text = raw.strip()
    if not text:
        return None

    def parse_segment(pos: int) -> tuple[str | None, int]:
        match = _TURN_SEGMENT_RE.match(text[pos:])
        if not match:
            return None, pos
        return match.group(0), pos + match.end()

    def parse_node(pos: int) -> tuple[str | None, int]:
        segment, pos = parse_segment(pos)
        if segment is None:
            return None, pos
        if pos < len(text) and text[pos] == "(":
            inner, pos = parse_node(pos + 1)
            if inner is None:
                return None, pos
            if pos >= len(text) or text[pos] != ")":
                return None, pos
            return f"{segment}({inner})", pos + 1
        return segment, pos

    parsed, end = parse_node(0)
    if parsed is None or end != len(text):
        return None
    return parsed


def parse_context_label(raw: str) -> tuple[int, int, str] | None:
    match = _LABEL_RE.match(raw.strip())
    if not match:
        return None
    turn = parse_turn_label(match.group("turn"))
    if turn is None:
        return None
    return int(match.group("head")), int(match.group("attached")), turn


def read_context_label(
    message: Mapping[str, Any],
    *,
    branch_index: int | None = None,
) -> tuple[int, int, str] | None:
    raw = _read_label_raw(message, branch_index=branch_index)
    if raw is None:
        return None
    parsed = parse_context_label(raw)
    if parsed is None:
        return None
    return normalize_context_label_parts(*parsed)


def _read_label_raw(message: Mapping[str, Any], *, branch_index: int | None = None) -> str | None:
    branches = message.get("userBranches")
    if isinstance(branches, list) and len(branches) > 1:
        bi = branch_index if branch_index is not None else clamp_active_branch_index(message)
        if 0 <= bi < len(branches):
            branch = branches[bi]
            if isinstance(branch, Mapping):
                raw = branch.get("contextLabel") or branch.get("context_label")
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
        if bi == 0:
            raw = message.get("contextLabel") or message.get("context_label")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None
    raw = message.get("contextLabel") or message.get("context_label")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


def read_stamped_context_label(
    message: Mapping[str, Any],
    *,
    branch_index: int | None = None,
) -> str | None:
    """Return stored label verbatim (immutable metadata)."""
    raw = _read_label_raw(message, branch_index=branch_index)
    if raw is None:
        return None
    if _LABEL_RE.match(raw) is None:
        return None
    return raw


def read_stamped_attached_version(
    message: Mapping[str, Any],
    *,
    branch_index: int | None = None,
) -> int:
    raw = _read_label_raw(message, branch_index=branch_index)
    if raw is None:
        return 0
    match = _LABEL_RE.match(raw)
    if match is None:
        return 0
    return max(0, int(match.group("attached")))


def _label_turn_part(raw: str) -> str | None:
    match = _LABEL_RE.match(raw.strip())
    if match is None:
        return None
    return match.group("turn")


def _should_keep_existing_label(existing: str, label: str) -> bool:
    """Once a message has contextLabel, it is never rewritten (except new branch turn)."""
    return bool(existing.strip())


def _stamp_label_on_user_message(
    message: Mapping[str, Any],
    label: str,
    turn_label: str,
) -> dict[str, Any]:
    updated = dict(message)
    branches = updated.get("userBranches")
    if isinstance(branches, list) and len(branches) > 1:
        bi = clamp_active_branch_index(updated)
        new_branches: list[Any] = []
        for index, branch in enumerate(branches):
            if index != bi:
                new_branches.append(dict(branch) if isinstance(branch, Mapping) else branch)
                continue
            branch_copy = dict(branch) if isinstance(branch, Mapping) else {}
            existing = branch_copy.get("contextLabel")
            if not existing and bi == 0:
                existing = updated.get("contextLabel")
            if isinstance(existing, str) and _should_keep_existing_label(existing, label):
                new_branches.append(branch_copy)
                continue
            branch_copy["contextLabel"] = label
            new_branches.append(branch_copy)
        if updated.get("contextLabel"):
            parent_label = updated["contextLabel"]
            if new_branches and isinstance(new_branches[0], Mapping):
                branch0 = dict(new_branches[0])
                if not branch0.get("contextLabel"):
                    branch0["contextLabel"] = parent_label
                    new_branches[0] = branch0
            updated.pop("contextLabel", None)
        updated["userBranches"] = new_branches
        return updated

    existing = updated.get("contextLabel")
    if isinstance(existing, str) and _should_keep_existing_label(existing, label):
        return updated
    updated["contextLabel"] = label
    return updated


def turn_label_for_node(
    *,
    global_turn: int,
    branch_index: int,
    branched: bool,
    path_prefix: str | None,
) -> str:
    """Build nested turn label for one user message on the active path."""
    if branched:
        # Nested fork (inside continuation): branch 0 keeps linear turn n → 3.2(4).
        # Top-level fork: both branches get suffix → 3.1, 3.2.
        if path_prefix is not None and branch_index == 0:
            node = str(global_turn)
        else:
            node = f"{global_turn}.{branch_index + 1}"
    else:
        node = str(global_turn)

    if not path_prefix:
        return node
    if "(" in path_prefix:
        return f"{path_prefix[:-1]}({node}))"
    return f"{path_prefix}({node})"


def resolve_turn_label(
    history: list[Mapping[str, Any]] | None,
    user_turn_count: int,
) -> str:
    """Turn suffix for a user-turn (includes branch suffix when branched)."""
    for entry in enumerate_active_user_turns(list(history or [])):
        if entry["turn"] == user_turn_count:
            return str(entry["turn_label"])
    return str(user_turn_count)


def enumerate_active_user_turns(
    history: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """User messages on the active path with sequential turn numbers and paths."""
    entries: list[dict[str, Any]] = []
    turn = 0

    def walk(
        items: list[Mapping[str, Any]],
        tree_prefix: list[int],
        path_prefix: str | None,
    ) -> None:
        nonlocal turn
        for index, message in enumerate(items):
            if not isinstance(message, Mapping):
                continue
            path = [*tree_prefix, index]
            if message.get("role") == "user":
                turn += 1
                branches = message.get("userBranches")
                branched = isinstance(branches, list) and len(branches) > 1
                branch_index = clamp_active_branch_index(message) if branches else 0
                turn_label = turn_label_for_node(
                    global_turn=turn,
                    branch_index=branch_index,
                    branched=branched,
                    path_prefix=path_prefix,
                )
                entries.append(
                    {
                        "turn": turn,
                        "turn_label": turn_label,
                        "path": path,
                        "message": message,
                        "branched": branched,
                        "branch_index": branch_index,
                    }
                )
                if branches:
                    branch = branches[branch_index]
                    if isinstance(branch, Mapping):
                        continuation = branch.get("continuation")
                        if isinstance(continuation, list):
                            walk(continuation, path, turn_label)
                    break

    walk(history, [], None)
    return entries


def label_for_path(history: list[Mapping[str, Any]], path: list[int]) -> str | None:
    for entry in enumerate_active_user_turns(history):
        if entry["path"] == path:
            parsed = read_context_label(
                entry["message"],
                branch_index=entry["branch_index"] if entry.get("branched") else None,
            )
            if parsed is None:
                return None
            return format_context_label(*parsed)
    return None


def stamp_context_label_on_path(
    history: list[Mapping[str, Any]],
    path: list[int],
    *,
    head: int,
    attached: int,
    turn_label: str,
) -> list[dict[str, Any]] | None:
    from app.services.ai.chat_history import map_message_at_path

    label = format_context_label(head, attached, turn_label)

    def attach(message: Mapping[str, Any]) -> dict[str, Any]:
        if message.get("role") != "user":
            return dict(message)
        return _stamp_label_on_user_message(dict(message), label, turn_label)

    return map_message_at_path(list(history), path, attach)


# Backward-compatible alias for tests/docs referencing the old flat branch suffix.
def turn_label_for_branch(turn: int, branch_index: int, *, branched: bool) -> str:
    return turn_label_for_node(
        global_turn=turn,
        branch_index=branch_index,
        branched=branched,
        path_prefix=None,
    )
