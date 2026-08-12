"""AI reply endpoint (Phase 2, step 3).

HTTP transport only: routing, auth, model resolution, key validation.
All orchestration logic lives in app.services.ai.reply_orchestrator.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, TenantKey
from app.db.models import Profile
from app.schemas.requests import AiReplyRequest
from app.services.ai import resolve_model_api_key
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_log import get_chat_filter, should_log_llm_context
from app.services.ai.embeddings import resolve_embedding_backend
from app.services.ai.keys import KeyResolution, KeySource, get_account_mode
from app.services.ai.providers import get_provider_spec, get_web_search_spec
from app.services.ai.web_search import call_perplexity_search
from app.services.ai.providers import WebSearchPath
from app.services.ai.note_citations import NoteCite
from app.services.ai.reply_pipeline_log import begin_reply_pipeline_trace, trace_step
from app.services.ai.rag_query import retrieve_rag_for_reply
from app.services.ai.rag_reasoner import resolve_rag_reasoner_llm
from app.services.ai.intent_router import classify_intent, parse_period
from app.services.ai.rag_tools import build_post_analytics_context
from app.services.ai.byok_profile import MASKED_VALUE, is_api_key_preview
from app.services.ai.reply_orchestrator import (
    ReplyContext,
    load_reply_context,
    prepare_summary_catalog,
    stream_reply_with_meta,
    stream_stub_with_meta,
)

router = APIRouter(prefix="/ai", tags=["AI"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _pick_llm_model(ai_profile: dict[str, Any], llm_id: str | None) -> dict[str, Any] | None:
    models = ai_profile.get("llmModels") or []
    if llm_id:
        for model in models:
            if model.get("id") == llm_id:
                return model
        for model in models:
            if model.get("active"):
                return model
        return models[0] if models else None
    for model in models:
        if model.get("active"):
            return model
    return models[0] if models else None


def _pick_web_model(ai_profile: dict[str, Any], web_id: str | None) -> dict[str, Any] | None:
    models = ai_profile.get("webSearchModels") or []
    if web_id:
        for model in models:
            if model.get("id") == web_id:
                return model
    for model in models:
        if model.get("active"):
            return model
    return models[0] if models else None


def _resolve_web_model_for_reply(
    ai_profile: dict[str, Any],
    web_id: str | None,
    provider: str | None,
    model_name: str | None,
) -> dict[str, Any] | None:
    """Resolve web search model from Postgres profile, with client overlay overrides."""
    profile_model = _pick_web_model(ai_profile, web_id)
    provider_name = (provider or "").strip()
    web_model = (model_name or "").strip()

    if provider_name and web_model:
        base = dict(profile_model or {})
        return {
            **base,
            "id": web_id or base.get("id", "client"),
            "provider": provider_name,
            "model": web_model,
            "active": True,
        }

    return profile_model


def _resolve_llm_model_for_reply(
    ai_profile: dict[str, Any],
    llm_id: str | None,
    provider: str | None,
    model_name: str | None,
) -> dict[str, Any] | None:
    """Resolve model from Postgres profile, with client overlay overrides."""
    profile_model = _pick_llm_model(ai_profile, llm_id)
    provider_name = (provider or "").strip()
    llm_model = (model_name or "").strip()

    if provider_name and llm_model:
        base = dict(profile_model or {})
        return {
            **base,
            "id": llm_id or base.get("id", "client"),
            "provider": provider_name,
            "model": llm_model,
            "active": True,
        }

    return profile_model


def _resolve_reply_key(
    user: CurrentUser,
    model: dict[str, Any] | None,
    override_api_key: str | None = None,
) -> KeyResolution:
    settings = get_settings()
    if model is None:
        mode = get_account_mode(user)
        return KeyResolution(api_key=None, source=KeySource.NONE, account_mode=mode)
    if (
        override_api_key
        and override_api_key.strip()
        and override_api_key.strip() != MASKED_VALUE
        and not is_api_key_preview(override_api_key.strip())
    ):
        model = {**model, "apiKey": override_api_key.strip()}
    return resolve_model_api_key(model, user, settings)


def _validate_model_for_llm(model: dict[str, Any]) -> tuple[str, str]:
    provider_name = str(model.get("provider", "")).strip()
    model_id = str(model.get("model", "")).strip()
    if not provider_name or not model_id:
        raise HTTPException(
            status_code=422,
            detail="AI недоступен: укажите провайдера и модель в профиле",
        )
    if get_provider_spec(provider_name) is None:
        raise HTTPException(
            status_code=422,
            detail=f"Провайдер «{provider_name}» не поддерживается",
        )
    return provider_name, model_id


@router.post("/reply/")
async def ai_reply(
    payload: AiReplyRequest,
    user: CurrentUser,
    session: DbSession,
    tenant_key: TenantKey,
) -> StreamingResponse:
    profile = await session.get(Profile, user.id)
    ai_profile = profile.ai if profile and profile.ai else {}
    channel_profile = profile.channel if profile and profile.channel else {}
    telegram_profile = profile.telegram if profile and profile.telegram else {}

    model = _resolve_llm_model_for_reply(
        ai_profile,
        payload.llm_id,
        payload.provider,
        payload.llm_model,
    )
    resolution = _resolve_reply_key(user, model, payload.api_key)

    if resolution.unavailable:
        raise HTTPException(status_code=422, detail="AI недоступен: укажите API ключ модели")

    history, post_data, chat_meta = await load_reply_context(payload, user, session)

    summary_catalog = await prepare_summary_catalog(
        session=session,
        profile=profile,
        payload=payload,
        post_data=post_data,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
    )

    ctx = ReplyContext(
        session=session,
        user=user,
        payload=payload,
        ai_profile=ai_profile,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        history=history,
        post_data=post_data,
        chat_meta=chat_meta,
        summary_catalog=summary_catalog,
    )

    if resolution.use_stub:
        if model is not None:
            ctx.model_profile_id = str(model.get("id") or "stub")
            ctx.provider_name = str(model.get("provider") or "Stub").strip()
            ctx.model_id = str(model.get("model") or "stub").strip()
        else:
            ctx.model_profile_id = "stub"
            ctx.provider_name = "Stub"
            ctx.model_id = "stub"
        ctx.is_stub = True
        return StreamingResponse(
            stream_stub_with_meta(ctx),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    if model is None:
        raise HTTPException(
            status_code=422,
            detail="AI недоступен: добавьте LLM модель в профиль",
        )

    provider_name, model_id = _validate_model_for_llm(model)
    spec = get_provider_spec(provider_name)
    if spec is None or not resolution.api_key:
        raise HTTPException(status_code=422, detail="AI недоступен: не удалось определить провайдер или API ключ")

    settings = get_settings()
    log_context = should_log_llm_context(
        enabled=settings.ai_context_log,
        chat_filter=get_chat_filter(),
        scope=payload.scope,
        chat_id=payload.chat_id,
        post_id=payload.post_id,
        post_chat_id=payload.post_chat_id,
    )

    ctx.spec = spec
    ctx.model_profile_id = str(model.get("id") or "client")
    ctx.model_id = model_id
    ctx.api_key = resolution.api_key
    ctx.provider_name = provider_name
    ctx.is_stub = False
    ctx.log_context = log_context
    ctx.context_trace_enabled = settings.ai_context_log

    begin_reply_pipeline_trace(
        enabled=settings.ai_context_log,
        chat_filter=get_chat_filter(),
        scope=payload.scope,
        chat_id=payload.chat_id,
        post_id=payload.post_id,
        post_chat_id=payload.post_chat_id,
        user_text=payload.text,
        post_data=post_data,
        rag_enabled=settings.rag_enabled,
        rag_settings={
            "rag_mode": settings.rag_mode,
            "rag_l0_enabled": settings.rag_l0_enabled,
            "rag_tier_b_enabled": settings.rag_tier_b_enabled,
            "rag_top_k": settings.rag_top_k,
            "rag_min_similarity": settings.rag_min_similarity,
            "rag_query_rewrite_on_miss": settings.rag_query_rewrite_on_miss,
            "ai_context_stamps": settings.ai_context_stamps,
        },
    )

    # Web search resolution (optional, from request)
    if payload.web_provider and payload.web_model:
        web_spec = get_web_search_spec(payload.web_provider, payload.web_model)
        if web_spec is not None:
            web_model = _resolve_web_model_for_reply(
                ai_profile,
                payload.web_id,
                payload.web_provider,
                payload.web_model,
            )
            web_resolution = _resolve_reply_key(user, web_model, payload.web_api_key)
            web_key_str = web_resolution.api_key or ""
            if web_key_str:
                ctx.web_spec = web_spec
                ctx.web_model = payload.web_model
                ctx.web_api_key = web_key_str

                # Path C: build query via web reasoner, then search, inject context
                if web_spec.path == WebSearchPath.PERPLEXITY_SEARCH:
                    try:
                        from app.services.ai.web_reasoner import (
                            rewrite_web_query_llm,
                            resolve_web_reasoner_llm,
                        )
                        search_query = payload.text
                        web_reasoner = resolve_web_reasoner_llm(user, ai_profile, settings)
                        if web_reasoner is not None:
                            r_spec, r_model, r_key = web_reasoner
                            search_query = await rewrite_web_query_llm(
                                user_text=payload.text,
                                history=history,
                                spec=r_spec,
                                model=r_model,
                                api_key=r_key,
                            )
                        web_ctx, web_cites = await call_perplexity_search(
                            query=search_query,
                            api_key=web_key_str,
                        )
                        ctx.web_cites = web_cites
                        ctx.web_search_context = web_ctx
                        trace_step(
                            "3. web.search",
                            [
                                f"provider={payload.web_provider}",
                                f"model={payload.web_model}",
                                f"query={search_query!r}",
                                f"context_chars={len(web_ctx)}",
                                f"cites={len(web_cites)}",
                            ],
                        )
                    except Exception as exc:
                        import logging as _log
                        _log.getLogger(__name__).warning("Web search (path C) failed: %s", exc)
            else:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "Web search skipped: no API key for %s / %s",
                    payload.web_provider,
                    payload.web_model,
                )

    # RAG retrieval: only for real LLM (not stub), when RAG_ENABLED=1
    settings = get_settings()
    rag_context: str | None = None
    rag_cites: list[NoteCite] = []
    if settings.rag_enabled:
        try:
            analytics_shortcut = False
            if (
                settings.rag_intent_routing_enabled
                and payload.scope == "post"
                and payload.post_id
            ):
                intent = classify_intent(payload.text, has_post_context=True)
                if intent == "post_analytics":
                    period = parse_period(payload.text)
                    trace_step("3. rag.analytics_shortcut", f"intent=post_analytics period={period}")
                    stale_after: float | None = None
                    if settings.telegram_analytics_snapshot_seconds > 0:
                        from app.services.analytics.channel_metrics import (
                            MISSED_SNAPSHOT_MULTIPLIER,
                        )

                        stale_after = (
                            settings.telegram_analytics_snapshot_seconds
                            * MISSED_SNAPSHOT_MULTIPLIER
                        )
                    rag_context, rag_cites, analytics_error = await build_post_analytics_context(
                        session,
                        user.id,
                        payload.post_id,
                        period,
                        snapshot_stale_after_seconds=stale_after,
                    )
                    if analytics_error:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Post analytics shortcut failed: %s", analytics_error
                        )
                        rag_context, rag_cites = "", []
                    else:
                        analytics_shortcut = True
                        trace_step(
                            "8. rag.result",
                            [
                                "source=post_analytics_shortcut",
                                f"context_chars={len(rag_context)}",
                                f"cites={len(rag_cites)}",
                            ],
                        )

            if not analytics_shortcut:
                embedding_backend = resolve_embedding_backend(user, ai_profile, settings)
                rag_reasoner_llm = resolve_rag_reasoner_llm(user, ai_profile, settings)
                rewrite_spec = rewrite_model = rewrite_api_key = None
                if rag_reasoner_llm is not None:
                    rewrite_spec, rewrite_model, rewrite_api_key = rag_reasoner_llm
                rag_context, rag_cites = await retrieve_rag_for_reply(
                    session=session,
                    user_id=user.id,
                    scope=payload.scope,
                    user_text=payload.text,
                    history=history,
                    embedding_backend=embedding_backend,
                    post_data=post_data,
                    tenant_key=tenant_key,
                    post_id=payload.post_id,
                    top_k=settings.rag_top_k,
                    min_similarity=settings.rag_min_similarity,
                    history_turns=settings.rag_query_history_turns,
                    query_max_chars=settings.rag_query_max_chars,
                    rewrite_on_miss=settings.rag_query_rewrite_on_miss,
                    rewrite_spec=rewrite_spec,
                    rewrite_model=rewrite_model,
                    rewrite_api_key=rewrite_api_key,
                    l0_enabled=settings.rag_l0_enabled,
                    escalate_min_similarity=settings.rag_escalate_min_similarity,
                    escalate_on_miss=settings.rag_escalate_on_miss,
                    tier_b_enabled=settings.rag_tier_b_enabled,
                    rag_mode=settings.rag_mode,
                    rag_agent_max_steps=settings.rag_agent_max_steps,
                    rag_agent_planning_mode=settings.rag_agent_planning_mode,
                    user=user,
                    ai_profile=ai_profile,
                    intent_routing_enabled=settings.rag_intent_routing_enabled,
                    scope_bias=settings.rag_scope_bias,
                    chat_id=payload.chat_id,
                    post_chat_id=payload.post_chat_id,
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("RAG retrieval skipped: %s", exc)
            trace_step("3. rag.error", f"retrieval failed: {exc}")

    ctx.rag_cites = rag_cites

    messages = assemble_reply_messages(
        ai_profile=ai_profile,
        user_text=payload.text,
        scope=payload.scope,
        history=history,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        post_data=post_data,
        chat_meta=chat_meta,
        summary_catalog=summary_catalog,
        log_labels=ctx.log_labels if log_context else None,
        log_stamps=ctx.log_stamps if log_context else None,
        rag_context=rag_context or None,
        web_search_context=ctx.web_search_context or None,
    )

    rag_attached = any(
        "Контекст из базы знаний" in str(message.get("content") or "")
        for message in messages
        if message.get("role") == "user"
    )
    web_attached = any(
        "Результаты веб-поиска" in str(message.get("content") or "")
        for message in messages
        if message.get("role") == "user"
    )
    trace_step(
        "9. prompt.assembly",
        [
            f"messages={len(messages)}",
            f"rag_block_attached={rag_attached}",
            f"web_block_attached={web_attached}",
            f"rag_context_chars={len(rag_context or '')}",
            f"web_context_chars={len(ctx.web_search_context or '')}",
            f"model={provider_name}/{model_id}",
        ],
    )

    return StreamingResponse(
        stream_reply_with_meta(ctx, messages),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
