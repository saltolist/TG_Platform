"""Plan head/attach maturation for context stamp mechanics."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.context_label_shared import _is_edit_fork_at_turn
from app.services.ai.context_stamp_history import (
    attach_already_stamped_on_earlier_msg,
    merge_pending_queues,
    pending_queue_from_stamp_attaches,
)
from app.services.ai.context_stamp_maturation import (
    _CATALOG_SNAPSHOT_CHANNEL,
    _CATALOG_SNAPSHOT_POST,
    _FORK_HEAD_CHANNEL,
    _FORK_HEAD_POST,
    _SUPPRESS_ATTACH_CHANNEL,
    _SUPPRESS_ATTACH_POST,
    _is_fork_edit_reply,
    edit_fork_unseen_layer_attach,
    fork_anchor_from_branch_zero,
    lock_edit_fork_heads,
    maturation_state_for_planning,
    mature_branch_heads,
)
from app.services.ai.context_stamp_types import (
    BranchStampState,
    LayerPending,
    PendingItem,
    SummaryVersions,
    normalize_summary_versions,
)

LayerName = str


def _layer_head(head: SummaryVersions, layer: LayerName) -> int:
    return max(0, int(head.get(layer) or 0))


def _layer_pending(pending: LayerPending, layer: LayerName) -> list[PendingItem]:
    return [dict(item) for item in list(pending.get(layer) or [])]


def _merge_pending_item(
    queue: list[PendingItem],
    *,
    version: int,
    since_msg: int,
) -> list[PendingItem]:
    if version <= 0 or since_msg <= 0:
        return queue
    versions = {int(item["version"]) for item in queue}
    if version in versions:
        return queue
    merged = [dict(item) for item in queue if int(item["version"]) < version]
    merged.append({"version": version, "sinceMsg": since_msg})
    merged.sort(key=lambda item: int(item["version"]))
    return merged


def _active_pending_versions(
    queue: list[PendingItem],
    *,
    current_msg: int,
) -> set[int]:
    return {
        int(item["version"])
        for item in queue
        if int(item.get("sinceMsg") or 0) <= current_msg
    }


def _pending_anchors_version_on_earlier_msg(
    version: int,
    *,
    layer: LayerName,
    current_msg: int,
    state: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> bool:
    for item in _layer_pending(state.get("pending") or {}, layer):
        if int(item["version"]) == version and int(item.get("sinceMsg") or 0) < current_msg:
            return True
    if history:
        from app.services.ai.context_stamp_history import stamped_layer_attach_by_msg

        for msg, attached in stamped_layer_attach_by_msg(history, layer).items():
            if msg < current_msg and attached == version:
                return True
    return False


def reconcile_pending_with_stamps(
    state: BranchStampState,
    history: list[Mapping[str, Any]] | None,
    *,
    scope: str,
    current_msg: int,
) -> BranchStampState:
    """Merge stored pending with anchors rebuilt from stamped attach on history."""
    head = normalize_summary_versions(state.get("head"), scope=scope)
    pending: LayerPending = {
        "channel": _layer_pending(state.get("pending") or {}, "channel"),
        "post": _layer_pending(state.get("pending") or {}, "post"),
    }
    for layer in ("channel", "post"):
        if layer == "post" and scope != "post":
            continue
        head_val = _layer_head(head, layer)
        from_stamps = pending_queue_from_stamp_attaches(
            history,
            layer=layer,
            head=head_val,
            up_to_msg=current_msg,
        )
        pending[layer] = merge_pending_queues(
            _layer_pending(pending, layer),
            from_stamps,
            head=head_val,
        )
    return {**state, "pending": pending}


def initialize_heads_if_empty(
    state: BranchStampState,
    *,
    latest_channel: int,
    latest_post: int,
    scope: str,
) -> BranchStampState:
    head = normalize_summary_versions(state.get("head"), scope=scope)
    if head["channel"] <= 0 and latest_channel > 0:
        head["channel"] = latest_channel
    if scope == "post" and head["post"] <= 0 and latest_post > 0:
        head["post"] = latest_post
    elif scope == "global":
        head["post"] = 0
    return {**state, "head": head}


def queue_catalog_bumps(
    state: BranchStampState,
    *,
    current_msg: int,
    latest_channel: int,
    latest_post: int,
    scope: str,
    history: list[Mapping[str, Any]] | None = None,
) -> BranchStampState:
    """Enqueue catalog versions newer than head for attach on this msg."""
    head = normalize_summary_versions(state.get("head"), scope=scope)
    pending: LayerPending = {
        "channel": _layer_pending(state.get("pending") or {}, "channel"),
        "post": _layer_pending(state.get("pending") or {}, "post"),
    }
    working = dict(state)

    def _queue_layer(
        layer: LayerName,
        *,
        latest: int,
        snapshot_key: str,
        suppress_key: str,
        fork_head_key: str,
    ) -> None:
        nonlocal pending, working
        head_val = _layer_head(head, layer)
        if latest <= head_val:
            return
        queue = _layer_pending(pending, layer)
        queued_versions = _active_pending_versions(queue, current_msg=current_msg)
        branch_fork_head = int(working.get(fork_head_key) or 0)
        suppress_up_to = int(working.get(suppress_key) or 0)
        if branch_fork_head > 0 and suppress_up_to > branch_fork_head:
            catalog_is_new = latest > suppress_up_to
        else:
            snapshot = int(working.get(snapshot_key) or 0)
            catalog_is_new = snapshot <= 0 or latest > snapshot
        if (
            catalog_is_new
            and latest not in queued_versions
            and not _pending_anchors_version_on_earlier_msg(
                latest,
                layer=layer,
                current_msg=current_msg,
                state=working,
                history=history,
            )
            and not attach_already_stamped_on_earlier_msg(
                history,
                layer=layer,
                version=latest,
                current_msg=current_msg,
            )
        ):
            pending[layer] = _merge_pending_item(
                [item for item in queue if int(item["version"]) <= head_val],
                version=latest,
                since_msg=current_msg,
            )
            working[snapshot_key] = latest

    _queue_layer(
        "channel",
        latest=latest_channel,
        snapshot_key=_CATALOG_SNAPSHOT_CHANNEL,
        suppress_key=_SUPPRESS_ATTACH_CHANNEL,
        fork_head_key=_FORK_HEAD_CHANNEL,
    )
    if scope == "post":
        _queue_layer(
            "post",
            latest=latest_post,
            snapshot_key=_CATALOG_SNAPSHOT_POST,
            suppress_key=_SUPPRESS_ATTACH_POST,
            fork_head_key=_FORK_HEAD_POST,
        )
    return {**working, "pending": pending}


def plan_attach_for_msg(
    state: BranchStampState,
    *,
    current_msg: int,
    scope: str,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[SummaryVersions, BranchStampState]:
    """Pick attach versions anchored on ``current_msg``; leave head unchanged."""
    head = normalize_summary_versions(state.get("head"), scope=scope)
    pending: LayerPending = {
        "channel": _layer_pending(state.get("pending") or {}, "channel"),
        "post": _layer_pending(state.get("pending") or {}, "post"),
    }
    attach: SummaryVersions = {"channel": 0, "post": 0}
    for layer in ("channel", "post"):
        if layer == "post" and scope != "post":
            continue
        head_val = _layer_head(head, layer)
        queue = _layer_pending(pending, layer)
        chosen = 0
        rest: list[PendingItem] = []
        for item in queue:
            since_msg = int(item.get("sinceMsg") or 0)
            version = int(item.get("version") or 0)
            if since_msg == current_msg and version > head_val:
                chosen = version
                continue
            rest.append(item)
        if chosen > 0 and attach_already_stamped_on_earlier_msg(
            history,
            layer=layer,
            version=chosen,
            current_msg=current_msg,
        ):
            chosen = 0
        if chosen > 0:
            attach[layer] = chosen
        pending[layer] = rest
    return attach, {**state, "pending": pending}


def advance_branch_after_reply(
    state: BranchStampState,
    *,
    current_msg: int,
    latest_channel: int,
    latest_post: int,
    scope: str,
    is_edit_fork: bool = False,
    history: list[Mapping[str, Any]] | None = None,
    window_user_turns: set[int] | None = None,
) -> tuple[SummaryVersions, SummaryVersions, BranchStampState]:
    """Return (head, attach, next_state) for stamping the current user turn."""
    working = maturation_state_for_planning(
        dict(state),
        history,
        current_msg=current_msg,
        scope=scope,
    )
    working = initialize_heads_if_empty(
        working,
        latest_channel=latest_channel,
        latest_post=latest_post,
        scope=scope,
    )
    if is_edit_fork:
        working["rolling_summary"] = ""
        working["rolling_summary_idx"] = 0
    working = reconcile_pending_with_stamps(
        working,
        history,
        scope=scope,
        current_msg=current_msg,
    )
    is_edit_turn = is_edit_fork or _is_edit_fork_at_turn(history, current_msg)
    working = mature_branch_heads(
        working,
        current_msg=current_msg,
        scope=scope,
        window_user_turns=window_user_turns,
        history=history,
        is_edit_fork_reply=is_edit_turn or _is_fork_edit_reply(history),
    )
    working = queue_catalog_bumps(
        working,
        current_msg=current_msg,
        latest_channel=latest_channel,
        latest_post=latest_post,
        scope=scope,
        history=history,
    )
    attach, working = plan_attach_for_msg(
        working,
        current_msg=current_msg,
        scope=scope,
        history=history,
    )
    head = normalize_summary_versions(working.get("head"), scope=scope)

    if is_edit_turn:
        fork_ch = int(working.get(_FORK_HEAD_CHANNEL) or 0)
        fork_post = int(working.get(_FORK_HEAD_POST) or 0)
        if fork_ch <= 0 or (scope == "post" and fork_post <= 0):
            anchor = fork_anchor_from_branch_zero(history, fork_msg=current_msg)
            if anchor is not None:
                anchor_head, _, _ = anchor
                if fork_ch <= 0:
                    fork_ch = int(anchor_head.get("channel") or 0)
                if scope == "post" and fork_post <= 0:
                    fork_post = int(anchor_head.get("post") or 0)
        if fork_ch > 0:
            head["channel"] = fork_ch
        if fork_post > 0 and scope == "post":
            head["post"] = fork_post
        if attach["channel"] <= 0:
            attach["channel"] = edit_fork_unseen_layer_attach(
                attach["channel"],
                layer="channel",
                head=head["channel"],
                latest=latest_channel,
                history=history,
                window_user_turns=window_user_turns,
            )
        if scope == "post" and attach["post"] <= 0:
            attach["post"] = edit_fork_unseen_layer_attach(
                attach["post"],
                layer="post",
                head=max(1, head["post"]),
                latest=latest_post,
                history=history,
                window_user_turns=window_user_turns,
            )

    working = lock_edit_fork_heads(
        {**working, "head": head},
        history=history,
        current_msg=current_msg,
        scope=scope,
    )
    head = normalize_summary_versions(working.get("head"), scope=scope)
    return head, attach, working  # type: ignore[return-value]


def is_edit_fork_at_address(
    history: list[Mapping[str, Any]] | None,
    *,
    msg: int,
    msg_version: int,
) -> bool:
    if msg_version <= 1:
        return False
    from app.services.ai.context_stamp_address import resolve_current_address

    stamp_context = {"branches": {}, "next_branch_id": 2, "branch_registry": {}}
    address, _ = resolve_current_address(history, stamp_context=stamp_context)
    if address is None:
        return False
    return int(address["msg"]) == msg and int(address["msgVersion"]) == msg_version
