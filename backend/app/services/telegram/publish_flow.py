"""Publish a draft post to the connected Telegram channel (Phase 3 / Step 4a+4b).

Used directly by ``POST /posts/:id/publish/`` (synchronous, like every other
Telegram flow in this codebase) and by the Celery task that fires when a
``schedule``d post's ``scheduledAt`` is reached (Step 4b).

Idempotent by design: once a post has ``data.telegramMessageId`` set, calling
this again is a no-op that returns the current post data instead of sending a
second message — this is what makes a retried/duplicated Celery task safe.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings, get_settings
from app.db.models import Post, Profile
from app.db.session import async_session_factory
from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity_for_profile
from app.services.telegram.comments_flow import (
    apply_initial_comments_thread_flag,
    comments_enabled,
    probe_comments_thread_for_post,
)
from app.services.telegram.net import (
    TelegramAuthError,
    decrypt_field,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.message_mapping import map_group_to_post, telethon_message_fetchable
from app.services.telegram.text_formatting import post_formatting_entities_from_payload
from app.services.telegram.post_sync import finalize_published_from_telegram, mark_post_published
from app.services.telegram.reconcile_flow import maybe_reconcile_after_rpc
from app.services.telegram.writer_session import open_outbound_telegram_client
from app.services.telegram.sync_pending import telegram_sync_pending

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


async def _send(
    client: Any, entity: Any, text: str, file_paths: list[str], entities: list[Any] | None = None
) -> Any:
    kwargs: dict[str, Any] = {}
    if entities:
        kwargs["formatting_entities"] = entities
    if not file_paths:
        return await client.send_message(entity, text, **kwargs)
    if len(file_paths) == 1:
        return await client.send_file(entity, file_paths[0], caption=text, **kwargs)
    return await client.send_file(entity, file_paths, caption=text, **kwargs)


def _extract_message_id(sent: Any) -> str:
    if isinstance(sent, (list, tuple)):
        sent = sent[0] if sent else None
    return str(getattr(sent, "id", "") or "")


def _normalize_sent_messages(sent: Any) -> list[Any]:
    if sent is None:
        return []
    if isinstance(sent, (list, tuple)):
        return [item for item in sent if item is not None]
    return [sent]


async def _fetch_published_messages(
    client: Any, entity: Any, telegram_message_id: str, sent: Any
) -> list[Any]:
    """Prefer a fresh channel fetch so ``date``/views match the live channel post."""
    try:
        msg_id = int(telegram_message_id)
    except ValueError:
        return _normalize_sent_messages(sent)

    for attempt in range(2):
        try:
            fetched = await client.get_messages(entity, ids=msg_id)
        except Exception:
            fetched = None
        if fetched:
            if isinstance(fetched, (list, tuple)):
                messages = [
                    item for item in fetched if telethon_message_fetchable(item)
                ]
            else:
                messages = [fetched] if telethon_message_fetchable(fetched) else []
            if messages and getattr(messages[0], "date", None) is not None:
                return messages
        if attempt == 0:
            await asyncio.sleep(0.4)

    return _normalize_sent_messages(sent)


async def _persist_post_data(user_id: UUID, post_id: UUID, data: dict[str, Any]) -> None:
    async with async_session_factory() as session:
        post = await session.get(Post, post_id)
        if post is None or post.user_id != user_id:
            return
        post.data = data
        flag_modified(post, "data")
        await session.commit()


async def _load_post_data(user_id: UUID, post_id: UUID) -> dict[str, Any]:
    async with async_session_factory() as session:
        post = await session.get(Post, post_id)
        if post is None or post.user_id != user_id:
            return {}
        return dict(post.data)


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

        if profile is None:
            raise TelegramAuthError("Профиль не найден", 400)

        telegram = profile.telegram or {}
        if telegram.get("channelStatus") != "connected":
            raise TelegramAuthError("Сначала подключите канал", 400)
        if telegram.get("authStatus") not in ("authorized", "connected"):
            raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)

        require_api_credentials(telegram, settings)
        if not decrypt_field(str(telegram.get("sessionString") or ""), settings):
            raise TelegramAuthError("Не удалось подготовить публикацию", 400)
        if not str(telegram.get("channelId") or "").strip() and not parse_channel_input(
            str(telegram.get("channel") or "")
        ):
            raise TelegramAuthError("Не удалось подготовить публикацию", 400)

        text = str(data.get("text") or "")
        formatting_entities = post_formatting_entities_from_payload(data)
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

    telegram_payload: dict[str, Any] | None = None
    telegram_message_id = ""
    merged_data: dict[str, Any] = {}

    async with telegram_sync_pending(user_id, post_id):
        async with open_outbound_telegram_client(profile, user_id, settings) as (
            client,
            telegram,
        ):
            entity = await resolve_channel_entity_for_profile(client, telegram, settings)
            sent = await with_timeout(
                _send(client, entity, text, file_paths, formatting_entities), settings
            )
            telegram_message_id = _extract_message_id(sent)
            if not telegram_message_id:
                raise TelegramAuthError(
                    "Telegram не подтвердил публикацию (часто из‑за рассинхрона часов в Docker). "
                    "Попробуйте ещё раз; если не помогает — запустите backend на хосте, не в контейнере.",
                    502,
                )
            messages = await _fetch_published_messages(
                client, entity, telegram_message_id, sent
            )
            telegram_payload = await map_group_to_post(client, messages, user_id, settings)

            async with async_session_factory() as session:
                profile_row = await session.get(Profile, user_id)
                telegram = dict(profile_row.telegram or {}) if profile_row else telegram
                if telegram_payload is not None:
                    merged_data = await finalize_published_from_telegram(
                        session, user_id, post_id, telegram_payload
                    )
                else:
                    merged_data = await mark_post_published(
                        session, user_id, post_id, telegram_message_id
                    )

            probed_data = await probe_comments_thread_for_post(
                client, entity, merged_data, telegram, settings
            )
            if probed_data == merged_data and comments_enabled(telegram):
                probed_data = apply_initial_comments_thread_flag(
                    merged_data, telegram
                )
            if probed_data != merged_data:
                await _persist_post_data(user_id, post_id, probed_data)
                merged_data = probed_data

            comment_fields = {
                key: merged_data[key]
                for key in (
                    "commentsThreadAvailable",
                    "commentsThreadLiveOptimistic",
                    "telegramDiscussionMessageId",
                )
                if key in merged_data
            }

            await maybe_reconcile_after_rpc(
                client,
                entity,
                user_id,
                settings,
                force=True,
                include_new_scan=True,
            )

            fresh = await _load_post_data(user_id, post_id)
            if fresh:
                merged_data = {**fresh, **comment_fields}

            if comment_fields.get("telegramDiscussionMessageId") or comment_fields.get(
                "commentsThreadLiveOptimistic"
            ):
                final_data = merged_data
            else:
                final_data = await probe_comments_thread_for_post(
                    client, entity, merged_data, telegram, settings
                )
                if comments_enabled(telegram) and not final_data.get(
                    "telegramDiscussionMessageId"
                ):
                    final_data = apply_initial_comments_thread_flag(final_data, telegram)
                if final_data != merged_data:
                    await _persist_post_data(user_id, post_id, final_data)
            merged_data = final_data

        return merged_data


__all__ = ["publish_post"]
