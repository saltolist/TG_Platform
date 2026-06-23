"""Orchestration layer for AI reply requests (Phase 2, step 3).

Assembles context, streams LLM output, finalises and persists metadata.
The HTTP transport layer (FastAPI router) stays in app/api/v1/ai.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LEGACY_PRESENTATION_EMAIL, PRESENTATION_EMAIL
from app.db.models import Profile, User
from app.db.resolve import get_owned_chat, get_owned_post
from app.schemas.requests import AiReplyRequest
from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint
from app.services.ai.chat_history import (
    filter_alternating_roles,
    linearize_for_llm,
    merge_history_stamps,
)
from app.services.ai.context import append_user_text_to_pairs, assemble_reply_messages
from app.services.ai.context_label import stamp_context_label_on_path
from app.services.ai.context_log import (
    get_chat_filter,
    log_llm_request,
    log_llm_response,
    should_log_llm_context,
)
from app.services.ai.context_meta import persist_chat_meta, refresh_context_meta_after_reply
from app.services.ai.llm import stream_llm_sse
from app.services.ai.orchestrator import resolve_orchestrator_llm
from app.services.ai.sse import format_sse_meta, parse_sse_text_chunk, stream_stub_reply
from app.services.ai.summary_catalog import (
    catalog_from_profile,
    ensure_initial_global_version,
    ensure_post_local_catalog_current,
    register_global_summary_version,
)

_PRESENTATION_EMAILS = frozenset({PRESENTATION_EMAIL, LEGACY_PRESENTATION_EMAIL})

_CHAT_META_KEYS = (
    "rolling_summary",
    "rolling_summary_idx",
    "rolling_summary_profile",
    "active_thread_key",
    "thread_context",
    "global_fingerprint_at_last_refresh",
    "label_context",
)


def prefers_server_chat_history(user: User) -> bool:
    """Writer accounts use Postgres as the sole history source for persisted chats."""
    return user.email not in _PRESENTATION_EMAILS


def extract_chat_meta(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    return {key: data[key] for key in _CHAT_META_KEYS if key in data}


def valid_pairs_with_assistant_reply(
    history: list[Mapping[str, Any]] | None,
    user_text: str,
    assistant_text: str,
) -> list[tuple[str, str]]:
    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)
    valid_pairs = append_user_text_to_pairs(valid_pairs, user_text)

    assistant_reply = assistant_text.strip()
    if assistant_reply:
        if valid_pairs and valid_pairs[-1][0] == "user":
            valid_pairs.append(("assistant", assistant_reply))
        elif not valid_pairs or valid_pairs[-1][0] != "assistant":
            valid_pairs.append(("assistant", assistant_reply))
        elif valid_pairs[-1][0] == "assistant":
            valid_pairs[-1] = ("assistant", assistant_reply)

    return valid_pairs


async def _load_owned_post_data(
    session: AsyncSession,
    user_id: uuid.UUID,
    post_id: str,
) -> Mapping[str, Any] | None:
    try:
        post = await get_owned_post(session, user_id, post_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    return post.data


async def load_reply_context(
    payload: AiReplyRequest,
    user: User,
    session: AsyncSession,
) -> tuple[list[Mapping[str, Any]] | None, Mapping[str, Any] | None, dict[str, Any]]:
    """Return (history, post_data, chat_meta) for the current request."""
    client_history = payload.history
    history: list[Mapping[str, Any]] | None = None
    post_data: Mapping[str, Any] | None = None
    chat_meta: dict[str, Any] = {}

    if payload.scope == "post" and payload.post_id:
        post_data = await _load_owned_post_data(session, user.id, payload.post_id)
        if post_data is not None and payload.post_chat_id:
            for chat in post_data.get("chats") or []:
                if not isinstance(chat, Mapping):
                    continue
                if str(chat.get("id")) == payload.post_chat_id:
                    db_history = list(chat.get("history") or [])
                    if prefers_server_chat_history(user):
                        history = db_history
                    elif isinstance(client_history, list):
                        history = merge_history_stamps(db_history, list(client_history))
                    else:
                        history = db_history
                    chat_meta = extract_chat_meta(chat)
                    break
    elif payload.chat_id:
        try:
            chat = await get_owned_chat(session, user.id, payload.chat_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            history = list(client_history or [])
        else:
            db_history = list(chat.data.get("history") or [])
            if prefers_server_chat_history(user):
                history = db_history
            elif isinstance(client_history, list):
                history = merge_history_stamps(db_history, list(client_history))
            else:
                history = db_history
            chat_meta = extract_chat_meta(chat.data)

    if history is None:
        history = list(client_history or [])

    if isinstance(payload.chat_meta, Mapping):
        chat_meta = {**chat_meta, **dict(payload.chat_meta)}

    return history, post_data, chat_meta


async def _reload_persisted_history(
    session: AsyncSession,
    user: User,
    payload: AiReplyRequest,
) -> list[dict[str, Any]] | None:
    """Reload chat history from Postgres before stamping (writer accounts only)."""
    if not prefers_server_chat_history(user):
        return None
    if payload.chat_id:
        try:
            chat = await get_owned_chat(session, user.id, payload.chat_id)
        except HTTPException:
            return None
        return list(chat.data.get("history") or [])

    if payload.scope == "post" and payload.post_id and payload.post_chat_id:
        post_data = await _load_owned_post_data(session, user.id, payload.post_id)
        if post_data is None:
            return None
        for chat in post_data.get("chats") or []:
            if not isinstance(chat, Mapping):
                continue
            if str(chat.get("id")) != payload.post_chat_id:
                continue
            return list(chat.get("history") or [])
    return None


async def _history_for_stamp(
    session: AsyncSession,
    user: User,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    reloaded = await _reload_persisted_history(session, user, payload)
    if reloaded is not None:
        return reloaded
    return list(history or [])


async def prepare_summary_catalog(
    *,
    session: AsyncSession,
    profile: Profile | None,
    payload: AiReplyRequest,
    post_data: Mapping[str, Any] | None,
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Ensure catalog is initialised and up-to-date; persist to profile if changed."""
    catalog = ensure_initial_global_version(
        catalog_from_profile(profile),
        channel=channel_profile,
        telegram=telegram_profile,
    )
    catalog, new_global = register_global_summary_version(
        catalog,
        channel=channel_profile,
        telegram=telegram_profile,
    )
    catalog_dirty = (
        profile is not None and not profile.summary_catalog and catalog.get("global")
    ) or new_global is not None

    if payload.scope == "post" and post_data is not None:
        post_id = str(post_data.get("id") or payload.post_id or "")
        if post_id:
            catalog, new_local = ensure_post_local_catalog_current(
                catalog,
                post_id=post_id,
                channel=channel_profile,
                telegram=telegram_profile,
                post=post_data,
            )
            if new_local is not None:
                catalog_dirty = True

    if profile is not None and catalog_dirty:
        profile.summary_catalog = catalog
        await session.flush()

    return catalog


async def finalize_context_meta(
    *,
    session: AsyncSession,
    user: User,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
    post_data: Mapping[str, Any] | None,
    chat_meta: dict[str, Any],
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
    assistant_text: str,
    ai_profile: dict[str, Any],
    summary_catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh rolling summary, stamp label on history, persist to DB."""
    post = post_data if payload.scope == "post" else None
    current_bundle = build_summary_bundle(
        channel_profile,
        telegram=telegram_profile,
        post=post,
    )
    fingerprint = bundle_fingerprint(channel_profile, telegram=telegram_profile, post=post)
    valid_pairs = valid_pairs_with_assistant_reply(history, payload.text, assistant_text)

    summary_llm = resolve_orchestrator_llm(user, ai_profile)

    catalog = ensure_initial_global_version(
        summary_catalog,
        channel=channel_profile,
        telegram=telegram_profile,
    )
    profile_row = await session.get(Profile, user.id)
    if profile_row is not None and not profile_row.summary_catalog and catalog.get("global"):
        profile_row.summary_catalog = catalog

    updated_meta = await refresh_context_meta_after_reply(
        chat_meta,
        history=history,
        valid_pairs=valid_pairs,
        current_bundle=current_bundle,
        current_fingerprint=fingerprint,
        llm=summary_llm,
        summary_catalog=catalog,
        scope=payload.scope,
        post_id=str(post.get("id") or "") if isinstance(post, Mapping) and post.get("id") else payload.post_id,
    )

    stamped_history: list[Mapping[str, Any]] | None = None
    label_stamp = updated_meta.get("context_label_stamp")
    if isinstance(label_stamp, Mapping):
        source_history = await _history_for_stamp(session, user, payload, history)
        path = label_stamp.get("path")
        if isinstance(path, list):
            stamp_kwargs: dict[str, Any] = {
                "turn_label": str(label_stamp.get("turn") or ""),
            }
            if label_stamp.get("scope") == "post":
                applied = stamp_context_label_on_path(
                    source_history,
                    [int(part) for part in path],
                    head_global=int(label_stamp.get("head_global") or 0),
                    head_local=int(label_stamp.get("head_local") or 1),
                    attached_global=int(label_stamp.get("attached_global") or 0),
                    attached_local=int(label_stamp.get("attached_local") or 0),
                    **stamp_kwargs,
                )
            else:
                applied = stamp_context_label_on_path(
                    source_history,
                    [int(part) for part in path],
                    head=int(label_stamp.get("head") or 0),
                    attached=int(label_stamp.get("attached") or 0),
                    **stamp_kwargs,
                )
            if applied is not None:
                stamped_history = applied

    await persist_chat_meta(
        session,
        user.id,
        payload,
        updated_meta,
        history=stamped_history,
    )
    await session.commit()
    return updated_meta


async def stream_reply_with_meta(
    *,
    session: AsyncSession,
    user: User,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
    post_data: Mapping[str, Any] | None,
    chat_meta: dict[str, Any],
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
    ai_profile: dict[str, Any],
    messages: list[dict[str, str]],
    spec: Any,
    model_id: str,
    api_key: str,
    provider_name: str,
    log_context: bool = False,
    summary_catalog: Mapping[str, Any] | None = None,
    log_labels: dict[int, str] | None = None,
) -> AsyncIterator[str]:
    if log_context:
        log_llm_request(
            scope=payload.scope,
            chat_id=payload.chat_id,
            post_id=payload.post_id,
            post_chat_id=payload.post_chat_id,
            provider=provider_name,
            model=model_id,
            history=history,
            messages=messages,
            message_labels=log_labels,
        )
    accumulated: list[str] = []
    async for event in stream_llm_sse(
        spec=spec,
        model=model_id,
        api_key=api_key,
        messages=messages,
    ):
        chunk = parse_sse_text_chunk(event)
        if chunk:
            accumulated.append(chunk)
        yield event

    assistant_text = "".join(accumulated)
    if log_context:
        log_llm_response(
            scope=payload.scope,
            chat_id=payload.chat_id,
            post_id=payload.post_id,
            post_chat_id=payload.post_chat_id,
            provider=provider_name,
            model=model_id,
            assistant_text=assistant_text,
        )
    updated_meta = await finalize_context_meta(
        session=session,
        user=user,
        payload=payload,
        history=history,
        post_data=post_data,
        chat_meta=chat_meta,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        assistant_text=assistant_text,
        ai_profile=ai_profile,
        summary_catalog=summary_catalog,
    )
    yield format_sse_meta(updated_meta)


async def stream_stub_with_meta(
    *,
    session: AsyncSession,
    user: User,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
    post_data: Mapping[str, Any] | None,
    chat_meta: dict[str, Any],
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
    ai_profile: dict[str, Any],
    summary_catalog: Mapping[str, Any] | None = None,
) -> AsyncIterator[str]:
    accumulated: list[str] = []
    async for event in stream_stub_reply(payload.text, scope=payload.scope):
        chunk = parse_sse_text_chunk(event)
        if chunk:
            accumulated.append(chunk)
        yield event

    assistant_text = "".join(accumulated)
    updated_meta = await finalize_context_meta(
        session=session,
        user=user,
        payload=payload,
        history=history,
        post_data=post_data,
        chat_meta=chat_meta,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        assistant_text=assistant_text,
        ai_profile=ai_profile,
        summary_catalog=summary_catalog,
    )
    yield format_sse_meta(updated_meta)
