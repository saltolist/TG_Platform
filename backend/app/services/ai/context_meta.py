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
from app.services.ai.context_config import HISTORY_WINDOW, PROMPT_WINDOW
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
from app.services.ai.summary_catalog import get_summary_catalog, normalize_catalog
from app.services.ai.thread_context import (
    GLOBAL_FINGERPRINT_KEY,
    flatten_thread_meta,
    resolve_thread_state,
)


from app.services.ai.context_turns import annotate_user_turns
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
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
    rolling_summary = str(thread_state.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(thread_state.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    summary_idx = max(0, summary_idx)

    if len(valid_pairs) > HISTORY_WINDOW and len(prefix) > summary_idx:
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
    latest_version = _latest_scope_version(catalog, scope=scope, post_id=post_id)
    thread_state, thread_key, threads = resolve_label_thread_state(
        chat_meta,
        history,
        latest_catalog_version=latest_version,
    )

    turn_entries = enumerate_active_user_turns(list(history or []))
    turn_label = resolve_turn_label(list(history or []), user_turn_count)
    stamp_path: list[int] | None = None
    if turn_entries:
        stamp_path = turn_entries[-1]["path"]

    head, attached, updated_thread = advance_label_thread_after_reply(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_version,
        window_user_turns=maturation_window_user_turns(valid_pairs),
        history=list(history or []),
    )

    prefix, _ = split_prefix_and_window(valid_pairs)
    rolling_summary = str(thread_state.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(thread_state.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    summary_idx = max(0, summary_idx)

    if len(valid_pairs) > HISTORY_WINDOW and len(prefix) > summary_idx:
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
    meta = flatten_label_thread_meta(updated_thread, thread_key=thread_key, threads=threads)

    if stamp_path is not None:
        meta["context_label_stamp"] = {
            "path": stamp_path,
            "head": head,
            "attached": attached,
            "turn": turn_label,
        }
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
