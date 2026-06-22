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
from app.services.ai.context_labels import (
    _merge_fork_metadata,
    advance_label_thread_after_reply,
    empty_label_thread_state,
    flatten_label_thread_meta,
    load_label_thread_context,
    maturation_state_for_planning,
    plan_context_label_for_turn,
    planned_context_label_at_turn,
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
    if layer == "local":
        # Global channel snapshot must not suppress local post attach on the same turn.
        merged.pop("catalog_snapshot_at_fork", None)
        local_snapshot = int(stored.get("catalog_snapshot_local_at_fork") or 0)
        if local_snapshot > 0:
            merged["catalog_snapshot_at_fork"] = local_snapshot
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
        synthetic.append({**dict(message), "contextLabel": flat})
    return synthetic


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
    planning_global = maturation_state_for_planning(
        stored_global,
        synth_global,
        user_turn_count=user_turn_count,
    )
    planning_local = maturation_state_for_planning(
        stored_local,
        synth_local,
        user_turn_count=user_turn_count,
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
    label_global = planned_context_label_at_turn(
        _post_layer_thread_state(base, "global"),
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_version=latest_global,
        window_user_turns=window_user_turns,
        history=synth_global,
    )
    label_local = planned_context_label_at_turn(
        _post_layer_thread_state(base, "local"),
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_version=max(1, latest_local),
        window_user_turns=window_user_turns,
        history=synth_local,
    )
    parsed_global = parse_context_label(label_global)
    parsed_local = parse_context_label(label_local)
    if parsed_global is None or parsed_local is None:
        return format_post_context_label(
            latest_global,
            max(1, latest_local),
            0,
            0,
            turn_label,
        )
    gh, ga, _ = parsed_global
    lh, la, _ = parsed_local
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
    if thread_key not in threads:
        threads[thread_key] = empty_post_label_thread_state(head_local=1)
    threads[thread_key] = _migrate_legacy_post_state(
        threads[thread_key],
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
    rolling_summary = str(thread_state.get("rolling_summary") or "").strip()

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
