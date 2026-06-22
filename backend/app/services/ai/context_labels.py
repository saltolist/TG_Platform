"""Thread state and prompt assembly driven by context labels + summary catalog."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import (
    active_thread_key,
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_primer import (
    DEFAULT_SYSTEM_PROMPT,
    PRIMER_ACK,
    build_dialog_messages,
    build_primer_user_content,
    take_prompt_window,
)
from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.context_label import (
    enumerate_active_user_turns,
    format_context_label,
    parse_context_label,
    read_stamped_attached_version,
    read_stamped_context_label,
    resolve_turn_label,
)
from app.services.ai.context_turns import annotate_user_turns, compute_window_user_turns
from app.services.ai.rolling_summary import reconcile_rolling_summary_fields
from app.services.ai.summary_catalog import (
    ensure_post_local_catalog_current,
    latest_scope_version,
    resolve_bundle_text,
)

THREAD_LABEL_STATE_KEY = "label_context"

_FORK_METADATA_KEYS = (
    "fork_branch_zero_head",
    "fork_suppress_attach_up_to",
    "catalog_snapshot_at_fork",
)


def empty_label_thread_state() -> dict[str, Any]:
    return {
        "head_version": 0,
        "pending_version": 0,
        "pending_since_turn": 0,
        "pending_queue": [],
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }


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


def _resolve_pending_queue(
    state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None = None,
    *,
    up_to_turn: int | None = None,
    user_turn_count: int | None = None,
) -> list[dict[str, int]]:
    """Pending queue for maturation/reconcile — stamps first, thread state fills gaps."""
    head = int(state.get("head_version") or 0)
    from_stamps = _pending_queue_from_stamps(history, head=head, up_to_turn=up_to_turn)
    if history is not None:
        queue = _merge_pending_queues(
            from_stamps,
            _pending_queue_from_state(state),
            head=head,
        )
    else:
        queue = _merge_pending_queues(_pending_queue_from_state(state), from_stamps, head=head)
    clip = user_turn_count if user_turn_count is not None else up_to_turn
    if clip is not None:
        queue = [item for item in queue if int(item["since_turn"]) <= clip]
    return queue


def _pending_queue_for_label_plan(
    state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None = None,
    *,
    user_turn_count: int | None = None,
) -> list[dict[str, int]]:
    """Pending queue for stamping — merge thread state with stamps (fork seed, unreconciled)."""
    head = int(state.get("head_version") or 0)
    from_stamps = _pending_queue_from_stamps(history, head=head)
    queue = _merge_pending_queues(_pending_queue_from_state(state), from_stamps, head=head)
    if user_turn_count is not None:
        queue = [item for item in queue if int(item["since_turn"]) <= user_turn_count]
    if history is not None:
        queue = [
            item
            for item in queue
            if not _turn_definitively_not_anchoring_version(
                int(item["since_turn"]),
                int(item["version"]),
                history,
            )
        ]
    return queue


def _active_attached_versions_in_history(
    history: list[Mapping[str, Any]] | None,
    *,
    head: int,
) -> set[int]:
    versions: set[int] = set()
    for entry in enumerate_active_user_turns(list(history or [])):
        branch_index = entry["branch_index"] if entry.get("branched") else None
        attached = read_stamped_attached_version(entry["message"], branch_index=branch_index)
        if attached > head:
            versions.add(attached)
    return versions


def _active_pending_versions(
    queue: list[dict[str, int]],
    history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
) -> set[int]:
    """Catalog versions already anchored on an earlier stamped turn, or queued ahead."""
    active: set[int] = set()
    for item in queue:
        since_turn = int(item["since_turn"])
        version = int(item["version"])
        if since_turn > user_turn_count:
            active.add(version)
            continue
        if history is None:
            if since_turn < user_turn_count:
                active.add(version)
            continue
        for entry in enumerate_active_user_turns(history):
            if int(entry["turn"]) != since_turn:
                continue
            branch_index = entry["branch_index"] if entry.get("branched") else None
            if read_stamped_attached_version(entry["message"], branch_index=branch_index) == version:
                active.add(version)
            break
    return active


def _reconcile_thread_state_with_history(
    state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
) -> dict[str, Any]:
    """Drop stale pending/snapshot metadata when turns with stamps were deleted."""
    head = int(state.get("head_version") or 0)
    queue = _resolve_pending_queue(
        state,
        history,
        up_to_turn=user_turn_count,
        user_turn_count=user_turn_count,
    )
    snapshot = int(state.get("catalog_snapshot_at_fork") or 0)
    active_attached = _active_attached_versions_in_history(history, head=head)
    if snapshot > head and snapshot not in active_attached:
        max_pending = max(
            (int(item["version"]) for item in queue if int(item["version"]) > head),
            default=0,
        )
        snapshot = max(
            max((version for version in active_attached if version > head), default=head),
            max_pending,
        )

    result = {
        **dict(state),
        "pending_queue": queue,
        "catalog_snapshot_at_fork": snapshot,
    }
    result = _sync_legacy_pending_fields(result)
    valid_pairs = filter_alternating_roles(linearize_for_llm(list(history or [])))
    return reconcile_rolling_summary_fields(result, valid_pairs)


def load_label_thread_context(meta: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(meta, Mapping):
        return {}
    raw = meta.get(THREAD_LABEL_STATE_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, Mapping)}


def _fork_anchor_from_branch_zero_label(
    history: list[Mapping[str, Any]] | None,
) -> tuple[int, int, int, bool] | None:
    """Head/pending from branch 0 stamp on the latest fork along the active path."""
    from app.services.ai.context_label import parse_context_label, read_stamped_context_label

    anchor: tuple[int, int, int, bool] | None = None
    for entry in enumerate_active_user_turns(list(history or [])):
        if not entry.get("branched"):
            continue
        message = entry["message"]
        branches = message.get("userBranches")
        if not isinstance(branches, list) or len(branches) < 2:
            continue
        branch0 = branches[0]
        if not isinstance(branch0, Mapping):
            continue
        raw = read_stamped_context_label(message, branch_index=0)
        if raw is None:
            candidate = branch0.get("contextLabel") or branch0.get("context_label")
            raw = candidate if isinstance(candidate, str) else None
        if not raw:
            continue
        parsed = parse_context_label(raw)
        if parsed is None:
            continue
        head, attached, turn_part = parsed
        pending = attached if attached > head else 0
        pending_since = int(entry["turn"]) if pending else 0
        anchor = (head, pending, pending_since, "(" in turn_part)
    return anchor


def seed_label_thread_from_parent(
    parent: Mapping[str, Any],
    *,
    user_turn_count: int,
    history: list[Mapping[str, Any]] | None = None,
    latest_catalog_version: int = 0,
) -> dict[str, Any]:
    """Fork: inherit head/pending from branch 0 label at the fork, clipped to fork turn."""
    state = empty_label_thread_state()
    head = int(parent.get("head_version") or 0)
    pending = int(parent.get("pending_version") or 0)
    pending_since = int(parent.get("pending_since_turn") or 0)

    anchor = _fork_anchor_from_branch_zero_label(history)
    edit_fork = _is_edit_fork_at_turn(history, user_turn_count)
    if anchor is not None:
        head, pending, pending_since, nested_fork = anchor
        parent_head = int(parent.get("head_version") or 0)
        state["fork_branch_zero_head"] = head
        # Nested fork: parent may have matured versions the branch-0 label never saw.
        if nested_fork and parent_head > head:
            state["fork_suppress_attach_up_to"] = parent_head
        if edit_fork:
            # Branch 1+ is a fresh line — do not inherit branch 0's float anchor at fork turn.
            pending = 0
            pending_since = 0

    if pending > 0 and pending_since > user_turn_count:
        pending = 0
        pending_since = 0

    state["head_version"] = head
    parent_queue = [
        item
        for item in _resolve_pending_queue(parent, history, up_to_turn=user_turn_count)
        if int(item["since_turn"]) <= user_turn_count
    ]
    if edit_fork:
        parent_queue = [
            item for item in parent_queue if int(item["since_turn"]) != user_turn_count
        ]
    queue = _merge_pending_queues(
        parent_queue,
        _pending_queue_from_stamps(history, head=head, up_to_turn=user_turn_count),
        ([{"version": pending, "since_turn": pending_since}] if pending > head and pending_since > 0 else []),
        head=head,
    )
    if edit_fork:
        queue = [item for item in queue if int(item["since_turn"]) != user_turn_count]
    state["pending_queue"] = queue
    if edit_fork:
        state["catalog_snapshot_at_fork"] = 0
    return _sync_legacy_pending_fields(state)


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


def _max_stamped_head_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    up_to_turn: int | None = None,
) -> int:
    from app.services.ai.context_label import parse_context_label

    max_head = 0
    for entry in enumerate_active_user_turns(list(history or [])):
        turn = int(entry["turn"])
        if up_to_turn is not None and turn > up_to_turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        raw = read_stamped_context_label(entry["message"], branch_index=branch_index)
        if raw is None:
            continue
        parsed = parse_context_label(raw)
        if parsed is None:
            continue
        max_head = max(max_head, int(parsed[0]))
    return max_head


def _max_stamped_attached_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    up_to_turn: int | None = None,
) -> int:
    max_attached = 0
    for entry in enumerate_active_user_turns(list(history or [])):
        turn = int(entry["turn"])
        if up_to_turn is not None and turn > up_to_turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        attached = read_stamped_attached_version(entry["message"], branch_index=branch_index)
        max_attached = max(max_attached, attached)
    return max_attached


def _merge_fork_metadata(
    base: dict[str, Any],
    stored: Mapping[str, Any],
) -> dict[str, Any]:
    for key in _FORK_METADATA_KEYS:
        if key in stored:
            base[key] = stored[key]
    return base


def _has_stamped_turns_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    up_to_turn: int | None = None,
) -> bool:
    for entry in enumerate_active_user_turns(list(history or [])):
        turn = int(entry["turn"])
        if up_to_turn is not None and turn > up_to_turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        if read_stamped_context_label(entry["message"], branch_index=branch_index) is not None:
            return True
    return False


def derive_maturation_state_from_stamps(
    history: list[Mapping[str, Any]] | None,
    *,
    up_to_turn: int | None = None,
) -> dict[str, Any]:
    """Build head/pending purely from stamped labels on the active path."""
    max_head = _max_stamped_head_on_path(history, up_to_turn=up_to_turn)
    queue = _pending_queue_from_stamps(history, head=max_head, up_to_turn=up_to_turn)
    state = {
        **empty_label_thread_state(),
        "head_version": max_head,
        "pending_queue": queue,
    }
    return _sync_legacy_pending_fields(state)


def maturation_state_for_assembly(
    stored: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
) -> dict[str, Any]:
    """Stamp-derived maturation state for read-path assembly (fork metadata from cache)."""
    if _has_stamped_turns_on_path(history, up_to_turn=user_turn_count):
        derived = derive_maturation_state_from_stamps(history, up_to_turn=user_turn_count)
        head = int(derived.get("head_version") or 0)
        queue = _merge_pending_queues(
            _pending_queue_from_state(derived),
            _pending_queue_from_state(stored),
            head=head,
        )
        if history:
            queue = [
                item
                for item in queue
                if not _turn_definitively_not_anchoring_version(
                    int(item["since_turn"]),
                    int(item["version"]),
                    history,
                )
            ]
        merged = {**empty_label_thread_state(), **derived, "pending_queue": queue}
        merged = _sync_legacy_pending_fields(merged)
        merged = _merge_fork_metadata(merged, stored)
    else:
        merged = _merge_fork_metadata(
            {**empty_label_thread_state(), **dict(stored)},
            stored,
        )
        merged = _sync_legacy_pending_fields(merged)
    if not int(merged.get("catalog_snapshot_at_fork") or 0):
        max_attached = _max_stamped_attached_on_path(history, up_to_turn=user_turn_count)
        head = int(merged.get("head_version") or 0)
        if max_attached > head:
            merged["catalog_snapshot_at_fork"] = max_attached
    return merged


def maturation_state_for_planning(
    stored: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
) -> dict[str, Any]:
    """Stamp-derived state before stamping ``user_turn_count`` (write-path / unstamped turns)."""
    clip = max(0, user_turn_count - 1)
    if _has_stamped_turns_on_path(history, up_to_turn=clip):
        derived = derive_maturation_state_from_stamps(history, up_to_turn=clip)
        head = int(derived.get("head_version") or 0)
        queue = _merge_pending_queues(
            _pending_queue_from_state(derived),
            _pending_queue_from_state(stored),
            _pending_queue_from_stamps(history, head=head, up_to_turn=clip),
            head=head,
        )
        merged = {**empty_label_thread_state(), **derived, "pending_queue": queue}
        merged = _sync_legacy_pending_fields(merged)
        merged = _merge_fork_metadata(merged, stored)
    else:
        merged = _merge_fork_metadata(
            {**empty_label_thread_state(), **dict(stored)},
            stored,
        )
        merged = _sync_legacy_pending_fields(merged)
    if not int(merged.get("catalog_snapshot_at_fork") or 0):
        max_attached = _max_stamped_attached_on_path(history, up_to_turn=clip)
        head = int(merged.get("head_version") or 0)
        if max_attached > head:
            merged["catalog_snapshot_at_fork"] = max_attached
    if _is_edit_fork_at_turn(history, user_turn_count):
        queue = list(merged.get("pending_queue") or [])
        merged["pending_queue"] = [
            item for item in queue if int(item["since_turn"]) != user_turn_count
        ]
        merged = _sync_legacy_pending_fields(merged)
    return merged


def _sync_thread_state_cache(
    stored: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> dict[str, Any]:
    """Align stored thread cache with stamp-derived head/pending (never above stamps)."""
    if not _has_stamped_turns_on_path(history, up_to_turn=user_turn_count):
        return dict(stored)
    derived = maturation_state_for_assembly(stored, history, user_turn_count=user_turn_count)
    matured = mature_head_version(
        derived,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    result = {
        **dict(stored),
        "head_version": matured["head_version"],
        "pending_queue": matured["pending_queue"],
        "pending_version": matured["pending_version"],
        "pending_since_turn": matured["pending_since_turn"],
    }
    return _merge_fork_metadata(result, stored)


def resolve_label_thread_state(
    meta: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    *,
    latest_catalog_version: int | None = None,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    base_meta = dict(meta) if isinstance(meta, Mapping) else {}
    thread_key = active_thread_key(list(history or []))
    threads = load_label_thread_context(base_meta)
    valid_pairs = filter_alternating_roles(linearize_for_llm(list(history or [])))
    user_turn_count = count_user_turns(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)
    prev_key = base_meta.get("active_thread_key")
    parent = _find_label_thread_parent(
        threads,
        thread_key,
        prev_key if isinstance(prev_key, str) else None,
    )

    if thread_key not in threads:
        if parent is not None:
            threads[thread_key] = seed_label_thread_from_parent(
                parent,
                user_turn_count=user_turn_count,
                history=list(history or []),
                latest_catalog_version=int(latest_catalog_version or 0),
            )
        else:
            threads[thread_key] = empty_label_thread_state()

    threads[thread_key] = _reconcile_thread_state_with_history(
        threads[thread_key],
        list(history or []),
        user_turn_count=user_turn_count,
    )

    if thread_key in threads and threads[thread_key] is not None:
        threads[thread_key] = _sync_thread_state_cache(
            threads[thread_key],
            list(history or []),
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        )

    return dict(threads[thread_key]), thread_key, threads


def _is_fork_edit_reply(history: list[Mapping[str, Any]] | None) -> bool:
    """True when the latest user-turn is an edited branch (not a new linear turn)."""
    entries = enumerate_active_user_turns(list(history or []))
    if not entries:
        return False
    last = entries[-1]
    return bool(last.get("branched")) and int(last.get("branch_index") or 0) > 0


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


def _active_path_has_user_turn(
    history: list[Mapping[str, Any]] | None,
    turn: int,
) -> bool:
    for entry in enumerate_active_user_turns(list(history or [])):
        if int(entry["turn"]) == turn:
            return True
    return False


def _catalog_versions_visible_in_window(
    history: list[Mapping[str, Any]] | None,
    *,
    head_version: int,
    window_user_turns: set[int] | None,
) -> set[int]:
    """Catalog versions already present in the LLM prompt window (primer head + stamped floats)."""
    visible: set[int] = set()
    if head_version > 0:
        visible.add(head_version)
    if not history or not window_user_turns:
        return visible
    for entry in enumerate_active_user_turns(history):
        turn = int(entry["turn"])
        if turn not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        attached = read_stamped_attached_version(entry["message"], branch_index=branch_index)
        if attached > 0:
            visible.add(attached)
    return visible


def _latest_unseen_catalog_version(
    *,
    head: int,
    latest: int,
    visible: set[int],
) -> int:
    """Latest catalog version not yet represented in the prompt window (skip superseded gaps)."""
    max_visible = max(visible) if visible else head
    baseline = max(head, max_visible)
    if latest <= baseline:
        return 0
    return latest


def _attached_obsolete_in_window(
    attached: int,
    *,
    head_version: int,
    history: list[Mapping[str, Any]] | None,
    window_user_turns: set[int] | None,
) -> bool:
    """True when a newer (or same) bundle version is already visible in the prompt window."""
    if attached <= 0:
        return False
    visible = _catalog_versions_visible_in_window(
        history,
        head_version=head_version,
        window_user_turns=window_user_turns,
    )
    baseline = max(head_version, max(visible) if visible else head_version)
    return attached <= baseline


def _attached_version_visible_in_window(
    history: list[Mapping[str, Any]] | None,
    *,
    version: int,
    head: int,
    window_user_turns: set[int] | None,
) -> bool:
    """True when a stamped floating bundle for version is still in the LLM prompt window."""
    if not history or not window_user_turns or version <= head:
        return False
    for entry in enumerate_active_user_turns(history):
        turn = int(entry["turn"])
        if turn not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        attached = read_stamped_attached_version(entry["message"], branch_index=branch_index)
        if attached == version:
            return True
    return False


def _pending_version_is_matured(
    pending_since_turn: int,
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None,
    pending_version: int = 0,
    head: int = 0,
    history: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Pending head matures after N turns, or once its anchor turn left the prompt window."""
    if pending_since_turn <= 0:
        return False
    # Branch edit re-processes an existing turn — never promote head on that reply.
    if history and _is_fork_edit_reply(history):
        return False
    if _attached_version_visible_in_window(
        history,
        version=pending_version,
        head=head,
        window_user_turns=window_user_turns,
    ):
        return False
    if user_turn_count >= pending_since_turn + SUMMARY_BUNDLE_CATCHUP_MESSAGES:
        return True
    if (
        window_user_turns is not None
        and pending_since_turn not in window_user_turns
        and user_turn_count > pending_since_turn
    ):
        return True
    return False


def mature_head_version(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    head = int(state.get("head_version") or 0)
    queue = _resolve_pending_queue(state, history, user_turn_count=user_turn_count)

    matured_any = True
    while matured_any and queue:
        matured_any = False
        oldest = queue[0]
        if not _pending_version_is_matured(
            oldest["since_turn"],
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
            pending_version=int(oldest["version"]),
            head=head,
            history=history,
        ):
            break
        if oldest["version"] > head:
            head = oldest["version"]
        queue = [item for item in queue if item["version"] > head]
        matured_any = True

    result = {
        **dict(state),
        "head_version": head,
        "pending_queue": queue,
    }
    return _sync_legacy_pending_fields(result)


def plan_context_label_for_turn(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int, dict[str, Any]]:
    """Compute head-attached for the user-turn about to receive a reply."""
    matured = mature_head_version(
        state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=history,
    )
    head = int(matured.get("head_version") or 0)
    attached = 0
    queue = _pending_queue_for_label_plan(matured, history, user_turn_count=user_turn_count)
    queued_versions = _active_pending_versions(
        queue,
        history,
        user_turn_count=user_turn_count,
    )

    if head <= 0 and latest_catalog_version > 0:
        head = latest_catalog_version
        matured = {**matured, "head_version": head}
        queue = [item for item in queue if item["version"] > head]
        queued_versions = {item["version"] for item in queue}

    if latest_catalog_version > head:
        branch_fork_head = int(matured.get("fork_branch_zero_head") or 0)
        suppress_up_to = int(matured.get("fork_suppress_attach_up_to") or 0)
        if branch_fork_head > 0 and suppress_up_to > branch_fork_head:
            catalog_is_new = latest_catalog_version > suppress_up_to
        else:
            snapshot = int(matured.get("catalog_snapshot_at_fork") or 0)
            catalog_is_new = snapshot <= 0 or latest_catalog_version > snapshot
        if (
            catalog_is_new
            and latest_catalog_version not in queued_versions
            and not _pending_anchors_version_on_earlier_turn(
                latest_catalog_version,
                user_turn_count=user_turn_count,
                thread_state=matured,
                history=history,
            )
        ):
            # Only the current catalog version is pending — no intermediate queue.
            queue = [
                item for item in queue if int(item["version"]) <= head
            ]
            queue.append(
                {"version": latest_catalog_version, "since_turn": user_turn_count}
            )
            attached = latest_catalog_version
            matured = {
                **matured,
                "pending_queue": queue,
                "catalog_snapshot_at_fork": latest_catalog_version,
            }
            matured = _sync_legacy_pending_fields(matured)

    return head, attached, matured


def floating_bundles_from_labels(
    history: list[Mapping[str, Any]],
    *,
    catalog: Mapping[str, Any],
    scope: str,
    post_id: str | None,
    window_user_turns: set[int],
) -> dict[int, str]:
    injections: dict[int, str] = {}
    for entry in enumerate_active_user_turns(history):
        turn = int(entry["turn"])
        message = entry["message"]
        branch_index = entry["branch_index"] if entry.get("branched") else None
        attached = read_stamped_attached_version(message, branch_index=branch_index)
        if attached <= 0 or turn not in window_user_turns:
            continue
        text = resolve_bundle_text(
            catalog,
            scope=scope,
            post_id=post_id,
            version=attached,
        )
        if text:
            injections[turn] = text
    return injections


def _stamped_attached_by_turn(
    history: list[Mapping[str, Any]],
) -> dict[int, int]:
    by_turn: dict[int, int] = {}
    for entry in enumerate_active_user_turns(history):
        branch_index = entry["branch_index"] if entry.get("branched") else None
        by_turn[int(entry["turn"])] = read_stamped_attached_version(
            entry["message"],
            branch_index=branch_index,
        )
    return by_turn


def _attached_blocked_by_earlier_anchor(
    attached: int,
    *,
    user_turn_count: int,
    thread_state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> bool:
    """True when an earlier user-turn already has this version stamped as attached."""
    if attached <= 0:
        return False
    for turn, stamped in _stamped_attached_by_turn(list(history or [])).items():
        if turn < user_turn_count and stamped == attached:
            return True
    return False


def _turn_definitively_not_anchoring_version(
    turn: int,
    version: int,
    history: list[Mapping[str, Any]] | None,
) -> bool:
    """True when a stamped turn proves this catalog version is not anchored there."""
    if not history:
        return False
    for entry in enumerate_active_user_turns(history):
        if int(entry["turn"]) != turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        if read_stamped_context_label(entry["message"], branch_index=branch_index) is None:
            return False
        return read_stamped_attached_version(entry["message"], branch_index=branch_index) != version
    return False


def _pending_anchors_version_on_earlier_turn(
    version: int,
    *,
    user_turn_count: int,
    thread_state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> bool:
    for item in _pending_queue_for_label_plan(
        thread_state,
        history,
        user_turn_count=user_turn_count,
    ):
        if int(item["version"]) != version:
            continue
        since_turn = int(item["since_turn"])
        if since_turn >= user_turn_count:
            continue
        if _turn_definitively_not_anchoring_version(since_turn, version, history):
            continue
        return True
    return False


def _attached_already_stamped_on_earlier_turn(
    attached: int,
    *,
    user_turn_count: int,
    history: list[Mapping[str, Any]] | None,
) -> bool:
    return _attached_blocked_by_earlier_anchor(
        attached,
        user_turn_count=user_turn_count,
        thread_state={},
        history=history,
    )


def _attached_already_anchored_on_earlier_turn(
    attached: int,
    *,
    user_turn_count: int,
    thread_state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> bool:
    """True when this version is already stamped or pending on an earlier user-turn."""
    if attached <= 0:
        return False
    if _attached_already_stamped_on_earlier_turn(
        attached,
        user_turn_count=user_turn_count,
        history=history,
    ):
        return True
    return _pending_anchors_version_on_earlier_turn(
        attached,
        user_turn_count=user_turn_count,
        thread_state=thread_state,
        history=history,
    )


def _full_pending_queue(
    state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> list[dict[str, int]]:
    """Pending queue without clipping to the current turn (for retroactive label checks)."""
    head = int(state.get("head_version") or 0)
    from_stamps = _pending_queue_from_stamps(history, head=head)
    return _merge_pending_queues(_pending_queue_from_state(state), from_stamps, head=head)


def _attached_introduced_after_turn(
    attached: int,
    *,
    user_turn_count: int,
    thread_state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> bool:
    """True when this catalog version is first introduced on a later user-turn."""
    if attached <= 0:
        return False
    for item in _full_pending_queue(thread_state, history):
        since_turn = int(item["since_turn"])
        if int(item["version"]) == attached and since_turn > user_turn_count:
            if not _active_path_has_user_turn(history, since_turn):
                continue
            return True
    for turn, stamped in _stamped_attached_by_turn(list(history or [])).items():
        if turn > user_turn_count and stamped == attached:
            return True
    return False


def _effective_attached_for_turn(
    thread_state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int]:
    label = planned_context_label_at_turn(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_version=latest_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    parsed = parse_context_label(label)
    if parsed is None:
        return 0, 0
    return parsed[0], parsed[1]


def planned_context_label_at_turn(
    thread_state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> str:
    """Plan label for an unstamped turn from stamp-derived state (never stored head alone)."""
    edit_fork = _is_edit_fork_at_turn(history, user_turn_count)
    planning_state = maturation_state_for_planning(
        thread_state,
        history,
        user_turn_count=user_turn_count,
    )
    head, attached, planned = plan_context_label_for_turn(
        planning_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    if attached <= 0 and not edit_fork:
        matured_head = int(planned.get("head_version") or head)
        for item in _pending_queue_for_label_plan(
            planned,
            history,
            user_turn_count=user_turn_count,
        ):
            if int(item["since_turn"]) != user_turn_count:
                continue
            version = int(item["version"])
            if version <= matured_head:
                continue
            if _turn_definitively_not_anchoring_version(user_turn_count, version, history):
                continue
            attached = version
            head = matured_head
            break
    if attached > 0 and _attached_already_anchored_on_earlier_turn(
        attached,
        user_turn_count=user_turn_count,
        thread_state=planning_state,
        history=history,
    ):
        attached = 0
    elif attached > 0 and _attached_introduced_after_turn(
        attached,
        user_turn_count=user_turn_count,
        thread_state=planning_state,
        history=history,
    ):
        attached = 0
    if edit_fork and attached <= 0:
        matured_head = int(planned.get("head_version") or head)
        visible = _catalog_versions_visible_in_window(
            history,
            head_version=matured_head,
            window_user_turns=window_user_turns,
        )
        unseen = _latest_unseen_catalog_version(
            head=matured_head,
            latest=latest_version,
            visible=visible,
        )
        if unseen > matured_head:
            attached = unseen
            head = matured_head
    if attached > 0 and _attached_obsolete_in_window(
        attached,
        head_version=head,
        history=history,
        window_user_turns=window_user_turns,
    ):
        attached = 0
    return format_context_label(head, attached, turn_label)


def _inject_bundle_at_turn(
    floating: dict[int, str],
    *,
    turn: int,
    version: int,
    catalog: Mapping[str, Any],
    scope: str,
    post_id: str | None,
) -> None:
    if turn in floating or version <= 0:
        return
    text = resolve_bundle_text(
        catalog,
        scope=scope,
        post_id=post_id,
        version=version,
    )
    if text:
        floating[turn] = text


def _floating_bundles_for_assemble(
    *,
    history: list[Mapping[str, Any]],
    thread_state: Mapping[str, Any],
    catalog: Mapping[str, Any],
    scope: str,
    post_id: str | None,
    window_user_turns: set[int],
    user_turn_count: int,
    latest_version: int,
) -> dict[int, str]:
    """Floating bundles: stamped attached first; plan only for unstamped window turns."""
    floating = floating_bundles_from_labels(
        history,
        catalog=catalog,
        scope=scope,
        post_id=post_id,
        window_user_turns=window_user_turns,
    )

    for entry in enumerate_active_user_turns(history):
        turn = int(entry["turn"])
        if turn not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        if read_stamped_context_label(entry["message"], branch_index=branch_index) is not None:
            continue
        turn_label = str(entry["turn_label"])
        label = planned_context_label_at_turn(
            thread_state,
            user_turn_count=turn,
            turn_label=turn_label,
            latest_version=latest_version,
            window_user_turns=window_user_turns,
            history=history,
        )
        parsed = parse_context_label(label)
        if parsed is None:
            continue
        _head, attached, _turn = parsed
        if attached > 0:
            _inject_bundle_at_turn(
                floating,
                turn=turn,
                version=attached,
                catalog=catalog,
                scope=scope,
                post_id=post_id,
            )

    stamped_turns = {
        int(entry["turn"])
        for entry in enumerate_active_user_turns(history)
        if read_stamped_context_label(
            entry["message"],
            branch_index=entry["branch_index"] if entry.get("branched") else None,
        )
        is not None
    }
    if user_turn_count in window_user_turns and user_turn_count not in stamped_turns:
        turn_label = resolve_turn_label(history, user_turn_count)
        label = planned_context_label_at_turn(
            thread_state,
            user_turn_count=user_turn_count,
            turn_label=turn_label,
            latest_version=latest_version,
            window_user_turns=window_user_turns,
            history=history,
        )
        parsed = parse_context_label(label)
        if parsed is not None:
            _head, attached, _turn = parsed
            if attached > 0:
                _inject_bundle_at_turn(
                    floating,
                    turn=user_turn_count,
                    version=attached,
                    catalog=catalog,
                    scope=scope,
                    post_id=post_id,
                )
    return floating


def primer_head_from_stamps(
    stored: Mapping[str, Any],
    *,
    user_turn_count: int,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> int:
    """Primer head from stamp-derived maturation state (stored head never overrides stamps)."""
    state = maturation_state_for_assembly(
        stored,
        list(history or []),
        user_turn_count=user_turn_count,
    )
    matured = mature_head_version(
        state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    head = int(matured.get("head_version") or 0)
    if head <= 0:
        return latest_catalog_version
    return head


def primer_head_from_thread(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> int:
    return primer_head_from_stamps(
        state,
        user_turn_count=user_turn_count,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
        history=history,
    )


def primer_log_label(head_version: int) -> str:
    return f"user/primer [{format_context_label(head_version, 0, '0')}]"


def _label_for_turn_label(
    labels_by_turn_label: dict[str, str],
    *,
    turn_label: str,
    thread_state: Mapping[str, Any],
    latest_version: int,
    user_turn_count: int,
    history: list[Mapping[str, Any]] | None = None,
    window_user_turns: set[int] | None = None,
) -> str:
    if turn_label in labels_by_turn_label:
        return labels_by_turn_label[turn_label]
    return planned_context_label_at_turn(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_version=latest_version,
        window_user_turns=window_user_turns,
        history=history,
    )


def fill_llm_log_labels(
    log_labels: dict[int, str],
    messages: list[dict[str, str]],
    *,
    head_version: int,
    history: list[Mapping[str, Any]],
    thread_state: Mapping[str, Any],
    latest_version: int,
    user_turn_count: int,
    valid_pairs: list[tuple[str, str]],
) -> None:
    """Annotate assembled LLM messages with context labels for terminal logging."""
    if not messages:
        return

    log_labels[0] = "system"
    if len(messages) > 1:
        log_labels[1] = primer_log_label(head_version)
    if len(messages) > 2:
        log_labels[2] = "assistant/primer-ack"

    labels_by_turn: dict[int, str] = {}
    for entry in enumerate_active_user_turns(history):
        branch_index = entry["branch_index"] if entry.get("branched") else None
        stamped = read_stamped_context_label(entry["message"], branch_index=branch_index)
        if stamped is not None:
            labels_by_turn[int(entry["turn"])] = stamped

    window_len = max(0, len(messages) - 3)
    window_annotated = annotate_user_turns(valid_pairs)[-window_len:] if window_len else []
    window_user_turns = compute_window_user_turns(valid_pairs)

    msg_idx = 3
    for user_turn, role, _content in window_annotated:
        if role == "assistant":
            log_labels[msg_idx] = "assistant"
        elif role == "user" and user_turn is not None:
            stamped = labels_by_turn.get(user_turn)
            if stamped is not None:
                log_labels[msg_idx] = f"user [{stamped}]"
            else:
                turn_label = resolve_turn_label(history, user_turn)
                label = _label_for_turn_label(
                    labels_by_turn_label={},
                    turn_label=turn_label,
                    thread_state=thread_state,
                    latest_version=latest_version,
                    user_turn_count=user_turn,
                    history=history,
                    window_user_turns=window_user_turns,
                )
                log_labels[msg_idx] = f"user [{label}]"
        else:
            log_labels[msg_idx] = role
        msg_idx += 1


def assemble_reply_messages_from_labels(
    *,
    ai_profile: Mapping[str, Any],
    user_text: str,
    scope: str = "global",
    history: list[Mapping[str, Any]] | None = None,
    chat_meta: Mapping[str, Any] | None = None,
    catalog: Mapping[str, Any],
    post_id: str | None = None,
    log_labels: dict[int, str] | None = None,
) -> list[dict[str, str]] | None:
    """Build messages from label catalog; None if catalog is empty."""
    global_versions = catalog.get("global") or []
    if scope == "post" and post_id:
        if not _local_versions_nonempty(catalog, post_id) and not global_versions:
            return None
    elif not global_versions:
        return None

    system_prompt = str(ai_profile.get("systemPrompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)
    trimmed = user_text.strip()
    if trimmed:
        if not valid_pairs or valid_pairs[-1][0] != "user":
            valid_pairs.append(("user", trimmed))
        elif valid_pairs[-1][1] != trimmed:
            valid_pairs.append(("user", trimmed))

    user_turn_count = count_user_turns(valid_pairs)
    window_pairs = take_prompt_window(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)

    latest_version = latest_scope_version(catalog, scope=scope, post_id=post_id)
    thread_state, _, _ = resolve_label_thread_state(
        chat_meta,
        list(history or []),
        latest_catalog_version=latest_version,
    )
    head_version = primer_head_from_thread(
        thread_state,
        user_turn_count=user_turn_count,
        latest_catalog_version=latest_version,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    head_text = resolve_bundle_text(
        catalog,
        scope=scope,
        post_id=post_id,
        version=head_version,
    )
    rolling_summary = str(thread_state.get("rolling_summary") or "").strip()

    floating = _floating_bundles_for_assemble(
        history=list(history or []),
        thread_state=thread_state,
        catalog=catalog,
        scope=scope,
        post_id=post_id,
        window_user_turns=window_user_turns,
        user_turn_count=user_turn_count,
        latest_version=latest_version,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_primer_user_content(head_text, rolling_summary)},
        {"role": "assistant", "content": PRIMER_ACK},
    ]
    messages.extend(
        build_dialog_messages(
            window_pairs,
            valid_pairs=valid_pairs,
            floating_bundles=floating,
        )
    )
    if log_labels is not None:
        fill_llm_log_labels(
            log_labels,
            messages,
            head_version=head_version,
            history=list(history or []),
            thread_state=thread_state,
            latest_version=latest_version,
            user_turn_count=user_turn_count,
            valid_pairs=valid_pairs,
        )
    return messages


def _local_versions_nonempty(catalog: Mapping[str, Any], post_id: str) -> bool:
    local = catalog.get("local")
    if not isinstance(local, Mapping):
        return False
    versions = local.get(post_id)
    return isinstance(versions, list) and len(versions) > 0


def advance_label_thread_after_reply(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int, dict[str, Any]]:
    planning_state = maturation_state_for_planning(
        state,
        list(history or []),
        user_turn_count=user_turn_count,
    )
    head, attached, next_state = plan_context_label_for_turn(
        planning_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    if attached > 0:
        if _attached_already_anchored_on_earlier_turn(
            attached,
            user_turn_count=user_turn_count,
            thread_state=planning_state,
            history=history,
        ):
            attached = 0
    next_state = mature_head_version(
        next_state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=history,
    )
    matured_head = int(next_state.get("head_version") or 0)
    if matured_head != head:
        head = matured_head
        attached = 0
    next_state = {
        **dict(state),
        **next_state,
    }
    return head, attached, _merge_fork_metadata(next_state, state)


def flatten_label_thread_meta(
    thread_state: Mapping[str, Any],
    *,
    thread_key: str,
    threads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "active_thread_key": thread_key,
        THREAD_LABEL_STATE_KEY: {key: dict(value) for key, value in threads.items()},
        "rolling_summary": str(thread_state.get("rolling_summary") or "").strip(),
        "rolling_summary_idx": int(thread_state.get("rolling_summary_idx") or 0),
    }
