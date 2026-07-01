"""Publish a draft post to the connected Telegram channel (Phase 3 / Step 4a+4b).

Used directly by ``POST /posts/:id/publish/`` (synchronous, like every other
Telegram flow in this codebase) and by the Celery task that fires when a
``schedule``d post's ``scheduledAt`` is reached (Step 4b).

Idempotent by design: once a post has ``data.telegramMessageId`` set, calling
this again is a no-op that returns the current post data instead of sending a
second message — this is what makes a retried/duplicated Celery task safe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.db.models import Post, Profile
from app.db.session import async_session_factory
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    TelegramAuthError,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.post_sync import mark_post_published
from app.services.telegram.session_guard import exclusive_telegram_access

_PUBLISHABLE_STATUSES = {"draft", "scheduled"}


def parse_scheduled_at(value: str) -> datetime:
    """Parse an ISO-8601 ``scheduledAt`` string (accepts trailing ``Z``, Python 3.11+)."""
    return datetime.fromisoformat(value)


def _local_media_path(url: Any, user_id: UUID, settings: Settings) -> str | None:
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    filename = url.rsplit("/", 1)[-1]
    if not filename:
        return None
    path = Path(settings.media_storage_root) / str(user_id) / filename
    return str(path) if path.is_file() else None


async def _send(client: Any, entity: Any, text: str, file_paths: list[str]) -> Any:
    if not file_paths:
        return await client.send_message(entity, text)
    if len(file_paths) == 1:
        return await client.send_file(entity, file_paths[0], caption=text)
    return await client.send_file(entity, file_paths, caption=text)


def _extract_message_id(sent: Any) -> str:
    if isinstance(sent, (list, tuple)):
        sent = sent[0] if sent else None
    return str(getattr(sent, "id", "") or "")


async def publish_post(
    user_id: UUID, post_id: UUID, settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()

    async with async_session_factory() as session:
        profile = await session.get(Profile, user_id)
        post = await session.get(Post, post_id)
        if post is None or post.user_id != user_id:
            raise TelegramAuthError("Пост не найден", 404)

        data = dict(post.data)
        if data.get("telegramMessageId"):
            return data  # already published — idempotent no-op (retry-safe)

        if data.get("status") not in _PUBLISHABLE_STATUSES:
            raise TelegramAuthError(
                "Пост уже опубликован или недоступен для публикации", 400
            )

        telegram = profile.telegram if profile is not None else {}
        if telegram.get("channelStatus") != "connected":
            raise TelegramAuthError("Сначала подключите канал", 400)
        if telegram.get("authStatus") not in ("authorized", "connected"):
            raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        parsed = parse_channel_input(str(telegram.get("channel") or ""))
        if not parsed or not session_string:
            raise TelegramAuthError("Не удалось подготовить публикацию", 400)

        text = str(data.get("text") or "")
        media_items = data.get("media") or []
        file_paths = [
            path
            for path in (
                _local_media_path(item.get("url"), user_id, settings)
                for item in media_items
                if isinstance(item, dict)
            )
            if path is not None
        ]
        if not text.strip() and not file_paths:
            raise TelegramAuthError("Пост пуст — нечего публиковать", 400)

    async with exclusive_telegram_access(user_id):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)
            sent = await with_timeout(_send(client, entity, text, file_paths), settings)
        finally:
            await disconnect_safely(client)

    telegram_message_id = _extract_message_id(sent)
    if not telegram_message_id:
        raise TelegramAuthError(
            "Telegram не подтвердил публикацию (часто из‑за рассинхрона часов в Docker). "
            "Попробуйте ещё раз; если не помогает — запустите backend на хосте, не в контейнере.",
            502,
        )
    async with async_session_factory() as session:
        return await mark_post_published(session, user_id, post_id, telegram_message_id)


__all__ = ["publish_post"]
