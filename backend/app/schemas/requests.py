from typing import Any, Literal, Optional

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
    chat_id: str | None = Field(default=None, validation_alias="chatId")
    post_id: str | None = Field(default=None, validation_alias="postId")
    post_chat_id: str | None = Field(default=None, validation_alias="postChatId")
    history: list[dict[str, Any]] | None = None
    chat_meta: dict[str, Any] | None = Field(default=None, validation_alias="chatMeta")
    llm_id: str | None = Field(default=None, validation_alias="llmId")
    api_key: str | None = Field(default=None, validation_alias="apiKey")
    provider: str | None = None
    llm_model: str | None = Field(default=None, validation_alias="model")
    # Web search target (optional)
    web_id: str | None = Field(default=None, validation_alias="webId")
    web_provider: str | None = Field(default=None, validation_alias="webProvider")
    web_model: str | None = Field(default=None, validation_alias="webModel")
    web_api_key: str | None = Field(default=None, validation_alias="webApiKey")


class AiReplyResponse(BaseModel):
    text: str


class RevealAiModelApiKeyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: str = Field(validation_alias="modelId")
    field: str


class RevealAiModelApiKeyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key: str = Field(serialization_alias="apiKey")


class RevealTelegramSecretRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    field: str


class RevealTelegramSecretResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: str


__all__ = [
    "PostIn",
    "ReorderRequest",
    "MessageRequest",
    "AiReplyRequest",
    "AiReplyResponse",
    "RevealAiModelApiKeyRequest",
    "RevealAiModelApiKeyResponse",
    "RevealTelegramSecretRequest",
    "RevealTelegramSecretResponse",
]
