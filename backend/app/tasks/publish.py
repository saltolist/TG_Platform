"""Celery task that fires a scheduled post's Telegram publish (Phase 3 / Step 4b).

Only this — the deferred half of publishing — runs through Celery. See
``app/celery_app.py`` and ``docs/backend/phases/phase-3-telegram.md`` (Step 4)
for why immediate publish and edit-sync stay synchronous in the API process.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from celery.signals import worker_ready
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.models import Post
from app.db.session import async_session_factory
from app.services.telegram.net import TelegramAuthError
from app.services.telegram.publish_flow import publish_post

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


async def _record_publish_error(post_id: UUID, user_id: UUID, error: str) -> None:
    async with async_session_factory() as session:
        post = await session.get(Post, post_id)
        if post is None or post.user_id != user_id:
            return
        data = dict(post.data)
        data["publishError"] = error[:500]
        post.data = data
        flag_modified(post, "data")
        await session.commit()


@celery_app.task(bind=True, name="app.tasks.publish.publish_scheduled_post")
def publish_scheduled_post(self: Any, post_id: str, user_id: str) -> None:
    settings = get_settings()
    try:
        _run_async(publish_post(UUID(user_id), UUID(post_id), settings))
    except TelegramAuthError as exc:
        logger.warning("Scheduled publish failed for post %s: %s", post_id, exc.detail)
        _run_async(_record_publish_error(UUID(post_id), UUID(user_id), exc.detail))
        if self.request.retries < settings.telegram_publish_max_retries:
            raise self.retry(exc=exc, countdown=30) from exc
    except Exception as exc:  # noqa: BLE001 — a crashed task must not lose the retry budget
        logger.exception("Scheduled publish crashed for post %s", post_id)
        _run_async(_record_publish_error(UUID(post_id), UUID(user_id), str(exc)))
        if self.request.retries < settings.telegram_publish_max_retries:
            raise self.retry(exc=exc, countdown=30) from exc


async def _reconcile_overdue_scheduled_posts() -> None:
    """Re-enqueue ``scheduled`` posts whose ``eta`` already passed with no active task.

    Runs once when the worker starts (see ``worker_ready`` below) — covers posts
    that were due while no worker/broker was up (deploys, restarts, downtime).
    No Celery Beat process is needed for this; see decision #2 in the Step 4 plan.
    """
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        result = await session.execute(select(Post))
        for post in result.scalars():
            data = post.data or {}
            if data.get("status") != "scheduled" or data.get("telegramMessageId"):
                continue
            scheduled_at = data.get("date")
            if not isinstance(scheduled_at, str):
                continue
            try:
                due_at = datetime.fromisoformat(scheduled_at)
            except ValueError:
                continue
            if due_at > now:
                continue
            async_result = publish_scheduled_post.apply_async(
                args=[str(post.id), str(post.user_id)]
            )
            new_data = dict(data)
            new_data["_celeryTaskId"] = async_result.id
            post.data = new_data
            flag_modified(post, "data")
            logger.info("Reconciled overdue scheduled post %s", post.id)
        await session.commit()


@worker_ready.connect
def _on_worker_ready(**_kwargs: Any) -> None:
    try:
        _run_async(_reconcile_overdue_scheduled_posts())
    except Exception:  # noqa: BLE001 — must not prevent the worker from starting
        logger.exception("Startup reconcile of scheduled posts failed")
