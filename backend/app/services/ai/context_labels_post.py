"""Post chat context labels: compound ``gHead.lHead-gAtt.lAtt-turn`` with dual maturation."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import (
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_label import (
    enumerate_active_user_turns,
    format_post_context_label,
    parse_post_context_label,
    read_stamped_context_label,
    read_stamped_post_label_parts,
    resolve_turn_label,
)
from app.services.ai.context_label import format_context_label, parse_context_label
from app.services.ai.context_label_shared import (
    _find_label_thread_parent,
    _fork_message_for_thread_key,
    _is_edit_fork_at_turn,
    _lock_edit_fork_head,
    _merge_fork_metadata,
    _merge_pending_queues,
    _path_indices,
    _pending_queue_from_stamps,
    _pending_queue_from_state,
    _sync_legacy_pending_fields,
)
from app.services.ai.context_labels import (
    advance_label_thread_after_reply,
    empty_label_thread_state,
    flatten_label_thread_meta,
    load_label_thread_context,
    maturation_state_for_assembly,
    maturation_state_for_planning,
    plan_context_label_for_turn,
    primer_head_from_stamps,
    reconcile_rolling_summary_fields,
)
from app.services.ai.context_primer import (
    DEFAULT_SYSTEM_PROMPT,
    PRIMER_ACK,
    build_dialog_messages,
    build_primer_user_content,
    take_prompt_window,
)
from app.services.ai.context_turns import annotate_user_turns, compute_window_user_turns
from app.services.ai.rolling_summary import rolling_summary_for_assembly
from app.services.ai.summary_catalog import (
    latest_global_version,
    latest_local_version,
    resolve_post_bundle_text,
    resolve_post_float_bundle_text,
)


def empty_post_label_thread_state(*, head_local: int = 1) -> dict[str, Any]:
    return {
        "head_global": 0,
        "head_local": max(1, head_local),
        "pending_global_queue": [],
        "pending_local_queue": [],
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }


def _sync_post_pending_legacy(state: dict[str, Any]) -> dict[str, Any]:
    gq = state.get("pending_global_queue") or []
    lq = state.get("pending_local_queue") or []
    state["pending_global_version"] = gq[-1]["version"] if gq else 0
    state["pending_global_since_turn"] = gq[-1]["since_turn"] if gq else 0
    state["pending_local_version"] = lq[-1]["version"] if lq else 0
    state["pending_local_since_turn"] = lq[-1]["since_turn"] if lq else 0
    return state


def _migrate_legacy_post_state(
    state: Mapping[str, Any],
    *,
    latest_global: int,
    latest_local: int,
) -> dict[str, Any]:
    if "head_global" in state or "head_local" in state:
        merged = {**empty_post_label_thread_state(head_local=latest_local), **dict(state)}
        merged["head_local"] = max(1, int(merged.get("head_local") or latest_local))
        return _sync_post_pending_legacy(merged)
    legacy_head = int(state.get("head_version") or 0)
    legacy_local = max(1, legacy_head if legacy_head > 0 else latest_local)
    merged = {
        **empty_post_label_thread_state(head_local=legacy_local),
        **dict(state),
        "head_global": latest_global if legacy_head <= 0 else min(legacy_head, latest_global),
        "head_local": legacy_local,
    }
    pending = int(state.get("pending_version") or 0)
    pending_since = int(state.get("pending_since_turn") or 0)
    if pending > legacy_local and pending_since > 0:
        merged["pending_local_queue"] = [{"version": pending, "since_turn": pending_since}]
    raw_q = state.get("pending_queue")
    if isinstance(raw_q, list):
        merged["pending_local_queue"] = [
            {"version": int(i["version"]), "since_turn": int(i["since_turn"])}
            for i in raw_q
            if isinstance(i, Mapping) and int(i.get("version") or 0) > 0
        ]
    return _sync_post_pending_legacy(merged)


def _is_fresh_post_label_thread(state: Mapping[str, Any]) -> bool:
    if int(state.get("head_global") or 0) > 0:
        return False
    if int(state.get("head_local") or 1) > 1:
        return False
    if state.get("pending_global_queue") or state.get("pending_local_queue"):
        return False
    if int(state.get("pending_version") or 0) > 0:
        return False
    return True



def _fork_turn_for_thread_key(
    history: list[Mapping[str, Any]] | None,
    thread_key: str,
) -> int | None:
    if not history or not thread_key or "@" not in thread_key:
        return None
    fork_path = thread_key.split(",")[-1].rsplit("@", 1)[0]
    target = _path_indices(fork_path)
    for entry in enumerate_active_user_turns(list(history)):
        if entry.get("path") == target:
            return int(entry["turn"])
    return None


def _fork_anchor_from_branch_zero_post_label(
    history: list[Mapping[str, Any]] | None,
    *,
    thread_key: str,
    latest_global: int,
) -> tuple[int, int, int, int, int, int, int, bool] | None:
    """Head/attach per layer from branch 0 on the fork that created ``thread_key``."""
    fork_message = _fork_message_for_thread_key(history, thread_key)
    if fork_message is None:
        return None
    branches = fork_message.get("userBranches")
    if not isinstance(branches, list) or len(branches) < 2:
        return None
    branch0 = branches[0]
    if not isinstance(branch0, Mapping):
        return None
    parsed = read_stamped_post_label_parts(
        fork_message,
        branch_index=0,
        legacy_global_version=latest_global,
    )
    if parsed is None:
        candidate = branch0.get("contextLabel") or branch0.get("context_label")
        if isinstance(candidate, str):
            parsed = read_stamped_post_label_parts(
                {"contextLabel": candidate},
                legacy_global_version=latest_global,
            )
    if parsed is None:
        return None
    gh, lh, ga, la, turn_part = parsed
    pg = ga if ga > gh else 0
    pl = la if la > lh else 0
    fork_turn = _fork_turn_for_thread_key(history, thread_key) or 0
    pg_since = fork_turn if pg else 0
    pl_since = fork_turn if pl else 0
    return (gh, lh, pg, pl, pg_since, pl_since, fork_turn, "(" in turn_part)


def _merge_layer_pending_queue(
    parent_queue: list[dict[str, int]],
    *,
    head: int,
    history: list[Mapping[str, Any]] | None,
    user_turn_count: int,
    latest_global: int,
    layer: str,
    anchor_version: int,
    anchor_since: int,
    edit_fork: bool,
) -> list[dict[str, int]]:
    synthetic = _post_layer_synthetic_history(
        history,
        layer=layer,
        latest_global=latest_global,
    )
    queue = _merge_pending_queues(
        parent_queue,
        _pending_queue_from_stamps(synthetic, head=head, up_to_turn=user_turn_count),
        (
            [{"version": anchor_version, "since_turn": anchor_since}]
            if anchor_version > head and anchor_since > 0
            else []
        ),
        head=head,
    )
    if edit_fork:
        queue = [item for item in queue if int(item["since_turn"]) != user_turn_count]
    return queue


def seed_post_label_thread_from_parent(
    parent: Mapping[str, Any],
    *,
    thread_key: str,
    user_turn_count: int,
    history: list[Mapping[str, Any]] | None,
    latest_global: int,
    latest_local: int,
) -> dict[str, Any]:
    """Fork: inherit compound heads from branch 0 label at the fork (global-chat parity)."""
    state = empty_post_label_thread_state()
    gh = int(parent.get("head_global") or 0)
    lh = max(1, int(parent.get("head_local") or 1))
    pg = int(parent.get("pending_global_version") or 0)
    pl = int(parent.get("pending_local_version") or 0)
    pg_since = int(parent.get("pending_global_since_turn") or 0)
    pl_since = int(parent.get("pending_local_since_turn") or 0)

    anchor = _fork_anchor_from_branch_zero_post_label(
        history,
        thread_key=thread_key,
        latest_global=latest_global,
    )
    edit_fork = _is_edit_fork_at_turn(history, user_turn_count)
    if anchor is not None:
        a_gh, a_lh, a_pg, a_pl, a_pg_since, a_pl_since, _fork_turn, nested_fork = anchor
        parent_gh = int(parent.get("fork_branch_zero_head_global") or parent.get("head_global") or 0)
        parent_lh = max(1, int(parent.get("fork_branch_zero_head_local") or parent.get("head_local") or 1))
        gh, lh = a_gh, max(1, a_lh)
        if nested_fork and parent_gh > 0 and a_pg == 0 and a_pl == 0 and a_gh > parent_gh:
            gh, lh = parent_gh, parent_lh
            state["fork_suppress_attach_global_up_to"] = a_gh
            if a_lh > lh:
                state["fork_suppress_attach_local_up_to"] = a_lh
        pg, pl, pg_since, pl_since = a_pg, a_pl, a_pg_since, a_pl_since
        state["fork_branch_zero_head_global"] = gh
        state["fork_branch_zero_head_local"] = lh
        if nested_fork and parent_gh > gh:
            state["fork_suppress_attach_global_up_to"] = parent_gh
        if nested_fork and parent_lh > lh:
            state["fork_suppress_attach_local_up_to"] = parent_lh
        if edit_fork:
            pg, pl, pg_since, pl_since = 0, 0, 0, 0

    if pg > 0 and pg_since > user_turn_count:
        pg, pg_since = 0, 0
    if pl > 0 and pl_since > user_turn_count:
        pl, pl_since = 0, 0

    parent_gq = [
        dict(item)
        for item in list(parent.get("pending_global_queue") or [])
        if int(item.get("since_turn") or 0) <= user_turn_count
    ]
    parent_lq = [
        dict(item)
        for item in list(parent.get("pending_local_queue") or [])
        if int(item.get("since_turn") or 0) <= user_turn_count
    ]
    if edit_fork:
        parent_gq = [item for item in parent_gq if int(item["since_turn"]) != user_turn_count]
        parent_lq = [item for item in parent_lq if int(item["since_turn"]) != user_turn_count]

    gq = _merge_layer_pending_queue(
        parent_gq,
        head=gh,
        history=history,
        user_turn_count=user_turn_count,
        latest_global=latest_global,
        layer="global",
        anchor_version=pg,
        anchor_since=pg_since,
        edit_fork=edit_fork,
    )
    lq = _merge_layer_pending_queue(
        parent_lq,
        head=lh,
        history=history,
        user_turn_count=user_turn_count,
        latest_global=latest_global,
        layer="local",
        anchor_version=pl,
        anchor_since=pl_since,
        edit_fork=edit_fork,
    )

    state["head_global"] = gh
    state["head_local"] = lh
    state["pending_global_queue"] = gq
    state["pending_local_queue"] = lq
    if edit_fork:
        state["catalog_snapshot_at_fork"] = 0
        state["catalog_snapshot_local_at_fork"] = 0
    return _sync_post_pending_legacy(state)


def _post_layer_thread_state(stored: Mapping[str, Any], layer: str) -> dict[str, Any]:
    """Map compound thread state to single-layer global-chat state."""
    base = empty_label_thread_state()
    if layer == "global":
        base["head_version"] = int(stored.get("head_global") or 0)
        base["pending_queue"] = [dict(item) for item in list(stored.get("pending_global_queue") or [])]
    else:
        if _is_fresh_post_label_thread(stored):
            base["head_version"] = 0
        else:
            base["head_version"] = max(1, int(stored.get("head_local") or 0))
        base["pending_queue"] = [dict(item) for item in list(stored.get("pending_local_queue") or [])]
    merged = _merge_fork_metadata(base, stored)
    if layer == "global":
        merged.pop("catalog_snapshot_local_at_fork", None)
        fork_gh = int(stored.get("fork_branch_zero_head_global") or 0)
        if fork_gh > 0:
            merged["fork_branch_zero_head"] = fork_gh
        suppress = int(stored.get("fork_suppress_attach_global_up_to") or 0)
        if suppress > 0:
            merged["fork_suppress_attach_up_to"] = suppress
    else:
        merged.pop("catalog_snapshot_at_fork", None)
        local_snapshot = int(stored.get("catalog_snapshot_local_at_fork") or 0)
        if local_snapshot > 0:
            merged["catalog_snapshot_at_fork"] = local_snapshot
        fork_lh = int(stored.get("fork_branch_zero_head_local") or 0)
        if fork_lh > 0:
            merged["fork_branch_zero_head"] = fork_lh
        suppress = int(stored.get("fork_suppress_attach_local_up_to") or 0)
        if suppress > 0:
            merged["fork_suppress_attach_up_to"] = suppress
    return merged


def _maturation_state_for_post_layer(
    stored: Mapping[str, Any],
    synthetic_history: list[Mapping[str, Any]] | None,
    *,
    user_turn_count: int,
    source_history: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stamp-derived layer state; fork-zero head caps polluted stamps on nested paths."""
    merged = maturation_state_for_planning(
        stored,
        synthetic_history,
        user_turn_count=user_turn_count,
    )
    fork_head = int(stored.get("fork_branch_zero_head") or 0)
    head = int(merged.get("head_version") or 0)
    if source_history and _is_edit_fork_at_turn(source_history, user_turn_count):
        merged = _lock_edit_fork_head(
            merged,
            history=source_history,
            user_turn_count=user_turn_count,
        )
    elif fork_head > 0 and head > fork_head:
        merged = {**merged, "head_version": fork_head}
        merged = _sync_legacy_pending_fields(merged)
    return merged



def _post_state_from_layer_states(
    global_state: Mapping[str, Any],
    local_state: Mapping[str, Any],
    base: Mapping[str, Any],
) -> dict[str, Any]:
    merged = {
        **dict(base),
        "head_global": int(global_state.get("head_version") or 0),
        "head_local": max(1, int(local_state.get("head_version") or 0)),
        "pending_global_queue": list(global_state.get("pending_queue") or []),
        "pending_local_queue": list(local_state.get("pending_queue") or []),
        "catalog_snapshot_at_fork": int(global_state.get("catalog_snapshot_at_fork") or 0),
        "catalog_snapshot_local_at_fork": int(local_state.get("catalog_snapshot_at_fork") or 0),
    }
    return _sync_post_pending_legacy(_merge_fork_metadata(merged, base))


def _post_layer_synthetic_history(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: str,
    latest_global: int,
) -> list[dict[str, Any]]:
    """Project compound post stamps onto global-chat ``head-attached-turn`` history per layer."""
    synthetic: list[dict[str, Any]] = []
    for entry in enumerate_active_user_turns(list(history or [])):
        message = entry["message"]
        if not isinstance(message, Mapping):
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        parsed = read_stamped_post_label_parts(
            message,
            branch_index=branch_index,
            legacy_global_version=latest_global,
        )
        if parsed is None:
            continue
        gh, lh, ga, la, _ = parsed
        if layer == "global":
            head, attached = gh, ga
        else:
            head, attached = lh, la
        flat = format_context_label(head, attached, str(entry["turn_label"]))
        # Branch-free nodes: label readers prefer userBranches over contextLabel.
        synthetic.append({"role": "user", "contextLabel": flat})
    return synthetic


def _immediate_label_thread_parent(
    threads: Mapping[str, Mapping[str, Any]],
    thread_key: str,
) -> Mapping[str, Any] | None:
    parts = thread_key.split(",")
    if len(parts) <= 1:
        return threads.get("")
    parent_key = ",".join(parts[:-1])
    parent = threads.get(parent_key)
    if parent is not None:
        return parent
    return threads.get("")


def _repair_post_fork_thread_state(
    state: Mapping[str, Any],
    *,
    thread_key: str,
    parent: Mapping[str, Any] | None,
    user_turn_count: int,
    history: list[Mapping[str, Any]] | None,
    latest_global: int,
    latest_local: int,
) -> dict[str, Any]:
    """Re-align fork thread heads with branch-zero anchor for this thread key."""
    if "@" not in thread_key or thread_key.count(",") < 1:
        return dict(state)
    seeded = seed_post_label_thread_from_parent(
        parent or empty_post_label_thread_state(),
        thread_key=thread_key,
        user_turn_count=user_turn_count,
        history=history,
        latest_global=latest_global,
        latest_local=latest_local,
    )
    if int(seeded.get("fork_branch_zero_head_global") or 0) <= 0:
        return dict(state)
    if (
        int(state.get("head_global") or 0) == int(seeded.get("head_global") or 0)
        and int(state.get("head_local") or 0) == int(seeded.get("head_local") or 0)
        and int(state.get("fork_branch_zero_head_global") or 0)
        == int(seeded.get("fork_branch_zero_head_global") or 0)
        and int(state.get("fork_branch_zero_head_local") or 0)
        == int(seeded.get("fork_branch_zero_head_local") or 0)
    ):
        return dict(state)
    return {
        **seeded,
        "rolling_summary": str(state.get("rolling_summary") or ""),
        "rolling_summary_idx": int(state.get("rolling_summary_idx") or 0),
    }


def plan_post_context_label_for_turn(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_global: int,
    latest_local: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int, int, int, dict[str, Any]]:
    """Plan compound label via two independent global-chat layer planners."""
    base = _migrate_legacy_post_state(
        state,
        latest_global=latest_global,
        latest_local=latest_local,
    )
    synth_global = _post_layer_synthetic_history(
        history, layer="global", latest_global=latest_global
    )
    synth_local = _post_layer_synthetic_history(
        history, layer="local", latest_global=latest_global
    )
    stored_global = _post_layer_thread_state(base, "global")
    stored_local = _post_layer_thread_state(base, "local")
    planning_global = _maturation_state_for_post_layer(
        stored_global,
        synth_global,
        user_turn_count=user_turn_count,
        source_history=history,
    )
    planning_local = _maturation_state_for_post_layer(
        stored_local,
        synth_local,
        user_turn_count=user_turn_count,
        source_history=history,
    )
    gh, ga, next_global = plan_context_label_for_turn(
        planning_global,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_global,
        window_user_turns=window_user_turns,
        history=synth_global,
    )
    lh, la, next_local = plan_context_label_for_turn(
        planning_local,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=max(1, latest_local),
        window_user_turns=window_user_turns,
        history=synth_local,
    )
    if history and _is_edit_fork_at_turn(history, user_turn_count):
        fork_gh = int(base.get("fork_branch_zero_head_global") or 0)
        fork_lh = max(1, int(base.get("fork_branch_zero_head_local") or 0))
        if fork_gh > 0:
            gh = fork_gh
        if fork_lh > 0:
            lh = fork_lh
    merged = _post_state_from_layer_states(next_global, next_local, base)
    return gh, max(1, lh), ga, la, merged


def planned_post_label_at_turn(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_global: int,
    latest_local: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> str:
    """Compose ``gHead.lHead-gAtt.lAtt-turn`` from two global-chat planners."""
    gh, lh, ga, la, _ = plan_post_context_label_for_turn(
        state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_global=latest_global,
        latest_local=latest_local,
        window_user_turns=window_user_turns,
        history=history,
    )
    return format_post_context_label(gh, max(1, lh), ga, la, turn_label)


def primer_post_heads_from_state(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    latest_global: int,
    latest_local: int,
    window_user_turns: set[int] | None,
    history: list[Mapping[str, Any]] | None,
) -> tuple[int, int]:
    base = _migrate_legacy_post_state(
        state,
        latest_global=latest_global,
        latest_local=latest_local,
    )
    synth_global = _post_layer_synthetic_history(
        history, layer="global", latest_global=latest_global
    )
    synth_local = _post_layer_synthetic_history(
        history, layer="local", latest_global=latest_global
    )
    gh = primer_head_from_stamps(
        _post_layer_thread_state(base, "global"),
        user_turn_count=user_turn_count,
        latest_catalog_version=latest_global,
        window_user_turns=window_user_turns,
        history=synth_global,
    )
    lh = primer_head_from_stamps(
        _post_layer_thread_state(base, "local"),
        user_turn_count=user_turn_count,
        latest_catalog_version=max(1, latest_local),
        window_user_turns=window_user_turns,
        history=synth_local,
    )
    if history and _is_edit_fork_at_turn(history, user_turn_count):
        fork_gh = int(base.get("fork_branch_zero_head_global") or 0)
        fork_lh = max(1, int(base.get("fork_branch_zero_head_local") or 0))
        if fork_gh > 0:
            gh = fork_gh
        if fork_lh > 0:
            lh = fork_lh
    return gh, max(1, lh)


def primer_post_log_label(head_global: int, head_local: int) -> str:
    return f"user/primer [{format_post_context_label(head_global, head_local, 0, 0, '0')}]"


def _floating_bundles_post(
    history: list[Mapping[str, Any]],
    *,
    catalog: Mapping[str, Any],
    post_id: str,
    window_user_turns: set[int],
    thread_state: Mapping[str, Any],
    latest_global: int,
    latest_local: int,
    user_turn_count: int,
) -> dict[int, str]:
    injections: dict[int, str] = {}
    for entry in enumerate_active_user_turns(history):
        turn = int(entry["turn"])
        if turn not in window_user_turns:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        parsed = read_stamped_post_label_parts(
            entry["message"],
            branch_index=branch_index,
            legacy_global_version=latest_global,
        )
        if parsed is not None:
            _gh, _lh, ga, la, _ = parsed
            if ga > 0 or la > 0:
                text = resolve_post_float_bundle_text(
                    catalog,
                    post_id=post_id,
                    attached_global=ga,
                    attached_local=la,
                )
                if text:
                    injections[turn] = text
            continue
        turn_label = str(entry["turn_label"])
        label = planned_post_label_at_turn(
            thread_state,
            user_turn_count=turn,
            turn_label=turn_label,
            latest_global=latest_global,
            latest_local=latest_local,
            window_user_turns=window_user_turns,
            history=history,
        )
        parts = parse_post_context_label(label)
        if parts is None:
            continue
        _gh, _lh, ga, la, _ = parts
        if ga > 0 or la > 0:
            text = resolve_post_float_bundle_text(
                catalog,
                post_id=post_id,
                attached_global=ga,
                attached_local=la,
            )
            if text:
                injections[turn] = text
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
        label = planned_post_label_at_turn(
            thread_state,
            user_turn_count=user_turn_count,
            turn_label=turn_label,
            latest_global=latest_global,
            latest_local=latest_local,
            window_user_turns=window_user_turns,
            history=history,
        )
        parts = parse_post_context_label(label)
        if parts is not None:
            _gh, _lh, ga, la, _ = parts
            if ga > 0 or la > 0:
                text = resolve_post_float_bundle_text(
                    catalog,
                    post_id=post_id,
                    attached_global=ga,
                    attached_local=la,
                )
                if text:
                    injections[user_turn_count] = text
    return injections


def fill_llm_log_labels_post(
    log_labels: dict[int, str],
    messages: list[dict[str, str]],
    *,
    head_global: int,
    head_local: int,
    history: list[Mapping[str, Any]],
    thread_state: Mapping[str, Any],
    latest_global: int,
    latest_local: int,
    user_turn_count: int,
    valid_pairs: list[tuple[str, str]],
) -> None:
    if not messages:
        return
    log_labels[0] = "system"
    if len(messages) > 1:
        log_labels[1] = primer_post_log_label(head_global, head_local)
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
                label = planned_post_label_at_turn(
                    thread_state,
                    user_turn_count=user_turn,
                    turn_label=turn_label,
                    latest_global=latest_global,
                    latest_local=latest_local,
                    window_user_turns=window_user_turns,
                    history=history,
                )
                log_labels[msg_idx] = f"user [{label}]"
        else:
            log_labels[msg_idx] = role
        msg_idx += 1


def resolve_post_label_thread_state(
    meta: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    *,
    latest_global: int,
    latest_local: int,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    from app.services.ai.chat_history import active_thread_key

    base_meta = dict(meta) if isinstance(meta, Mapping) else {}
    thread_key = active_thread_key(list(history or []))
    threads = load_label_thread_context(base_meta)
    prev_key = base_meta.get("active_thread_key")
    parent = _find_label_thread_parent(
        threads,
        thread_key,
        prev_key if isinstance(prev_key, str) else None,
    )
    user_turn_count = count_user_turns(
        filter_alternating_roles(linearize_for_llm(list(history or [])))
    )
    hist = list(history or [])
    if thread_key not in threads:
        if parent is not None:
            threads[thread_key] = seed_post_label_thread_from_parent(
                parent,
                thread_key=thread_key,
                user_turn_count=user_turn_count,
                history=hist,
                latest_global=latest_global,
                latest_local=latest_local,
            )
        else:
            threads[thread_key] = empty_post_label_thread_state(head_local=1)
    threads[thread_key] = _migrate_legacy_post_state(
        threads[thread_key],
        latest_global=latest_global,
        latest_local=latest_local,
    )
    prefix_parts = thread_key.split(",") if thread_key else []
    for index in range(1, len(prefix_parts) + 1):
        prefix_key = ",".join(prefix_parts[:index])
        if "@" not in prefix_key or prefix_key not in threads:
            continue
        prefix_parent = _immediate_label_thread_parent(threads, prefix_key)
        threads[prefix_key] = _repair_post_fork_thread_state(
            threads[prefix_key],
            thread_key=prefix_key,
            parent=prefix_parent,
            user_turn_count=user_turn_count,
            history=hist,
            latest_global=latest_global,
            latest_local=latest_local,
        )
    valid_pairs = filter_alternating_roles(linearize_for_llm(list(history or [])))
    threads[thread_key] = reconcile_rolling_summary_fields(threads[thread_key], valid_pairs)
    return dict(threads[thread_key]), thread_key, threads


def assemble_reply_messages_from_post_labels(
    *,
    ai_profile: Mapping[str, Any],
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    chat_meta: Mapping[str, Any] | None,
    catalog: Mapping[str, Any],
    post_id: str,
    log_labels: dict[int, str] | None = None,
) -> list[dict[str, str]] | None:
    latest_global = latest_global_version(catalog)
    latest_local = latest_local_version(catalog, post_id)
    if latest_local <= 0 and latest_global <= 0:
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

    thread_state, _, _ = resolve_post_label_thread_state(
        chat_meta,
        list(history or []),
        latest_global=latest_global,
        latest_local=max(1, latest_local),
    )
    head_g, head_l = primer_post_heads_from_state(
        thread_state,
        user_turn_count=user_turn_count,
        latest_global=latest_global,
        latest_local=max(1, latest_local),
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    head_text = resolve_post_bundle_text(
        catalog,
        post_id=post_id,
        global_version=head_g,
        local_version=head_l,
    )
    rolling_summary = rolling_summary_for_assembly(thread_state, valid_pairs)

    floating = _floating_bundles_post(
        list(history or []),
        catalog=catalog,
        post_id=post_id,
        window_user_turns=window_user_turns,
        thread_state=thread_state,
        latest_global=latest_global,
        latest_local=max(1, latest_local),
        user_turn_count=user_turn_count,
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
        fill_llm_log_labels_post(
            log_labels,
            messages,
            head_global=head_g,
            head_local=head_l,
            history=list(history or []),
            thread_state=thread_state,
            latest_global=latest_global,
            latest_local=max(1, latest_local),
            user_turn_count=user_turn_count,
            valid_pairs=valid_pairs,
        )
    return messages


def advance_post_label_thread_after_reply(
    state: Mapping[str, Any],
    *,
    user_turn_count: int,
    turn_label: str,
    latest_global: int,
    latest_local: int,
    window_user_turns: set[int] | None = None,
    history: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int, int, int, dict[str, Any]]:
    base = _migrate_legacy_post_state(
        state,
        latest_global=latest_global,
        latest_local=max(1, latest_local),
    )
    synth_global = _post_layer_synthetic_history(
        history, layer="global", latest_global=latest_global
    )
    synth_local = _post_layer_synthetic_history(
        history, layer="local", latest_global=latest_global
    )
    gh, ga, next_global = advance_label_thread_after_reply(
        _post_layer_thread_state(base, "global"),
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_global,
        window_user_turns=window_user_turns,
        history=synth_global,
    )
    lh, la, next_local = advance_label_thread_after_reply(
        _post_layer_thread_state(base, "local"),
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=max(1, latest_local),
        window_user_turns=window_user_turns,
        history=synth_local,
    )
    if history and _is_edit_fork_at_turn(history, user_turn_count):
        fork_gh = int(base.get("fork_branch_zero_head_global") or 0)
        fork_lh = max(1, int(base.get("fork_branch_zero_head_local") or 0))
        if fork_gh > 0:
            gh = fork_gh
        if fork_lh > 0:
            lh = fork_lh
    next_state = _post_state_from_layer_states(next_global, next_local, base)
    return gh, max(1, lh), ga, la, _merge_fork_metadata(next_state, base)


def flatten_post_label_thread_meta(
    thread_state: Mapping[str, Any],
    *,
    thread_key: str,
    threads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return flatten_label_thread_meta(
        thread_state,
        thread_key=thread_key,
        threads=threads,
    )
