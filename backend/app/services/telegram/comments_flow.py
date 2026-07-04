"""Bidirectional comment sync via Telegram linked discussion groups (Phase 3 / Step 5b)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from telethon import utils
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetDiscussionMessageRequest

from app.core.config import Settings, get_settings
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Post, Profile
from app.services.telegram.channel_flow import (
    channel_peer_id,
    parse_channel_input,
    resolve_channel_entity,
    resolve_channel_entity_for_profile,
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
from app.services.telegram.session_guard import exclusive_telegram_access
from app.services.telegram.media_storage import save_message_media
from app.services.telegram.post_sync import touch_telegram_profile
from app.services.telegram.text_formatting import apply_message_text_fields, extract_plain_text

logger = logging.getLogger(__name__)

PLATFORM_SELF_COMMENT_AUTHOR = "Вы"


def _preserve_comment_author(platform_author: Any, telegram_author: Any) -> str:
    """Keep the platform label for comments authored on-site."""
    if str(platform_author or "").strip() == PLATFORM_SELF_COMMENT_AUTHOR:
        return PLATFORM_SELF_COMMENT_AUTHOR
    if telegram_author:
        return str(telegram_author)
    return str(platform_author or "Пользователь")

_COMMENT_PROBE_ATTEMPTS = 3
_COMMENT_PROBE_DELAY_SECONDS = 0.3


@dataclass
class CommentSyncResult:
    comments: list[dict[str, Any]] | None = None
    telegram_discussion_message_id: str | None = None
    comments_thread_available: bool | None = None
    error: str | None = None


def comments_enabled(telegram: dict[str, Any]) -> bool:
    return bool(telegram.get("commentsEnabled")) and bool(telegram.get("discussionChatId"))


def require_comments_enabled(telegram: dict[str, Any]) -> None:
    if not comments_enabled(telegram):
        raise TelegramAuthError(
            "В канале не включены обсуждения — включите их в настройках Telegram",
            400,
        )


async def resolve_discussion_chat_id(
    client: Any, channel_entity: Any, settings: Settings
) -> int | None:
    try:
        full = await with_timeout(client(GetFullChannelRequest(channel_entity)), settings)
    except Exception:
        return None
    linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
    if linked is None:
        return None
    try:
        return int(linked)
    except (TypeError, ValueError):
        return None


def apply_discussion_settings(
    telegram: dict[str, Any], discussion_chat_id: int | None
) -> dict[str, Any]:
    """Merge linked discussion group fields into a telegram profile dict."""
    updated = dict(telegram)
    updated["discussionChatId"] = str(discussion_chat_id) if discussion_chat_id else ""
    updated["commentsEnabled"] = bool(discussion_chat_id)
    return updated


async def refresh_channel_comments_settings(
    client: Any,
    channel_entity: Any,
    telegram: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Re-read linked discussion group from Telegram (e.g. after channel goes public)."""
    discussion_chat_id = await resolve_discussion_chat_id(client, channel_entity, settings)
    return apply_discussion_settings(telegram, discussion_chat_id)


async def probe_comments_thread_for_post(
    client: Any,
    channel_entity: Any,
    post_data: dict[str, Any],
    telegram: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Probe discussion thread so comments UI can appear for ingested posts."""
    if not comments_enabled(telegram) or post_data.get("status") != "published":
        return post_data

    msg_id_raw = post_data.get("telegramMessageId")
    if not msg_id_raw:
        return post_data
    try:
        channel_msg_id = int(msg_id_raw)
    except (TypeError, ValueError):
        return post_data

    root_id = None
    confirmed_absent = False
    for attempt in range(_COMMENT_PROBE_ATTEMPTS):
        root_id, confirmed_absent = await probe_discussion_root(
            client, channel_entity, channel_msg_id, settings
        )
        if root_id is not None or confirmed_absent:
            break
        if attempt < _COMMENT_PROBE_ATTEMPTS - 1:
            await asyncio.sleep(_COMMENT_PROBE_DELAY_SECONDS)

    if root_id is not None:
        probed, _ = apply_comments_thread_probe(post_data, root_id)
        return probed
    if confirmed_absent:
        probed, _ = apply_comments_thread_probe(
            post_data, None, confirmed_absent=True
        )
        return probed

    # Linked discussion group exists but TG may not expose the thread instantly.
    optimistic = dict(post_data)
    optimistic["commentsThreadAvailable"] = True
    return optimistic


def apply_optimistic_comments_thread(
    post_data: dict[str, Any], telegram: dict[str, Any]
) -> dict[str, Any]:
    """Fast path for batch ingest — show comments UI without blocking on TG probe."""
    if not comments_enabled(telegram) or post_data.get("status") != "published":
        return post_data
    if post_data.get("commentsThreadAvailable") or post_data.get("telegramDiscussionMessageId"):
        return post_data
    optimistic = dict(post_data)
    optimistic["commentsThreadAvailable"] = True
    return optimistic


def apply_comments_thread_probe(
    post_data: dict[str, Any],
    root_id: int | None,
    *,
    confirmed_absent: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Set per-post comment thread availability from a Telegram probe."""
    updated = dict(post_data)
    if root_id is not None:
        updated["commentsThreadAvailable"] = True
        updated["telegramDiscussionMessageId"] = str(root_id)
        changed = post_data.get("commentsThreadAvailable") is not True or post_data.get(
            "telegramDiscussionMessageId"
        ) != str(root_id)
        return updated, changed

    if post_data.get("commentsThreadAvailable") or post_data.get("telegramDiscussionMessageId"):
        return post_data, False
    if not confirmed_absent:
        return post_data, False

    updated["commentsThreadAvailable"] = False
    updated.pop("telegramDiscussionMessageId", None)
    changed = post_data.get("commentsThreadAvailable") is not False or bool(
        post_data.get("telegramDiscussionMessageId")
    )
    return updated, changed


async def post_has_discussion_thread(
    client: Any,
    channel_entity: Any,
    channel_message_id: int,
    settings: Settings,
) -> bool:
    """True when Telegram has a discussion root for this channel post."""
    root_id = await get_discussion_root_message_id(
        client, channel_entity, channel_message_id, settings
    )
    return root_id is not None


def _discussion_peer_id(discussion_chat_id: int | str) -> int:
    try:
        value = int(discussion_chat_id)
    except (TypeError, ValueError):
        raise TelegramAuthError("Некорректный идентификатор группы обсуждений", 400) from None
    if value < 0:
        return value
    return int(f"-100{value}")


async def get_discussion_root_message_id(
    client: Any,
    channel_entity: Any,
    channel_message_id: int,
    settings: Settings,
) -> int | None:
    root_id, _confirmed_absent = await probe_discussion_root(
        client, channel_entity, channel_message_id, settings
    )
    return root_id


async def probe_discussion_root(
    client: Any,
    channel_entity: Any,
    channel_message_id: int,
    settings: Settings,
) -> tuple[int | None, bool]:
    """Return ``(root_id, confirmed_absent)``.

    ``confirmed_absent`` is True only when Telegram responded and the post clearly
    has no linked discussion thread. Network/timeouts are inconclusive (False).
    """
    try:
        result = await with_timeout(
            client(
                GetDiscussionMessageRequest(peer=channel_entity, msg_id=channel_message_id)
            ),
            settings,
        )
    except Exception:
        return None, False
    messages = list(getattr(result, "messages", None) or [])
    if not messages:
        return None, False

    try:
        channel_id = channel_peer_id(channel_entity)
    except (TypeError, ValueError):
        channel_id = None

    def _safe_peer_id(obj: Any) -> int | None:
        try:
            return utils.get_peer_id(obj)
        except (TypeError, ValueError, AttributeError):
            return None

    # A linked discussion group shows up as a second chat (a megagroup) distinct
    # from the broadcast channel itself. Its absence means the post has no
    # comment thread (e.g. published before discussions were enabled).
    discussion_chat_id = None
    has_discussion_group = False
    for chat in getattr(result, "chats", None) or []:
        if getattr(chat, "broadcast", False):
            continue
        if getattr(chat, "megagroup", False) or getattr(chat, "gigagroup", False):
            has_discussion_group = True
            discussion_chat_id = _safe_peer_id(chat)
            break
        peer = _safe_peer_id(chat)
        if peer is not None and channel_id is not None and peer != channel_id:
            has_discussion_group = True
            discussion_chat_id = peer
            break

    if not has_discussion_group:
        return None, True

    for message in messages:
        if (
            discussion_chat_id is not None
            and _safe_peer_id(getattr(message, "peer_id", None)) == discussion_chat_id
        ):
            msg_id = getattr(message, "id", None)
            if msg_id:
                return int(msg_id), False

    # Peers couldn't be resolved to ids (common in unit mocks and some
    # Telethon payloads); the discussion root is returned last, so fall back
    # to it now that we know a discussion group exists.
    root = messages[-1]
    msg_id = getattr(root, "id", None)
    if msg_id:
        return int(msg_id), False
    return None, False


def _message_date_iso(message: Any) -> str:
    date = getattr(message, "date", None)
    if date is None:
        return datetime.now(timezone.utc).isoformat()
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat()


def _sender_id(message: Any) -> int | None:
    """Best-effort stable sender id used to cache display names within a batch."""
    from_id = getattr(message, "from_id", None)
    for attr in ("user_id", "channel_id", "chat_id"):
        value = getattr(from_id, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    sender_id = getattr(message, "sender_id", None)
    if sender_id is not None:
        try:
            return int(sender_id)
        except (TypeError, ValueError):
            return None
    return None


def _format_sender_name(sender: Any) -> str:
    if sender is None:
        return "Пользователь"
    first = str(getattr(sender, "first_name", None) or "").strip()
    last = str(getattr(sender, "last_name", None) or "").strip()
    title = str(getattr(sender, "title", None) or "").strip()
    username = str(getattr(sender, "username", None) or "").strip()
    if first or last:
        return " ".join(part for part in (first, last) if part)
    if title:
        return title
    if username:
        return f"@{username.lstrip('@')}"
    return "Пользователь"


async def _sender_display_name(
    client: Any,
    message: Any,
    *,
    cache: dict[int, str] | None = None,
) -> str:
    """Resolve a comment author name, caching by sender id to avoid repeat RPCs.

    Under high comment volume many messages share the same author; caching by
    ``sender_id`` collapses N ``get_sender()`` round-trips into one per author.
    """
    if getattr(message, "out", False):
        return PLATFORM_SELF_COMMENT_AUTHOR

    sender_id = _sender_id(message)
    if cache is not None and sender_id is not None and sender_id in cache:
        return cache[sender_id]
    try:
        sender = await message.get_sender()
    except Exception:
        sender = None
    name = _format_sender_name(sender)
    if cache is not None and sender_id is not None:
        cache[sender_id] = name
    return name


def _reply_to_message_id(message: Any) -> int | None:
    reply_to = getattr(message, "reply_to", None)
    if reply_to is None:
        return None
    reply_msg_id = getattr(reply_to, "reply_to_msg_id", None)
    if reply_msg_id is None:
        return None
    try:
        return int(reply_msg_id)
    except (TypeError, ValueError):
        return None


def _comment_platform_id(message_id: int) -> str:
    return f"tg-{message_id}"


def normalize_post_comments(comments: Any) -> list[dict[str, Any]]:
    """Drop null optional fields so API JSON matches frontend schema."""
    if not isinstance(comments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in comments:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        if row.get("replyToId") is None:
            row.pop("replyToId", None)
        normalized.append(row)
    return normalized


def merge_patch_comments(
    previous: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply a client comments PATCH without dropping Telegram sync metadata.

    Retry flows may re-send a stale comments array that omits ``telegramMessageId``
    for rows already posted to the discussion group — preserve those ids from
    *previous* server state so we do not push duplicates to Telegram.
    """
    prev_by_id: dict[str, dict[str, Any]] = {}
    for item in previous:
        if not isinstance(item, Mapping):
            continue
        comment_id = str(item.get("id") or "")
        if comment_id:
            prev_by_id[comment_id] = dict(item)

    merged: list[dict[str, Any]] = []
    for item in incoming:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        comment_id = str(row.get("id") or "")
        prev = prev_by_id.get(comment_id)
        if prev is not None:
            if not row.get("telegramMessageId") and prev.get("telegramMessageId"):
                row["telegramMessageId"] = prev["telegramMessageId"]
            if not row.get("textHtml") and prev.get("textHtml"):
                row["textHtml"] = prev.get("textHtml")
        merged.append(row)
    return normalize_post_comments(merged)


def _comment_text_key(text: Any) -> str:
    return str(text or "").strip()


def _comment_media_signature(media: Any) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(media, list):
        return ()
    signature: list[tuple[str, str, str]] = []
    for item in media:
        if not isinstance(item, Mapping):
            continue
        signature.append(
            (
                str(item.get("kind") or ""),
                str(item.get("type") or ""),
                str(item.get("name") or ""),
            )
        )
    return tuple(signature)


def _comment_reply_key(comment: Mapping[str, Any]) -> str | None:
    reply = comment.get("replyToId")
    if reply is None:
        return None
    return str(reply)


def _parse_comment_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _comment_dates_close(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    max_delta_seconds: int = 600,
) -> bool:
    left_date = _parse_comment_date(left.get("date"))
    right_date = _parse_comment_date(right.get("date"))
    if left_date is None or right_date is None:
        return True
    return abs((left_date - right_date).total_seconds()) <= max_delta_seconds


def comments_probable_same(
    platform: Mapping[str, Any],
    telegram: Mapping[str, Any],
) -> bool:
    """True when a TG row is likely the same comment as a pending platform row."""
    if platform.get("telegramMessageId"):
        return False
    if not telegram.get("telegramMessageId"):
        return False
    if _comment_reply_key(platform) != _comment_reply_key(telegram):
        return False
    if _comment_text_key(platform.get("text")) != _comment_text_key(telegram.get("text")):
        return False
    if _comment_media_signature(platform.get("media")) != _comment_media_signature(
        telegram.get("media")
    ):
        return False
    if not _comment_text_key(platform.get("text")) and not _comment_media_signature(
        platform.get("media")
    ):
        return False
    return _comment_dates_close(platform, telegram)


def _link_pending_to_telegram(
    pending: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(pending)
    tg_id = str(incoming.get("telegramMessageId") or "")
    if tg_id:
        merged["telegramMessageId"] = tg_id
    for field in ("text", "date"):
        if incoming.get(field) is not None:
            merged[field] = incoming.get(field)
    if "textHtml" in incoming:
        incoming_html = incoming.get("textHtml")
        if incoming_html:
            merged["textHtml"] = incoming_html
        else:
            merged.pop("textHtml", None)
    if incoming.get("media") is not None:
        merged["media"] = incoming.get("media")
    reply = incoming.get("replyToId", merged.get("replyToId"))
    if reply is not None:
        merged["replyToId"] = reply
    else:
        merged.pop("replyToId", None)
    return merged


def _find_synced_telegram_twin(
    pending: Mapping[str, Any],
    comments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in comments:
        if not item.get("telegramMessageId"):
            continue
        if comments_probable_same(pending, item):
            return item
    return None


def _pair_pending_with_telegram(
    existing: list[dict[str, Any]],
    from_telegram: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    used_tg: set[str] = set()
    pairs: dict[str, dict[str, Any]] = {}
    for item in existing:
        if item.get("telegramMessageId"):
            continue
        platform_id = str(item.get("id") or "")
        if not platform_id:
            continue
        for incoming in from_telegram:
            tg_id = str(incoming.get("telegramMessageId") or "")
            if not tg_id or tg_id in used_tg:
                continue
            if comments_probable_same(item, incoming):
                pairs[platform_id] = dict(incoming)
                used_tg.add(tg_id)
                break
    return pairs


def dedupe_platform_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse pending + TG twins that already sit in the same list."""
    pending = [dict(item) for item in comments if not item.get("telegramMessageId")]
    with_tg = [dict(item) for item in comments if item.get("telegramMessageId")]
    by_tg = {str(item["telegramMessageId"]): item for item in with_tg}

    merged: list[dict[str, Any]] = []
    consumed_tg: set[str] = set()

    for item in pending:
        twin = _find_synced_telegram_twin(item, with_tg)
        if twin is None:
            merged.append(item)
            continue
        tg_id = str(twin.get("telegramMessageId") or "")
        merged.append(_link_pending_to_telegram(item, twin))
        consumed_tg.add(tg_id)

    for tg_id, item in by_tg.items():
        if tg_id not in consumed_tg:
            merged.append(item)

    merged.sort(key=lambda row: row.get("date") or "")
    return merged


def merge_comments(
    existing: list[dict[str, Any]],
    from_telegram: list[dict[str, Any]],
    *,
    prune_missing_synced: bool = False,
) -> list[dict[str, Any]]:
    """Merge TG comments with platform state.

    ``prune_missing_synced`` is only safe after a full Telegram pull. Live-sync
    passes partial batches, so missing ids there must not be treated as deletes.
    """
    by_tg_id: dict[str, dict[str, Any]] = {}
    for item in from_telegram:
        tg_id = str(item.get("telegramMessageId") or "")
        if tg_id:
            by_tg_id[tg_id] = dict(item)

    pending_pairs = _pair_pending_with_telegram(existing, from_telegram)

    merged: list[dict[str, Any]] = []
    seen_tg: set[str] = set()

    for item in existing:
        copy = dict(item)
        platform_id = str(copy.get("id") or "")
        if platform_id and platform_id in pending_pairs:
            incoming = pending_pairs[platform_id]
            merged.append(_link_pending_to_telegram(copy, incoming))
            tg_id = str(incoming.get("telegramMessageId") or "")
            if tg_id:
                seen_tg.add(tg_id)
            continue

        tg_id = str(copy.get("telegramMessageId") or "")
        if tg_id and tg_id in by_tg_id:
            incoming = by_tg_id[tg_id]
            reply_to_id = incoming.get("replyToId", copy.get("replyToId"))
            copy.update(
                {
                    "author": _preserve_comment_author(copy.get("author"), incoming.get("author")),
                    "text": incoming.get("text", copy.get("text")),
                    "date": incoming.get("date", copy.get("date")),
                }
            )
            if "textHtml" in incoming:
                incoming_html = incoming.get("textHtml")
                if incoming_html:
                    copy["textHtml"] = incoming_html
                else:
                    copy.pop("textHtml", None)
            if incoming.get("media") is not None:
                copy["media"] = incoming.get("media")
            if reply_to_id is not None:
                copy["replyToId"] = reply_to_id
            else:
                copy.pop("replyToId", None)
            merged.append(copy)
            seen_tg.add(tg_id)
        elif not tg_id:
            merged.append(copy)
        elif not prune_missing_synced:
            merged.append(copy)

    for item in from_telegram:
        tg_id = str(item.get("telegramMessageId") or "")
        if tg_id and tg_id not in seen_tg:
            merged.append(dict(item))

    return dedupe_platform_comments(merged)


async def map_telegram_messages_to_comments(
    client: Any,
    messages: list[Any],
    *,
    discussion_root_id: int,
    user_id: UUID,
    settings: Settings,
    existing: list[dict[str, Any]] | None = None,
    sender_cache: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    existing = existing or []
    platform_id_by_tg: dict[str, str] = {}
    for item in existing:
        tg_id = str(item.get("telegramMessageId") or "")
        if tg_id:
            platform_id_by_tg[tg_id] = str(item.get("id") or _comment_platform_id(int(tg_id)))

    sorted_messages = sorted(messages, key=lambda msg: getattr(msg, "id", 0))
    comments: list[dict[str, Any]] = []
    for message in sorted_messages:
        msg_id = int(getattr(message, "id", 0) or 0)
        if msg_id <= 0 or msg_id == discussion_root_id:
            continue
        reply_to = _reply_to_message_id(message)
        reply_to_id = None
        if reply_to and reply_to != discussion_root_id:
            parent_platform_id = platform_id_by_tg.get(str(reply_to))
            if parent_platform_id:
                reply_to_id = parent_platform_id
        text = extract_plain_text(message)
        if not text and getattr(message, "media", None) is None:
            continue
        platform_id = platform_id_by_tg.get(str(msg_id)) or _comment_platform_id(msg_id)
        platform_id_by_tg[str(msg_id)] = platform_id
        media_item = await save_message_media(client, message, user_id, settings)
        payload: dict[str, Any] = {
            "id": platform_id,
            "author": await _sender_display_name(client, message, cache=sender_cache),
            "text": text,
            "date": _message_date_iso(message),
            "telegramMessageId": str(msg_id),
        }
        apply_message_text_fields(payload, message)
        if reply_to_id is not None:
            payload["replyToId"] = reply_to_id
        if media_item is not None:
            payload["media"] = [media_item]
        comments.append(payload)
    return comments


async def fetch_comments_from_telegram(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    channel_message_id: int,
    user_id: UUID,
    settings: Settings,
    *,
    existing: list[dict[str, Any]] | None = None,
) -> tuple[int | None, list[dict[str, Any]], bool, bool]:
    root_id, confirmed_absent = await probe_discussion_root(
        client, channel_entity, channel_message_id, settings
    )
    if root_id is None:
        return None, [], confirmed_absent, False

    discussion_peer = _discussion_peer_id(discussion_chat_id)
    try:
        discussion_entity = await with_timeout(client.get_entity(discussion_peer), settings)
    except Exception:
        return root_id, [], False, False

    collected: list[Any] = []
    try:
        async for message in client.iter_messages(
            discussion_entity, reply_to=root_id, limit=200
        ):
            if getattr(message, "id", None) == root_id:
                continue
            collected.append(message)
    except Exception:
        return root_id, [], False, False

    comments = await map_telegram_messages_to_comments(
        client,
        collected,
        discussion_root_id=root_id,
        user_id=user_id,
        settings=settings,
        existing=existing,
    )
    return root_id, comments, False, True


def _local_media_path(url: Any, user_id: UUID, settings: Settings) -> str | None:
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    filename = url.rsplit("/", 1)[-1]
    if not filename:
        return None
    path = Path(settings.media_storage_root) / str(user_id) / filename
    return str(path) if path.is_file() else None


def _extract_sent_message_id(sent: Any) -> str:
    if isinstance(sent, (list, tuple)):
        sent = sent[0] if sent else None
    return str(getattr(sent, "id", "") or "")


async def _send_comment_message(
    client: Any,
    discussion_entity: Any,
    comment: dict[str, Any],
    reply_to: int,
    user_id: UUID,
    settings: Settings,
) -> str:
    text = str(comment.get("text") or "")
    media = comment.get("media")
    file_paths: list[str] = []
    if isinstance(media, list):
        for item in media:
            if not isinstance(item, Mapping):
                continue
            path = _local_media_path(item.get("url"), user_id, settings)
            if path:
                file_paths.append(path)

    if file_paths:
        if len(file_paths) == 1:
            sent = await client.send_file(
                discussion_entity, file_paths[0], caption=text, reply_to=reply_to
            )
        else:
            sent = await client.send_file(
                discussion_entity, file_paths, caption=text, reply_to=reply_to
            )
    else:
        sent = await client.send_message(discussion_entity, text, reply_to=reply_to)
    return _extract_sent_message_id(sent)


def removed_comment_telegram_message_ids(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[str]:
    """Telegram message ids for comments removed from the platform list."""
    current_ids = {
        str(item.get("id"))
        for item in current
        if isinstance(item, Mapping) and item.get("id")
    }
    removed: list[str] = []
    for item in previous:
        if not isinstance(item, Mapping):
            continue
        comment_id = str(item.get("id") or "")
        if not comment_id or comment_id in current_ids:
            continue
        tg_id = item.get("telegramMessageId")
        if tg_id:
            removed.append(str(tg_id))
    return removed


async def delete_discussion_comments_in_telegram(
    profile: Profile,
    discussion_chat_id: int | str,
    telegram_message_ids: list[str],
    user_id: UUID,
    settings: Settings | None = None,
) -> str | None:
    """Delete discussion comments in Telegram. Returns an error message or None."""
    from app.services.telegram.message_mapping import is_message_gone_error

    settings = settings or get_settings()
    msg_ids: list[int] = []
    for raw in telegram_message_ids:
        try:
            msg_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not msg_ids:
        return None

    try:
        async with _with_telegram_client(profile, user_id, settings) as (
            client,
            _channel_entity,
            _telegram,
        ):
            discussion_peer = _discussion_peer_id(discussion_chat_id)
            discussion_entity = await with_timeout(client.get_entity(discussion_peer), settings)
            try:
                await with_timeout(client.delete_messages(discussion_entity, msg_ids), settings)
            except TelegramAuthError as exc:
                if is_message_gone_error(exc):
                    return None
                return exc.detail
            except Exception as exc:  # noqa: BLE001
                if is_message_gone_error(exc):
                    return None
                return str(exc) or "Не удалось удалить комментарий в Telegram"
    except TelegramAuthError as exc:
        return exc.detail
    except Exception as exc:  # noqa: BLE001
        return str(exc) or "Не удалось удалить комментарий в Telegram"
    return None


def _find_pending_platform_comments(
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Comments authored on the platform that Telegram hasn't confirmed yet.

    This intentionally ignores whether the comment is brand new: a comment whose
    previous push failed (e.g. VPN/network drop) stays without ``telegramMessageId``
    and must be retried on the next sync instead of being stuck forever.
    """
    return [
        dict(item)
        for item in comments
        if isinstance(item, Mapping) and not item.get("telegramMessageId")
    ]


async def sync_new_comments_to_telegram(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    channel_message_id: int,
    post_data: dict[str, Any],
    new_comments: list[dict[str, Any]],
    user_id: UUID,
    settings: Settings,
) -> CommentSyncResult:
    if not new_comments:
        return CommentSyncResult(comments=list(post_data.get("comments") or []))

    root_id = post_data.get("telegramDiscussionMessageId")
    if root_id:
        try:
            root_id_int = int(root_id)
        except (TypeError, ValueError):
            root_id_int = None
    else:
        root_id_int = None
    if root_id_int is None:
        root_id_int = await get_discussion_root_message_id(
            client, channel_entity, channel_message_id, settings
        )
    if root_id_int is None:
        return CommentSyncResult(error="Не удалось найти обсуждение поста в Telegram")

    discussion_peer = _discussion_peer_id(discussion_chat_id)
    discussion_entity = await with_timeout(client.get_entity(discussion_peer), settings)

    comments = [dict(item) for item in post_data.get("comments") or []]
    by_id = {str(item.get("id")): item for item in comments if item.get("id")}

    for comment in new_comments:
        comment_id = str(comment.get("id") or "")
        twin = _find_synced_telegram_twin(comment, comments)
        if twin is not None:
            target = by_id.get(comment_id)
            if target is not None:
                target["telegramMessageId"] = str(twin.get("telegramMessageId") or "")
            continue

        reply_to = root_id_int
        parent_id = comment.get("replyToId")
        if parent_id:
            parent = by_id.get(str(parent_id))
            parent_tg = parent.get("telegramMessageId") if parent else None
            if parent_tg:
                try:
                    reply_to = int(parent_tg)
                except (TypeError, ValueError):
                    reply_to = root_id_int
        try:
            tg_msg_id = await with_timeout(
                _send_comment_message(
                    client,
                    discussion_entity,
                    comment,
                    reply_to,
                    user_id,
                    settings,
                ),
                settings,
            )
        except TelegramAuthError as exc:
            return CommentSyncResult(error=exc.detail)
        except Exception as exc:  # noqa: BLE001
            return CommentSyncResult(error=str(exc) or "Не удалось отправить комментарий")

        target = by_id.get(comment_id)
        if target is None:
            continue
        target["telegramMessageId"] = tg_msg_id

    return CommentSyncResult(
        comments=dedupe_platform_comments(comments),
        telegram_discussion_message_id=str(root_id_int),
    )


async def pull_comments_from_telegram(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    channel_message_id: int,
    user_id: UUID,
    post_data: dict[str, Any],
    settings: Settings,
) -> CommentSyncResult:
    existing = list(post_data.get("comments") or [])
    (
        root_id,
        from_tg,
        confirmed_absent,
        comments_complete,
    ) = await fetch_comments_from_telegram(
        client,
        channel_entity,
        discussion_chat_id,
        channel_message_id,
        user_id,
        settings,
        existing=existing,
    )
    if root_id is None:
        if confirmed_absent:
            return CommentSyncResult(comments=existing, comments_thread_available=False)
        return CommentSyncResult(comments=existing)
    merged = merge_comments(existing, from_tg, prune_missing_synced=comments_complete)
    return CommentSyncResult(
        comments=merged,
        telegram_discussion_message_id=str(root_id),
        comments_thread_available=True,
    )


@asynccontextmanager
async def _with_telegram_client(profile: Profile, user_id: UUID, settings: Settings):
    telegram = profile.telegram or {}
    require_comments_enabled(telegram)
    api_id, api_hash = require_api_credentials(telegram, settings)
    session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
    if not session_string:
        raise TelegramAuthError("Не удалось подготовить синхронизацию комментариев", 400)

    async with exclusive_telegram_access(
        user_id, listener_stop_timeout=settings.telegram_short_rpc_listener_stop_seconds
    ):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            channel_entity = await resolve_channel_entity_for_profile(
                client, telegram, settings
            )
            yield client, channel_entity, telegram
        finally:
            await disconnect_safely(client)


async def sync_post_comments_pull(
    profile: Profile,
    post_data: dict[str, Any],
    user_id: UUID,
    settings: Settings | None = None,
) -> CommentSyncResult:
    settings = settings or get_settings()
    telegram_message_id = post_data.get("telegramMessageId")
    if not telegram_message_id:
        return CommentSyncResult(comments=list(post_data.get("comments") or []))
    try:
        channel_msg_id = int(telegram_message_id)
    except (TypeError, ValueError):
        return CommentSyncResult(error="Некорректный идентификатор поста в Telegram")

    discussion_chat_id = (profile.telegram or {}).get("discussionChatId")
    if not discussion_chat_id:
        return CommentSyncResult(error="В канале не включены обсуждения")

    try:
        async with _with_telegram_client(profile, user_id, settings) as (
            client,
            channel_entity,
            _telegram,
        ):
            return await pull_comments_from_telegram(
                client,
                channel_entity,
                discussion_chat_id,
                channel_msg_id,
                user_id,
                post_data,
                settings,
            )
    except TelegramAuthError as exc:
        return CommentSyncResult(error=exc.detail)
    return CommentSyncResult(error="Не удалось подключиться к Telegram")


async def sync_post_comments_push(
    profile: Profile,
    post_data: dict[str, Any],
    user_id: UUID,
    settings: Settings | None = None,
) -> CommentSyncResult:
    settings = settings or get_settings()
    telegram_message_id = post_data.get("telegramMessageId")
    if not telegram_message_id:
        return CommentSyncResult(comments=list(post_data.get("comments") or []))
    try:
        channel_msg_id = int(telegram_message_id)
    except (TypeError, ValueError):
        return CommentSyncResult(error="Некорректный идентификатор поста в Telegram")

    discussion_chat_id = (profile.telegram or {}).get("discussionChatId")
    if not discussion_chat_id:
        return CommentSyncResult(
            error="В канале не включены обсуждения — включите их в настройках Telegram"
        )

    new_comments = _find_pending_platform_comments(list(post_data.get("comments") or []))
    if not new_comments:
        return CommentSyncResult(comments=list(post_data.get("comments") or []))

    try:
        async with _with_telegram_client(profile, user_id, settings) as (
            client,
            channel_entity,
            _telegram,
        ):
            return await sync_new_comments_to_telegram(
                client,
                channel_entity,
                discussion_chat_id,
                channel_msg_id,
                post_data,
                new_comments,
                user_id,
                settings,
            )
    except TelegramAuthError as exc:
        return CommentSyncResult(error=exc.detail)
    return CommentSyncResult(error="Не удалось подключиться к Telegram")


_comment_push_tasks: set[asyncio.Task[Any]] = set()
_comment_push_chains: dict[str, asyncio.Task[Any]] = {}


@dataclass
class _DiscussionOutboundJob:
    delete_telegram_message_ids: list[str]
    push_pending: bool
    delete_attempt: int = 0


_discussion_outbound_queues: dict[str, list[_DiscussionOutboundJob]] = {}


def _ensure_discussion_outbound_drain(user_id: UUID, post_key: str) -> None:
    existing = _comment_push_chains.get(post_key)
    if existing is not None and not existing.done():
        return

    async def drain_queue() -> None:
        previous = _comment_push_chains.get(post_key)
        current = asyncio.current_task()
        if previous is not None and previous is not current:
            try:
                await previous
            except Exception:
                pass
        while True:
            batch = _discussion_outbound_queues.pop(post_key, [])
            if not batch:
                break
            delete_ids: list[str] = []
            push_pending = False
            delete_attempt = 0
            for outbound in batch:
                delete_ids.extend(outbound.delete_telegram_message_ids)
                push_pending = push_pending or outbound.push_pending
                delete_attempt = max(delete_attempt, outbound.delete_attempt)
            if delete_ids:
                unique_delete_ids = list(dict.fromkeys(delete_ids))
                await _delete_discussion_comments_background(
                    user_id,
                    post_key,
                    unique_delete_ids,
                    delete_attempt=delete_attempt,
                )
            if push_pending:
                await push_pending_post_comments(user_id, post_key)

    task = asyncio.create_task(drain_queue())
    _comment_push_chains[post_key] = task
    _comment_push_tasks.add(task)

    def _cleanup(done: asyncio.Task[Any]) -> None:
        _comment_push_tasks.discard(done)
        if _comment_push_chains.get(post_key) is done:
            _comment_push_chains.pop(post_key, None)
        if _discussion_outbound_queues.get(post_key):
            _ensure_discussion_outbound_drain(user_id, post_key)

    task.add_done_callback(_cleanup)


def _enqueue_discussion_outbound(
    user_id: UUID,
    post_id: str,
    *,
    delete_telegram_message_ids: list[str] | None = None,
    push_pending: bool = False,
    delete_attempt: int = 0,
) -> None:
    """Serialize discussion outbound RPCs per post (one listener pause at a time)."""
    post_key = str(post_id)
    job = _DiscussionOutboundJob(
        delete_telegram_message_ids=list(delete_telegram_message_ids or []),
        push_pending=push_pending,
        delete_attempt=delete_attempt,
    )
    if not job.delete_telegram_message_ids and not job.push_pending:
        return

    _discussion_outbound_queues.setdefault(post_key, []).append(job)
    _ensure_discussion_outbound_drain(user_id, post_key)


async def _delete_discussion_comments_background(
    user_id: UUID,
    post_id: str,
    telegram_message_ids: list[str],
    *,
    delete_attempt: int = 0,
) -> None:
    from app.db.session import async_session_factory

    if not telegram_message_ids:
        return

    try:
        async with async_session_factory() as session:
            profile = await session.get(Profile, user_id)
            if profile is None:
                return
            telegram = profile.telegram or {}
            discussion_chat_id = telegram.get("discussionChatId")
            if not discussion_chat_id:
                return
            error = await delete_discussion_comments_in_telegram(
                profile,
                discussion_chat_id,
                telegram_message_ids,
                user_id,
            )
            if error:
                logger.warning(
                    "Background comment delete failed for post %s: %s",
                    post_id,
                    error,
                )
                if delete_attempt < 3:
                    _enqueue_discussion_outbound(
                        user_id,
                        post_id,
                        delete_telegram_message_ids=telegram_message_ids,
                        delete_attempt=delete_attempt + 1,
                    )
                return
            await touch_telegram_profile(
                session,
                profile,
                comment_only=True,
                comment_revision_delta=len(telegram_message_ids),
            )
            await session.commit()
    except Exception:
        logger.exception("Background comment delete crashed for post %s", post_id)
        if delete_attempt < 3:
            _enqueue_discussion_outbound(
                user_id,
                post_id,
                delete_telegram_message_ids=telegram_message_ids,
                delete_attempt=delete_attempt + 1,
            )


async def persist_comment_push_result(
    session: Any,
    post: Post,
    profile: Profile,
    comment_result: CommentSyncResult,
) -> dict[str, Any]:
    if comment_result.error:
        return {"commentSyncError": comment_result.error}
    if comment_result.comments is None:
        return {}
    updated = dict(post.data)
    updated["comments"] = normalize_post_comments(
        dedupe_platform_comments(comment_result.comments)
    )
    if comment_result.telegram_discussion_message_id:
        updated["telegramDiscussionMessageId"] = (
            comment_result.telegram_discussion_message_id
        )
        updated["commentsThreadAvailable"] = True
    post.data = updated
    flag_modified(post, "data")
    await touch_telegram_profile(session, profile, comment_only=True)
    await session.commit()
    return dict(updated)


async def push_pending_post_comments(user_id: UUID, post_id: str) -> None:
    from fastapi import HTTPException

    from app.db.resolve import get_owned_post
    from app.db.session import async_session_factory

    settings = get_settings()
    try:
        async with async_session_factory() as session:
            try:
                post = await get_owned_post(session, user_id, post_id)
            except HTTPException:
                return
            profile = await session.get(Profile, user_id)
            if profile is None:
                return
            post_data = dict(post.data)
            if post_data.get("status") != "published":
                return
            if not post_data.get("telegramMessageId"):
                return
            pending = _find_pending_platform_comments(list(post_data.get("comments") or []))
            if not pending:
                return

            comment_result = await sync_post_comments_push(
                profile, post_data, user_id, settings
            )
            if comment_result.error:
                logger.warning(
                    "Comment push failed for post %s: %s", post_id, comment_result.error
                )
                return
            await persist_comment_push_result(session, post, profile, comment_result)
    except Exception:
        logger.exception("Background comment push crashed for post %s", post_id)


def schedule_post_comments_push(user_id: UUID, post_id: str) -> None:
    """Push platform comments to Telegram without blocking the PATCH response."""
    _enqueue_discussion_outbound(user_id, post_id, push_pending=True)


def schedule_discussion_comments_delete(
    user_id: UUID,
    post_id: str,
    telegram_message_ids: list[str],
) -> None:
    """Delete discussion comments in Telegram without blocking the PATCH response."""
    _enqueue_discussion_outbound(
        user_id,
        post_id,
        delete_telegram_message_ids=telegram_message_ids,
    )


async def drain_scheduled_comment_pushes(timeout: float = 10.0) -> None:
    """Wait for in-flight background comment pushes (tests)."""
    pending = [task for task in _comment_push_tasks if not task.done()]
    if not pending:
        return
    _done, still_pending = await asyncio.wait(pending, timeout=timeout)
    for task in still_pending:
        task.cancel()


async def handle_live_discussion_message(
    client: Any,
    message: Any,
    user_id: UUID,
    session_factory: Any,
    settings: Settings | None = None,
) -> None:
    """Upsert one discussion-group message into the matching platform post."""
    await handle_live_discussion_messages(
        client, [message], user_id, session_factory, settings=settings
    )


async def handle_live_discussion_messages(
    client: Any,
    messages: list[Any],
    user_id: UUID,
    session_factory: Any,
    *,
    settings: Settings | None = None,
) -> None:
    """Upsert a batch of discussion messages, grouped per post.

    All comments for the same post are merged and persisted with a single
    commit (one ``syncRevision`` bump), so a burst of dozens of comments/sec
    does not translate into dozens of DB writes and frontend refetch signals.
    """
    from app.services.telegram.post_sync import (
        apply_discussion_comments,
        find_post_for_discussion_reply,
    )

    settings = settings or get_settings()

    if not messages:
        return

    messages_by_reply: dict[int, list[Any]] = {}
    for message in messages:
        reply_to = _reply_to_message_id(message)
        if reply_to is None:
            continue
        messages_by_reply.setdefault(reply_to, []).append(message)

    if not messages_by_reply:
        return

    sender_cache: dict[int, str] = {}

    async with session_factory() as session:
        # Multiple reply-to roots may resolve to the same post; collapse them.
        grouped_by_post: dict[Any, tuple[Any, int, list[Any]]] = {}
        for reply_to, thread_messages in messages_by_reply.items():
            post = await find_post_for_discussion_reply(session, user_id, reply_to)
            if post is None:
                continue
            root_raw = post.data.get("telegramDiscussionMessageId")
            try:
                root_id = int(root_raw) if root_raw else reply_to
            except (TypeError, ValueError):
                root_id = reply_to
            entry = grouped_by_post.get(post.id)
            if entry is None:
                grouped_by_post[post.id] = (post, root_id, list(thread_messages))
            else:
                entry[2].extend(thread_messages)

        changed_any = False
        for post, root_id, thread_messages in grouped_by_post.values():
            comments = await map_telegram_messages_to_comments(
                client,
                thread_messages,
                discussion_root_id=root_id,
                user_id=user_id,
                settings=settings,
                existing=list(post.data.get("comments") or []),
                sender_cache=sender_cache,
            )
            if not comments:
                continue
            changed = await apply_discussion_comments(
                session,
                user_id,
                post,
                comments,
                discussion_root_id=str(root_id),
            )
            changed_any = changed_any or changed

        if changed_any:
            await session.commit()


class DiscussionCommentBuffer:
    """Debounce inbound discussion-group comments and flush them in batches.

    A single flush persists every buffered comment for the channel with one DB
    transaction per affected post, so a burst of dozens of comments/sec is
    coalesced into a handful of writes and one ``syncRevision`` bump per post.
    """

    def __init__(
        self,
        client: Any,
        user_id: UUID,
        session_factory: Any,
        *,
        settings: Settings,
        debounce_seconds: float,
        on_error: Any | None = None,
    ) -> None:
        self._client = client
        self._user_id = user_id
        self._session_factory = session_factory
        self._settings = settings
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._on_error = on_error
        self._pending: list[Any] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None

    async def add(self, message: Any) -> None:
        async with self._lock:
            self._pending.append(message)
        if self._debounce_seconds <= 0:
            await self._flush_now()
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
            await self._flush_now()
        except asyncio.CancelledError:
            pass

    async def _flush_now(self) -> None:
        async with self._lock:
            batch = self._pending
            self._pending = []
        if not batch:
            return
        try:
            await handle_live_discussion_messages(
                self._client,
                batch,
                self._user_id,
                self._session_factory,
                settings=self._settings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Discussion comment batch flush failed for user %s", self._user_id
            )
            if self._on_error is not None:
                try:
                    await self._on_error(str(exc))
                except Exception:  # noqa: BLE001
                    logger.debug("Comment buffer on_error hook failed", exc_info=True)

    async def flush(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
        await self._flush_now()


async def reconcile_post_comments(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    user_id: UUID,
    post_data: dict[str, Any],
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    """Pull TG comments for one post; return updated post_data and whether it changed."""
    telegram_message_id = post_data.get("telegramMessageId")
    if not telegram_message_id:
        return post_data, False
    try:
        channel_msg_id = int(telegram_message_id)
    except (TypeError, ValueError):
        return post_data, False

    existing = list(post_data.get("comments") or [])
    (
        root_id,
        from_tg,
        confirmed_absent,
        comments_complete,
    ) = await fetch_comments_from_telegram(
        client,
        channel_entity,
        discussion_chat_id,
        channel_msg_id,
        user_id,
        settings,
        existing=existing,
    )
    probed, probe_changed = apply_comments_thread_probe(
        post_data, root_id, confirmed_absent=confirmed_absent
    )
    if root_id is None:
        return probed, probe_changed

    merged_comments = merge_comments(
        existing, from_tg, prune_missing_synced=comments_complete
    )
    updated = dict(probed)
    updated["comments"] = merged_comments
    changed = probe_changed or merged_comments != existing
    return updated, changed


async def map_single_discussion_message(
    client: Any,
    message: Any,
    *,
    discussion_root_id: int,
    user_id: UUID,
    settings: Settings,
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Map one live-sync discussion message to a platform comment dict."""
    comments = await map_telegram_messages_to_comments(
        client,
        [message],
        discussion_root_id=discussion_root_id,
        user_id=user_id,
        settings=settings,
        existing=existing,
    )
    return comments[0] if comments else None


__all__ = [
    "CommentSyncResult",
    "DiscussionCommentBuffer",
    "apply_comments_thread_probe",
    "apply_optimistic_comments_thread",
    "comments_enabled",
    "comments_probable_same",
    "delete_discussion_comments_in_telegram",
    "drain_scheduled_comment_pushes",
    "fetch_comments_from_telegram",
    "get_discussion_root_message_id",
    "handle_live_discussion_message",
    "handle_live_discussion_messages",
    "map_single_discussion_message",
    "map_telegram_messages_to_comments",
    "merge_comments",
    "merge_patch_comments",
    "normalize_post_comments",
    "post_has_discussion_thread",
    "probe_discussion_root",
    "probe_comments_thread_for_post",
    "pull_comments_from_telegram",
    "refresh_channel_comments_settings",
    "reconcile_post_comments",
    "removed_comment_telegram_message_ids",
    "resolve_discussion_chat_id",
    "schedule_discussion_comments_delete",
    "schedule_post_comments_push",
    "sync_new_comments_to_telegram",
    "sync_post_comments_pull",
    "sync_post_comments_push",
]
