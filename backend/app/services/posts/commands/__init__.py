"""Typed post commands — shared by REST and agent executor."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Post, User
from app.db.resolve import get_owned_post
from app.services.posts_payload import normalize_post_for_api


async def execute_post_command(
    session: AsyncSession,
    *,
    user: User,
    command: str,
    payload: dict[str, Any],
    resource_version: str | None = None,
    enqueue_post_text=None,
) -> dict[str, Any]:
    if command == "create_post":
        return await _create_post(
            session,
            user=user,
            payload=payload,
            enqueue_post_text=enqueue_post_text,
        )
    if command == "edit_post":
        return await _edit_post(
            session,
            user=user,
            payload=payload,
            resource_version=resource_version,
        )
    if command == "schedule_post":
        return await _schedule_post(session, user=user, payload=payload)
    if command == "cancel_schedule":
        return await _cancel_schedule(session, user=user, payload=payload)
    if command == "publish_post":
        return await _publish_post(session, user=user, payload=payload)
    if command == "delete_post":
        return await _delete_post(session, user=user, payload=payload)
    if command == "restore_post":
        return await _restore_post(session, user=user, payload=payload)
    if command == "attach_media":
        return await _attach_media(session, user=user, payload=payload)
    raise HTTPException(status_code=400, detail=f"Unknown command: {command}")


async def _create_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
    enqueue_post_text=None,
) -> dict[str, Any]:
    from app.services.telegram.text_formatting import apply_platform_text_fields

    if enqueue_post_text is None:
        from app.services.ai.rag_worker import enqueue_post_text_job

        enqueue_post_text = enqueue_post_text_job

    post_id = uuid.UUID(str(payload.get("id") or uuid.uuid4()))
    data = dict(payload.get("data") or {})
    data.setdefault("id", str(post_id))
    data.setdefault("status", "draft")
    apply_platform_text_fields(data)
    count = await session.scalar(
        select(func.count()).select_from(Post).where(Post.user_id == user.id)
    )
    post = Post(id=post_id, user_id=user.id, data=data, position=count or 0)
    session.add(post)
    await enqueue_post_text(session, user.id, str(post_id))
    await session.flush()
    return {"post_id": str(post_id), "status": "created", "post": data}


async def _edit_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
    resource_version: str | None,
) -> dict[str, Any]:
    post_id = str(payload.get("post_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    current_version = str(post.data.get("syncRevision") or post.created_at.isoformat())
    if resource_version and resource_version != current_version:
        raise HTTPException(status_code=409, detail="resource_version_conflict")
    patch = dict(payload.get("patch") or {})
    allowed = {"text", "textHtml", "notes", "media", "title"}
    for key, value in patch.items():
        if key in allowed:
            post.data[key] = value
    await session.flush()
    return {
        "post_id": post_id,
        "resource_version": str(post.data.get("syncRevision") or post.created_at.isoformat()),
    }


async def _schedule_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.celery_app import celery_app
    from app.db.models import Profile
    from app.services.profile_defaults import empty_telegram_profile
    from app.services.telegram.publish_flow import parse_scheduled_at
    from app.tasks.publish import publish_scheduled_post

    post_id = str(payload.get("post_id") or "")
    scheduled_at = str(payload.get("scheduled_at") or "")
    post = await get_owned_post(session, user.id, post_id)
    if post.data.get("telegramMessageId"):
        raise HTTPException(status_code=400, detail="Пост уже опубликован")
    profile = await session.get(Profile, user.id)
    telegram = profile.telegram if profile and profile.telegram else empty_telegram_profile()
    if telegram.get("channelStatus") != "connected":
        raise HTTPException(status_code=400, detail="Сначала подключите канал")
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise HTTPException(status_code=400, detail="Сначала авторизуйтесь в Telegram")
    try:
        scheduled_dt = parse_scheduled_at(scheduled_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректная дата публикации") from None
    data = dict(post.data)
    if data.get("_celeryTaskId"):
        celery_app.control.revoke(data["_celeryTaskId"])
    task = publish_scheduled_post.apply_async(
        args=[str(post.id), str(user.id)],
        eta=scheduled_dt,
    )
    data.update({"status": "scheduled", "date": scheduled_at, "_celeryTaskId": task.id})
    data.pop("publishError", None)
    post.data = data
    await session.flush()
    return {"post_id": post_id, "scheduled_at": scheduled_at}


async def _cancel_schedule(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.celery_app import celery_app

    post_id = str(payload.get("post_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    data = dict(post.data)
    task_id = data.pop("_celeryTaskId", None)
    if task_id:
        celery_app.control.revoke(task_id)
    if data.get("status") == "scheduled":
        data["status"] = "draft"
    data.pop("date", None)
    post.data = data
    await session.flush()
    return {"post_id": post_id, "status": str(data.get("status") or "draft")}


async def _publish_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.services.telegram.net import TelegramAuthError
    from app.services.telegram.publish_flow import publish_post as telegram_publish

    post_id = str(payload.get("post_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    if post.data.get("telegramMessageId"):
        return {"post_id": post_id, "status": "published", "idempotent": True}
    try:
        updated = await telegram_publish(user.id, post.id, settings=get_settings())
    except TelegramAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    post.data = {**post.data, **updated}
    await session.flush()
    return {"post_id": post_id, "status": str(post.data.get("status") or "published")}


async def _delete_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.db.models import Profile
    from app.services.ai.rag_worker import enqueue_post_rag_delete_jobs
    from app.services.telegram.net import TelegramAuthError
    from app.services.telegram.post_sync import mark_post_deleted
    from app.services.telegram.delete_flow import delete_message_in_telegram
    from app.services.telegram.sync_pending import telegram_sync_pending

    post_id = str(payload.get("post_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    if post.data.get("status") == "deleted":
        return {"post_id": post_id, "status": "deleted", "idempotent": True}
    async with telegram_sync_pending(user.id, post_id):
        telegram_message_id = post.data.get("telegramMessageId")
        if telegram_message_id:
            profile = await session.get(Profile, user.id)
            if profile is not None:
                try:
                    await delete_message_in_telegram(
                        profile,
                        str(telegram_message_id),
                        user.id,
                    )
                except TelegramAuthError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        await mark_post_deleted(post)
        await enqueue_post_rag_delete_jobs(
            session,
            user.id,
            dict(post.data),
            db_row_id=str(post.id),
        )
    await session.flush()
    return {"post_id": post_id, "status": "deleted"}


async def _restore_post(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.services.telegram.post_sync import restore_deleted_post_to_draft

    post_id = str(payload.get("post_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    post.data = restore_deleted_post_to_draft(dict(post.data))
    await session.flush()
    return {"post_id": post_id, "status": "draft"}


async def _attach_media(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    post_id = str(payload.get("post_id") or "")
    asset_id = str(payload.get("asset_id") or "")
    post = await get_owned_post(session, user.id, post_id)
    media = list(post.data.get("media") or [])
    media.append(
        {
            "id": asset_id,
            "assetId": asset_id,
            "type": payload.get("mime_type") or "image/png",
            "name": payload.get("name") or "generated",
            "url": payload.get("preview_url") or "",
        }
    )
    post.data["media"] = media
    await session.flush()
    return {"post_id": post_id, "asset_id": asset_id, "media_count": len(media)}
