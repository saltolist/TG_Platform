import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.core.deps import CurrentUser, CurrentWriter, DbSession
from app.db.models import Post, Profile
from app.db.resolve import get_owned_post
from app.schemas.requests import PostScheduleRequest, ReorderRequest
from app.schemas.resources import PostIn
from app.services.ai.chat_history import merge_history_stamps
from app.services.ai.context_meta import apply_rolling_summary_reconcile_to_chat_data
from app.services.ai.summary_catalog import catalog_from_profile, register_local_summary_version
from app.services.ai.rag_worker import enqueue_note_job
from app.services.profile_defaults import empty_channel_profile, empty_telegram_profile
from app.services.telegram.comments_flow import (
    comments_enabled,
    merge_patch_comments,
    normalize_post_comments,
    removed_comment_telegram_message_ids,
    require_comments_enabled,
    schedule_discussion_comments_delete,
    schedule_post_comments_push,
    sync_post_comments_pull,
)
from app.services.telegram.delete_flow import delete_message_in_telegram
from app.services.telegram.edit_flow import sync_edit_to_telegram
from app.services.telegram.net import TelegramAuthError
from app.services.telegram.post_sync import mark_post_deleted, restore_deleted_post_to_draft
from app.services.telegram.publish_flow import parse_scheduled_at
from app.services.telegram.publish_flow import publish_post as run_telegram_publish
from app.services.posts_payload import normalize_post_for_api
from app.services.telegram.sync_pending import (
    enrich_posts_for_user as enrich_post_sync_pending,
    telegram_sync_pending,
)
from app.tasks.publish import publish_scheduled_post

router = APIRouter(prefix="/posts", tags=["Posts"])


async def enrich_posts_for_user(
    user_id: uuid.UUID, posts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from app.services.telegram.comment_sync_pending import (
        enrich_posts_for_user as enrich_comment_sync_pending,
    )

    enriched = await enrich_post_sync_pending(user_id, posts)
    return await enrich_comment_sync_pending(user_id, enriched)


@router.get("/")
async def list_posts(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(Post).where(Post.user_id == user.id).order_by(Post.position, Post.created_at)
    )
    return await enrich_posts_for_user(
        user.id,
        [
            normalize_post_for_api(post.data, db_id=str(post.id))
            for post in result.scalars().all()
        ],
    )


@router.get("/{post_id}/")
async def get_post(post_id: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    """Return one post from DB (no Telegram round-trip). Used by open-post polling."""
    post = await get_owned_post(session, user.id, post_id)
    enriched = await enrich_posts_for_user(
        user.id,
        [normalize_post_for_api(post.data, db_id=str(post.id))],
    )
    return enriched[0]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_post(payload: PostIn, user: CurrentWriter, session: DbSession) -> dict[str, Any]:
    try:
        post_id = uuid.UUID(payload.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный id поста")

    data = payload.model_dump()
    count = await session.scalar(
        select(func.count()).select_from(Post).where(Post.user_id == user.id)
    )
    session.add(Post(id=post_id, user_id=user.id, position=count or 0, data=data))
    await session.commit()
    return data


@router.put("/reorder/")
async def reorder_posts(
    payload: ReorderRequest, user: CurrentWriter, session: DbSession
) -> list[dict[str, Any]]:
    result = await session.execute(select(Post).where(Post.user_id == user.id))
    by_id = {str(post.id): post for post in result.scalars().all()}

    ordered: list[dict[str, Any]] = []
    for index, item in enumerate(payload.posts):
        post = by_id.get(str(item.get("id")))
        if post is None:
            continue
        post.position = index
        post.data = item
        ordered.append(item)

    await session.commit()
    return ordered


@router.patch("/{post_id}/")
async def update_post(
    post_id: str, patch: dict[str, Any], user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    post = await get_owned_post(session, user.id, post_id)
    previous_text = post.data.get("text")
    previous_status = post.data.get("status")
    previous_telegram_message_id = post.data.get("telegramMessageId")
    previous_task_id = post.data.get("_celeryTaskId")

    merged = {**post.data, **patch}
    if isinstance(patch.get("comments"), list):
        merged["comments"] = merge_patch_comments(
            list(post.data.get("comments") or []),
            patch["comments"],
        )
    elif isinstance(merged.get("comments"), list):
        merged["comments"] = normalize_post_comments(merged["comments"])
    if isinstance(patch.get("chats"), list) and isinstance(post.data.get("chats"), list):
        existing_by_id = {
            str(chat.get("id")): chat
            for chat in post.data.get("chats") or []
            if isinstance(chat, Mapping)
        }
        merged_chats: list[dict[str, Any]] = []
        for chat in patch["chats"]:
            if not isinstance(chat, Mapping):
                merged_chats.append(chat)
                continue
            chat_id = str(chat.get("id") or "")
            existing = existing_by_id.get(chat_id)
            chat_copy = dict(chat)
            if existing is not None and isinstance(chat.get("history"), list):
                chat_copy["history"] = merge_history_stamps(
                    list(existing.get("history") or []),
                    chat["history"],
                    strip_incoming=True,
                )
                chat_copy.update(
                    apply_rolling_summary_reconcile_to_chat_data(
                        {**dict(existing), **chat_copy},
                        chat_copy["history"],
                    )
                )
            merged_chats.append(chat_copy)
        merged["chats"] = merged_chats
    merged["id"] = post.data.get("id", str(post.id))

    if previous_status == "deleted" and merged.get("status") == "draft":
        merged = restore_deleted_post_to_draft(merged)

    telegram_message_id_for_edit = previous_telegram_message_id or merged.get("telegramMessageId")
    if (
        telegram_message_id_for_edit
        and isinstance(patch.get("text"), str)
        and merged.get("text") != previous_text
    ):
        merged["_platformTextEditAt"] = datetime.now(timezone.utc).isoformat()
        merged.pop("textHtml", None)

    # Step 4b: cancelling a scheduled post (status leaves "scheduled") revokes its Celery task.
    if (
        previous_status == "scheduled"
        and merged.get("status") != "scheduled"
        and previous_task_id
    ):
        celery_app.control.revoke(previous_task_id)
        merged.pop("_celeryTaskId", None)
        merged.pop("publishError", None)

    profile = await session.get(Profile, user.id)
    channel = profile.channel if profile and profile.channel else empty_channel_profile()
    telegram = profile.telegram if profile and profile.telegram else empty_telegram_profile()
    catalog = catalog_from_profile(profile)
    updated_catalog, _version = register_local_summary_version(
        catalog,
        post_id=str(merged.get("id") or post_id),
        channel=channel,
        telegram=telegram,
        post=merged,
    )
    if profile is not None:
        profile.summary_catalog = updated_catalog
    elif _version is not None:
        profile = Profile(user_id=user.id, summary_catalog=updated_catalog)
        session.add(profile)

    previous_comments = list(post.data.get("comments") or [])
    comment_delete_error: str | None = None
    scheduled_delete_tg_ids: list[str] = []
    if isinstance(patch.get("comments"), list):
        removed_tg_ids = removed_comment_telegram_message_ids(
            previous_comments,
            list(merged.get("comments") or []),
        )
        if (
            removed_tg_ids
            and profile is not None
            and merged.get("status") == "published"
            and (previous_telegram_message_id or merged.get("telegramMessageId"))
        ):
            if not comments_enabled(telegram):
                comment_delete_error = (
                    "В канале не включены обсуждения — нельзя удалить комментарий в Telegram"
                )
                merged["comments"] = previous_comments
            else:
                discussion_chat_id = telegram.get("discussionChatId")
                if not discussion_chat_id:
                    comment_delete_error = "В канале не включены обсуждения"
                    merged["comments"] = previous_comments
                else:
                    scheduled_delete_tg_ids = removed_tg_ids

    post.data = merged
    # Enqueue RAG indexing for any notes present in the patch
    effective_post_id = str(merged.get("id") or post_id)
    if isinstance(patch.get("notes"), list):
        for note in patch["notes"]:
            if isinstance(note, Mapping) and note.get("id"):
                await enqueue_note_job(
                    session, user.id, "upsert", "post",
                    str(note["id"]), effective_post_id,
                )
    await session.commit()

    response = dict(merged)
    if comment_delete_error:
        response["commentSyncError"] = comment_delete_error

    # Step 4c: propagate a text edit of an already-published/imported post to Telegram.
    # Best-effort — the DB write above already succeeded regardless of this outcome.
    telegram_message_id = previous_telegram_message_id or merged.get("telegramMessageId")
    if (
        telegram_message_id
        and profile is not None
        and isinstance(patch.get("text"), str)
        and merged.get("text") != previous_text
    ):
        async with telegram_sync_pending(user.id, post_id):
            sync_result = await sync_edit_to_telegram(
                profile, str(telegram_message_id), str(merged.get("text") or ""), user.id
            )
        if sync_result.deleted_in_telegram:
            post = await get_owned_post(session, user.id, post_id)
            await session.refresh(post)
            response = dict(post.data)
        elif sync_result.error:
            response["telegramSyncError"] = sync_result.error

    telegram_message_id = previous_telegram_message_id or merged.get("telegramMessageId")
    if (
        telegram_message_id
        and profile is not None
        and isinstance(patch.get("comments"), list)
        and merged.get("status") == "published"
    ):
        pending_without_tg = [
            item
            for item in merged.get("comments") or []
            if isinstance(item, Mapping) and not item.get("telegramMessageId")
        ]
        if pending_without_tg:
            if not comments_enabled(telegram):
                response["commentSyncError"] = (
                    "В канале не включены обсуждения — включите их в настройках Telegram"
                )
            else:
                schedule_post_comments_push(user.id, post_id)

    if scheduled_delete_tg_ids:
        schedule_discussion_comments_delete(user.id, post_id, scheduled_delete_tg_ids)

    return response


@router.post("/{post_id}/sync-comments/")
async def sync_post_comments_endpoint(
    post_id: str, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    """Pull discussion comments from Telegram for a linked post (Phase 3 / Step 5b)."""
    post = await get_owned_post(session, user.id, post_id)
    profile = await session.get(Profile, user.id)
    if profile is None:
        raise HTTPException(status_code=400, detail="Профиль не найден")

    telegram = profile.telegram if profile.telegram else empty_telegram_profile()
    if not post.data.get("telegramMessageId"):
        return dict(post.data)

    try:
        require_comments_enabled(telegram)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    result = await sync_post_comments_pull(profile, post.data, user.id)

    response = dict(post.data)
    if result.comments is not None:
        updated = dict(post.data)
        updated["comments"] = normalize_post_comments(result.comments)
        if result.telegram_discussion_message_id:
            updated["telegramDiscussionMessageId"] = result.telegram_discussion_message_id
        if result.comments_thread_available is not None:
            updated["commentsThreadAvailable"] = result.comments_thread_available
            if not result.comments_thread_available:
                updated.pop("telegramDiscussionMessageId", None)
        if result.comments_pull_complete is not None:
            updated["commentsPullComplete"] = result.comments_pull_complete
        post.data = updated
        await session.commit()
        response = dict(updated)
    if result.error:
        response["commentSyncError"] = result.error
    if result.comments_pull_complete is not None:
        response["commentsPullComplete"] = result.comments_pull_complete
    return response


@router.post("/{post_id}/publish/")
async def publish_post_endpoint(
    post_id: str, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    """Send a draft post to the connected Telegram channel now (Phase 3 / Step 4a)."""
    post = await get_owned_post(session, user.id, post_id)
    try:
        return await run_telegram_publish(user.id, post.id)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/{post_id}/schedule/")
async def schedule_post_endpoint(
    post_id: str, payload: PostScheduleRequest, user: CurrentWriter, session: DbSession
) -> dict[str, Any]:
    """Queue a draft post for publication at ``scheduledAt`` (Phase 3 / Step 4b)."""
    post = await get_owned_post(session, user.id, post_id)
    data = dict(post.data)
    if data.get("telegramMessageId"):
        raise HTTPException(status_code=400, detail="Пост уже опубликован")

    profile = await session.get(Profile, user.id)
    telegram = profile.telegram if profile and profile.telegram else empty_telegram_profile()
    if telegram.get("channelStatus") != "connected":
        raise HTTPException(status_code=400, detail="Сначала подключите канал")
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise HTTPException(status_code=400, detail="Сначала авторизуйтесь в Telegram")

    try:
        scheduled_dt = parse_scheduled_at(payload.scheduled_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата публикации") from None

    old_task_id = data.get("_celeryTaskId")
    if old_task_id:
        celery_app.control.revoke(old_task_id)

    async_result = publish_scheduled_post.apply_async(
        args=[str(post.id), str(user.id)], eta=scheduled_dt
    )

    data["status"] = "scheduled"
    data["date"] = payload.scheduled_at
    data["_celeryTaskId"] = async_result.id
    data.pop("publishError", None)
    post.data = data
    await session.commit()
    return post.data


@router.delete("/{post_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: str,
    user: CurrentWriter,
    session: DbSession,
    permanent: bool = Query(False),
) -> Response:
    post = await get_owned_post(session, user.id, post_id)

    if permanent:
        if post.data.get("status") != "deleted":
            raise HTTPException(
                status_code=400,
                detail="Удалить навсегда можно только пост из раздела удалённых",
            )
        effective_post_id = str(post.data.get("id") or post_id)
        notes = post.data.get("notes")
        if isinstance(notes, list):
            for note in notes:
                if isinstance(note, Mapping) and note.get("id"):
                    await enqueue_note_job(
                        session,
                        user.id,
                        "delete",
                        "post",
                        str(note["id"]),
                        effective_post_id,
                    )
        await session.delete(post)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if post.data.get("status") == "deleted":
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async with telegram_sync_pending(user.id, post_id):
        # Step 4c (delete): a Telegram-linked post is a mirror of the channel — remove
        # the channel message first and abort (keep the platform post) if that fails.
        telegram_message_id = post.data.get("telegramMessageId")
        if telegram_message_id:
            profile = await session.get(Profile, user.id)
            if profile is not None:
                try:
                    await delete_message_in_telegram(
                        profile, str(telegram_message_id), user.id
                    )
                except TelegramAuthError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        await mark_post_deleted(post)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
