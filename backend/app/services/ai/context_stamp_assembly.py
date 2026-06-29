"""Assemble LLM messages from context stamps (v2 mechanics)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import (
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_label_shared import _is_edit_fork_at_turn
from app.services.ai.context_primer import (
    PRIMER_ACK,
    attach_floating_bundle_to_user_message,
    build_dialog_messages,
    build_primer_user_content,
    build_system_prompt,
    format_bundle_sections,
    format_channel_summary,
    format_post_summary,
    take_prompt_window,
    wrap_user_request,
)
from app.services.ai.context_turns import annotate_user_turns
from app.services.ai.context_stamp_history import stamps_by_msg_on_active_path
from app.services.ai.context_stamp_label import (
    format_stamp_label,
    format_stamp_primer_label,
    read_context_stamp,
)
from app.services.ai.context_stamp_address import (
    ensure_branch_state,
    load_stamp_context,
    resolve_current_address,
)
from app.services.ai.context_stamp_planner import (
    advance_branch_after_reply,
    initialize_heads_if_empty,
)
from app.services.ai.context_stamp_maturation import (
    has_stamped_msgs_on_path,
    maturation_state_for_assembly,
    primer_heads_from_state,
)
from app.services.ai.context_stamp_state import (
    ensure_edit_fork_branch_seeded,
    get_branch_state,
    resolve_stamp_thread_state,
)
from app.services.ai.context_stamp_types import SummaryVersions, branch_state_key
from app.services.ai.rolling_summary import rolling_summary_for_assembly
from app.services.ai.summary_catalog import (
    latest_global_version,
    latest_local_version,
    latest_scope_version,
    resolve_bundle_text,
    resolve_post_bundle_parts,
)


def _rolling_summary_for_branch(branch_state: Mapping[str, Any], valid_pairs: list[tuple[str, str]]) -> str:
    return rolling_summary_for_assembly(branch_state, valid_pairs)


def _float_text_from_stamp(
    stamp: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any],
    post_id: str | None,
    scope: str,
) -> str:
    summary = stamp.get("summary")
    if not isinstance(summary, dict):
        return ""
    attach = summary.get("attach")
    if not isinstance(attach, dict):
        return ""
    ch_att = max(0, int(attach.get("channel") or 0))
    post_att = max(0, int(attach.get("post") or 0))
    parts: list[str] = []
    if ch_att > 0:
        parts.append(
            format_channel_summary(
                resolve_bundle_text(
                    catalog,
                    scope="global",
                    post_id=None,
                    version=ch_att,
                ),
                updated=True,
            )
        )
    if scope == "post" and post_id and post_att > 0:
        channel_text, post_text = resolve_post_bundle_parts(
            catalog,
            post_id=post_id,
            global_version=0,
            local_version=post_att,
        )
        if post_text.strip():
            parts.append(format_post_summary(post_text, updated=True))
        elif channel_text.strip():
            parts.append(format_post_summary(channel_text, updated=True))
    return "\n\n".join(part for part in parts if part.strip())


def _floating_bundles_from_stamps(
    *,
    history: list[Mapping[str, Any]],
    window_user_turns: set[int],
    catalog: Mapping[str, Any],
    scope: str,
    post_id: str | None,
) -> dict[int, str]:
    stamps = stamps_by_msg_on_active_path(history)
    floating: dict[int, str] = {}
    for msg, stamp in stamps.items():
        if msg not in window_user_turns:
            continue
        block = _float_text_from_stamp(stamp, catalog=catalog, post_id=post_id, scope=scope)
        if block:
            floating[msg] = block
    return floating


def _primer_head_text(
    head: SummaryVersions,
    *,
    catalog: Mapping[str, Any],
    scope: str,
    post_id: str | None,
) -> str:
    ch = max(0, int(head.get("channel") or 0))
    post_v = max(0, int(head.get("post") or 0))
    if scope == "post" and post_id:
        channel_text, post_text = resolve_post_bundle_parts(
            catalog,
            post_id=post_id,
            global_version=ch,
            local_version=max(1, post_v) if post_v > 0 else 1,
        )
        return format_bundle_sections(channel_text=channel_text, post_text=post_text)
    version = ch if ch > 0 else latest_global_version(catalog)
    return format_channel_summary(
        resolve_bundle_text(catalog, scope="global", post_id=None, version=version)
    )


def fill_stamp_log_labels(
    log_labels: dict[int, str],
    messages: list[dict[str, str]],
    *,
    head: SummaryVersions,
    stamps: dict[int, Mapping[str, Any]],
    scope: str,
    valid_pairs: list[tuple[str, str]],
    log_stamps: dict[int, dict[str, Any]] | None = None,
) -> None:
    if not messages:
        return
    log_labels[0] = "system"
    if len(messages) > 1:
        log_labels[1] = f"user/primer [{format_stamp_primer_label(head, scope=scope)}]"
    if len(messages) > 2:
        log_labels[2] = "assistant/primer-ack"

    window_len = max(0, len(messages) - 3)
    window_annotated = annotate_user_turns(valid_pairs)[-window_len:] if window_len else []

    msg_idx = 3
    for user_turn, role, content in window_annotated:
        rendered = messages[msg_idx]["content"] if msg_idx < len(messages) else content
        if role == "assistant":
            log_labels[msg_idx] = "assistant"
        elif role == "user" and user_turn is not None:
            stamp = stamps.get(user_turn)
            if stamp is not None:
                label = format_stamp_label(stamp)
                if log_stamps is not None:
                    log_stamps[msg_idx] = dict(stamp)
                if "Обновлённый профиль канала:" in rendered or "Обновлённый пост:" in rendered:
                    log_labels[msg_idx] = f"user/float [{label}]"
                else:
                    log_labels[msg_idx] = f"user [{label}]"
            else:
                log_labels[msg_idx] = f"user [{user_turn}]"
        else:
            log_labels[msg_idx] = role
        msg_idx += 1


def assemble_reply_messages_from_stamps(
    *,
    ai_profile: Mapping[str, Any],
    user_text: str,
    scope: str = "global",
    history: list[Mapping[str, Any]] | None = None,
    chat_meta: Mapping[str, Any] | None = None,
    catalog: Mapping[str, Any],
    post_id: str | None = None,
    log_labels: dict[int, str] | None = None,
    log_stamps: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, str]] | None:
    """Build LLM messages from v2 context stamps; None if catalog empty."""
    latest_channel = latest_global_version(catalog)
    latest_post = latest_local_version(catalog, post_id or "") if scope == "post" and post_id else 0
    if scope == "post" and post_id:
        if latest_post <= 0 and latest_channel <= 0:
            return None
    elif not (catalog.get("global") or []):
        return None

    post_head_default = max(1, latest_post) if scope == "post" else 0
    system_prompt = build_system_prompt(str(ai_profile.get("systemPrompt") or ""), scope=scope)
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
    history_user_turn_count = count_user_turns(
        filter_alternating_roles(linearize_for_llm(list(history or [])))
    )

    branch_state, branch_id, stamp_context = resolve_stamp_thread_state(
        chat_meta,
        history,
        post_head=post_head_default,
    )
    current_address, _current_path = resolve_current_address(
        list(history or []),
        stamp_context=stamp_context,
    )
    pending_new_turn = user_turn_count > history_user_turn_count
    if current_address is None:
        current_address = {
            "msg": user_turn_count,
            "msgVersion": 1,
            "branch": branch_id,
        }
    elif pending_new_turn:
        current_address = {
            **current_address,
            "msg": user_turn_count,
            "msgVersion": 1,
        }
    branch_id = int(current_address["branch"])
    current_msg = int(current_address["msg"])
    is_edit_fork = (
        not pending_new_turn
        and int(current_address.get("msgVersion") or 1) > 1
        and _is_edit_fork_at_turn(list(history or []), current_msg)
    )
    if is_edit_fork:
        ensure_edit_fork_branch_seeded(
            stamp_context,
            branch_id,
            fork_path=_current_path,
            fork_msg=current_msg,
            scope=scope,
            history=list(history or []),
            post_head=post_head_default,
        )
    ensure_branch_state(stamp_context, branch_id, post_head=post_head_default)
    branch_state = get_branch_state(stamp_context, branch_id, post_head=post_head_default)
    from app.services.ai.context_turns import compute_window_user_turns

    window_user_turns = compute_window_user_turns(valid_pairs)
    if user_turn_count <= 1 and not has_stamped_msgs_on_path(history):
        branch_state = initialize_heads_if_empty(
            branch_state,
            latest_channel=latest_channel,
            latest_post=latest_post,
            scope=scope,
        )
    else:
        branch_state = maturation_state_for_assembly(
            branch_state,
            list(history or []),
            current_msg=current_msg,
            scope=scope,
        )
    head_for_primer = primer_heads_from_state(
        branch_state,
        current_msg=current_msg,
        latest_channel=latest_channel,
        latest_post=latest_post,
        scope=scope,
        window_user_turns=window_user_turns,
        history=list(history or []),
    )
    _, planned_attach, _ = advance_branch_after_reply(
        branch_state,
        current_msg=current_msg,
        latest_channel=latest_channel,
        latest_post=latest_post,
        scope=scope,
        is_edit_fork=is_edit_fork,
        history=list(history or []),
        window_user_turns=window_user_turns,
    )

    head_text = _primer_head_text(
        head_for_primer,
        catalog=catalog,
        scope=scope,
        post_id=post_id,
    )
    rolling_summary = _rolling_summary_for_branch(branch_state, valid_pairs)

    stamped = stamps_by_msg_on_active_path(history)
    floating = _floating_bundles_from_stamps(
        history=list(history or []),
        window_user_turns=window_user_turns,
        catalog=catalog,
        scope=scope,
        post_id=post_id,
    )
    if current_msg in window_user_turns and current_msg not in stamped:
        planned_block = _float_text_from_stamp(
            {"summary": {"attach": planned_attach}},
            catalog=catalog,
            post_id=post_id,
            scope=scope,
        )
        if planned_block:
            floating[current_msg] = planned_block

    stamps_for_log = dict(stamped)
    if current_msg in window_user_turns and current_msg not in stamps_for_log:
        from app.services.ai.context_stamp_label import build_context_stamp

        stamps_for_log[current_msg] = build_context_stamp(
            scope=scope,
            address=current_address,
            head=head_for_primer,
            attach=planned_attach,
            catalog_channel=latest_channel,
            catalog_post=latest_post,
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
        fill_stamp_log_labels(
            log_labels,
            messages,
            head=head_for_primer,
            stamps=stamps_for_log,
            scope=scope,
            valid_pairs=valid_pairs,
            log_stamps=log_stamps,
        )
    return messages
