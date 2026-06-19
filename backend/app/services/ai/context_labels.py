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
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }


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
        parent_matured = mature_head_version(parent, user_turn_count=user_turn_count)
        parent_head = int(parent_matured.get("head_version") or 0)
        state["fork_branch_zero_head"] = head
        # Nested fork: parent may have matured versions the branch-0 label never saw.
        if nested_fork and parent_head > head:
            state["fork_suppress_attach_up_to"] = parent_head

    if pending > 0 and pending_since > user_turn_count:
        pending = 0
        pending_since = 0

    state["head_version"] = head
    state["pending_version"] = pending
    state["pending_since_turn"] = pending_since
    return state


def resolve_label_thread_state(
    meta: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    *,
    latest_catalog_version: int | None = None,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    base_meta = dict(meta) if isinstance(meta, Mapping) else {}
    thread_key = active_thread_key(list(history or []))
    threads = load_label_thread_context(base_meta)
    user_turn_count = count_user_turns(linearize_for_llm(list(history or [])))

    if thread_key not in threads:
        prev_key = base_meta.get("active_thread_key")
        parent = None
        if isinstance(prev_key, str):
            parent = threads.get(prev_key)
        if parent is None and threads:
            for key in sorted(threads.keys(), key=len, reverse=True):
                if thread_key == key or thread_key.startswith(f"{key},"):
                    parent = threads[key]
                    break
        if parent is not None:
            threads[thread_key] = seed_label_thread_from_parent(
                parent,
                user_turn_count=user_turn_count,
                history=list(history or []),
                latest_catalog_version=int(latest_catalog_version or 0),
            )
        else:
            threads[thread_key] = empty_label_thread_state()

    return dict(threads[thread_key]), thread_key, threads


def _pending_version_is_matured(
    pending_since_turn: int,
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None,
) -> bool:
    """Pending head matures after N turns, or once its anchor turn left the prompt window."""
    if pending_since_turn <= 0:
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
) -> dict[str, Any]:
    head = int(state.get("head_version") or 0)
    pending = int(state.get("pending_version") or 0)
    pending_since = int(state.get("pending_since_turn") or 0)
    if pending > 0 and pending_since > 0:
        if _pending_version_is_matured(
            pending_since,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        ):
            head = pending
            pending = 0
            pending_since = 0
    return {
        **dict(state),
        "head_version": head,
        "pending_version": pending,
        "pending_since_turn": pending_since,
    }


def plan_context_label_for_turn(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_catalog_version: int,
    window_user_turns: set[int] | None = None,
) -> tuple[int, int, dict[str, Any]]:
    """Compute head-attached for the user-turn about to receive a reply."""
    matured = mature_head_version(
        state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    head = int(matured.get("head_version") or 0)
    pending = int(matured.get("pending_version") or 0)
    attached = 0

    if head <= 0 and latest_catalog_version > 0:
        head = latest_catalog_version
        matured = {**matured, "head_version": head}

    if latest_catalog_version > head:
        branch_fork_head = int(matured.get("fork_branch_zero_head") or 0)
        suppress_up_to = int(matured.get("fork_suppress_attach_up_to") or 0)
        if branch_fork_head > 0 and suppress_up_to > branch_fork_head:
            catalog_is_new = latest_catalog_version > suppress_up_to
        else:
            snapshot = int(matured.get("catalog_snapshot_at_fork") or 0)
            catalog_is_new = snapshot <= 0 or latest_catalog_version > snapshot
        if pending == 0:
            if catalog_is_new:
                matured = {
                    **matured,
                    "pending_version": latest_catalog_version,
                    "pending_since_turn": user_turn_count,
                    "catalog_snapshot_at_fork": latest_catalog_version,
                }
                attached = latest_catalog_version
        elif latest_catalog_version > pending:
            matured = {
                **matured,
                "pending_version": latest_catalog_version,
                "pending_since_turn": user_turn_count,
                "catalog_snapshot_at_fork": latest_catalog_version,
            }
            attached = latest_catalog_version

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
) -> int:
    matured = mature_head_version(
        state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
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
) -> str:
    if turn_label in labels_by_turn_label:
        return labels_by_turn_label[turn_label]
    head, attached, _ = plan_context_label_for_turn(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_version,
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
) -> tuple[int, int, dict[str, Any]]:
    head, attached, next_state = plan_context_label_for_turn(
        state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
    )
    next_state = mature_head_version(
        next_state,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
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
