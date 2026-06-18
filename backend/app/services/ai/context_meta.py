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
from app.services.ai.message_bundle import (
    apply_bundle_context_stamp_to_history,
    compute_bundle_context_stamp,
    last_user_message_path,
)
from app.services.ai.thread_context import (
    GLOBAL_FINGERPRINT_KEY,
    flatten_thread_meta,
    resolve_thread_state,
)


def compute_window_user_turns(
    pairs: list[tuple[str, str]],
    *,
    window_size: int = PROMPT_WINDOW,
) -> set[int]:
    if window_size <= 0 or not pairs:
        return set()
    window_len = min(window_size, len(pairs))
    window_annotated = annotate_user_turns(pairs)[-window_len:]
    return {
        user_turn
        for user_turn, role, _ in window_annotated
        if role == "user" and user_turn is not None
    }
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


def annotate_user_turns(
    pairs: list[tuple[str, str]],
) -> list[tuple[int | None, str, str]]:
    user_turn = 0
    annotated: list[tuple[int | None, str, str]] = []
    for role, content in pairs:
        if role == "user":
            user_turn += 1
            annotated.append((user_turn, role, content))
        else:
            annotated.append((None, role, content))
    return annotated


async def refresh_context_meta_after_reply(
    chat_meta: Mapping[str, Any] | None,
    *,
    history: list[Mapping[str, Any]] | None,
    valid_pairs: list[tuple[str, str]],
    current_bundle: str,
    current_fingerprint: str,
    llm: _LLMParams | None = None,
) -> dict[str, Any]:
    """Update rolling summary and bundle profile after a completed assistant reply.

    ``llm`` — resolved orchestrator (provider, model, api_key), not the reply model.
    """
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

    patch = {key: meta[key] for key in meta if key != "bundle_context_stamp"}
    if history is not None:
        patch["history"] = history

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
            chats[index] = {**dict(chat), **patch}
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

    chat.data = {**chat.data, **patch}
    return True
