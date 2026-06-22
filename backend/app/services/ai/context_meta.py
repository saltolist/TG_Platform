"""Chat context metadata: rolling summary + bundle profile persistence."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.resolve import get_owned_chat, get_owned_post
from app.schemas.requests import AiReplyRequest
from app.services.ai.bundle_profile import advance_bundle_profile
from app.services.ai.chat_history import count_user_turns
from app.services.ai.context_config import PROMPT_WINDOW
from app.services.ai.context_turns import compute_window_user_turns, maturation_window_user_turns
from app.services.ai.context_label import enumerate_active_user_turns, resolve_turn_label
from app.services.ai.context_labels import (
    advance_label_thread_after_reply,
    flatten_label_thread_meta,
    resolve_label_thread_state,
)
from app.services.ai.message_bundle import (
    apply_bundle_context_stamp_to_history,
    compute_bundle_context_stamp,
    last_user_message_path,
)
from app.services.ai.summary_catalog import get_summary_catalog, latest_scope_version, normalize_catalog
from app.services.ai.thread_context import (
    GLOBAL_FINGERPRINT_KEY,
    flatten_thread_meta,
    resolve_thread_state,
)


from app.services.ai.context_turns import annotate_user_turns
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
    is_meta_rolling_summary_response,
    reconcile_rolling_summary_fields,
    update_rolling_summary_llm,
    update_rolling_summary_template,
)

_LLMParams = tuple[Any, str, str]  # spec, model, api_key


def split_prefix_and_window(
    pairs: list[tuple[str, str]],
    *,
    window_size: int = PROMPT_WINDOW,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    if window_size <= 0 or len(pairs) <= window_size:
        return [], pairs
    return pairs[:-window_size], pairs[-window_size:]


def apply_rolling_summary_reconcile_to_chat_data(
    chat_data: Mapping[str, Any],
    history: list[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return chat.data fields to merge after history changed (dialog summary only)."""
    from app.services.ai.chat_history import (
        active_thread_key,
        filter_alternating_roles,
        linearize_for_llm,
    )
    from app.services.ai.context_labels import (
        flatten_label_thread_meta,
        load_label_thread_context,
    )
    from app.services.ai.thread_context import (
        flatten_thread_meta,
        load_thread_context,
    )

    valid_pairs = filter_alternating_roles(linearize_for_llm(list(history or [])))
    thread_key = active_thread_key(list(history or []))

    label_threads = load_label_thread_context(chat_data)
    if label_threads and thread_key in label_threads:
        reconciled = reconcile_rolling_summary_fields(label_threads[thread_key], valid_pairs)
        if reconciled == label_threads[thread_key]:
            return {}
        updated_threads = {**label_threads, thread_key: reconciled}
        return flatten_label_thread_meta(
            reconciled,
            thread_key=thread_key,
            threads=updated_threads,
        )

    threads = load_thread_context(chat_data)
    if threads and thread_key in threads:
        reconciled = reconcile_rolling_summary_fields(threads[thread_key], valid_pairs)
        if reconciled == threads[thread_key]:
            return {}
        updated_threads = {**threads, thread_key: reconciled}
        return flatten_thread_meta(
            reconciled,
            thread_key=thread_key,
            threads=updated_threads,
        )

    flat_state = {
        "rolling_summary": chat_data.get("rolling_summary"),
        "rolling_summary_idx": chat_data.get("rolling_summary_idx"),
    }
    reconciled = reconcile_rolling_summary_fields(flat_state, valid_pairs)
    if (
        reconciled.get("rolling_summary") == chat_data.get("rolling_summary")
        and reconciled.get("rolling_summary_idx") == chat_data.get("rolling_summary_idx")
    ):
        return {}
    return {
        "rolling_summary": reconciled.get("rolling_summary") or "",
        "rolling_summary_idx": int(reconciled.get("rolling_summary_idx") or 0),
    }


async def refresh_context_meta_after_reply(
    chat_meta: Mapping[str, Any] | None,
    *,
    history: list[Mapping[str, Any]] | None,
    valid_pairs: list[tuple[str, str]],
    current_bundle: str,
    current_fingerprint: str,
    llm: _LLMParams | None = None,
    summary_catalog: Mapping[str, Any] | None = None,
    scope: str = "global",
    post_id: str | None = None,
) -> dict[str, Any]:
    """Update rolling summary and bundle profile after a completed assistant reply.

    ``llm`` — resolved orchestrator (provider, model, api_key), not the reply model.
    """
    catalog = normalize_catalog(summary_catalog)
    if catalog.get("global"):
        return await _refresh_context_meta_labels(
            chat_meta,
            history=history,
            valid_pairs=valid_pairs,
            catalog=catalog,
            llm=llm,
            scope=scope,
            post_id=post_id,
        )

    thread_state, thread_key, threads = resolve_thread_state(
        chat_meta,
        history,
        global_fingerprint=current_fingerprint,
    )
    user_turn_count = count_user_turns(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)

    bundle_profile, global_fingerprint = advance_bundle_profile(
        thread_state.get("rolling_summary_profile"),
        current_bundle=current_bundle,
        current_fingerprint=current_fingerprint,
        global_fingerprint_at_last_refresh=thread_state.get(GLOBAL_FINGERPRINT_KEY),
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )

    prefix, _ = split_prefix_and_window(valid_pairs)
    summary_state = reconcile_rolling_summary_fields(thread_state, valid_pairs)
    rolling_summary = str(summary_state.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(summary_state.get("rolling_summary_idx") or 0)
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

    updated_thread_state = {
        **dict(thread_state),
        "rolling_summary": rolling_summary,
        "rolling_summary_idx": summary_idx,
        "rolling_summary_profile": bundle_profile,
        GLOBAL_FINGERPRINT_KEY: global_fingerprint,
    }
    threads[thread_key] = updated_thread_state
    meta = flatten_thread_meta(
        updated_thread_state,
        thread_key=thread_key,
        threads=threads,
    )
    stamp_path = last_user_message_path(history)
    if stamp_path is not None:
        stamp = compute_bundle_context_stamp(
            bundle_profile,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        )
        meta["bundle_context_stamp"] = {
            "path": stamp_path,
            **stamp,
        }
    return meta


async def _refresh_context_meta_labels(
    chat_meta: Mapping[str, Any] | None,
    *,
    history: list[Mapping[str, Any]] | None,
    valid_pairs: list[tuple[str, str]],
    catalog: Mapping[str, Any],
    llm: _LLMParams | None,
    scope: str,
    post_id: str | None,
) -> dict[str, Any]:
    user_turn_count = count_user_turns(valid_pairs)
    latest_global = latest_scope_version(catalog, scope="global", post_id=None)
    latest_local = latest_scope_version(catalog, scope=scope, post_id=post_id)
    thread_state, thread_key, threads = resolve_label_thread_state(
        chat_meta,
        history,
        latest_catalog_version=latest_local if scope == "post" else latest_global,
    )

    turn_entries = enumerate_active_user_turns(list(history or []))
    turn_label = resolve_turn_label(list(history or []), user_turn_count)
    stamp_path: list[int] | None = None
    if turn_entries:
        stamp_path = turn_entries[-1]["path"]

    if scope == "post" and post_id:
        from app.services.ai.context_labels_post import (
            advance_post_label_thread_after_reply,
            flatten_post_label_thread_meta,
            resolve_post_label_thread_state,
        )

        thread_state, thread_key, threads = resolve_post_label_thread_state(
            chat_meta,
            history,
            latest_global=latest_global,
            latest_local=max(1, latest_local),
        )
        hg, hl, ag, al, updated_thread = advance_post_label_thread_after_reply(
            thread_state,
            user_turn_count=user_turn_count,
            turn_label=turn_label,
            latest_global=latest_global,
            latest_local=max(1, latest_local),
            window_user_turns=maturation_window_user_turns(valid_pairs),
            history=list(history or []),
        )
        head, attached = hg, ag
    else:
        head, attached, updated_thread = advance_label_thread_after_reply(
            thread_state,
            user_turn_count=user_turn_count,
            turn_label=turn_label,
            latest_catalog_version=latest_local if scope == "post" else latest_global,
            window_user_turns=maturation_window_user_turns(valid_pairs),
            history=list(history or []),
        )
        hg = hl = ag = al = None

    prefix, _ = split_prefix_and_window(valid_pairs)
    summary_state = reconcile_rolling_summary_fields(updated_thread, valid_pairs)
    rolling_summary = str(summary_state.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(summary_state.get("rolling_summary_idx") or 0)
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

    updated_thread = {
        **updated_thread,
        "rolling_summary": rolling_summary,
        "rolling_summary_idx": summary_idx,
    }
    threads[thread_key] = updated_thread
    if scope == "post" and post_id:
        from app.services.ai.context_labels_post import flatten_post_label_thread_meta

        meta = flatten_post_label_thread_meta(updated_thread, thread_key=thread_key, threads=threads)
    else:
        meta = flatten_label_thread_meta(updated_thread, thread_key=thread_key, threads=threads)

    if stamp_path is not None:
        stamp: dict[str, Any] = {
            "path": stamp_path,
            "turn": turn_label,
        }
        if scope == "post" and post_id and hg is not None:
            stamp.update(
                {
                    "head_global": hg,
                    "head_local": hl,
                    "attached_global": ag,
                    "attached_local": al,
                    "scope": "post",
                }
            )
        else:
            stamp["head"] = head
            stamp["attached"] = attached
        meta["context_label_stamp"] = stamp
    return meta


async def persist_chat_meta(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: AiReplyRequest,
    meta: Mapping[str, Any],
    *,
    history: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Persist context metadata to Postgres when the chat is stored server-side."""
    if not meta and history is None:
        return False

    patch = {key: meta[key] for key in meta if key not in ("bundle_context_stamp", "context_label_stamp")}
    if history is not None:
        from app.services.ai.chat_history import merge_history_stamps

        history = list(history)

    if payload.scope == "post" and payload.post_id and payload.post_chat_id:
        try:
            post = await get_owned_post(session, user_id, payload.post_id)
        except HTTPException:
            return False

        chats = list(post.data.get("chats") or [])
        updated = False
        for index, chat in enumerate(chats):
            if not isinstance(chat, Mapping):
                continue
            if str(chat.get("id")) != payload.post_chat_id:
                continue
            chat_patch = dict(patch)
            if history is not None:
                existing_history = list(chat.get("history") or [])
                chat_patch["history"] = merge_history_stamps(existing_history, history)
            chats[index] = {**dict(chat), **chat_patch}
            updated = True
            break
        if not updated:
            return False

        post.data = {**post.data, "chats": chats}
        return True

    if not payload.chat_id:
        return False

    try:
        chat = await get_owned_chat(session, user_id, payload.chat_id)
    except HTTPException:
        return False

    if history is not None:
        existing_history = list(chat.data.get("history") or [])
        patch["history"] = merge_history_stamps(existing_history, history)

    chat.data = {**chat.data, **patch}
    return True
