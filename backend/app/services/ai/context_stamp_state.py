"""Per-branch stamp state load/save and flatten for chat meta."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.context_label_shared import _is_edit_fork_at_turn
from app.services.ai.context_stamp_address import (
    ensure_branch_state,
    load_stamp_context,
    resolve_active_branch_id,
    resolve_fork_parent_branch_id,
)
from app.services.ai.context_stamp_history import merge_pending_queues
from app.services.ai.context_stamp_maturation import (
    _FORK_HEAD_CHANNEL,
    _FORK_HEAD_POST,
    _SUPPRESS_ATTACH_CHANNEL,
    _SUPPRESS_ATTACH_POST,
    fork_anchor_from_branch_zero,
)
from app.services.ai.context_stamp_types import (
    ACTIVE_BRANCH_KEY,
    STAMP_CONTEXT_KEY,
    STAMP_MECHANICS_FLAG,
    BranchStampState,
    StampContextRoot,
    branch_state_key,
    normalize_summary_versions,
)
from app.services.ai.rolling_summary import reconcile_rolling_summary_fields


def get_branch_state(
    stamp_context: StampContextRoot,
    branch_id: int,
    *,
    post_head: int = 0,
) -> BranchStampState:
    ensure_branch_state(stamp_context, branch_id, post_head=post_head)
    raw = stamp_context["branches"][branch_state_key(branch_id)]
    return dict(raw)


def resolve_stamp_thread_state(
    chat_meta: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    *,
    post_head: int = 0,
) -> tuple[BranchStampState, int, StampContextRoot]:
    stamp_context = load_stamp_context(chat_meta, post_head=post_head)
    branch_id = resolve_active_branch_id(history, stamp_context)
    ensure_branch_state(stamp_context, branch_id, post_head=post_head)
    state = get_branch_state(stamp_context, branch_id, post_head=post_head)
    return state, branch_id, stamp_context


def flatten_stamp_meta(
    branch_state: BranchStampState,
    *,
    branch_id: int,
    stamp_context: StampContextRoot,
) -> dict[str, Any]:
    branches = dict(stamp_context.get("branches") or {})
    branches[branch_state_key(branch_id)] = dict(branch_state)
    return {
        STAMP_MECHANICS_FLAG: True,
        ACTIVE_BRANCH_KEY: branch_id,
        STAMP_CONTEXT_KEY: {
            "branches": branches,
            "next_branch_id": int(stamp_context.get("next_branch_id") or 2),
            "branch_registry": dict(stamp_context.get("branch_registry") or {}),
        },
    }


def is_pristine_branch_state(
    state: Mapping[str, Any] | None,
    *,
    post_head_default: int,
) -> bool:
    """True for placeholder branch rows created by ``ensure_branch_state`` only."""
    if not isinstance(state, Mapping):
        return True
    if state.get(_FORK_HEAD_CHANNEL) or state.get(_FORK_HEAD_POST):
        return False
    if str(state.get("rolling_summary") or "").strip():
        return False
    pending = state.get("pending") or {}
    if list(pending.get("channel") or []) or list(pending.get("post") or []):
        return False
    head = normalize_summary_versions(state.get("head"), scope="post")
    return int(head.get("channel") or 0) <= 0 and int(head.get("post") or 0) == post_head_default


def ensure_edit_fork_branch_seeded(
    stamp_context: StampContextRoot,
    branch_id: int,
    *,
    fork_path: list[int] | None,
    fork_msg: int,
    scope: str,
    history: list[Mapping[str, Any]] | None,
    post_head: int,
) -> None:
    """Seed edit-fork branch state from branch-0 stamp before placeholder overwrite."""
    key = branch_state_key(branch_id)
    branches = stamp_context.setdefault("branches", {})
    existing = branches.get(key)
    if existing is not None and not is_pristine_branch_state(existing, post_head_default=post_head):
        return
    parent_id = resolve_fork_parent_branch_id(
        stamp_context,
        fork_path=list(fork_path or []),
        fork_branch_id=branch_id,
    )
    ensure_branch_state(stamp_context, parent_id, post_head=post_head)
    parent_state = branches[branch_state_key(parent_id)]
    branches[key] = seed_branch_from_parent(
        dict(parent_state),
        fork_msg=fork_msg,
        scope=scope,
        history=history,
        current_msg=fork_msg,
    )


def seed_branch_from_parent(
    parent: BranchStampState,
    *,
    fork_msg: int,
    scope: str,
    history: list[Mapping[str, Any]] | None = None,
    current_msg: int = 0,
) -> BranchStampState:
    """Fork: inherit heads from branch-0 stamp at fork; clip pending to fork turn."""
    head = normalize_summary_versions(parent.get("head"), scope=scope)
    pending = parent.get("pending") or {"channel": [], "post": []}
    channel_q = [
        dict(item)
        for item in list(pending.get("channel") or [])
        if int(item.get("sinceMsg") or 0) <= fork_msg
    ]
    post_q = [
        dict(item)
        for item in list(pending.get("post") or [])
        if int(item.get("sinceMsg") or 0) <= fork_msg
    ]
    state: dict[str, Any] = {
        "head": dict(head),
        "pending": {"channel": channel_q, "post": post_q},
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }

    edit_fork = bool(history and current_msg > 0 and _is_edit_fork_at_turn(history, current_msg))
    anchor = fork_anchor_from_branch_zero(history, fork_msg=fork_msg)
    if anchor is not None:
        anchor_head, anchor_pending, nested_fork = anchor
        parent_ch = int(parent.get(_FORK_HEAD_CHANNEL) or parent.get("head", {}).get("channel") or 0)
        parent_post = int(
            parent.get(_FORK_HEAD_POST) or parent.get("head", {}).get("post") or 0
        )
        head = normalize_summary_versions(anchor_head, scope=scope)
        state[_FORK_HEAD_CHANNEL] = head["channel"]
        if scope == "post":
            state[_FORK_HEAD_POST] = head["post"]
        if nested_fork and not edit_fork:
            if parent_ch > head["channel"]:
                state[_SUPPRESS_ATTACH_CHANNEL] = parent_ch
            if scope == "post" and parent_post > head["post"]:
                state[_SUPPRESS_ATTACH_POST] = parent_post
        if edit_fork:
            anchor_pending = {"channel": [], "post": []}
        for layer in ("channel", "post"):
            if layer == "post" and scope != "post":
                continue
            head_val = max(0, int(head.get(layer) or 0))
            merged = merge_pending_queues(
                channel_q if layer == "channel" else post_q,
                list(anchor_pending.get(layer) or []),
                head=head_val,
            )
            if edit_fork:
                merged = [
                    item for item in merged if int(item.get("sinceMsg") or 0) != current_msg
                ]
            state["pending"][layer] = merged
        state["head"] = head

    if edit_fork:
        state["catalog_snapshot_channel"] = 0
        if scope == "post":
            state["catalog_snapshot_post"] = 0

    return state  # type: ignore[return-value]


def reconcile_branch_rolling(
    branch_state: BranchStampState,
    valid_pairs: list[tuple[str, str]],
) -> BranchStampState:
    reconciled = reconcile_rolling_summary_fields(branch_state, valid_pairs)
    return {
        **branch_state,
        "rolling_summary": str(reconciled.get("rolling_summary") or ""),
        "rolling_summary_idx": int(reconciled.get("rolling_summary_idx") or 0),
    }
