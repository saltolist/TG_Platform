import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import engine
from app.services.ai.context_log import init_chat_filter

logging.basicConfig(level=logging.INFO)
_context_logger = logging.getLogger("tg.ai.context")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic (see scripts/entrypoint.sh and `alembic upgrade head`).
    if settings.ai_context_log:
        init_chat_filter(settings.ai_context_log_chat)
        chat_id = settings.ai_context_log_chat.strip()
        if chat_id:
            _context_logger.info("AI context log ON → chat %s (from env)", chat_id)
        else:
            _context_logger.info(
                "AI context log ON — set chat: ./scripts/ai-log-chat.sh <chat-id>"
            )
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Error"
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Невалидное тело запроса", "details": jsonable_encoder(exc.errors())},
    )


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_v1_prefix)
