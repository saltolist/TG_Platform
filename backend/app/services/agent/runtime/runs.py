"""Agent run orchestration facade."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, GlobalNote, Profile, User
from app.db.resolve import get_owned_chat, get_owned_post
from app.services.agent.runtime import events as event_service
from app.services.agent.runtime.context import RuntimeContext


async def start_run(
    session: AsyncSession,
    *,
    user: User,
    thread_id: str,
    scope: str = "global",
    chat_id: str | None = None,
    post_id: str | None = None,
    post_chat_id: str | None = None,
    timezone: str | None = None,
) -> tuple[Any, int]:
    run = await event_service.create_run(
        session,
        user_id=user.id,
        thread_id=thread_id,
        scope=scope,
        chat_id=chat_id,
        post_id=post_id,
        post_chat_id=post_chat_id,
        tz_name=timezone,
    )
    evt = await event_service.append_event(
        session,
        run_id=run.id,
        event_type="run_started",
        payload={"thread_id": thread_id, "scope": scope},
    )
    await session.commit()
    return run, evt.sequence


def build_runtime_context(
    *,
    session_factory,
    user: User,
    tenant_key: str | None,
    settings,
    embedding_backend,
    scope: str,
    post_data: dict[str, Any] | None,
    ai_profile: dict[str, Any],
) -> RuntimeContext:
    return RuntimeContext(
        session_factory=session_factory,
        user_id=user.id,
        user=user,
        tenant_key=tenant_key,
        settings=settings,
        embedding_backend=embedding_backend,
        scope=scope,
        post_data=post_data,
        ai_profile=ai_profile,
    )


async def load_run_history(
    session: AsyncSession,
    run: AgentRun,
    user: User,
) -> list[Mapping[str, Any]]:
    """Load prior chat turns for an agent run (agent-runtime-sprints §2.1).

    Reuses the same server-side history sources as the legacy reply path
    (`reply_orchestrator.load_reply_context`): `GlobalChat.data.history` for
    global scope, the matching entry in `post.data["chats"]` for post scope.
    Missing/unowned chats resolve to an empty history rather than failing the
    run — memory is a quality improvement, not a hard dependency.
    """
    from app.services.ai.reply_orchestrator import _load_owned_post_data

    if run.scope == "post" and run.post_id:
        post_data = await _load_owned_post_data(session, user.id, run.post_id)
        if post_data is None:
            return []
        chats = [c for c in (post_data.get("chats") or []) if isinstance(c, Mapping)]
        if not chats:
            return []
        chat = None
        # post_chat_id is authoritative (mirrors AiReplyRequest.post_chat_id).
        # chat_id is a fallback for runs created before that column existed.
        target_id = run.post_chat_id or run.chat_id
        if target_id:
            chat = next((c for c in chats if str(c.get("id")) == target_id), None)
        if chat is None:
            chat = chats[-1]
        return list(chat.get("history") or [])

    if run.chat_id:
        try:
            chat = await get_owned_chat(session, user.id, run.chat_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise
        return list(chat.data.get("history") or [])

    return []


async def rebuild_runtime_context_for_run(
    session: AsyncSession,
    run: AgentRun,
    user_text: str = "",
) -> RuntimeContext:
    """Reconstruct the full RuntimeContext for a persisted run.

    Used by the initial executor and, crucially, by HITL resume — the resume
    cfg must carry runtime_context or any research/answer node reached after the
    interrupt raises KeyError on config["configurable"]["runtime_context"]
    (agent-runtime-sprints §1.5). Single source of truth for context assembly so
    the two paths cannot drift.

    `user_text` is the current turn's question, used only to exclude a
    duplicate trailing history entry when building `dialog_context`
    (agent-runtime-sprints §2.1). Resume calls omit it — there is no new
    question on resume, and passing "" simply includes all recent history.
    """
    from app.core.config import get_settings
    from app.db.session import async_session_factory
    from app.services.ai.embeddings import resolve_embedding_backend
    from app.services.ai.rag_dialog_ledger import (
        chat_ledger_key,
        ledger_chat_id,
        load_ledger,
    )
    from app.services.ai.rag_query import build_planner_dialog_context
    from app.services.ai.rag_reasoner import resolve_rag_reasoner_llm
    from app.services.ai.orchestrator import resolve_answer_llm
    from app.services.agent.runtime.turn_contract import build_turn_contract

    settings = get_settings()
    # A HITL resume is a continuation of the interrupted run, not a new turn.
    # Prefer the durable checkpoint snapshot when no new user text is supplied;
    # rebuilding a contract from the latest dialog could otherwise change the
    # target revision and silently drop evidence requirements.
    persisted_snapshot = dict(run.snapshot or {})
    persisted_user_text = str(persisted_snapshot.get("user_text") or "").strip()
    effective_user_text = user_text or persisted_user_text
    persisted_contract = persisted_snapshot.get("turn_contract")
    user = await session.scalar(select(User).where(User.id == run.user_id))
    if user is None:
        raise RuntimeError("agent_run_user_not_found")
    profile = await session.get(Profile, user.id)
    ai_profile = dict(profile.ai or {}) if profile else {}
    channel_profile = dict(profile.channel) if profile and profile.channel else None
    telegram_profile = dict(profile.telegram) if profile and profile.telegram else None
    reasoner = resolve_rag_reasoner_llm(user, ai_profile, settings)
    answer_llm = resolve_answer_llm(user, ai_profile, settings)
    if reasoner:
        import logging as _logging
        _logging.getLogger(__name__).info(
            "Agent planner model resolved: provider=%s model=%s run_id=%s",
            getattr(reasoner[0], "name", "?"),
            reasoner[1],
            run.id,
        )
    if answer_llm:
        import logging as _logging
        _logging.getLogger(__name__).info(
            "Agent answer model resolved: provider=%s model=%s run_id=%s",
            getattr(answer_llm[0], "name", "?"),
            answer_llm[1],
            run.id,
        )
    post_data = None
    if run.post_id:
        # Resolve by UUID PK OR legacy JSONB data['id'] — the same canonical
        # resolver the mutation executor (_edit_post) uses. run.post_id can be a
        # legacy numeric id like "3" (older posts store data['id'] as a small
        # int while the PK is a UUID); the previous uuid.UUID(run.post_id)-only
        # lookup raised ValueError and left post_data=None, so edit_post silently
        # produced an empty payload and no editable proposal ever reached the
        # user (chat 61af02c7, post data.id="3").
        try:
            post = await get_owned_post(session, user.id, run.post_id)
            post_data = dict(post.data)
        except HTTPException:
            post_data = None
    from app.services.ai.chat_history import extract_last_proposed_edit

    history = await load_run_history(session, run, user)
    last_proposed_post_html = extract_last_proposed_edit(history) if history else None
    recent_note_row = await session.scalar(
        select(GlobalNote)
        .where(GlobalNote.user_id == user.id)
        .order_by(GlobalNote.created_at.desc())
        .limit(1)
    )
    recent_note: dict[str, Any] | None = None
    if recent_note_row is not None:
        recent_note = {
            **dict(recent_note_row.data or {}),
            "id": str(recent_note_row.id),
            "created_at": recent_note_row.created_at.isoformat(),
        }
    ledger_key = chat_ledger_key(
        scope=run.scope,
        chat_id=ledger_chat_id(
            scope=run.scope,
            chat_id=run.chat_id,
            post_chat_id=run.post_chat_id,
        ),
        post_id=str((post_data or {}).get("id") or run.post_id or "") or None,
    )
    dialog_ledger = await load_ledger(
        session,
        user_id=user.id,
        chat_key=ledger_key,
    )
    message_manifests: tuple[Mapping[str, Any], ...] = ()
    if getattr(settings, "dialog_message_context_manifest_v1", True):
        from app.services.agent.runtime.message_context import load_recent_message_contexts

        message_manifests = await load_recent_message_contexts(
            session,
            user_id=user.id,
            ledger_key=ledger_key,
        )
    dialog_context = build_planner_dialog_context(
        effective_user_text,
        history,
        message_manifests=(
            message_manifests
            if getattr(settings, "agent_dialog_context_v2", True)
            else ()
        ),
    ) if history or message_manifests else ""
    known_refs: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for manifest in message_manifests:
        for raw in manifest.get("context_refs") or ():
            if not isinstance(raw, Mapping):
                continue
            ref = str(raw.get("ref") or "").strip()
            role = str(raw.get("role") or "")
            if not ref or role not in {"used_context", "claim_support"} or ref in seen_refs:
                continue
            seen_refs.add(ref)
            known_refs.append({
                "ref": ref,
                "kind": str(raw.get("kind") or ""),
                "revision": raw.get("revision"),
                "title": str(raw.get("title") or "") or None,
            })
            if len(known_refs) >= 8:
                break
        if len(known_refs) >= 8:
            break
    if history:
        # Preserve a bounded summary for turns outside the verbatim window.
        from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm
        from app.services.ai.rolling_summary import rolling_summary_for_assembly

        valid_pairs = filter_alternating_roles(linearize_for_llm(history))
        older_summary = rolling_summary_for_assembly({}, valid_pairs)
        if older_summary:
            dialog_context = (
                f"Ранее в диалоге: {older_summary}\n\n{dialog_context}"
                if dialog_context
                else f"Ранее в диалоге: {older_summary}"
            )
    if len(dialog_context) > 4000:
        dialog_context = dialog_context[-4000:]
    legacy_resolver_enabled = bool(
        getattr(settings, "agent_referent_resolution_legacy", False)
        and getattr(settings, "semantic_referent_resolution_v1", True)
    )
    prior_contract = next(
        (dict(turn.turn_contract) for turn in reversed(dialog_ledger) if turn.turn_contract),
        None,
    )
    turn_contract = build_turn_contract(
        user_text=effective_user_text,
        history=history,
        scope=run.scope,
        recent_note=recent_note,
        dialog_ledger=dialog_ledger if legacy_resolver_enabled else (),
        open_post=post_data,
        prior_contract=prior_contract,
        message_manifests=message_manifests if legacy_resolver_enabled else (),
        semantic_referent_enabled=legacy_resolver_enabled,
        v2_enabled=settings.agent_turn_contract_v2_enabled,
        batch_enabled=settings.agent_batch_path_v1_enabled,
    )
    if not user_text and isinstance(persisted_contract, dict) and persisted_contract:
        turn_contract = dict(persisted_contract)
    return RuntimeContext(
        session_factory=async_session_factory,
        user_id=user.id,
        user=user,
        tenant_key=None,
        settings=settings,
        embedding_backend=resolve_embedding_backend(user, ai_profile, settings),
        scope=run.scope,
        post_data=post_data,
        ai_profile=ai_profile,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        reasoner_spec=reasoner[0] if reasoner else None,
        reasoner_model=reasoner[1] if reasoner else "",
        reasoner_api_key=reasoner[2] if reasoner else "",
        planner_spec=reasoner[0] if reasoner else None,
        planner_model=reasoner[1] if reasoner else "",
        planner_api_key=reasoner[2] if reasoner else "",
        answer_spec=answer_llm[0] if answer_llm else None,
        answer_model=answer_llm[1] if answer_llm else "",
        answer_api_key=answer_llm[2] if answer_llm else "",
        dialog_context=dialog_context,
        known_context_refs=tuple(known_refs),
        turn_contract=turn_contract,
        dialog_ledger=dialog_ledger,
        ledger_key=ledger_key,
        last_proposed_post_html=last_proposed_post_html,
        user_timezone=run.timezone,
    )
