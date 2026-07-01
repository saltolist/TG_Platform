"""Celery application for deferred Telegram publishing (Phase 3 / Step 4b).

Only scheduled ("publish later") posts go through this queue — immediate
publish (4a) and text edit-sync (4c) run synchronously inside the API
request, same as every other Telegram flow in this codebase (see
``docs/backend/phases/phase-3-telegram.md``, Step 4).

``task_acks_late=False`` (the default) + a deterministic ``task_id`` per post
(``publish:<post_id>``) keep this simple: a crashed worker does not silently
redeliver a task whose Telegram side-effect may have already happened.
``worker_prefetch_multiplier=1`` avoids two publish tasks for the same user
racing for the same MTProto session (see ``session_guard.py``).
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "tg_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.publish"],
)

celery_app.conf.update(
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    timezone="UTC",
    enable_utc=True,
)
