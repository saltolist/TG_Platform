"""Stamp-derived head maturation (parity with legacy context_labels)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.context_label_shared import _is_edit_fork_at_turn
from app.services.ai.context_stamp_history import (
    merge_pending_queues,
    pending_queue_from_stamp_attaches,
    stamped_layer_attach_by_msg,
)
from app.services.ai.context_stamp_label import read_context_stamp
from app.services.ai.context_stamp_types import (
    BranchStampState,
    LayerPending,
    PendingItem,
    SummaryVersions,
    normalize_summary_versions,
)
from app.services.ai.context_label import enumerate_active_user_turns

LayerName = str

_FORK_HEAD_CHANNEL = "fork_branch_zero_head_channel"
_FORK_HEAD_POST = "fork_branch_zero_head_post"
_SUPPRESS_ATTACH_CHANNEL = "fork_suppress_attach_channel_up_to"
_SUPPRESS_ATTACH_POST = "fork_suppress_attach_post_up_to"
_CATALOG_SNAPSHOT_CHANNEL = "catalog_snapshot_channel"
_CATALOG_SNAPSHOT_POST = "catalog_snapshot_post"


def _layer_head(head: SummaryVersions, layer: LayerName) -> int:
    return max(0, int(head.get(layer) or 0))


def _layer_pending(pending: LayerPending, layer: LayerName) -> list[PendingItem]:
    return [dict(item) for item in list(pending.get(layer) or [])]


def _is_fork_edit_reply(history: list[Mapping[str, Any]] | None) -> bool:
    entries = enumerate_active_user_turns(list(history or []))
    if not entries:
        return False
    last = entries[-1]
    return bool(last.get("branched")) and int(last.get("branch_index") or 0) > 0


def has_stamped_msgs_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    up_to_msg: int | None = None,
) -> bool:
    for entry in enumerate_active_user_turns(list(history or [])):
        msg = int(entry["turn"])
        if up_to_msg is not None and msg > up_to_msg:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        if read_context_stamp(entry["message"], branch_index=branch_index) is not None:
            return True
    return False


def max_stamped_head_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: LayerName,
    up_to_msg: int | None = None,
) -> int:
    max_head = 0
    for entry in enumerate_active_user_turns(list(history or [])):
        msg = int(entry["turn"])
        if up_to_msg is not None and msg > up_to_msg:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        stamp = read_context_stamp(entry["message"], branch_index=branch_index)
        if stamp is None:
            continue
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            continue
        head_raw = summary.get("head")
        if not isinstance(head_raw, dict):
            continue
        max_head = max(max_head, max(0, int(head_raw.get(layer) or 0)))
    return max_head


def max_stamped_attached_on_path(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: LayerName,
    up_to_msg: int | None = None,
) -> int:
    max_attached = 0
    for msg, attached in stamped_layer_attach_by_msg(history, layer).items():
        if up_to_msg is not None and msg > up_to_msg:
            continue
        max_attached = max(max_attached, attached)
    return max_attached


def attached_version_visible_in_window(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: LayerName,
    version: int,
    head: int,
    window_user_turns: set[int] | None,
) -> bool:
    if not history or not window_user_turns or version <= head:
        return False
    for entry in enumerate_active_user_turns(history):
        msg = int(entry["turn"])
        if msg not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        stamp = read_context_stamp(entry["message"], branch_index=branch_index)
        if stamp is None:
            continue
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            continue
        attach = summary.get("attach")
        if not isinstance(attach, dict):
            continue
        if int(attach.get(layer) or 0) == version:
            return True
    return False


def _catalog_versions_visible_in_window(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: LayerName,
    head_version: int,
    window_user_turns: set[int] | None,
) -> set[int]:
    visible: set[int] = set()
    if head_version > 0:
        visible.add(head_version)
    if not history or not window_user_turns:
        return visible
    for entry in enumerate_active_user_turns(history):
        msg = int(entry["turn"])
        if msg not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        stamp = read_context_stamp(entry["message"], branch_index=branch_index)
        if stamp is None:
            continue
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            continue
        attach = summary.get("attach")
        if not isinstance(attach, dict):
            continue
        attached = max(0, int(attach.get(layer) or 0))
        if attached > 0:
            visible.add(attached)
    return visible


def _latest_unseen_catalog_version(
    *,
    head: int,
    latest: int,
    visible: set[int],
) -> int:
    max_visible = max(visible) if visible else head
    baseline = max(head, max_visible)
    if latest <= baseline:
        return 0
    return latest


def _pending_version_is_matured(
    since_msg: int,
    *,
    current_msg: int,
    window_user_turns: set[int] | None,
    pending_version: int,
    head: int,
    layer: LayerName,
    history: list[Mapping[str, Any]] | None,
    is_edit_fork_reply: bool,
) -> bool:
    if since_msg <= 0:
        return False
    if is_edit_fork_reply:
        return False
    if attached_version_visible_in_window(
        history,
        layer=layer,
        version=pending_version,
        head=head,
        window_user_turns=window_user_turns,
    ):
        return False
    if current_msg >= since_msg + SUMMARY_BUNDLE_CATCHUP_MESSAGES:
        return True
    if (
        window_user_turns is not None
        and since_msg not in window_user_turns
        and current_msg > since_msg
    ):
        return True
    return False


def mature_layer_head(
    head: SummaryVersions,
    pending: LayerPending,
    layer: LayerName,
    *,
    current_msg: int,
    scope: str,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
    is_edit_fork_reply: bool = False,
) -> tuple[int, list[PendingItem]]:
    if layer == "post" and scope != "post":
        return 0, []
    head_val = _layer_head(head, layer)
    queue = _layer_pending(pending, layer)
    matured = True
    while matured and queue:
        matured = False
        oldest = queue[0]
        since_msg = int(oldest.get("sinceMsg") or 0)
        version = int(oldest.get("version") or 0)
        if since_msg <= 0 or version <= head_val:
            queue = queue[1:]
            matured = True
            continue
        if not _pending_version_is_matured(
            since_msg,
            current_msg=current_msg,
            window_user_turns=window_user_turns,
            pending_version=version,
            head=head_val,
            layer=layer,
            history=history,
            is_edit_fork_reply=is_edit_fork_reply,
        ):
            break
        if version > head_val:
            head_val = version
        queue = [item for item in queue if int(item["version"]) > head_val]
        matured = True
    return head_val, queue


def mature_branch_heads(
    state: BranchStampState,
    *,
    current_msg: int,
    scope: str,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
    is_edit_fork_reply: bool = False,
) -> BranchStampState:
    head = normalize_summary_versions(state.get("head"), scope=scope)
    pending: LayerPending = {
        "channel": _layer_pending(state.get("pending") or {}, "channel"),
        "post": _layer_pending(state.get("pending") or {}, "post"),
    }
    ch_head, ch_q = mature_layer_head(
        head,
        pending,
        "channel",
        current_msg=current_msg,
        scope=scope,
        window_user_turns=window_user_turns,
        history=history,
        is_edit_fork_reply=is_edit_fork_reply,
    )
    post_head, post_q = mature_layer_head(
        head,
        pending,
        "post",
        current_msg=current_msg,
        scope=scope,
        window_user_turns=window_user_turns,
        history=history,
        is_edit_fork_reply=is_edit_fork_reply,
    )
    head["channel"] = ch_head
    if scope == "post":
        head["post"] = post_head
    else:
        head["post"] = 0
    pending["channel"] = ch_q
    pending["post"] = post_q if scope == "post" else []
    return {**state, "head": head, "pending": pending}


def _merge_fork_metadata(merged: dict[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    for key in (
        _FORK_HEAD_CHANNEL,
        _FORK_HEAD_POST,
        _SUPPRESS_ATTACH_CHANNEL,
        _SUPPRESS_ATTACH_POST,
        _CATALOG_SNAPSHOT_CHANNEL,
        _CATALOG_SNAPSHOT_POST,
    ):
        if key in stored:
            merged[key] = stored[key]
    return merged


def derive_maturation_state_from_stamps(
    history: list[Mapping[str, Any]] | None,
    *,
    scope: str,
    up_to_msg: int | None = None,
) -> BranchStampState:
    head: SummaryVersions = {
        "channel": max_stamped_head_on_path(history, layer="channel", up_to_msg=up_to_msg),
        "post": max_stamped_head_on_path(history, layer="post", up_to_msg=up_to_msg),
    }
    if scope == "global":
        head["post"] = 0
    pending: LayerPending = {"channel": [], "post": []}
    for layer in ("channel", "post"):
        if layer == "post" and scope != "post":
            continue
        head_val = _layer_head(head, layer)
        pending[layer] = pending_queue_from_stamp_attaches(
            history,
            layer=layer,
            head=head_val,
            up_to_msg=up_to_msg,
        )
    return {
        "head": normalize_summary_versions(head, scope=scope),
        "pending": pending,
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }


def lock_edit_fork_heads(
    state: Mapping[str, Any],
    *,
    history: list[Mapping[str, Any]] | None,
    current_msg: int,
    scope: str,
) -> dict[str, Any]:
    merged = dict(state)
    if not history or not _is_edit_fork_at_turn(history, current_msg):
        return merged
    head = normalize_summary_versions(merged.get("head"), scope=scope)
    fork_ch = int(merged.get(_FORK_HEAD_CHANNEL) or 0)
    fork_post = int(merged.get(_FORK_HEAD_POST) or 0)
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
    merged["head"] = head
    if fork_ch > 0:
        merged[_FORK_HEAD_CHANNEL] = fork_ch
    if fork_post > 0 and scope == "post":
        merged[_FORK_HEAD_POST] = fork_post
    return merged


def maturation_state_for_assembly(
    stored: BranchStampState,
    history: list[Mapping[str, Any]] | None,
    *,
    current_msg: int,
    scope: str,
) -> BranchStampState:
    if not has_stamped_msgs_on_path(history, up_to_msg=current_msg):
        return dict(stored)
    derived = derive_maturation_state_from_stamps(history, scope=scope, up_to_msg=current_msg)
    head = normalize_summary_versions(derived.get("head"), scope=scope)
    pending: LayerPending = {"channel": [], "post": []}
    for layer in ("channel", "post"):
        if layer == "post" and scope != "post":
            continue
        head_val = _layer_head(head, layer)
        pending[layer] = merge_pending_queues(
            _layer_pending(derived.get("pending") or {}, layer),
            _layer_pending(stored.get("pending") or {}, layer),
            head=head_val,
        )
    merged: dict[str, Any] = {
        **dict(stored),
        "head": head,
        "pending": pending,
    }
    merged = _merge_fork_metadata(merged, stored)
    if not int(merged.get(_CATALOG_SNAPSHOT_CHANNEL) or 0):
        max_attached = max_stamped_attached_on_path(history, layer="channel", up_to_msg=current_msg)
        ch_head = _layer_head(head, "channel")
        if max_attached > ch_head:
            merged[_CATALOG_SNAPSHOT_CHANNEL] = max_attached
    if scope == "post" and not int(merged.get(_CATALOG_SNAPSHOT_POST) or 0):
        max_attached = max_stamped_attached_on_path(history, layer="post", up_to_msg=current_msg)
        post_head = _layer_head(head, "post")
        if max_attached > post_head:
            merged[_CATALOG_SNAPSHOT_POST] = max_attached
    return lock_edit_fork_heads(merged, history=history, current_msg=current_msg, scope=scope)  # type: ignore[return-value]


def maturation_state_for_planning(
    stored: BranchStampState,
    history: list[Mapping[str, Any]] | None,
    *,
    current_msg: int,
    scope: str,
) -> BranchStampState:
    clip = max(0, current_msg - 1)
    if not has_stamped_msgs_on_path(history, up_to_msg=clip):
        return dict(stored)
    derived = derive_maturation_state_from_stamps(history, scope=scope, up_to_msg=clip)
    head = normalize_summary_versions(derived.get("head"), scope=scope)
    pending: LayerPending = {"channel": [], "post": []}
    for layer in ("channel", "post"):
        if layer == "post" and scope != "post":
            continue
        head_val = _layer_head(head, layer)
        from_stamps = pending_queue_from_stamp_attaches(
            history,
            layer=layer,
            head=head_val,
            up_to_msg=clip,
        )
        pending[layer] = merge_pending_queues(
            _layer_pending(derived.get("pending") or {}, layer),
            _layer_pending(stored.get("pending") or {}, layer),
            from_stamps,
            head=head_val,
        )
    merged: dict[str, Any] = {
        **dict(stored),
        "head": head,
        "pending": pending,
    }
    merged = _merge_fork_metadata(merged, stored)
    if not int(merged.get(_CATALOG_SNAPSHOT_CHANNEL) or 0):
        max_attached = max_stamped_attached_on_path(history, layer="channel", up_to_msg=clip)
        ch_head = _layer_head(head, "channel")
        if max_attached > ch_head:
            merged[_CATALOG_SNAPSHOT_CHANNEL] = max_attached
    if scope == "post" and not int(merged.get(_CATALOG_SNAPSHOT_POST) or 0):
        max_attached = max_stamped_attached_on_path(history, layer="post", up_to_msg=clip)
        post_head = _layer_head(head, "post")
        if max_attached > post_head:
            merged[_CATALOG_SNAPSHOT_POST] = max_attached
    if _is_edit_fork_at_turn(history, current_msg):
        pending_clip = dict(merged.get("pending") or {})
        for layer in ("channel", "post"):
            pending_clip[layer] = [
                dict(item)
                for item in _layer_pending(pending_clip, layer)
                if int(item.get("sinceMsg") or 0) != current_msg
            ]
        merged["pending"] = pending_clip
        merged[_CATALOG_SNAPSHOT_CHANNEL] = 0
        if scope == "post":
            merged[_CATALOG_SNAPSHOT_POST] = 0
    return lock_edit_fork_heads(merged, history=history, current_msg=current_msg, scope=scope)  # type: ignore[return-value]


def edit_fork_unseen_layer_attach(
    attached: int,
    *,
    layer: LayerName,
    head: int,
    latest: int,
    history: list[Mapping[str, Any]] | None,
    window_user_turns: set[int] | None = None,
) -> int:
    """Edit fork: attach latest catalog version not yet visible in the LLM window."""
    if attached > 0 or latest <= head:
        return attached
    visible = _catalog_versions_visible_in_window(
        history,
        layer=layer,
        head_version=head,
        window_user_turns=window_user_turns,
    )
    unseen = _latest_unseen_catalog_version(head=head, latest=latest, visible=visible)
    return unseen if unseen > head else attached


def primer_heads_from_state(
    state: Mapping[str, Any],
    *,
    current_msg: int,
    latest_channel: int,
    latest_post: int,
    scope: str,
    window_user_turns: set[int] | None,
    history: list[Mapping[str, Any]] | None,
) -> SummaryVersions:
    assembly = maturation_state_for_assembly(
        dict(state),  # type: ignore[arg-type]
        history,
        current_msg=current_msg,
        scope=scope,
    )
    matured = mature_branch_heads(
        assembly,  # type: ignore[arg-type]
        current_msg=current_msg,
        scope=scope,
        window_user_turns=window_user_turns,
        history=history,
        is_edit_fork_reply=_is_edit_fork_at_turn(history, current_msg)
        or _is_fork_edit_reply(history),
    )
    head = normalize_summary_versions(matured.get("head"), scope=scope)
    if _is_edit_fork_at_turn(history, current_msg):
        fork_ch = int(state.get(_FORK_HEAD_CHANNEL) or 0)
        fork_post = int(state.get(_FORK_HEAD_POST) or 0)
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
    if head["channel"] <= 0 and latest_channel > 0:
        head["channel"] = latest_channel
    if scope == "post" and head["post"] <= 0 and latest_post > 0:
        head["post"] = latest_post
    return head


def fork_anchor_from_branch_zero(
    history: list[Mapping[str, Any]] | None,
    *,
    fork_msg: int,
) -> tuple[SummaryVersions, LayerPending, bool] | None:
    """Head/pending from branch-0 stamp on the fork message."""
    for entry in enumerate_active_user_turns(list(history or [])):
        if int(entry["turn"]) != fork_msg:
            continue
        if not entry.get("branched"):
            return None
        message = entry["message"]
        stamp = read_context_stamp(message, branch_index=0)
        if stamp is None:
            branches = message.get("userBranches")
            if isinstance(branches, list) and branches:
                branch0 = branches[0]
                if isinstance(branch0, Mapping):
                    stamp = read_context_stamp(branch0)
        if stamp is None:
            return None
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            return None
        head_raw = summary.get("head")
        attach_raw = summary.get("attach")
        if not isinstance(head_raw, dict) or not isinstance(attach_raw, dict):
            return None
        scope = stamp.get("scope")
        if scope not in ("global", "post"):
            scope = "post" if int(head_raw.get("post") or 0) > 0 else "global"
        head = normalize_summary_versions(head_raw, scope=scope)
        attach = normalize_summary_versions(attach_raw, scope=scope)
        pending: LayerPending = {"channel": [], "post": []}
        ch_head = _layer_head(head, "channel")
        ch_att = _layer_head(attach, "channel")
        if ch_att > ch_head:
            pending["channel"] = [{"version": ch_att, "sinceMsg": fork_msg}]
        if scope == "post":
            post_head = _layer_head(head, "post")
            post_att = _layer_head(attach, "post")
            if post_att > post_head:
                pending["post"] = [{"version": post_att, "sinceMsg": fork_msg}]
        nested_fork = int(stamp.get("address", {}).get("msgVersion") or 1) > 1
        return head, pending, nested_fork
    return None
