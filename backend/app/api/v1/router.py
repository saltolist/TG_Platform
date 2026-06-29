from fastapi import APIRouter

from app.api.v1 import ai, analytics, auth, chats, dev_context_log, notes, overlay, posts, profile

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(posts.router)
api_router.include_router(chats.router)
api_router.include_router(notes.router)
api_router.include_router(overlay.router)
api_router.include_router(profile.router)
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
api_router.include_router(dev_context_log.router)


@api_router.get("/health/", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
