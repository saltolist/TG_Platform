from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resources import PostIn


class ReorderRequest(BaseModel):
    posts: list[dict[str, Any]]


class MessageRequest(BaseModel):
    text: str


class AiReplyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    scope: Literal["global", "post"] = "global"
    llm_id: str | None = Field(default=None, validation_alias="llmId")


class AiReplyResponse(BaseModel):
    text: str


__all__ = [
    "PostIn",
    "ReorderRequest",
    "MessageRequest",
    "AiReplyRequest",
    "AiReplyResponse",
]
