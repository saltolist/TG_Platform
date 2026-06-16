from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.resources import PostIn


class ReorderRequest(BaseModel):
    posts: list[dict[str, Any]]


class MessageRequest(BaseModel):
    text: str


class AiReplyRequest(BaseModel):
    text: str
    scope: Literal["global", "post"] = "global"


class AiReplyResponse(BaseModel):
    text: str


__all__ = [
    "PostIn",
    "ReorderRequest",
    "MessageRequest",
    "AiReplyRequest",
    "AiReplyResponse",
]
