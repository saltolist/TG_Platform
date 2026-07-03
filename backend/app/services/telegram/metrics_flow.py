"""Lightweight Telegram post metrics sync (views, reactions, reposts)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services.telegram.message_mapping import (
    map_message_for_reconcile,
    telethon_message_fetchable,
)
from app.services.telegram.post_sync import (
    load_linked_posts_for_reconcile,
    update_telegram_post,
    _find_telegram_post,
)

logger = logging.getLogger(__name__)


def extract_reactions_list(msg_reactions: Any) -> list[dict[str, Any]]:
    """Map Telethon ``MessageReactions`` to platform reaction rows."""
    reactions: list[dict[str, Any]] = []
    if msg_reactions is None:
        return reactions
    for item in getattr(msg_reactions, "results", None) or []:
        count = int(getattr(item, "count", 0) or 0)
        if count <= 0:
            continue
        emoticon = getattr(getattr(item, "reaction", None), "emoticon", None)
        if emoticon:
            reactions.append({"emoji": str(emoticon), "count": count})
    return reactions


async def persist_metrics_for_message(
    session: AsyncSession,
    user_id: UUID,
    telegram_message_id: str,
    metrics: dict[str, Any],
    *,
    preserve_text: str,
) -> bool:
    """Write metrics for a linked post; returns True when the row changed."""
    existing = await _find_telegram_post(session, user_id, telegram_message_id)
    if existing is None or existing.data.get("status") == "deleted":
        return False
    before = dict(existing.data)
    await update_telegram_post(
        session,
        user_id,
        {
            "telegramMessageId": telegram_message_id,
            "text": preserve_text,
            "metrics": metrics,
        },
    )
    return dict(existing.data) != before


async def persist_metrics_from_fetched_message(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: UUID,
    message: Any,
    *,
    session: AsyncSession | None = None,
    commit: bool = True,
) -> bool:
    """Update DB metrics from a Telethon channel message object."""
    if not telethon_message_fetchable(message):
        return False
    post_data = map_message_for_reconcile(message)
    if post_data is None:
        return False
    msg_id = str(post_data.get("telegramMessageId") or "")
    if not msg_id:
        return False
    metrics = post_data.get("metrics")
    if not isinstance(metrics, dict):
        return False

    async def _apply(db: AsyncSession) -> bool:
        existing = await _find_telegram_post(db, user_id, msg_id)
        if existing is None:
            return False
        preserve_text = str(existing.data.get("text") or post_data.get("text") or "")
        return await persist_metrics_for_message(
            db,
            user_id,
            msg_id,
            metrics,
            preserve_text=preserve_text,
        )

    if session is not None:
        return await _apply(session)

    async with session_factory() as db:
        changed = await _apply(db)
        if changed and commit:
            await db.commit()
        return changed


async def persist_metrics_for_message_ids(
    client: Any,
    entity: Any,
    user_id: UUID,
    message_ids: list[int],
    session_factory: async_sessionmaker[AsyncSession],
    *,
    reaction_updates: dict[int, Any] | None = None,
) -> int:
    """Batch persist metrics — skips ``get_messages`` when reaction snapshots suffice."""
    if not message_ids:
        return 0

    reaction_updates = reaction_updates or {}
    fetch_ids: list[int] = []
    reactions_only: dict[int, list[dict[str, Any]]] = {}

    for msg_id in message_ids:
        snapshot = extract_reactions_list(
            getattr(reaction_updates.get(msg_id), "reactions", None)
        )
        if snapshot:
            reactions_only[msg_id] = snapshot
        else:
            fetch_ids.append(msg_id)

    fetched_by_id: dict[int, Any] = {}
    if fetch_ids:
        try:
            fetched = await client.get_messages(entity, ids=fetch_ids)
        except Exception:
            logger.debug("Batch get_messages for metrics failed", exc_info=True)
            fetched = None

        if fetched is not None:
            if not isinstance(fetched, (list, tuple)):
                fetched = [fetched]
            for message in fetched:
                if telethon_message_fetchable(message):
                    fetched_by_id[int(getattr(message, "id", 0))] = message

    updated = 0
    async with session_factory() as session:
        for msg_id in message_ids:
            message = fetched_by_id.get(msg_id)
            if telethon_message_fetchable(message):
                if await persist_metrics_from_fetched_message(
                    session_factory,
                    user_id,
                    message,
                    session=session,
                    commit=False,
                ):
                    updated += 1
                continue

            reactions = reactions_only.get(msg_id)
            if not reactions:
                continue
            existing = await _find_telegram_post(session, user_id, str(msg_id))
            if existing is None:
                continue
            old_metrics = dict(existing.data.get("metrics") or {})
            merged = {**old_metrics, "reactions": reactions}
            if merged == old_metrics:
                continue
            preserve_text = str(existing.data.get("text") or "")
            if await persist_metrics_for_message(
                session,
                user_id,
                str(msg_id),
                merged,
                preserve_text=preserve_text,
            ):
                updated += 1

        if updated:
            await session.commit()
    if updated:
        logger.debug(
            "Metrics sync updated %s posts for user %s (batch %s ids, %s RPC)",
            updated,
            user_id,
            len(message_ids),
            len(fetch_ids),
        )
    return updated


class MetricsThrottleBuffer:
    """Coalesce live metrics events — at most one Telegram RPC batch per interval."""

    def __init__(
        self,
        client: Any,
        entity: Any,
        user_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        min_interval_seconds: float,
    ) -> None:
        self._client = client
        self._entity = entity
        self._user_id = user_id
        self._session_factory = session_factory
        self._min_interval = max(0.0, min_interval_seconds)
        self._pending_ids: set[int] = set()
        self._pending_updates: dict[int, Any] = {}
        self._lock = asyncio.Lock()
        self._last_flush = 0.0
        self._scheduled_task: asyncio.Task[None] | None = None

    async def mark_dirty(self, msg_id: int, update: Any | None = None) -> None:
        if msg_id <= 0:
            return
        async with self._lock:
            self._pending_ids.add(msg_id)
            if update is not None:
                self._pending_updates[msg_id] = update
        if self._min_interval <= 0:
            await self._flush_now()
            return

        now = time.monotonic()
        async with self._lock:
            elapsed = now - self._last_flush
            if elapsed >= self._min_interval:
                if self._scheduled_task is not None and not self._scheduled_task.done():
                    self._scheduled_task.cancel()
                self._scheduled_task = asyncio.create_task(self._flush_now())
            elif self._scheduled_task is None or self._scheduled_task.done():
                delay = self._min_interval - elapsed
                self._scheduled_task = asyncio.create_task(self._delayed_flush(delay))

    async def _delayed_flush(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._flush_now()
        except asyncio.CancelledError:
            pass

    async def flush(self) -> None:
        await self._flush_now()

    async def _flush_now(self) -> None:
        from app.services.telegram.sync_coordination import ingest_lock_busy

        async with self._lock:
            if not self._pending_ids:
                return
            msg_ids = list(self._pending_ids)
            updates = dict(self._pending_updates)
            self._pending_ids.clear()
            self._pending_updates.clear()
            self._last_flush = time.monotonic()

        if ingest_lock_busy(self._user_id):
            async with self._lock:
                self._pending_ids.update(msg_ids)
                self._pending_updates.update(updates)
            if self._scheduled_task is None or self._scheduled_task.done():
                self._scheduled_task = asyncio.create_task(self._delayed_flush(1.0))
            return

        await persist_metrics_for_message_ids(
            self._client,
            self._entity,
            self._user_id,
            msg_ids,
            self._session_factory,
            reaction_updates=updates,
        )


async def handle_live_message_reactions(
    update: Any,
    buffer: MetricsThrottleBuffer,
) -> None:
    """Queue ``UpdateMessageReactions`` for throttled batch sync."""
    msg_id = int(getattr(update, "msg_id", 0) or 0)
    if msg_id <= 0:
        return
    await buffer.mark_dirty(msg_id, update)


async def poll_recent_post_metrics(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Batch-fetch metrics for the newest linked posts (fallback when live events drop)."""
    window = max(1, settings.telegram_metrics_poll_window)
    async with session_factory() as session:
        linked = await load_linked_posts_for_reconcile(session, user_id, window)
        message_ids: list[int] = []
        for post in linked:
            try:
                msg_id = int(post.data.get("telegramMessageId") or 0)
            except (TypeError, ValueError):
                continue
            if msg_id > 0:
                message_ids.append(msg_id)
    return await persist_metrics_for_message_ids(
        client,
        entity,
        user_id,
        message_ids,
        session_factory,
    )
