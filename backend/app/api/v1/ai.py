from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import Profile
from app.schemas.requests import AiReplyRequest
from app.services.ai import resolve_model_api_key
from app.services.ai.keys import AccountMode, KeyResolution, KeySource, get_account_mode
from app.services.ai.llm import build_reply_messages, stream_llm_sse
from app.services.ai.providers import get_provider_spec
from app.services.ai.sse import stream_stub_reply

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


def _resolve_reply_key(
    user: CurrentUser,
    ai_profile: dict[str, Any],
    llm_id: str | None,
) -> KeyResolution:
    settings = get_settings()
    model = _pick_llm_model(ai_profile, llm_id)
    if model is None:
        mode = get_account_mode(user)
        return KeyResolution(api_key=None, source=KeySource.NONE, account_mode=mode)
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
) -> StreamingResponse:
    profile = await session.get(Profile, user.id)
    ai_profile = profile.ai if profile and profile.ai else {}
    model = _pick_llm_model(ai_profile, payload.llm_id)
    resolution = _resolve_reply_key(user, ai_profile, payload.llm_id)

    if resolution.unavailable:
        raise HTTPException(status_code=422, detail="AI недоступен: укажите API ключ модели")

    if resolution.use_stub:
        return StreamingResponse(
            stream_stub_reply(payload.text, scope=payload.scope),
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

    messages = build_reply_messages(ai_profile, payload.text, scope=payload.scope)
    return StreamingResponse(
        stream_llm_sse(
            spec=spec,
            model=model_id,
            api_key=resolution.api_key,
            messages=messages,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
