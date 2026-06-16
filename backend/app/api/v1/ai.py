from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.requests import AiReplyRequest, AiReplyResponse
from app.services.ai import generate_reply

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post("/reply/", response_model=AiReplyResponse)
async def ai_reply(payload: AiReplyRequest, user: CurrentUser) -> AiReplyResponse:
    return AiReplyResponse(text=generate_reply(payload.text, scope=payload.scope))
