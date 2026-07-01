"""Incremental DB sync for Telegram-sourced posts (live-sync)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

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
    telegram["syncRevision"] = int(telegram.get("syncRevision") or 0) + 1
    telegram["syncStatus"] = sync_status
    telegram["syncError"] = sync_error[:500] if sync_error else ""
    profile.telegram = telegram


async def mark_post_deleted(post: Post) -> None:
    """Soft-delete: keep the row but move the post to ``status: deleted``."""
    data = dict(post.data)
    if data.get("status") == "deleted":
        return
    data["status"] = "deleted"
    data["deletedAt"] = datetime.now(timezone.utc).isoformat()
    post.data = data
    flag_modified(post, "data")


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
        await update_telegram_post(session, user_id, post_data)
        return

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


def _content_unchanged(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """True when *incoming* text/media match *existing* — nothing worth persisting.

    Guards against a live-sync loop: a platform-triggered edit (Step 4c) commits
    the new text to the DB *before* calling Telethon ``edit_message``, so the
    ``MessageEdited`` echo that live-sync receives afterwards carries exactly
    the same content. Skipping the write avoids a spurious ``syncRevision``
    bump (which would otherwise trigger an unnecessary frontend refetch).
    """
    existing_text = str(existing.get("text") or "")
    incoming_text = str(incoming.get("text") or "")
    if existing_text != incoming_text:
        return False
    incoming_media = incoming.get("media")
    if incoming_media and incoming_media != existing.get("media"):
        return False
    return True


def _incoming_telegram_edit_is_stale(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """Drop a live-sync text update that predates the latest platform-side edit.

    Compares Telethon's ``edit_date`` (carried as ``_telegramEditDate``) against
    ``_platformTextEditAt``, set by ``PATCH /posts/:id`` when the user saves a
    text change. Stale ``MessageEdited`` events that were in flight before the
    platform edit no longer roll back the DB row.
    """
    if str(existing.get("text") or "") == str(incoming.get("text") or ""):
        return False

    platform_at_raw = existing.get("_platformTextEditAt")
    if not platform_at_raw:
        return False

    telegram_edit_raw = incoming.get("_telegramEditDate")
    if not telegram_edit_raw:
        # Catch-up / delayed events without edit_date must not roll back a platform save
        # that has not yet been echoed to Telegram.
        return True

    try:
        platform_at = datetime.fromisoformat(str(platform_at_raw))
        telegram_edit = datetime.fromisoformat(str(telegram_edit_raw))
    except ValueError:
        return True
    if platform_at.tzinfo is None:
        platform_at = platform_at.replace(tzinfo=timezone.utc)
    if telegram_edit.tzinfo is None:
        telegram_edit = telegram_edit.replace(tzinfo=timezone.utc)
    return telegram_edit < platform_at


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

    if _content_unchanged(existing.data, post_data):
        return

    if _incoming_telegram_edit_is_stale(existing.data, post_data):
        return

    merged = {**existing.data, **post_data}
    if post_data.get("date"):
        merged["date"] = post_data["date"]
    if merged.get("status") == "published" and merged.get("source") == "telegram":
        merged.pop("created", None)
    new_media = post_data.get("media")
    old_media = existing.data.get("media")
    if not new_media and old_media:
        merged["media"] = old_media
    existing.data = merged
    flag_modified(existing, "data")
    await touch_telegram_profile(session, profile, last_message_id=msg_id)


async def mark_post_published(
    session: AsyncSession, user_id: UUID, post_id: UUID, telegram_message_id: str
) -> dict[str, Any]:
    """Persist the result of a successful platform → Telegram publish (Step 4a/4b)."""
    post = await session.get(Post, post_id)
    if post is None or post.user_id != user_id:
        return {}
    data = dict(post.data)
    data["status"] = "published"
    data["date"] = datetime.now(timezone.utc).isoformat()
    data["telegramMessageId"] = telegram_message_id
    data["source"] = "telegram"
    data.pop("created", None)
    data.pop("_celeryTaskId", None)
    data.pop("publishError", None)
    post.data = data
    flag_modified(post, "data")
    await session.commit()
    return data


async def finalize_published_from_telegram(
    session: AsyncSession,
    user_id: UUID,
    post_id: UUID,
    telegram_payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge a Telethon-mapped channel post into an existing platform draft after publish."""
    post = await session.get(Post, post_id)
    if post is None or post.user_id != user_id:
        return {}

    existing = dict(post.data)
    merged: dict[str, Any] = {
        **telegram_payload,
        "id": existing.get("id") or str(post_id),
        "notes": existing.get("notes") or [],
        "chats": existing.get("chats") or [],
        "comments": telegram_payload.get("comments") or existing.get("comments") or [],
    }
    if telegram_payload.get("date"):
        merged["date"] = telegram_payload["date"]
    merged.pop("created", None)
    merged.pop("_celeryTaskId", None)
    merged.pop("publishError", None)
    post.data = merged
    flag_modified(post, "data")
    await session.commit()
    return merged


async def delete_telegram_post(
    session: AsyncSession, user_id: UUID, telegram_message_id: str
) -> None:
    profile = await session.get(Profile, user_id)
    if profile is None:
        return

    existing = await _find_telegram_post(session, user_id, telegram_message_id)
    if existing is None:
        return

    await mark_post_deleted(existing)
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
