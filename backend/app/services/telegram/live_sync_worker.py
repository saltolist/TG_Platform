"""Long-lived Telethon listeners for live Telegram channel sync (Phase 3 / Step 3.5)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import events
from telethon import errors as telethon_errors
from telethon.tl.types import (
    UpdateChannelMessageForwards,
    UpdateChannelMessageViews,
    UpdateMessageReactions,
)

from app.core.config import Settings, get_settings
from app.db.models import Profile
from app.services.telegram.channel_flow import (
    parse_channel_input,
    resolve_channel_entity,
)
from app.services.telegram.message_mapping import (
    collect_posts_from_iter,
    map_group_to_post,
    map_message_for_reconcile,
    message_is_importable,
    should_defer_media_fetch,
)
from app.services.telegram.text_formatting import message_entities
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    TelegramAuthError,
    call_with_flood_wait,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    refresh_telethon_clock,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.clock_sync import (
    refine_clock_from_live_message,
    reinforce_clock_after_telegram_rpc,
)
from app.services.telegram.comments_flow import (
    DiscussionCommentBuffer,
    apply_comments_thread_probe,
    apply_initial_comments_thread_flag,
    comments_enabled,
    probe_discussion_root,
    probe_pending_comments_thread_flags,
)
from app.services.telegram.metrics_flow import (
    MetricsThrottleBuffer,
    handle_live_channel_message_forwards,
    handle_live_channel_message_views,
    handle_live_message_reactions,
    poll_recent_post_metrics,
)
from app.services.telegram.post_sync import (
    _find_telegram_post,
    delete_telegram_post,
    repair_empty_telegram_posts,
    set_sync_error,
    touch_telegram_profile,
    update_telegram_post,
    upsert_telegram_post,
)
from app.services.telegram.reconcile_flow import reconcile_channel_window
from app.services.telegram.session_guard import telegram_session_lock
from app.services.telegram.sync_coordination import (
    run_channel_ingest,
    run_channel_ingest_if_idle,
)

logger = logging.getLogger(__name__)


def should_listen(telegram: dict[str, Any]) -> bool:
    if telegram.get("channelStatus") != "connected":
        return False
    if telegram.get("syncMode") == "publish-only":
        return False
    if not telegram.get("sessionString"):
        return False
    if telegram.get("importStatus") == "importing":
        return False
    return True


class AlbumBuffer:
    """Debounce album parts sharing the same ``grouped_id``."""

    def __init__(
        self,
        debounce_seconds: float,
        flush_callback: Any,
    ) -> None:
        self._debounce_seconds = debounce_seconds
        self._flush_callback = flush_callback
        self._pending: dict[int, list[Any]] = {}
        self._generation: dict[int, int] = {}

    async def add(self, message: Any) -> None:
        gid = getattr(message, "grouped_id", None) or None
        if not gid:
            await self._flush_callback([message])
            return

        self._pending.setdefault(gid, []).append(message)
        generation = self._generation.get(gid, 0) + 1
        self._generation[gid] = generation
        asyncio.create_task(self._debounced_flush(gid, generation))

    async def _debounced_flush(self, group_id: int, generation: int) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
            if self._generation.get(group_id) != generation:
                return
            messages = self._pending.pop(group_id, [])
            self._generation.pop(group_id, None)
            if messages:
                await self._flush_callback(messages)
        except asyncio.CancelledError:
            pass

    async def flush_all(self) -> None:
        for gid in list(self._pending.keys()):
            messages = self._pending.pop(gid, [])
            self._generation.pop(gid, None)
            if messages:
                await self._flush_callback(messages)
        self._pending.clear()
        self._generation.clear()


class ListenerRegistry:
    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._stop_events: dict[UUID, asyncio.Event] = {}
        self._clients: dict[UUID, Any] = {}

    def is_running(self, user_id: UUID) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    def register_client(self, user_id: UUID, client: Any) -> None:
        self._clients[user_id] = client

    def unregister_client(self, user_id: UUID, client: Any) -> None:
        if self._clients.get(user_id) is client:
            self._clients.pop(user_id, None)

    async def force_disconnect_active_client(self, user_id: UUID) -> None:
        client = self._clients.pop(user_id, None)
        if client is None:
            return
        try:
            await disconnect_safely(client)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Forced live-sync client disconnect failed for user %s",
                user_id,
                exc_info=True,
            )

    def start_user_listener(self, user_id: UUID) -> None:
        if self.is_running(user_id):
            return
        stop_event = asyncio.Event()
        self._stop_events[user_id] = stop_event
        task = asyncio.create_task(
            _run_user_listener(user_id, stop_event),
            name=f"telegram-live-sync-{user_id}",
        )
        task.add_done_callback(lambda _t: self._cleanup_user(user_id))
        self._tasks[user_id] = task

    def stop_user_listener(self, user_id: UUID) -> None:
        stop_event = self._stop_events.get(user_id)
        if stop_event is not None:
            stop_event.set()
        task = self._tasks.get(user_id)
        if task is not None and not task.done():
            task.cancel()

    async def await_stop_user_listener(
        self, user_id: UUID, timeout: float | None = None
    ) -> None:
        """Signal the listener to stop and wait until its MTProto session is released."""
        settings = get_settings()
        wait_seconds = (
            timeout if timeout is not None else settings.telegram_listener_stop_timeout_seconds
        )
        stop_event = self._stop_events.get(user_id)
        task = self._tasks.get(user_id)
        if stop_event is None and task is None:
            return
        if stop_event is not None:
            stop_event.set()
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=wait_seconds)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("Live-sync listener stop timed out for user %s", user_id)
                await self.force_disconnect_active_client(user_id)
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Live-sync listener did not exit after forced disconnect for user %s",
                        user_id,
                    )
                except asyncio.CancelledError:
                    pass
        self._cleanup_user(user_id)

    def _cleanup_user(self, user_id: UUID) -> None:
        self._stop_events.pop(user_id, None)
        self._tasks.pop(user_id, None)
        self._clients.pop(user_id, None)

    async def reconcile_from_db(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        desired: set[UUID] = set()
        async with session_factory() as session:
            result = await session.execute(select(Profile))
            for profile in result.scalars():
                if should_listen(profile.telegram or {}):
                    desired.add(profile.user_id)

        current = {uid for uid, task in self._tasks.items() if not task.done()}
        for user_id in desired - current:
            self.start_user_listener(user_id)
        for user_id in current - desired:
            self.stop_user_listener(user_id)


listener_registry = ListenerRegistry()


def effective_sync_status(telegram: dict[str, Any], user_id: UUID) -> tuple[str, str]:
    """Return public ``(syncStatus, syncError)`` reflecting the real listener state."""
    if not should_listen(telegram):
        return str(telegram.get("syncStatus") or "idle"), str(telegram.get("syncError") or "")
    if listener_registry.is_running(user_id):
        return "listening", ""
    stored_status = str(telegram.get("syncStatus") or "idle")
    stored_error = str(telegram.get("syncError") or "")
    if stored_status == "listening":
        return "idle", stored_error
    return stored_status, stored_error


def ensure_user_listener(user_id: UUID, telegram: dict[str, Any]) -> None:
    """Start the MTProto listener when the profile expects live-sync but none is running."""
    if should_listen(telegram) and not listener_registry.is_running(user_id):
        listener_registry.start_user_listener(user_id)


def apply_effective_sync_fields(telegram: dict[str, Any], user_id: UUID) -> dict[str, Any]:
    """Overlay sync fields with the effective listener state for API responses."""
    result = dict(telegram)
    sync_status, sync_error = effective_sync_status(telegram, user_id)
    result["syncStatus"] = sync_status
    result["syncError"] = sync_error
    return result


async def _load_listener_credentials(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> tuple[dict[str, Any], int, int, str, str, str] | None:
    settings = get_settings()
    async with session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return None
        telegram = profile.telegram or {}
        if not should_listen(telegram):
            return None

        api_id, api_hash = require_api_credentials(telegram, settings)
        session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
        channel_input = str(telegram.get("channel") or "")
        parsed = parse_channel_input(channel_input)
        if not parsed or not session_string:
            return None

        min_id = int(telegram.get("lastTelegramMessageId") or 0)
        return telegram, api_id, api_hash, session_string, parsed, min_id


async def _load_last_telegram_message_id(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> int:
    async with session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return 0
        try:
            return int((profile.telegram or {}).get("lastTelegramMessageId") or 0)
        except (TypeError, ValueError):
            return 0


async def _collect_catch_up_posts_lightweight(
    client: Any,
    entity: Any,
    *,
    min_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fast catch-up for drift correction — no media downloads."""

    async def _collect() -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        async for message in client.iter_messages(entity, min_id=min_id, limit=max(limit * 5, limit)):
            if not message_is_importable(message):
                continue
            mapped = map_message_for_reconcile(message)
            if mapped is not None:
                collected.append(mapped)
            if len(collected) >= limit:
                break
        return collected

    return await call_with_flood_wait(_collect)


async def _catch_up(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    min_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    lightweight: bool = False,
) -> None:
    scan_limit = settings.telegram_reconcile_new_scan_limit
    if min_id <= 0:
        if lightweight:
            posts = await _collect_catch_up_posts_lightweight(
                client, entity, min_id=0, limit=scan_limit
            )
        else:
            posts = await collect_posts_from_iter(
                client,
                entity,
                user_id,
                settings,
                limit=scan_limit,
            )
    else:
        # New messages since lastTelegramMessageId need full media ingest — lightweight
        # reconcile payloads have no media[] and create empty sticker/voice shells.
        posts = await collect_posts_from_iter(
            client,
            entity,
            user_id,
            settings,
            limit=scan_limit,
            min_id=min_id,
        )
    if not posts:
        return
    async with session_factory() as session:
        profile = await session.get(Profile, user_id)
        telegram = dict(profile.telegram or {}) if profile else {}
    probed_posts: list[dict[str, Any]] = posts
    async with session_factory() as session:
        for post_data in probed_posts:
            try:
                msg_id = int(post_data.get("telegramMessageId") or 0)
            except (TypeError, ValueError):
                msg_id = 0
            if min_id > 0 and msg_id > min_id:
                post_data = apply_initial_comments_thread_flag(post_data, telegram)
            await upsert_telegram_post(session, user_id, post_data)
        await session.commit()


async def _startup_catch_up(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    min_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One-shot lightweight catch-up — skipped when maintenance already runs."""

    async def _pass() -> None:
        await _catch_up(
            client,
            entity,
            user_id,
            settings,
            min_id,
            session_factory,
            lightweight=True,
        )

    try:
        await run_channel_ingest_if_idle(user_id, _pass, label="startup-catch-up")
    except Exception:
        logger.debug("Startup live-sync catch-up failed for user %s", user_id, exc_info=True)


async def _run_channel_maintenance_pass(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Single background pass: missed posts, deletion drift, metrics (no media download)."""
    min_id = await _load_last_telegram_message_id(session_factory, user_id)
    try:
        await _catch_up(
            client,
            entity,
            user_id,
            settings,
            min_id,
            session_factory,
            lightweight=True,
        )
    except Exception:
        logger.exception("Maintenance catch-up failed for user %s", user_id)
    try:
        repaired = await repair_empty_telegram_posts(
            client, entity, user_id, settings, session_factory
        )
        if repaired:
            logger.debug(
                "Repaired %s empty Telegram posts for user %s", repaired, user_id
            )
    except Exception:
        logger.exception("Maintenance empty-post repair failed for user %s", user_id)
    try:
        await reconcile_channel_window(
            client,
            entity,
            user_id,
            settings,
            session_factory,
            force=True,
            include_new_scan=False,
            include_comments=False,
        )
    except Exception:
        logger.exception("Maintenance reconcile failed for user %s", user_id)
    try:
        probed = await probe_pending_comments_thread_flags(
            client,
            entity,
            user_id,
            session_factory,
            settings,
        )
        if probed:
            logger.debug(
                "Maintenance comments-thread probe updated %s posts for user %s",
                probed,
                user_id,
            )
    except Exception:
        logger.exception("Maintenance comments-thread probe failed for user %s", user_id)
    try:
        updated = await poll_recent_post_metrics(
            client, entity, user_id, settings, session_factory
        )
        if updated:
            logger.debug("Maintenance metrics poll updated %s posts for user %s", updated, user_id)
    except Exception:
        logger.exception("Maintenance metrics poll failed for user %s", user_id)


async def _channel_maintenance_loop(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
) -> None:
    """Periodic unified maintenance — one ingest lock, minimal MTProto RPC."""
    interval = max(20.0, settings.telegram_channel_maintenance_seconds)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=8.0)
        return
    except asyncio.TimeoutError:
        pass
    while not stop_event.is_set():
        try:

            async def _pass() -> None:
                await _run_channel_maintenance_pass(
                    client, entity, user_id, settings, session_factory
                )

            await run_channel_ingest(user_id, _pass)
        except Exception:
            logger.exception("Channel maintenance failed for user %s", user_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            return


async def _fast_catch_up_loop(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
) -> None:
    """Optional extra poll when ``telegram_live_sync_fast_poll_seconds`` > 0 (Docker clock skew)."""
    interval = settings.telegram_live_sync_fast_poll_seconds
    if interval <= 0:
        return
    interval = max(15.0, interval)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            return

        async def _pass() -> None:
            min_id = await _load_last_telegram_message_id(session_factory, user_id)
            if min_id <= 0:
                return
            await _catch_up(
                client,
                entity,
                user_id,
                settings,
                min_id,
                session_factory,
                lightweight=True,
            )

        try:
            await run_channel_ingest_if_idle(user_id, _pass, label="fast-poll")
        except Exception:
            logger.debug("Fast live-sync poll failed for user %s", user_id, exc_info=True)


async def _load_last_analytics_snapshot_at(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> float | None:
    """Seconds elapsed since the last analytics snapshot, or None when never taken."""
    from datetime import datetime, timezone

    async with session_factory() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            return None
        raw = (profile.telegram or {}).get("lastAnalyticsSnapshotAt")
    if not raw:
        return None
    try:
        captured = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - captured).total_seconds()


async def _analytics_snapshot_loop(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
) -> None:
    """Capture channel metric snapshots every ``telegram_analytics_snapshot_seconds``."""
    from app.services.analytics.analytics_snapshot import capture_channel_snapshot

    interval = settings.telegram_analytics_snapshot_seconds
    if interval <= 0:
        return
    interval = max(60.0, interval)

    # Take the first snapshot shortly after connect when the stored one is stale
    # (or missing) so a fresh deploy starts collecting history right away.
    elapsed = await _load_last_analytics_snapshot_at(session_factory, user_id)
    first_delay = 30.0 if elapsed is None or elapsed >= interval else interval - elapsed
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:

            async def _pass() -> None:
                await capture_channel_snapshot(
                    session_factory, user_id, client, entity, settings
                )

            await run_channel_ingest(user_id, _pass)
        except Exception:
            logger.exception("Analytics snapshot failed for user %s", user_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass


async def _periodic_clock_refresh_loop(
    client: Any,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Keep Telethon time_offset aligned — Docker VM clocks drift during long sessions."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60.0)
            return
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            await refresh_telethon_clock(client, settings)
        except Exception:
            logger.debug("Periodic Telethon clock refresh failed", exc_info=True)


async def _refresh_channel_message(client: Any, entity: Any, message: Any) -> Any:
    """Fetch the full channel message — edit events often carry a partial payload."""
    msg_id = getattr(message, "id", None)
    if not msg_id:
        return message
    try:
        fetched = await call_with_flood_wait(
            lambda: client.get_messages(entity, ids=msg_id)
        )
    except Exception:
        logger.debug("Failed to refresh message %s for live-sync edit", msg_id, exc_info=True)
        return message
    if not fetched:
        return message
    return fetched[0] if isinstance(fetched, (list, tuple)) else fetched


async def _probe_new_post_comments(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    telegram: dict[str, Any],
    telegram_message_id: str,
) -> None:
    """Confirm discussion root for a live-ingested post; never clear the live optimistic flag."""
    try:
        async with session_factory() as session:
            post = await _find_telegram_post(session, user_id, telegram_message_id)
            if post is None:
                return
            post_data = dict(post.data)
        if not comments_enabled(telegram):
            return
        try:
            channel_msg_id = int(telegram_message_id)
        except (TypeError, ValueError):
            return

        root_id = None
        for attempt in range(3):
            root_id, _confirmed_absent = await probe_discussion_root(
                client, entity, channel_msg_id, settings
            )
            if root_id is not None:
                break
            if attempt < 2:
                await asyncio.sleep(0.3)

        if root_id is None:
            return

        probed, changed = apply_comments_thread_probe(post_data, root_id)
        if not changed:
            return
        async with session_factory() as session:
            post = await _find_telegram_post(session, user_id, telegram_message_id)
            profile = await session.get(Profile, user_id)
            if post is None or profile is None:
                return
            post.data = probed
            flag_modified(post, "data")
            await touch_telegram_profile(session, profile)
            await session.commit()
    except Exception:
        logger.debug(
            "Background comment-thread probe failed for tg-%s user %s",
            telegram_message_id,
            user_id,
            exc_info=True,
        )


async def _enrich_live_post_media(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    telegram_message_id: str,
) -> None:
    try:
        post_data = await map_group_to_post(
            client,
            messages,
            user_id,
            settings,
            fetch_media=True,
        )
        if post_data is None or not post_data.get("media"):
            return
        async with session_factory() as session:
            await update_telegram_post(session, user_id, post_data)
            await session.commit()
    except Exception:
        logger.debug(
            "Background media enrich failed for tg-%s user %s",
            telegram_message_id,
            user_id,
            exc_info=True,
        )


async def _persist_group(
    client: Any,
    entity: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    telegram: dict[str, Any],
    *,
    update: bool = False,
) -> None:
    if not messages:
        return
    if not any(message_is_importable(m) for m in messages):
        return

    existing_media: list[dict[str, Any]] | None = None
    if update:
        msg_id = str(getattr(messages[0], "id", "") or "")
        if msg_id:
            async with session_factory() as session:
                existing = await _find_telegram_post(session, user_id, msg_id)
                if existing is not None:
                    raw = existing.data.get("media")
                    if isinstance(raw, list):
                        existing_media = [item for item in raw if isinstance(item, dict)]

    needs_media_fetch = any(getattr(message, "media", None) for message in messages)
    defer_media = should_defer_media_fetch(messages, update=update)
    post_data = await map_group_to_post(
        client,
        messages,
        user_id,
        settings,
        fetch_media=not defer_media,
        existing_media=existing_media if update else None,
    )
    if post_data is None:
        return
    refine_clock_from_live_message(client, messages[0], settings)
    if not update:
        async with session_factory() as session:
            profile = await session.get(Profile, user_id)
            if profile is not None:
                telegram = dict(profile.telegram or {})
        post_data = apply_initial_comments_thread_flag(post_data, telegram)
    async with session_factory() as session:
        if update:
            await update_telegram_post(session, user_id, post_data)
        else:
            await upsert_telegram_post(session, user_id, post_data)
        await session.commit()
    logger.info(
        "Live-sync %s post tg-%s for user %s",
        "updated" if update else "upserted",
        post_data.get("telegramMessageId"),
        user_id,
    )
    if not update:
        msg_id = str(post_data.get("telegramMessageId") or "")
        if msg_id:
            asyncio.create_task(
                _probe_new_post_comments(
                    client,
                    entity,
                    user_id,
                    settings,
                    session_factory,
                    telegram,
                    msg_id,
                )
            )
            if needs_media_fetch and defer_media:
                asyncio.create_task(
                    _enrich_live_post_media(
                        client,
                        messages,
                        user_id,
                        settings,
                        session_factory,
                        msg_id,
                    )
                )


async def _run_user_listener(user_id: UUID, stop_event: asyncio.Event) -> None:
    settings = get_settings()
    session_factory = _get_session_factory()

    while not stop_event.is_set():
        creds = await _load_listener_credentials(session_factory, user_id)
        if creds is None:
            return

        _telegram, api_id, api_hash, session_string, parsed, min_id = creds

        try:
            async with telegram_session_lock(user_id):
                if stop_event.is_set():
                    return

                client = build_client(api_id, api_hash, session_string)
                listener_registry.register_client(user_id, client)
                comment_buffer = DiscussionCommentBuffer(
                    client,
                    user_id,
                    session_factory,
                    settings=settings,
                    debounce_seconds=settings.telegram_comment_debounce_seconds,
                    on_error=lambda detail: set_sync_error(
                        user_id, detail, session_factory
                    ),
                )

                periodic_drift_task: asyncio.Task[None] | None = None
                clock_refresh_task: asyncio.Task[None] | None = None
                fast_poll_task: asyncio.Task[None] | None = None
                analytics_snapshot_task: asyncio.Task[None] | None = None
                try:
                    await connect_telegram_client(client, settings)
                    entity = await resolve_channel_entity(client, parsed, settings)
                    await reinforce_clock_after_telegram_rpc(client, settings)
                    metrics_buffer = MetricsThrottleBuffer(
                        client,
                        entity,
                        user_id,
                        session_factory,
                        min_interval_seconds=settings.telegram_metrics_min_sync_seconds,
                    )
                    album_buffer = AlbumBuffer(
                        settings.telegram_album_debounce_seconds,
                        lambda msgs: _persist_group(
                            client,
                            entity,
                            [m for m in msgs if message_is_importable(m)],
                            user_id,
                            settings,
                            session_factory,
                            _telegram,
                            update=False,
                        ),
                    )

                    async def _handle_message_edit(message: Any) -> None:
                        if not message_entities(message):
                            message = await _refresh_channel_message(client, entity, message)
                        if not message_is_importable(message):
                            return
                        gid = getattr(message, "grouped_id", None) or None
                        messages = [message]
                        if gid:
                            siblings = await call_with_flood_wait(
                                lambda: client.get_messages(entity, grouped_id=gid)
                            )
                            if siblings:
                                messages = list(siblings)
                        await _persist_group(
                            client,
                            entity,
                            messages,
                            user_id,
                            settings,
                            session_factory,
                            _telegram,
                            update=True,
                        )

                    @client.on(events.NewMessage(chats=entity))
                    async def on_new_message(event: events.NewMessage.Event) -> None:
                        try:
                            message = event.message
                            grouped_id = getattr(message, "grouped_id", None) or None
                            if grouped_id:
                                await album_buffer.add(message)
                                return
                            if not message_is_importable(message):
                                return
                            await album_buffer.add(message)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Live-sync NewMessage failed for user %s", user_id)
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.MessageEdited(chats=entity))
                    async def on_message_edited(event: events.MessageEdited.Event) -> None:
                        try:
                            if getattr(event.message, "edit_hide", False):
                                msg_id = int(getattr(event.message, "id", 0) or 0)
                                await metrics_buffer.mark_dirty(msg_id)
                                return
                            await _handle_message_edit(event.message)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Live-sync MessageEdited failed for user %s", user_id)
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.Raw(UpdateMessageReactions))
                    async def on_message_reactions(event: UpdateMessageReactions) -> None:
                        try:
                            await handle_live_message_reactions(event, metrics_buffer)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "Live-sync UpdateMessageReactions failed for user %s",
                                user_id,
                            )
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.Raw(UpdateChannelMessageViews))
                    async def on_channel_message_views(event: UpdateChannelMessageViews) -> None:
                        try:
                            await handle_live_channel_message_views(
                                event, entity, user_id, session_factory
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "Live-sync UpdateChannelMessageViews failed for user %s",
                                user_id,
                            )
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.Raw(UpdateChannelMessageForwards))
                    async def on_channel_message_forwards(
                        event: UpdateChannelMessageForwards,
                    ) -> None:
                        try:
                            await handle_live_channel_message_forwards(
                                event, entity, user_id, session_factory
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "Live-sync UpdateChannelMessageForwards failed for user %s",
                                user_id,
                            )
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.MessageDeleted(chats=entity))
                    async def on_message_deleted(event: events.MessageDeleted.Event) -> None:
                        try:
                            deleted_ids = getattr(event, "deleted_ids", None) or []
                            if not deleted_ids:
                                return
                            logger.info(
                                "Live-sync MessageDeleted for user %s: %s",
                                user_id,
                                deleted_ids,
                            )
                            async with session_factory() as session:
                                for msg_id in deleted_ids:
                                    await delete_telegram_post(session, user_id, str(msg_id))
                                await session.commit()
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Live-sync MessageDeleted failed for user %s", user_id)
                            await set_sync_error(user_id, str(exc), session_factory)

                    discussion_entity = None
                    discussion_chat_id = _telegram.get("discussionChatId")
                    if (
                        settings.telegram_live_comments_enabled
                        and discussion_chat_id
                        and _telegram.get("commentsEnabled")
                    ):
                        try:
                            from app.services.telegram.comments_flow import _discussion_peer_id

                            discussion_peer = _discussion_peer_id(discussion_chat_id)
                            discussion_entity = await with_timeout(
                                client.get_entity(discussion_peer), settings
                            )
                        except Exception:
                            logger.debug(
                                "Discussion group entity unavailable for user %s",
                                user_id,
                                exc_info=True,
                            )

                    if discussion_entity is not None:

                        @client.on(events.NewMessage(chats=discussion_entity))
                        async def on_discussion_message(
                            event: events.NewMessage.Event,
                        ) -> None:
                            try:
                                await comment_buffer.add(event.message)
                            except Exception as exc:  # noqa: BLE001
                                logger.exception(
                                    "Live-sync discussion NewMessage failed for user %s",
                                    user_id,
                                )
                                await set_sync_error(user_id, str(exc), session_factory)

                        @client.on(events.MessageEdited(chats=discussion_entity))
                        async def on_discussion_message_edited(
                            event: events.MessageEdited.Event,
                        ) -> None:
                            try:
                                await comment_buffer.add(event.message)
                            except Exception as exc:  # noqa: BLE001
                                logger.exception(
                                    "Live-sync discussion MessageEdited failed for user %s",
                                    user_id,
                                )
                                await set_sync_error(user_id, str(exc), session_factory)

                    async with session_factory() as session:
                        profile = await session.get(Profile, user_id)
                        if profile is not None:
                            from app.services.telegram.post_sync import touch_telegram_profile

                            await touch_telegram_profile(
                                session,
                                profile,
                                sync_status="listening",
                                sync_error="",
                                status_only=True,
                            )
                            await session.commit()
                    logger.info("Live-sync listening for user %s", user_id)

                    asyncio.create_task(
                        _startup_catch_up(
                            client,
                            entity,
                            user_id,
                            settings,
                            min_id,
                            session_factory,
                        )
                    )

                    periodic_drift_task = asyncio.create_task(
                        _channel_maintenance_loop(
                            client,
                            entity,
                            user_id,
                            settings,
                            session_factory,
                            stop_event,
                        )
                    )
                    clock_refresh_task = asyncio.create_task(
                        _periodic_clock_refresh_loop(client, settings, stop_event)
                    )
                    if settings.telegram_analytics_snapshot_seconds > 0:
                        analytics_snapshot_task = asyncio.create_task(
                            _analytics_snapshot_loop(
                                client,
                                entity,
                                user_id,
                                settings,
                                session_factory,
                                stop_event,
                            )
                        )
                    if settings.telegram_live_sync_fast_poll_seconds > 0:
                        fast_poll_task = asyncio.create_task(
                            _fast_catch_up_loop(
                                client,
                                entity,
                                user_id,
                                settings,
                                session_factory,
                                stop_event,
                            )
                        )

                    disconnect_task = asyncio.create_task(client.run_until_disconnected())
                    stop_wait = asyncio.create_task(stop_event.wait())
                    done, pending = await asyncio.wait(
                        {disconnect_task, stop_wait},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    if stop_event.is_set():
                        await album_buffer.flush_all()
                        await comment_buffer.flush()
                        await metrics_buffer.flush()
                        return
                except asyncio.CancelledError:
                    await album_buffer.flush_all()
                    await comment_buffer.flush()
                    await metrics_buffer.flush()
                    raise
                except telethon_errors.FloodWaitError as exc:
                    seconds = min(int(getattr(exc, "seconds", 0) or 0), 60)
                    logger.warning(
                        "Live-sync FloodWait for user %s (%ss) — backing off before reconnect",
                        user_id,
                        seconds,
                    )
                    await asyncio.sleep(max(1, seconds))
                except TelegramAuthError as exc:
                    if exc.status_code == 504:
                        logger.warning(
                            "Live-sync Telegram timeout for user %s: %s", user_id, exc.detail
                        )
                    else:
                        logger.exception("Live-sync listener error for user %s", user_id)
                        await set_sync_error(user_id, str(exc), session_factory)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Live-sync listener error for user %s", user_id)
                    await set_sync_error(user_id, str(exc), session_factory)
                finally:
                    if clock_refresh_task is not None:
                        clock_refresh_task.cancel()
                        try:
                            await clock_refresh_task
                        except asyncio.CancelledError:
                            pass
                    if fast_poll_task is not None:
                        fast_poll_task.cancel()
                        try:
                            await fast_poll_task
                        except asyncio.CancelledError:
                            pass
                    if analytics_snapshot_task is not None:
                        analytics_snapshot_task.cancel()
                        try:
                            await analytics_snapshot_task
                        except asyncio.CancelledError:
                            pass
                    if periodic_drift_task is not None:
                        periodic_drift_task.cancel()
                        try:
                            await periodic_drift_task
                        except asyncio.CancelledError:
                            pass
                    listener_registry.unregister_client(user_id, client)
                    await disconnect_safely(client)
        except asyncio.CancelledError:
            raise

        if stop_event.is_set():
            return
        await asyncio.sleep(settings.telegram_live_sync_reconnect_seconds)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    from app.db.session import async_session_factory

    return async_session_factory


async def telegram_live_sync_worker(
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event | None = None,
) -> None:
    settings = get_settings()
    if not settings.telegram_live_sync_enabled:
        logger.info("Telegram live-sync disabled — worker not started.")
        return

    logger.info("Telegram live-sync worker started.")
    await listener_registry.reconcile_from_db(session_factory)

    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            await listener_registry.reconcile_from_db(session_factory)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Telegram live-sync reconcile error: %s", exc)
        await asyncio.sleep(settings.telegram_live_sync_registry_refresh_seconds)

    for user_id in list(listener_registry._tasks.keys()):
        listener_registry.stop_user_listener(user_id)
    logger.info("Telegram live-sync worker stopped.")
