"""Refresh chat meta and stamps after AI reply (v2 mechanics)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import count_user_turns
from app.services.ai.context_meta import split_prefix_and_window
from app.services.ai.context_stamp_address import (
    ensure_branch_state,
    resolve_active_branch_id,
    resolve_current_address,
)
from app.services.ai.context_stamp_label import build_context_stamp
from app.services.ai.context_stamp_planner import advance_branch_after_reply, initialize_heads_if_empty
from app.services.ai.context_stamp_maturation import has_stamped_msgs_on_path
from app.services.ai.context_turns import maturation_window_user_turns
from app.services.ai.context_stamp_state import (
    ensure_edit_fork_branch_seeded,
    flatten_stamp_meta,
    get_branch_state,
    load_stamp_context,
    reconcile_branch_rolling,
)
from app.services.ai.context_stamp_types import STAMP_MECHANICS_FLAG, branch_state_key
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
    is_meta_rolling_summary_response,
    update_rolling_summary_llm,
    update_rolling_summary_template,
)
from app.services.ai.summary_catalog import latest_global_version, latest_local_version

_LLMParams = tuple[Any, str, str]


async def refresh_stamp_meta_after_reply(
    chat_meta: Mapping[str, Any] | None,
    *,
    history: list[Mapping[str, Any]] | None,
    valid_pairs: list[tuple[str, str]],
    llm: _LLMParams | None = None,
    summary_catalog: Mapping[str, Any] | None = None,
    scope: str = "global",
    post_id: str | None = None,
) -> dict[str, Any]:
    catalog = summary_catalog or {}
    latest_channel = latest_global_version(catalog)
    latest_post = latest_local_version(catalog, post_id or "") if scope == "post" and post_id else 0
    post_head_default = max(1, latest_post) if scope == "post" else 0

    stamp_context = load_stamp_context(chat_meta, post_head=post_head_default)
    address, stamp_path = resolve_current_address(history, stamp_context=stamp_context)
    if address is None or stamp_path is None:
        return {STAMP_MECHANICS_FLAG: True}

    branch_id = int(address["branch"])
    current_msg = int(address["msg"])
    is_edit_fork = int(address.get("msgVersion") or 1) > 1
    if is_edit_fork:
        ensure_edit_fork_branch_seeded(
            stamp_context,
            branch_id,
            fork_path=stamp_path,
            fork_msg=current_msg,
            scope=scope,
            history=list(history or []),
            post_head=post_head_default,
        )
    ensure_branch_state(stamp_context, branch_id, post_head=post_head_default)

    branch_state = get_branch_state(stamp_context, branch_id, post_head=post_head_default)
    if not has_stamped_msgs_on_path(history, up_to_msg=current_msg):
        branch_state = initialize_heads_if_empty(
            branch_state,
            latest_channel=latest_channel,
            latest_post=latest_post,
            scope=scope,
        )
    window_user_turns = maturation_window_user_turns(valid_pairs)

    head, attach, updated_branch = advance_branch_after_reply(
        branch_state,
        current_msg=current_msg,
        latest_channel=latest_channel,
        latest_post=latest_post,
        scope=scope,
        is_edit_fork=is_edit_fork,
        history=list(history or []),
        window_user_turns=window_user_turns,
    )

    prefix, _ = split_prefix_and_window(valid_pairs)
    updated_branch = reconcile_branch_rolling(updated_branch, valid_pairs)
    rolling_summary = str(updated_branch.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(updated_branch.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    summary_idx = max(0, summary_idx)
    if is_meta_rolling_summary_response(rolling_summary):
        rolling_summary = ""
        summary_idx = 0

    if len(prefix) > summary_idx:
        new_segment = prefix[summary_idx:]
        exchanges = exchanges_from_messages(new_segment)
        if exchanges:
            if llm is not None:
                spec, model, api_key = llm
                rolling_summary = await update_rolling_summary_llm(
                    rolling_summary,
                    exchanges,
                    spec=spec,
                    model=model,
                    api_key=api_key,
                )
            else:
                rolling_summary = update_rolling_summary_template(rolling_summary, exchanges)
            summary_idx = len(prefix)

    updated_branch = {
        **updated_branch,
        "rolling_summary": rolling_summary,
        "rolling_summary_idx": summary_idx,
    }
    stamp_context["branches"][branch_state_key(branch_id)] = updated_branch

    stamp = build_context_stamp(
        scope=scope,
        address=address,
        head=head,
        attach=attach,
        catalog_channel=latest_channel,
        catalog_post=latest_post,
    )
    meta = flatten_stamp_meta(updated_branch, branch_id=branch_id, stamp_context=stamp_context)
    meta["context_stamp"] = {
        "path": stamp_path,
        "stamp": stamp,
    }
    return meta
