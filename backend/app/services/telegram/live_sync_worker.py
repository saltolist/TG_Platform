"""Long-lived Telethon listeners for live Telegram channel sync (Phase 3 / Step 3.5)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import events

from app.core.config import Settings, get_settings
from app.db.models import Profile
from app.services.telegram.channel_flow import (
    parse_channel_input,
    resolve_channel_entity,
)
from app.services.telegram.message_mapping import (
    collect_posts_from_iter,
    map_group_to_post,
    message_is_importable,
)
from app.services.telegram.mtproto_client import build_client
from app.services.telegram.net import (
    TelegramAuthError,
    connect_telegram_client,
    decrypt_field,
    disconnect_safely,
    require_api_credentials,
    with_timeout,
)
from app.services.telegram.post_sync import (
    delete_telegram_post,
    set_sync_error,
    update_telegram_post,
    upsert_telegram_post,
)
from app.services.telegram.session_guard import telegram_session_lock

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

    def is_running(self, user_id: UUID) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

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
            except asyncio.TimeoutError:
                logger.warning("Live-sync listener stop timed out for user %s", user_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._cleanup_user(user_id)

    def _cleanup_user(self, user_id: UUID) -> None:
        self._stop_events.pop(user_id, None)
        self._tasks.pop(user_id, None)

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


async def _catch_up(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    min_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if min_id <= 0:
        return
    posts = await collect_posts_from_iter(
        client,
        entity,
        user_id,
        settings,
        limit=settings.telegram_import_post_limit,
        min_id=min_id,
    )
    if not posts:
        return
    async with session_factory() as session:
        for post_data in posts:
            await upsert_telegram_post(session, user_id, post_data)
        await session.commit()


async def _refresh_channel_message(client: Any, entity: Any, message: Any) -> Any:
    """Fetch the full channel message — edit events often carry a partial payload."""
    msg_id = getattr(message, "id", None)
    if not msg_id:
        return message
    try:
        fetched = await client.get_messages(entity, ids=msg_id)
    except Exception:
        logger.debug("Failed to refresh message %s for live-sync edit", msg_id, exc_info=True)
        return message
    if not fetched:
        return message
    return fetched[0] if isinstance(fetched, (list, tuple)) else fetched


async def _persist_group(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    update: bool = False,
) -> None:
    if not messages:
        return
    if not any(message_is_importable(m) for m in messages):
        return
    post_data = await map_group_to_post(client, messages, user_id, settings)
    if post_data is None:
        return
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
                album_buffer = AlbumBuffer(
                    settings.telegram_album_debounce_seconds,
                    lambda msgs: _persist_group(
                        client,
                        [m for m in msgs if message_is_importable(m)],
                        user_id,
                        settings,
                        session_factory,
                        update=False,
                    ),
                )

                try:
                    await connect_telegram_client(client, settings)
                    entity = await resolve_channel_entity(client, parsed, settings)
                    await _catch_up(client, entity, user_id, settings, min_id, session_factory)

                    async def _handle_message_edit(message: Any) -> None:
                        message = await _refresh_channel_message(client, entity, message)
                        if not message_is_importable(message):
                            return
                        gid = getattr(message, "grouped_id", None) or None
                        messages = [message]
                        if gid:
                            siblings = await client.get_messages(entity, grouped_id=gid)
                            if siblings:
                                messages = list(siblings)
                        await _persist_group(
                            client,
                            messages,
                            user_id,
                            settings,
                            session_factory,
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
                            await _handle_message_edit(event.message)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Live-sync MessageEdited failed for user %s", user_id)
                            await set_sync_error(user_id, str(exc), session_factory)

                    @client.on(events.MessageDeleted(chats=entity))
                    async def on_message_deleted(event: events.MessageDeleted.Event) -> None:
                        try:
                            deleted_ids = getattr(event, "deleted_ids", None) or []
                            async with session_factory() as session:
                                for msg_id in deleted_ids:
                                    await delete_telegram_post(session, user_id, str(msg_id))
                                await session.commit()
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Live-sync MessageDeleted failed for user %s", user_id)
                            await set_sync_error(user_id, str(exc), session_factory)

                    async with session_factory() as session:
                        profile = await session.get(Profile, user_id)
                        if profile is not None:
                            from app.services.telegram.post_sync import touch_telegram_profile

                    await touch_telegram_profile(
                        session, profile, sync_status="listening", sync_error=""
                    )
                    await session.commit()
                    logger.info("Live-sync listening for user %s", user_id)

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
                        return
                except asyncio.CancelledError:
                    await album_buffer.flush_all()
                    raise
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
