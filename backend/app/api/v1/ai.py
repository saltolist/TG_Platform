import uuid
from collections.abc import AsyncIterator
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import Profile
from app.db.resolve import get_owned_chat, get_owned_post
from app.schemas.requests import AiReplyRequest
from app.services.ai import resolve_model_api_key
from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint
from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_meta import refresh_context_meta_after_reply, persist_chat_meta
from app.services.ai.keys import KeyResolution, KeySource, get_account_mode
from app.services.ai.llm import stream_llm_sse
from app.services.ai.orchestrator import resolve_orchestrator_llm
from app.services.ai.providers import get_provider_spec
from app.services.ai.sse import format_sse_meta, parse_sse_text_chunk, stream_stub_reply

router = APIRouter(prefix="/ai", tags=["AI"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_CHAT_META_KEYS = (
    "rolling_summary",
    "rolling_summary_idx",
    "rolling_summary_profile",
)


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
    if override_api_key and override_api_key.strip():
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


def _extract_chat_meta(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    return {key: data[key] for key in _CHAT_META_KEYS if key in data}


def _valid_pairs_with_assistant_reply(
    history: list[Mapping[str, Any]] | None,
    user_text: str,
    assistant_text: str,
) -> list[tuple[str, str]]:
    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)

    trimmed_user_text = user_text.strip()
    if trimmed_user_text:
        if not valid_pairs or valid_pairs[-1][0] != "user":
            valid_pairs.append(("user", trimmed_user_text))
        elif valid_pairs[-1][1] != trimmed_user_text:
            valid_pairs.append(("user", trimmed_user_text))

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
    session: DbSession,
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


async def _load_reply_context(
    payload: AiReplyRequest,
    user: CurrentUser,
    session: DbSession,
) -> tuple[list[Mapping[str, Any]] | None, Mapping[str, Any] | None, dict[str, Any]]:
    history = payload.history
    post_data: Mapping[str, Any] | None = None
    chat_meta: dict[str, Any] = {}

    if payload.scope == "post" and payload.post_id:
        post_data = await _load_owned_post_data(session, user.id, payload.post_id)
        if history is None and payload.post_chat_id and post_data is not None:
            for chat in post_data.get("chats") or []:
                if not isinstance(chat, Mapping):
                    continue
                if str(chat.get("id")) == payload.post_chat_id:
                    history = list(chat.get("history") or [])
                    chat_meta = _extract_chat_meta(chat)
                    break
    elif history is None and payload.chat_id:
        try:
            chat = await get_owned_chat(session, user.id, payload.chat_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            history = []
        else:
            history = list(chat.data.get("history") or [])
            chat_meta = _extract_chat_meta(chat.data)

    if isinstance(payload.chat_meta, Mapping):
        chat_meta = {**chat_meta, **dict(payload.chat_meta)}

    return history, post_data, chat_meta


async def _finalize_context_meta(
    *,
    session: DbSession,
    user: CurrentUser,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
    post_data: Mapping[str, Any] | None,
    chat_meta: dict[str, Any],
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
    assistant_text: str,
    ai_profile: dict[str, Any],
) -> dict[str, Any]:
    post = post_data if payload.scope == "post" else None
    current_bundle = build_summary_bundle(
        channel_profile,
        telegram=telegram_profile,
        post=post,
    )
    fingerprint = bundle_fingerprint(channel_profile, post=post)
    valid_pairs = _valid_pairs_with_assistant_reply(history, payload.text, assistant_text)

    summary_llm = resolve_orchestrator_llm(user, ai_profile)

    updated_meta = await refresh_context_meta_after_reply(
        chat_meta,
        valid_pairs=valid_pairs,
        current_bundle=current_bundle,
        current_fingerprint=fingerprint,
        llm=summary_llm,
    )
    await persist_chat_meta(session, user.id, payload, updated_meta)
    await session.commit()
    return updated_meta


async def _stream_reply_with_meta(
    *,
    session: DbSession,
    user: CurrentUser,
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
) -> AsyncIterator[str]:
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
    updated_meta = await _finalize_context_meta(
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
    )
    yield format_sse_meta(updated_meta)


async def _stream_stub_with_meta(
    *,
    session: DbSession,
    user: CurrentUser,
    payload: AiReplyRequest,
    history: list[Mapping[str, Any]] | None,
    post_data: Mapping[str, Any] | None,
    chat_meta: dict[str, Any],
    channel_profile: Mapping[str, Any],
    telegram_profile: Mapping[str, Any],
    ai_profile: dict[str, Any],
) -> AsyncIterator[str]:
    accumulated: list[str] = []
    async for event in stream_stub_reply(payload.text, scope=payload.scope):
        chunk = parse_sse_text_chunk(event)
        if chunk:
            accumulated.append(chunk)
        yield event

    assistant_text = "".join(accumulated)
    updated_meta = await _finalize_context_meta(
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
    )
    yield format_sse_meta(updated_meta)


@router.post("/reply/")
async def ai_reply(
    payload: AiReplyRequest,
    user: CurrentUser,
    session: DbSession,
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

    history, post_data, chat_meta = await _load_reply_context(payload, user, session)

    if resolution.use_stub:
        return StreamingResponse(
            _stream_stub_with_meta(
                session=session,
                user=user,
                payload=payload,
                history=history,
                post_data=post_data,
                chat_meta=chat_meta,
                channel_profile=channel_profile,
                telegram_profile=telegram_profile,
                ai_profile=ai_profile,
            ),
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
    assert spec is not None and resolution.api_key

    messages = assemble_reply_messages(
        ai_profile=ai_profile,
        user_text=payload.text,
        scope=payload.scope,
        history=history,
        channel_profile=channel_profile,
        telegram_profile=telegram_profile,
        post_data=post_data,
        chat_meta=chat_meta,
    )
    return StreamingResponse(
        _stream_reply_with_meta(
            session=session,
            user=user,
            payload=payload,
            history=history,
            post_data=post_data,
            chat_meta=chat_meta,
            channel_profile=channel_profile,
            telegram_profile=telegram_profile,
            ai_profile=ai_profile,
            messages=messages,
            spec=spec,
            model_id=model_id,
            api_key=resolution.api_key,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
