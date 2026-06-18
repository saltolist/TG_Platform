"""Chat context metadata: rolling summary + bundle profile persistence."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.resolve import get_owned_chat, get_owned_post
from app.schemas.requests import AiReplyRequest
from app.services.ai.bundle_profile import ensure_bundle_profile
from app.services.ai.chat_history import count_user_turns
from app.services.ai.context_config import HISTORY_WINDOW, PROMPT_WINDOW
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
    valid_pairs: list[tuple[str, str]],
    current_bundle: str,
    current_fingerprint: str,
    llm: _LLMParams | None = None,
) -> dict[str, Any]:
    """Update rolling summary and bundle profile after a completed assistant reply.

    ``llm`` — resolved orchestrator (provider, model, api_key), not the reply model.
    """
    base_meta = dict(chat_meta) if isinstance(chat_meta, Mapping) else {}
    user_turn_count = count_user_turns(valid_pairs)

    bundle_profile = ensure_bundle_profile(
        base_meta.get("rolling_summary_profile"),
        current_bundle=current_bundle,
        current_fingerprint=current_fingerprint,
        user_turn_count=user_turn_count,
    )

    prefix, _ = split_prefix_and_window(valid_pairs)
    rolling_summary = str(base_meta.get("rolling_summary") or "").strip()
    try:
        summary_idx = int(base_meta.get("rolling_summary_idx") or 0)
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

    return {
        "rolling_summary": rolling_summary,
        "rolling_summary_idx": summary_idx,
        "rolling_summary_profile": bundle_profile,
    }


async def persist_chat_meta(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: AiReplyRequest,
    meta: Mapping[str, Any],
) -> bool:
    """Persist context metadata to Postgres when the chat is stored server-side."""
    if not meta:
        return False

    patch = {key: meta[key] for key in meta}

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
