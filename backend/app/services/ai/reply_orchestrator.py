"""Orchestration layer for AI reply requests (Phase 2, step 3).

Assembles context, streams LLM output, finalises and persists metadata.
The HTTP transport layer (FastAPI router) stays in app/api/v1/ai.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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
from app.services.ai.note_citations import NoteCite, prepare_note_citations_for_reply
from app.services.ai.context import append_user_text_to_pairs, assemble_reply_messages
from app.core.config import get_settings
from app.services.ai.context_label import stamp_context_label_on_path
from app.services.ai.context_stamp_label import stamp_context_stamp_on_path
from app.services.ai.context_stamp_types import (
    ACTIVE_BRANCH_KEY,
    STAMP_CONTEXT_KEY,
    STAMP_MECHANICS_FLAG,
)
from app.services.ai.context_labels import THREAD_LABEL_STATE_KEY
from app.services.ai.context_log import (
    get_chat_filter,
    log_llm_request,
    log_llm_response,
    should_log_llm_context,
)
from app.services.ai.context_meta import persist_chat_meta, refresh_context_meta_after_reply
from app.services.ai.context_stamp_meta import refresh_stamp_meta_after_reply
from app.services.ai.llm import stream_llm_sse
from app.services.ai.orchestrator import resolve_orchestrator_llm
from app.services.ai.providers import ProviderSpec
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
    THREAD_LABEL_STATE_KEY,
    STAMP_CONTEXT_KEY,
    STAMP_MECHANICS_FLAG,
    ACTIVE_BRANCH_KEY,
)


@dataclass
class ReplyContext:
    """All resolved context for one AI reply request.

    Built once in the endpoint, passed as a single object to streaming functions.
    """

    session: AsyncSession
    user: User
    payload: AiReplyRequest
    ai_profile: dict[str, Any]
    channel_profile: Mapping[str, Any]
    telegram_profile: Mapping[str, Any]
    history: list[Mapping[str, Any]] | None
    post_data: Mapping[str, Any] | None
    chat_meta: dict[str, Any]
    summary_catalog: Mapping[str, Any]

    # LLM parameters — set after model/key resolution, absent for stub mode
    spec: ProviderSpec | None = None
    model_id: str = ""
    api_key: str = ""
    provider_name: str = ""

    # Logging
    log_context: bool = False
    log_labels: dict[int, str] = field(default_factory=dict)
    log_stamps: dict[int, dict[str, Any]] = field(default_factory=dict)
    rag_cites: list[NoteCite] = field(default_factory=list)


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


async def _finalize_context_meta(ctx: ReplyContext, assistant_text: str) -> dict[str, Any]:
    """Refresh rolling summary, stamp label on history, persist to DB."""
    post = ctx.post_data if ctx.payload.scope == "post" else None
    current_bundle = build_summary_bundle(
        ctx.channel_profile,
        telegram=ctx.telegram_profile,
        post=post,
    )
    fingerprint = bundle_fingerprint(ctx.channel_profile, telegram=ctx.telegram_profile, post=post)
    valid_pairs = valid_pairs_with_assistant_reply(ctx.history, ctx.payload.text, assistant_text)

    summary_llm = resolve_orchestrator_llm(ctx.user, ctx.ai_profile)

    catalog = ensure_initial_global_version(
        ctx.summary_catalog,
        channel=ctx.channel_profile,
        telegram=ctx.telegram_profile,
    )
    profile_row = await ctx.session.get(Profile, ctx.user.id)
    if profile_row is not None and not profile_row.summary_catalog and catalog.get("global"):
        profile_row.summary_catalog = catalog

    updated_meta = None
    if get_settings().ai_context_stamps:
        updated_meta = await refresh_stamp_meta_after_reply(
            ctx.chat_meta,
            history=ctx.history,
            valid_pairs=valid_pairs,
            llm=summary_llm,
            summary_catalog=catalog,
            scope=ctx.payload.scope,
            post_id=str(post.get("id") or "") if isinstance(post, Mapping) and post.get("id") else ctx.payload.post_id,
        )
    else:
        updated_meta = await refresh_context_meta_after_reply(
            ctx.chat_meta,
            history=ctx.history,
            valid_pairs=valid_pairs,
            current_bundle=current_bundle,
            current_fingerprint=fingerprint,
            llm=summary_llm,
            summary_catalog=catalog,
            scope=ctx.payload.scope,
            post_id=str(post.get("id") or "") if isinstance(post, Mapping) and post.get("id") else ctx.payload.post_id,
        )

    stamped_history: list[Mapping[str, Any]] | None = None
    if get_settings().ai_context_stamps:
        stamp_payload = updated_meta.get("context_stamp")
        if isinstance(stamp_payload, Mapping):
            source_history = await _history_for_stamp(ctx.session, ctx.user, ctx.payload, ctx.history)
            path = stamp_payload.get("path")
            stamp = stamp_payload.get("stamp")
            if isinstance(path, list) and isinstance(stamp, Mapping):
                applied = stamp_context_stamp_on_path(
                    source_history,
                    [int(part) for part in path],
                    stamp,  # type: ignore[arg-type]
                )
                if applied is not None:
                    stamped_history = applied
    else:
        label_stamp = updated_meta.get("context_label_stamp")
        if isinstance(label_stamp, Mapping):
            source_history = await _history_for_stamp(ctx.session, ctx.user, ctx.payload, ctx.history)
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
        ctx.session,
        ctx.user.id,
        ctx.payload,
        updated_meta,
        history=stamped_history,
    )
    await ctx.session.commit()
    return updated_meta


async def stream_reply_with_meta(ctx: ReplyContext, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    if ctx.log_context:
        log_llm_request(
            scope=ctx.payload.scope,
            chat_id=ctx.payload.chat_id,
            post_id=ctx.payload.post_id,
            post_chat_id=ctx.payload.post_chat_id,
            provider=ctx.provider_name,
            model=ctx.model_id,
            history=ctx.history,
            messages=messages,
            message_labels=ctx.log_labels if ctx.log_labels else None,
            message_stamps=ctx.log_stamps if ctx.log_stamps else None,
        )
    accumulated: list[str] = []
    async for event in stream_llm_sse(
        spec=ctx.spec,
        model=ctx.model_id,
        api_key=ctx.api_key,
        messages=messages,
    ):
        chunk = parse_sse_text_chunk(event)
        if chunk:
            accumulated.append(chunk)
        yield event

    assistant_text = "".join(accumulated)
    assistant_text = prepare_note_citations_for_reply(assistant_text, ctx.rag_cites)
    updated_meta = await _finalize_context_meta(ctx, assistant_text)
    if ctx.log_context:
        log_llm_response(
            scope=ctx.payload.scope,
            chat_id=ctx.payload.chat_id,
            post_id=ctx.payload.post_id,
            post_chat_id=ctx.payload.post_chat_id,
            provider=ctx.provider_name,
            model=ctx.model_id,
            assistant_text=assistant_text,
            context_stamp=updated_meta.get("context_stamp")
            if isinstance(updated_meta.get("context_stamp"), Mapping)
            else None,
        )
    updated_meta["assistant_text"] = assistant_text
    yield format_sse_meta(updated_meta)


async def stream_stub_with_meta(ctx: ReplyContext) -> AsyncIterator[str]:
    accumulated: list[str] = []
    async for event in stream_stub_reply(ctx.payload.text, scope=ctx.payload.scope):
        chunk = parse_sse_text_chunk(event)
        if chunk:
            accumulated.append(chunk)
        yield event

    assistant_text = "".join(accumulated)
    updated_meta = await _finalize_context_meta(ctx, assistant_text)
    yield format_sse_meta(updated_meta)
