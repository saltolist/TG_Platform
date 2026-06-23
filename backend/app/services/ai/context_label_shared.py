"""Shared utilities used by both context_labels.py and context_labels_post.py.

These were previously either duplicated verbatim or imported as private symbols
across module boundaries.  Moving them here makes the shared contract explicit.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import active_thread_key  # noqa: F401 – re-exported for consumers
from app.services.ai.context_label import enumerate_active_user_turns, read_stamped_attached_version, read_stamped_context_label

# ---------------------------------------------------------------------------
# Fork-metadata key tuple (used by _merge_fork_metadata)
# ---------------------------------------------------------------------------

_FORK_METADATA_KEYS = (
    "fork_branch_zero_head",
    "fork_suppress_attach_up_to",
    "catalog_snapshot_at_fork",
)

# ---------------------------------------------------------------------------
# Thread-key / history navigation helpers (verbatim duplicate in both files)
# ---------------------------------------------------------------------------


def _path_indices(path_str: str) -> list[int]:
    return [int(part) for part in path_str.split(".") if part]


def _fork_message_for_thread_key(
    history: list[Mapping[str, Any]] | None,
    thread_key: str,
) -> Mapping[str, Any] | None:
    """User fork message that created ``thread_key`` (last comma segment)."""
    if not history or not thread_key or "@" not in thread_key:
        return None
    segments = thread_key.split(",")
    parsed: list[tuple[str, int]] = []
    for segment in segments:
        if "@" not in segment:
            return None
        path_part, branch_part = segment.rsplit("@", 1)
        try:
            parsed.append((path_part, int(branch_part)))
        except ValueError:
            return None
    path0, _ = parsed[0]
    head_indices = _path_indices(path0)
    if not head_indices:
        return None
    if head_indices[0] >= len(history):
        return None
    message = history[head_indices[0]]
    if not isinstance(message, Mapping):
        return None
    if len(parsed) == 1:
        return message
    for index in range(1, len(parsed)):
        _, prev_branch = parsed[index - 1]
        path_part, _ = parsed[index]
        cont_indices = _path_indices(path_part)
        if not cont_indices:
            return None
        cont_idx = cont_indices[-1]
        branches = message.get("userBranches")
        if not isinstance(branches, list) or prev_branch >= len(branches):
            return None
        branch = branches[prev_branch]
        if not isinstance(branch, Mapping):
            return None
        continuation = branch.get("continuation")
        if not isinstance(continuation, list) or cont_idx >= len(continuation):
            return None
        message = continuation[cont_idx]
        if not isinstance(message, Mapping):
            return None
    return message


# ---------------------------------------------------------------------------
# Pending-queue helpers
# ---------------------------------------------------------------------------


def _pending_queue_from_state(state: Mapping[str, Any]) -> list[dict[str, int]]:
    """Pending catalog versions with anchor turns, oldest first."""
    raw = state.get("pending_queue")
    if isinstance(raw, list) and raw:
        items: list[dict[str, int]] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            version = int(entry.get("version") or 0)
            since_turn = int(entry.get("since_turn") or 0)
            if version > 0 and since_turn > 0:
                items.append({"version": version, "since_turn": since_turn})
        if items:
            return sorted(items, key=lambda item: (item["since_turn"], item["version"]))

    pending = int(state.get("pending_version") or 0)
    pending_since = int(state.get("pending_since_turn") or 0)
    head = int(state.get("head_version") or 0)
    if pending > head and pending_since > 0:
        return [{"version": pending, "since_turn": pending_since}]
    return []


def _pending_queue_from_stamps(
    history: list[Mapping[str, Any]] | None,
    *,
    head: int,
    up_to_turn: int | None = None,
) -> list[dict[str, int]]:
    """Rebuild pending queue from stamped attached versions on the active path."""
    from app.services.ai.context_label import read_context_label

    by_version: dict[int, int] = {}
    for entry in enumerate_active_user_turns(list(history or [])):
        turn = int(entry["turn"])
        if up_to_turn is not None and turn > up_to_turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        parsed = read_context_label(entry["message"], branch_index=branch_index)
        if parsed is None:
            continue
        _stamp_head, attached, _turn = parsed
        if attached <= head:
            continue
        if attached not in by_version or turn < by_version[attached]:
            by_version[attached] = turn
    return sorted(
        [{"version": version, "since_turn": by_version[version]} for version in by_version],
        key=lambda item: (item["since_turn"], item["version"]),
    )


def _merge_pending_queues(
    *queues: list[dict[str, int]],
    head: int,
) -> list[dict[str, int]]:
    by_version: dict[int, int] = {}
    for queue in queues:
        for item in queue:
            version = int(item["version"])
            since_turn = int(item["since_turn"])
            if version <= head:
                continue
            if version not in by_version or since_turn < by_version[version]:
                by_version[version] = since_turn
    return sorted(
        [{"version": version, "since_turn": by_version[version]} for version in by_version],
        key=lambda item: (item["since_turn"], item["version"]),
    )


def _sync_legacy_pending_fields(state: dict[str, Any]) -> dict[str, Any]:
    queue = _pending_queue_from_state(state)
    state["pending_queue"] = queue
    if queue:
        state["pending_version"] = queue[-1]["version"]
        state["pending_since_turn"] = queue[-1]["since_turn"]
    else:
        state["pending_version"] = 0
        state["pending_since_turn"] = 0
    return state


# ---------------------------------------------------------------------------
# Fork-metadata merge
# ---------------------------------------------------------------------------


def _merge_fork_metadata(
    base: dict[str, Any],
    stored: Mapping[str, Any],
) -> dict[str, Any]:
    for key in _FORK_METADATA_KEYS:
        if key in stored:
            base[key] = stored[key]
    return base


# ---------------------------------------------------------------------------
# Thread parent lookup
# ---------------------------------------------------------------------------


def _find_label_thread_parent(
    threads: Mapping[str, Mapping[str, Any]],
    thread_key: str,
    prev_key: str | None,
) -> Mapping[str, Any] | None:
    if isinstance(prev_key, str):
        parent = threads.get(prev_key)
        if parent is not None:
            return parent
    for key in sorted(threads.keys(), key=len, reverse=True):
        if thread_key == key or thread_key.startswith(f"{key},"):
            return threads[key]
    return threads.get("")


# ---------------------------------------------------------------------------
# Edit-fork detection and head locking
# ---------------------------------------------------------------------------


def _is_edit_fork_at_turn(
    history: list[Mapping[str, Any]] | None,
    user_turn_count: int,
) -> bool:
    """True when ``user_turn_count`` is an edited branch (branch_index > 0) on the active path."""
    for entry in enumerate_active_user_turns(list(history or [])):
        if int(entry["turn"]) != user_turn_count:
            continue
        return bool(entry.get("branched")) and int(entry.get("branch_index") or 0) > 0
    return False


def _lock_edit_fork_head(
    state: Mapping[str, Any],
    *,
    history: list[Mapping[str, Any]] | None,
    user_turn_count: int,
) -> dict[str, Any]:
    """Edit fork: head is immutable — always branch-0 head at the creating fork."""
    merged = dict(state)
    if not history or not _is_edit_fork_at_turn(history, user_turn_count):
        return merged
    fork_head = int(merged.get("fork_branch_zero_head") or 0)
    if fork_head > 0:
        merged["head_version"] = fork_head
        merged = _sync_legacy_pending_fields(merged)
    return merged
