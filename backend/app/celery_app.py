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
from celery.signals import worker_process_init, worker_process_shutdown, worker_ready

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "tg_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.publish",
        "app.tasks.analytics_snapshot",
        "app.tasks.media_generation",
        "app.tasks.agent_runs",
    ],
)

celery_app.conf.update(
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    timezone="UTC",
    enable_utc=True,
    # fastembed construction can exceed billiard's 4s child-alive default on
    # a cold host; the child must finish real warmup before it accepts work.
    worker_proc_alive_timeout=90.0,
    task_default_queue="telegram-io",
    task_routes={
        "app.tasks.agent_runs.execute_agent_run_task": {"queue": "agent-interactive"},
        "media_generation.run_job": {"queue": "agent-heavy"},
        "media_generation.cancel_provider_operation": {"queue": "agent-heavy"},
        "app.tasks.analytics_snapshot.capture_all_channel_snapshots": {"queue": "analytics"},
        "app.tasks.publish.publish_scheduled_post": {"queue": "telegram-io"},
    }
    if settings.agent_runtime_phase1_enabled
    else {},
)


@worker_ready.connect
def _start_prometheus_exporter(**_kwargs):
    """Start the merged metrics endpoint after the prefork pool is ready."""
    from app.services.agent.runtime.prometheus_exporter import start_multiprocess_server

    start_multiprocess_server()


@worker_process_init.connect
def _initialize_worker_process(**_kwargs):
    if not settings.agent_runtime_phase1_enabled:
        return
    from app.tasks.async_runtime import initialize_worker_process

    initialize_worker_process()


@worker_process_shutdown.connect
def _shutdown_worker_process(**_kwargs):
    if settings.agent_runtime_phase1_enabled:
        from app.tasks.async_runtime import shutdown_worker_process

        shutdown_worker_process()
    from app.services.agent.runtime.prometheus_exporter import mark_process_dead

    mark_process_dead()

if settings.telegram_analytics_snapshot_seconds > 0:
    celery_app.conf.beat_schedule = {
        "capture-channel-metric-snapshots": {
            "task": "app.tasks.analytics_snapshot.capture_all_channel_snapshots",
            "schedule": settings.telegram_analytics_snapshot_seconds,
        },
    }
