"""Incremental DB sync for Telegram-sourced posts (live-sync)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Post, Profile
from app.db.seed_ids import user_scoped_entity_uuid


def _parse_message_id(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def load_linked_posts_for_reconcile(
    session: AsyncSession, user_id: UUID, limit: int
) -> list[Post]:
    """Published/linked posts with a Telegram message id (excludes soft-deleted)."""
    msg_id_expr = Post.data["telegramMessageId"].astext
    result = await session.execute(
        select(Post)
        .where(
            Post.user_id == user_id,
            msg_id_expr != "",
            msg_id_expr.isnot(None),
            Post.data["status"].astext != "deleted",
        )
        .order_by(cast(msg_id_expr, Integer).desc())
        .limit(limit)
    )
    return list(result.scalars())


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
    comment_only: bool = False,
    comment_revision_delta: int = 1,
    metrics_only: bool = False,
    status_only: bool = False,
) -> None:
    telegram = dict(profile.telegram or {})
    if last_message_id is not None:
        seen = _parse_message_id(last_message_id)
        stored = _parse_message_id(telegram.get("lastTelegramMessageId"))
        telegram["lastTelegramMessageId"] = str(max(seen, stored))
    if status_only:
        telegram["syncStatus"] = sync_status
        telegram["syncError"] = sync_error[:500] if sync_error else ""
        profile.telegram = telegram
        flag_modified(profile, "telegram")
        from app.services.telegram.sync_events import publish_telegram_sync_event

        publish_telegram_sync_event(profile.user_id, telegram)
        return
    telegram["lastSync"] = datetime.now(timezone.utc).isoformat()
    if comment_only:
        # Comment-only updates bump a separate revision so the frontend does not
        # refetch the whole post list on every inbound discussion comment. Comments
        # are pulled lazily (post open / comments tab / reconcile) instead.
        telegram["commentsRevision"] = int(telegram.get("commentsRevision") or 0) + max(
            1, comment_revision_delta
        )
    elif metrics_only:
        # Views/reposts/reactions from live MessageEdited — same lazy model as
        # comments: persist to DB, refresh on open post / reconcile, not feed.
        telegram["metricsRevision"] = int(telegram.get("metricsRevision") or 0) + 1
    else:
        telegram["syncRevision"] = int(telegram.get("syncRevision") or 0) + 1
    telegram["syncStatus"] = sync_status
    telegram["syncError"] = sync_error[:500] if sync_error else ""
    profile.telegram = telegram
    flag_modified(profile, "telegram")
    from app.services.telegram.sync_events import publish_telegram_sync_event

    publish_telegram_sync_event(profile.user_id, telegram)


async def mark_post_deleted(post: Post) -> None:
    """Soft-delete: keep the row but move the post to ``status: deleted``."""
    data = dict(post.data)
    if data.get("status") == "deleted":
        return
    data["status"] = "deleted"
    data["deletedAt"] = datetime.now(timezone.utc).isoformat()
    clear_post_engagement_data(data)
    post.data = data
    flag_modified(post, "data")


def clear_post_engagement_data(data: dict[str, Any]) -> None:
    """Drop comments, reactions/views and Telegram discussion linkage for this post."""
    data["comments"] = []
    data.pop("metrics", None)
    for key in (
        "commentSyncError",
        "telegramDiscussionMessageId",
        "commentsThreadAvailable",
        "commentsThreadLiveOptimistic",
    ):
        data.pop(key, None)


def restore_deleted_post_to_draft(merged: dict[str, Any]) -> dict[str, Any]:
    """Turn a soft-deleted post back into a draft (clears Telegram link and metrics)."""
    data = dict(merged)
    data["status"] = "draft"
    data["created"] = data.get("created") or datetime.now(timezone.utc).isoformat()
    for key in (
        "deletedAt",
        "telegramMessageId",
        "metrics",
        "source",
        "date",
        "_celeryTaskId",
        "publishError",
    ):
        data.pop(key, None)
    clear_post_engagement_data(data)
    return data


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
    from app.services.ai.rag_worker import enqueue_post_text_job

    effective_id = str(post_data.get("id") or msg_id)
    await enqueue_post_text_job(session, user_id, effective_id, post_data=post_data)
    telegram = dict(profile.telegram or {})
    telegram["importedPosts"] = int(telegram.get("importedPosts") or 0) + 1
    profile.telegram = telegram

    await touch_telegram_profile(session, profile, last_message_id=msg_id)


_COMMENT_THREAD_KEYS = (
    "commentsThreadAvailable",
    "commentsThreadLiveOptimistic",
    "telegramDiscussionMessageId",
)


def _comment_thread_unchanged(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    for key in _COMMENT_THREAD_KEYS:
        if existing.get(key) != incoming.get(key):
            return False
    return True


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
    if str(existing.get("textHtml") or "") != str(incoming.get("textHtml") or ""):
        return False
    incoming_media = incoming.get("media")
    if incoming_media and incoming_media != existing.get("media"):
        return False
    if (existing.get("metrics") or {}) != (incoming.get("metrics") or {}):
        return False
    return _comment_thread_unchanged(existing, incoming)


def _is_metrics_only_change(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """True when only views/reposts/reactions differ (text and media unchanged)."""
    if str(existing.get("text") or "") != str(incoming.get("text") or ""):
        return False
    incoming_media = incoming.get("media")
    existing_media = existing.get("media")
    if incoming_media and incoming_media != existing_media:
        return False
    return (existing.get("metrics") or {}) != (incoming.get("metrics") or {})


_PRESERVE_NON_EMPTY_ON_EMPTY_LIST = ("comments", "notes", "chats")


def _merge_telegram_post_payload(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge a Telethon-mapped payload into stored post data.

    Channel ingest always maps ``comments``/``notes``/``chats`` to ``[]``. Those
    fields are managed separately (comments_flow, platform UI) and must not be
    wiped by media enrich, message edits, or catch-up updates.
    """
    patched = dict(incoming)
    for key in _PRESERVE_NON_EMPTY_ON_EMPTY_LIST:
        if patched.get(key) == [] and existing.get(key):
            patched.pop(key, None)
    return {**existing, **patched}


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

    if existing.data.get("status") == "deleted":
        return

    if _content_unchanged(existing.data, post_data):
        return

    if _incoming_telegram_edit_is_stale(existing.data, post_data):
        return

    previous_data = dict(existing.data)
    merged = _merge_telegram_post_payload(existing.data, post_data)
    if post_data.get("date"):
        merged["date"] = post_data["date"]
    if merged.get("status") == "published" and merged.get("source") == "telegram":
        merged.pop("created", None)
    new_media = post_data.get("media")
    old_media = existing.data.get("media")
    if not new_media and old_media:
        merged["media"] = old_media
    metrics_only = _is_metrics_only_change(existing.data, merged)
    existing.data = merged
    flag_modified(existing, "data")

    previous_id = str(previous_data.get("id") or "")
    new_id = str(merged.get("id") or "")
    id_changed = previous_id != new_id
    became_telegram_published = merged.get("status") == "published" and merged.get(
        "source"
    ) == "telegram" and (
        previous_data.get("status") != "published"
        or previous_data.get("source") != "telegram"
    )
    if id_changed or became_telegram_published:
        from app.services.ai.rag_worker import enqueue_post_text_job

        canonical_id = str(merged.get("id") or existing.id)
        await enqueue_post_text_job(
            session, user_id, canonical_id, post_data=merged
        )

    await touch_telegram_profile(
        session, profile, last_message_id=msg_id, metrics_only=metrics_only
    )


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
    profile = await session.get(Profile, user_id)
    if profile is not None:
        await touch_telegram_profile(
            session, profile, last_message_id=telegram_message_id
        )
    from app.services.ai.rag_worker import enqueue_post_text_job

    effective_id = str(data.get("id") or post_id)
    await enqueue_post_text_job(session, user_id, effective_id, post_data=data)
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
    profile = await session.get(Profile, user_id)
    if profile is not None:
        await touch_telegram_profile(
            session, profile, last_message_id=merged.get("telegramMessageId")
        )
    from app.services.ai.rag_worker import enqueue_post_text_job

    effective_id = str(merged.get("id") or post_id)
    await enqueue_post_text_job(session, user_id, effective_id, post_data=merged)
    await session.commit()
    return merged


async def find_post_for_discussion_reply(
    session: AsyncSession, user_id: UUID, reply_to_msg_id: int, *, window: int = 200
) -> Post | None:
    """Find a linked post whose discussion thread contains *reply_to_msg_id*."""
    reply_str = str(reply_to_msg_id)
    result = await session.execute(
        select(Post).where(
            Post.user_id == user_id,
            Post.data["telegramDiscussionMessageId"].astext == reply_str,
            Post.data["status"].astext != "deleted",
        )
    )
    post = result.scalar_one_or_none()
    if post is not None:
        return post

    linked = await load_linked_posts_for_reconcile(session, user_id, window)
    for candidate in linked:
        for comment in candidate.data.get("comments") or []:
            if str(comment.get("telegramMessageId") or "") == reply_str:
                return candidate
    return None


async def apply_discussion_comment(
    session: AsyncSession,
    user_id: UUID,
    post: Post,
    comment: dict[str, Any],
    *,
    discussion_root_id: str | None = None,
) -> bool:
    """Merge one discussion comment into *post*; return True when persisted."""
    return await apply_discussion_comments(
        session,
        user_id,
        post,
        [comment],
        discussion_root_id=discussion_root_id,
    )


async def apply_discussion_comments(
    session: AsyncSession,
    user_id: UUID,
    post: Post,
    comments: list[dict[str, Any]],
    *,
    discussion_root_id: str | None = None,
) -> bool:
    """Merge a batch of discussion comments into *post*; one profile touch.

    Batching keeps high-volume threads from bumping ``syncRevision`` (and the
    frontend refetch it triggers) once per inbound comment.
    """
    from app.services.telegram.comments_flow import merge_comments

    if not comments:
        return False

    profile = await session.get(Profile, user_id)
    if profile is None:
        return False

    existing = list(post.data.get("comments") or [])
    merged = merge_comments(existing, comments)
    if merged == existing:
        return False

    data = dict(post.data)
    data["comments"] = merged
    if discussion_root_id:
        data["telegramDiscussionMessageId"] = discussion_root_id
    post.data = data
    flag_modified(post, "data")
    await touch_telegram_profile(session, profile, comment_only=True)
    return True


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
    from app.services.ai.rag_worker import enqueue_post_rag_delete_jobs

    await enqueue_post_rag_delete_jobs(
        session, user_id, dict(existing.data), db_row_id=str(existing.id)
    )
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


async def repair_empty_telegram_posts(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Any,
    session_factory: Any,
    *,
    limit: int = 15,
) -> int:
    """Re-fetch Telegram payloads for posts saved without text or media."""
    from app.services.telegram.message_mapping import (
        map_group_to_post,
        message_is_importable,
    )

    async with session_factory() as session:
        result = await session.execute(
            select(Post).where(Post.user_id == user_id).order_by(Post.position).limit(120)
        )
        candidates: list[str] = []
        for post in result.scalars():
            data = post.data
            if data.get("status") != "published":
                continue
            msg_id = str(data.get("telegramMessageId") or "")
            if not msg_id:
                continue
            text = str(data.get("text") or "").strip()
            media = data.get("media")
            has_media = isinstance(media, list) and len(media) > 0
            if text and has_media:
                continue
            candidates.append(msg_id)

    repaired = 0
    for msg_id in candidates[:limit]:
        try:
            channel_msg_id = int(msg_id)
        except (TypeError, ValueError):
            continue
        try:
            fetched = await client.get_messages(entity, ids=channel_msg_id)
        except Exception:
            continue
        if not fetched:
            continue
        message = fetched[0] if isinstance(fetched, (list, tuple)) else fetched
        if not message_is_importable(message):
            continue
        messages = [message]
        gid = getattr(message, "grouped_id", None) or None
        if gid:
            try:
                siblings = await client.get_messages(entity, grouped_id=gid)
                if siblings:
                    messages = list(siblings)
            except Exception:
                pass
        full = await map_group_to_post(
            client, messages, user_id, settings, fetch_media=True
        )
        if full is None:
            continue
        if not str(full.get("text") or "").strip() and not full.get("media"):
            continue
        async with session_factory() as session:
            await update_telegram_post(session, user_id, full)
            profile = await session.get(Profile, user_id)
            if profile is not None:
                await touch_telegram_profile(session, profile)
            await session.commit()
        repaired += 1
    return repaired
