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
    read_stamped_attached_version,
    read_stamped_context_label,
    resolve_turn_label,
)
from app.services.ai.context_turns import annotate_user_turns, compute_window_user_turns
from app.services.ai.summary_catalog import resolve_bundle_text

THREAD_LABEL_STATE_KEY = "label_context"


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
    if isinstance(raw, list):
        items: list[dict[str, int]] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            version = int(entry.get("version") or 0)
            since_turn = int(entry.get("since_turn") or 0)
            if version > 0 and since_turn > 0:
                items.append({"version": version, "since_turn": since_turn})
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
    head = int(state.get("head_version") or 0)
    from_stamps = _pending_queue_from_stamps(history, head=head, up_to_turn=up_to_turn)
    if history is not None:
        queue = from_stamps
    else:
        queue = _merge_pending_queues(_pending_queue_from_state(state), from_stamps, head=head)
    clip = user_turn_count if user_turn_count is not None else up_to_turn
    if clip is not None:
        queue = [item for item in queue if int(item["since_turn"]) <= clip]
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
        snapshot = max((version for version in active_attached if version > head), default=head)

    result = {
        **dict(state),
        "pending_queue": queue,
        "catalog_snapshot_at_fork": snapshot,
    }
    return _sync_legacy_pending_fields(result)


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
    if anchor is not None:
        head, pending, pending_since, nested_fork = anchor
        parent_head = int(parent.get("head_version") or 0)
        state["fork_branch_zero_head"] = head
        # Nested fork: parent may have matured versions the branch-0 label never saw.
        if nested_fork and parent_head > head:
            state["fork_suppress_attach_up_to"] = parent_head

    if pending > 0 and pending_since > user_turn_count:
        pending = 0
        pending_since = 0

    state["head_version"] = head
    parent_queue = [
        item
        for item in _resolve_pending_queue(parent, history, up_to_turn=user_turn_count)
        if int(item["since_turn"]) <= user_turn_count
    ]
    queue = _merge_pending_queues(
        parent_queue,
        _pending_queue_from_stamps(history, head=head, up_to_turn=user_turn_count),
        ([{"version": pending, "since_turn": pending_since}] if pending > head and pending_since > 0 else []),
        head=head,
    )
    state["pending_queue"] = queue
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


def _max_stamped_head_on_path(history: list[Mapping[str, Any]] | None) -> int:
    from app.services.ai.context_label import parse_context_label

    max_head = 0
    for entry in enumerate_active_user_turns(list(history or [])):
        branch_index = entry["branch_index"] if entry.get("branched") else None
        raw = read_stamped_context_label(entry["message"], branch_index=branch_index)
        if raw is None:
            continue
        parsed = parse_context_label(raw)
        if parsed is None:
            continue
        max_head = max(max_head, int(parsed[0]))
    return max_head


def _repair_premature_stored_head(
    stored: Mapping[str, Any],
    *,
    parent: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    user_turn_count: int,
    window_user_turns: set[int] | None,
) -> dict[str, Any]:
    """Demote head that was persisted before maturation guards or wrong window."""
    stored_head = int(stored.get("head_version") or 0)
    if not history:
        return dict(stored)

    anchor = _fork_anchor_from_branch_zero_label(history)
    if anchor is not None and parent is not None:
        baseline = seed_label_thread_from_parent(
            parent,
            user_turn_count=user_turn_count,
            history=list(history or []),
        )
    else:
        max_stamped_head = _max_stamped_head_on_path(history)
        if max_stamped_head <= 0:
            return dict(stored)
        baseline = {
            **empty_label_thread_state(),
            "head_version": max_stamped_head,
            "pending_queue": _merge_pending_queues(
                _pending_queue_from_stamps(history, head=max_stamped_head),
                _pending_queue_from_state(stored),
                head=max_stamped_head,
            ),
        }

    corrected = mature_head_version(
        baseline,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    corrected_head = int(corrected.get("head_version") or 0)
    if stored_head <= corrected_head:
        return dict(stored)

    merged = {
        **dict(stored),
        "head_version": corrected_head,
        "pending_queue": corrected.get("pending_queue") or [],
    }
    return _sync_legacy_pending_fields(merged)


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
        threads[thread_key] = _repair_premature_stored_head(
            threads[thread_key],
            parent=parent,
            history=list(history or []),
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
    queue = _resolve_pending_queue(matured, history, user_turn_count=user_turn_count)
    queued_versions = {item["version"] for item in queue}

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
        if catalog_is_new and latest_catalog_version not in queued_versions:
            queue = [
                *queue,
                {"version": latest_catalog_version, "since_turn": user_turn_count},
            ]
            queue.sort(key=lambda item: (item["since_turn"], item["version"]))
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


def primer_head_from_thread(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> int:
    matured = mature_head_version(
        state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        history=history,
    )
    head = int(matured.get("head_version") or 0)
    if head <= 0:
        return latest_catalog_version
    return head


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
    head, attached, _ = plan_context_label_for_turn(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    return format_context_label(head, attached, turn_label)


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

    latest_version = _latest_scope_version(catalog, scope=scope, post_id=post_id)
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

    floating = floating_bundles_from_labels(
        list(history or []),
        catalog=catalog,
        scope=scope,
        post_id=post_id,
        window_user_turns=window_user_turns,
    )

    # Pending attached on current turn (not yet stamped on history)
    turn_label = resolve_turn_label(list(history or []), user_turn_count)
    _head, attached_now, _ = plan_context_label_for_turn(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_version,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    if attached_now > 0 and user_turn_count in window_user_turns:
        pending_text = resolve_bundle_text(
            catalog,
            scope=scope,
            post_id=post_id,
            version=attached_now,
        )
        if pending_text:
            floating[user_turn_count] = pending_text

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


def _latest_scope_version(catalog: Mapping[str, Any], *, scope: str, post_id: str | None) -> int:
    if scope == "post" and post_id:
        local = catalog.get("local")
        if isinstance(local, Mapping):
            versions = local.get(post_id)
            if isinstance(versions, list) and versions:
                return int(versions[-1].get("version") or 0)
    global_versions = catalog.get("global") or []
    if global_versions:
        return int(global_versions[-1].get("version") or 0)
    return 0


def advance_label_thread_after_reply(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int, dict[str, Any]]:
    head, attached, next_state = plan_context_label_for_turn(
        state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
        history=history,
    )
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
    return head, attached, next_state


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
