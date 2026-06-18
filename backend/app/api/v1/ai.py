from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.db.models import Profile
from app.schemas.requests import AiReplyRequest
from app.services.ai import resolve_model_api_key
from app.services.ai.keys import AccountMode, KeyResolution, KeySource, get_account_mode
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
        if mode == AccountMode.REAL:
            return KeyResolution(api_key=None, source=KeySource.NONE, account_mode=mode)
        return KeyResolution(api_key=None, source=KeySource.NONE, account_mode=mode)
    return resolve_model_api_key(model, user, settings)


@router.post("/reply/")
async def ai_reply(
    payload: AiReplyRequest,
    user: CurrentUser,
    session: DbSession,
) -> StreamingResponse:
    profile = await session.get(Profile, user.id)
    ai_profile = profile.ai if profile and profile.ai else {}
    resolution = _resolve_reply_key(user, ai_profile, payload.llm_id)

    if resolution.unavailable:
        raise HTTPException(status_code=422, detail="AI недоступен: укажите API ключ модели")

    # Step 3.1: SSE wiring with stub stream. Real LLM arrives in step 3.2.
    return StreamingResponse(
        stream_stub_reply(payload.text, scope=payload.scope),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
