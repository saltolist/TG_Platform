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
from app.services.ai.providers import get_provider_spec
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag import format_rag_context, retrieve_top_k
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
    ctx.model_id = model_id
    ctx.api_key = resolution.api_key
    ctx.provider_name = provider_name
    ctx.log_context = log_context

    # RAG retrieval: only for real LLM (not stub), when RAG_ENABLED=1
    settings = get_settings()
    rag_context: str | None = None
    rag_cites: list[NoteCite] = []
    if settings.rag_enabled:
        try:
            embedding_backend = resolve_embedding_backend(user, ai_profile, settings)
            query_vec = await embedding_backend.embed_query(payload.text)
            top_k_results = await retrieve_top_k(
                session=session,
                user_id=user.id,
                scope=payload.scope,
                query_vec=query_vec,
                model_key=embedding_backend.model_key,
                k=settings.rag_top_k,
                min_similarity=settings.rag_min_similarity,
                post_id=payload.post_id,
                tenant_key=tenant_key,
            )
            rag_context, rag_cites = await format_rag_context(
                session=session,
                user_id=user.id,
                results=top_k_results,
                scope=payload.scope,
                post_data=post_data,
                tenant_key=tenant_key,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("RAG retrieval skipped: %s", exc)

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
        rag_context=rag_context or None,
    )
    return StreamingResponse(
        stream_reply_with_meta(ctx, messages),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
