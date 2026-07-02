"""Window reconcile — compare linked platform posts with the live Telegram channel."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Post, Profile
from app.services.telegram.message_mapping import (
    collect_posts_from_iter,
    map_message_for_reconcile,
)
from app.services.telegram.post_sync import (
    _find_telegram_post,
    delete_telegram_post,
    load_linked_posts_for_reconcile,
    touch_telegram_profile,
    update_telegram_post,
    upsert_telegram_post,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_redis_client: Any | None = None
_redis_unavailable = False
_memory_throttle: dict[str, float] = {}


@dataclass
class ReconcileStats:
    checked: int = 0
    updated: int = 0
    deleted: int = 0
    imported: int = 0
    skipped_throttle: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "updated": self.updated,
            "deleted": self.deleted,
            "imported": self.imported,
            "skippedThrottle": self.skipped_throttle,
        }


def _throttle_key(user_id: UUID) -> str:
    return f"tg:reconcile:{user_id}"


async def _get_redis() -> Any | None:
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        from redis.asyncio import Redis

        settings = get_settings()
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:  # noqa: BLE001
        logger.warning("Redis unavailable for telegram reconcile throttle — using in-memory fallback")
        _redis_unavailable = True
        return None


def _memory_try_acquire(user_id: UUID, ttl: int) -> bool:
    key = str(user_id)
    now = time.monotonic()
    expires = _memory_throttle.get(key, 0.0)
    if expires > now:
        return False
    _memory_throttle[key] = now + ttl
    return True


async def try_acquire_reconcile_slot(
    user_id: UUID, settings: Settings, *, force: bool = False
) -> bool:
    if force:
        return True
    ttl = max(1, int(settings.telegram_reconcile_throttle_seconds))
    redis = await _get_redis()
    if redis is None:
        return _memory_try_acquire(user_id, ttl)
    acquired = await redis.set(_throttle_key(user_id), "1", nx=True, ex=ttl)
    return bool(acquired)


async def _fetch_messages_by_ids(
    client: Any, entity: Any, message_ids: list[int]
) -> dict[int, Any]:
    found: dict[int, Any] = {}
    for offset in range(0, len(message_ids), _BATCH_SIZE):
        chunk = message_ids[offset : offset + _BATCH_SIZE]
        try:
            fetched = await client.get_messages(entity, ids=chunk)
        except Exception:
            logger.debug("get_messages batch failed for ids %s", chunk, exc_info=True)
            continue
        if fetched is None:
            continue
        if not isinstance(fetched, (list, tuple)):
            fetched = [fetched]
        if len(fetched) == len(chunk):
            for msg_id, message in zip(chunk, fetched, strict=False):
                if message is not None:
                    found[msg_id] = message
        else:
            for message in fetched:
                if message is not None:
                    found[int(getattr(message, "id", 0))] = message
    return found


async def reconcile_channel_window(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    window: int | None = None,
    force: bool = False,
    include_new_scan: bool = True,
) -> ReconcileStats:
    stats = ReconcileStats()
    if not settings.telegram_reconcile_enabled:
        return stats

    if not await try_acquire_reconcile_slot(user_id, settings, force=force):
        stats.skipped_throttle = True
        logger.debug("Reconcile throttled for user %s", user_id)
        return stats

    window_size = window if window is not None else settings.telegram_reconcile_window

    async with session_factory() as session:
        linked_posts = await load_linked_posts_for_reconcile(session, user_id, window_size)
        message_ids: list[int] = []
        posts_by_msg_id: dict[int, Post] = {}
        for post in linked_posts:
            try:
                msg_id = int(post.data.get("telegramMessageId") or 0)
            except (TypeError, ValueError):
                continue
            if msg_id <= 0:
                continue
            message_ids.append(msg_id)
            posts_by_msg_id[msg_id] = post

        stats.checked = len(message_ids)
        tg_messages = await _fetch_messages_by_ids(client, entity, message_ids)

        profile = await session.get(Profile, user_id)
        if profile is None:
            return stats

        for msg_id, post in posts_by_msg_id.items():
            tg_message = tg_messages.get(msg_id)
            if tg_message is None:
                if post.data.get("status") == "published":
                    await delete_telegram_post(session, user_id, str(msg_id))
                    stats.deleted += 1
                continue

            post_data = map_message_for_reconcile(tg_message)
            if post_data is None:
                continue

            before = dict(post.data)
            await update_telegram_post(session, user_id, post_data)
            if dict(post.data) != before:
                stats.updated += 1

        if include_new_scan:
            scan_limit = settings.telegram_reconcile_new_scan_limit
            if scan_limit > 0:
                channel_posts = await collect_posts_from_iter(
                    client,
                    entity,
                    user_id,
                    settings,
                    limit=scan_limit,
                )
                for post_data in channel_posts:
                    msg_id = str(post_data.get("telegramMessageId") or "")
                    if not msg_id:
                        continue
                    existing = await _find_telegram_post(session, user_id, msg_id)
                    if existing is not None:
                        if existing.data.get("status") == "deleted":
                            continue
                        continue
                    await upsert_telegram_post(session, user_id, post_data)
                    stats.imported += 1

        await touch_telegram_profile(session, profile)
        await session.commit()

    logger.info(
        "Channel reconcile for user %s: checked=%s updated=%s deleted=%s imported=%s",
        user_id,
        stats.checked,
        stats.updated,
        stats.deleted,
        stats.imported,
    )
    return stats


async def maybe_reconcile_after_rpc(
    client: Any,
    entity: Any,
    user_id: UUID,
    settings: Settings,
    *,
    force: bool = False,
) -> None:
    """Best-effort reconcile after a short TG RPC; never raises."""
    try:
        from app.db.session import async_session_factory

        await reconcile_channel_window(
            client,
            entity,
            user_id,
            settings,
            async_session_factory,
            force=force,
        )
    except Exception:
        logger.exception("Channel reconcile after RPC failed for user %s", user_id)


async def run_manual_reconcile(profile: Profile, user_id: UUID) -> ReconcileStats:
    """Connect, reconcile the channel window, disconnect — for the manual API."""
    from app.services.telegram.channel_flow import parse_channel_input, resolve_channel_entity
    from app.services.telegram.mtproto_client import build_client
    from app.services.telegram.net import (
        TelegramAuthError,
        connect_telegram_client,
        decrypt_field,
        disconnect_safely,
        require_api_credentials,
    )
    from app.services.telegram.session_guard import exclusive_telegram_access
    from app.db.session import async_session_factory

    settings = get_settings()
    telegram = profile.telegram or {}

    if telegram.get("channelStatus") != "connected":
        raise TelegramAuthError("Сначала подключите канал", 400)
    if telegram.get("authStatus") not in ("authorized", "connected"):
        raise TelegramAuthError("Сначала авторизуйтесь в Telegram", 400)
    if telegram.get("importStatus") == "importing":
        raise TelegramAuthError("Дождитесь завершения импорта канала", 409)
    if telegram.get("syncMode") == "publish-only":
        raise TelegramAuthError("Режим «только публикация» — сверка недоступна", 400)

    api_id, api_hash = require_api_credentials(telegram, settings)
    session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
    parsed = parse_channel_input(str(telegram.get("channel") or ""))
    if not parsed or not session_string:
        raise TelegramAuthError("Не удалось подготовить сверку с каналом", 400)

    stats = ReconcileStats()
    async with exclusive_telegram_access(user_id):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            entity = await resolve_channel_entity(client, parsed, settings)
            stats = await reconcile_channel_window(
                client,
                entity,
                user_id,
                settings,
                async_session_factory,
                force=True,
            )
        finally:
            await disconnect_safely(client)
    return stats


async def reset_reconcile_throttle_storage() -> None:
    """Test helper — drop in-memory throttle state and redis connection."""
    global _redis_client, _redis_unavailable
    _memory_throttle.clear()
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _redis_unavailable = False


__all__ = [
    "ReconcileStats",
    "maybe_reconcile_after_rpc",
    "reconcile_channel_window",
    "reset_reconcile_throttle_storage",
    "run_manual_reconcile",
    "try_acquire_reconcile_slot",
]
