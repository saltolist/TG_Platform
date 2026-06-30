"""Pydantic mirrors of frontend Zod schemas (shared/api/schemas)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ChatMessageContract(ApiModel):
    role: Literal["user", "ai"]
    text: str | None = None


class GlobalChatContract(ApiModel):
    id: str
    title: str
    preview: str
    date: str
    history: list[ChatMessageContract]
    kind: Literal["default", "omnichannel"] | None = None


class GlobalNoteContract(ApiModel):
    id: str
    title: str
    ai: bool
    date: str
    body: str


class PostContract(ApiModel):
    id: str
    status: Literal["published", "scheduled", "draft"]
    rubric: str | None
    text: str
    notes: list[Any] = Field(default_factory=list)
    chats: list[Any] = Field(default_factory=list)


class AuthSessionContract(BaseModel):
    token: str | None = None
    accountId: str
    email: str
    createdAt: str


class AiReplyContract(BaseModel):
    text: str


class ErrorContract(BaseModel):
    error: str


def parse_posts_list(data: object) -> list[PostContract]:
    if not isinstance(data, list):
        raise TypeError("expected list")
    return [PostContract.model_validate(item) for item in data]


def parse_global_chats_list(data: object) -> list[GlobalChatContract]:
    if not isinstance(data, list):
        raise TypeError("expected list")
    return [GlobalChatContract.model_validate(item) for item in data]


def parse_global_notes_list(data: object) -> list[GlobalNoteContract]:
    if not isinstance(data, list):
        raise TypeError("expected list")
    return [GlobalNoteContract.model_validate(item) for item in data]


def parse_auth_session(data: object) -> AuthSessionContract:
    session = AuthSessionContract.model_validate(data)
    UUID(session.accountId)
    return session


def parse_ai_reply(data: object) -> AiReplyContract:
    return AiReplyContract.model_validate(data)
