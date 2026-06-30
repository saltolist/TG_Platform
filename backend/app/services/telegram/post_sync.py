"""Incremental DB sync for Telegram-sourced posts (live-sync)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Post, Profile
from app.db.seed_ids import user_scoped_entity_uuid


def _parse_message_id(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _find_telegram_post(
    session: AsyncSession, user_id: UUID, telegram_message_id: str
) -> Post | None:
    result = await session.execute(
        select(Post).where(
            Post.user_id == user_id,
            Post.data["telegramMessageId"].astext == telegram_message_id,
        )
    )
    return result.scalar_one_or_none()


async def _shift_positions(session: AsyncSession, user_id: UUID, delta: int) -> None:
    result = await session.execute(select(Post).where(Post.user_id == user_id))
    for post in result.scalars():
        post.position += delta


async def _recompact_positions(session: AsyncSession, user_id: UUID) -> None:
    result = await session.execute(
        select(Post).where(Post.user_id == user_id).order_by(Post.position)
    )
    for index, post in enumerate(result.scalars()):
        post.position = index


async def touch_telegram_profile(
    session: AsyncSession,
    profile: Profile,
    *,
    last_message_id: str | int | None = None,
    sync_status: str = "listening",
    sync_error: str = "",
) -> None:
    telegram = dict(profile.telegram or {})
    if last_message_id is not None:
        seen = _parse_message_id(last_message_id)
        stored = _parse_message_id(telegram.get("lastTelegramMessageId"))
        telegram["lastTelegramMessageId"] = str(max(seen, stored))
    telegram["lastSync"] = datetime.now(timezone.utc).isoformat()
    telegram["syncStatus"] = sync_status
    telegram["syncError"] = sync_error[:500] if sync_error else ""
    profile.telegram = telegram


async def upsert_telegram_post(
    session: AsyncSession, user_id: UUID, post_data: dict[str, Any]
) -> None:
    profile = await session.get(Profile, user_id)
    if profile is None:
        return

    msg_id = str(post_data.get("telegramMessageId") or "")
    if not msg_id:
        return

    existing = await _find_telegram_post(session, user_id, msg_id)
    if existing is not None:
        existing.data = post_data
    else:
        await _shift_positions(session, user_id, 1)
        session.add(
            Post(
                id=user_scoped_entity_uuid(user_id, "post", f"tg-{msg_id}"),
                user_id=user_id,
                position=0,
                data=post_data,
            )
        )
        telegram = dict(profile.telegram or {})
        telegram["importedPosts"] = int(telegram.get("importedPosts") or 0) + 1
        profile.telegram = telegram

    await touch_telegram_profile(session, profile, last_message_id=msg_id)


async def update_telegram_post(
    session: AsyncSession, user_id: UUID, post_data: dict[str, Any]
) -> None:
    profile = await session.get(Profile, user_id)
    if profile is None:
        return

    msg_id = str(post_data.get("telegramMessageId") or "")
    if not msg_id:
        return

    existing = await _find_telegram_post(session, user_id, msg_id)
    if existing is None:
        await upsert_telegram_post(session, user_id, post_data)
        return

    merged = {**existing.data, **post_data}
    new_media = post_data.get("media")
    old_media = existing.data.get("media")
    if not new_media and old_media:
        merged["media"] = old_media
    existing.data = merged
    await touch_telegram_profile(session, profile, last_message_id=msg_id)


async def delete_telegram_post(
    session: AsyncSession, user_id: UUID, telegram_message_id: str
) -> None:
    profile = await session.get(Profile, user_id)
    if profile is None:
        return

    existing = await _find_telegram_post(session, user_id, telegram_message_id)
    if existing is None:
        return

    await session.delete(existing)
    await _recompact_positions(session, user_id)

    telegram = dict(profile.telegram or {})
    count = int(telegram.get("importedPosts") or 0)
    telegram["importedPosts"] = max(0, count - 1)
    profile.telegram = telegram
    await touch_telegram_profile(session, profile, last_message_id=telegram_message_id)


async def set_sync_error(user_id: UUID, error: str, session_factory: Any) -> None:
    async with session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return
        await touch_telegram_profile(
            session, profile, sync_status="error", sync_error=error
        )
        await session.commit()
