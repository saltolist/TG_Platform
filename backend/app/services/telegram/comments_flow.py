"""Bidirectional comment sync via Telegram linked discussion groups (Phase 3 / Step 5b)."""

from __future__ import annotations

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
from app.db.models import Profile
from app.services.telegram.channel_flow import (
    channel_peer_id,
    parse_channel_input,
    resolve_channel_entity,
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


@dataclass
class CommentSyncResult:
    comments: list[dict[str, Any]] | None = None
    telegram_discussion_message_id: str | None = None
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
    try:
        result = await with_timeout(
            client(
                GetDiscussionMessageRequest(peer=channel_entity, msg_id=channel_message_id)
            ),
            settings,
        )
    except Exception:
        return None
    messages = list(getattr(result, "messages", None) or [])
    if not messages:
        return None
    discussion_peer = None
    discussion_chat_id = None
    for chat in getattr(result, "chats", None) or []:
        try:
            if utils.get_peer_id(chat) != channel_peer_id(channel_entity):
                discussion_peer = chat
                discussion_chat_id = utils.get_peer_id(chat)
                break
        except (TypeError, ValueError):
            continue
    for message in messages:
        try:
            peer = utils.get_peer_id(getattr(message, "peer_id", None))
        except (TypeError, ValueError):
            peer = None
        if discussion_chat_id is not None and peer == discussion_chat_id:
            msg_id = getattr(message, "id", None)
            if msg_id:
                return int(msg_id)
    if len(messages) >= 2:
        root = messages[-1]
        msg_id = getattr(root, "id", None)
        if msg_id:
            return int(msg_id)
    root = messages[0]
    msg_id = getattr(root, "id", None)
    return int(msg_id) if msg_id else None


def _message_date_iso(message: Any) -> str:
    date = getattr(message, "date", None)
    if date is None:
        return datetime.now(timezone.utc).isoformat()
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat()


async def _sender_display_name(client: Any, message: Any) -> str:
    try:
        sender = await message.get_sender()
    except Exception:
        sender = None
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


def merge_comments(
    existing: list[dict[str, Any]],
    from_telegram: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge TG comments with platform state; keep pending platform-only comments."""
    by_tg_id: dict[str, dict[str, Any]] = {}
    for item in from_telegram:
        tg_id = str(item.get("telegramMessageId") or "")
        if tg_id:
            by_tg_id[tg_id] = dict(item)

    merged: list[dict[str, Any]] = []
    seen_tg: set[str] = set()

    for item in existing:
        copy = dict(item)
        tg_id = str(copy.get("telegramMessageId") or "")
        if tg_id and tg_id in by_tg_id:
            incoming = by_tg_id[tg_id]
            copy.update(
                {
                    "author": incoming.get("author", copy.get("author")),
                    "text": incoming.get("text", copy.get("text")),
                    "date": incoming.get("date", copy.get("date")),
                    "replyToId": incoming.get("replyToId", copy.get("replyToId")),
                }
            )
            merged.append(copy)
            seen_tg.add(tg_id)
        elif not tg_id:
            merged.append(copy)
        else:
            merged.append(copy)

    for item in from_telegram:
        tg_id = str(item.get("telegramMessageId") or "")
        if tg_id and tg_id not in seen_tg:
            merged.append(dict(item))

    merged.sort(key=lambda row: row.get("date") or "")
    return merged


async def map_telegram_messages_to_comments(
    client: Any,
    messages: list[Any],
    *,
    discussion_root_id: int,
    existing: list[dict[str, Any]] | None = None,
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
        text = str(getattr(message, "message", None) or "").strip()
        if not text and getattr(message, "media", None) is None:
            continue
        platform_id = platform_id_by_tg.get(str(msg_id)) or _comment_platform_id(msg_id)
        platform_id_by_tg[str(msg_id)] = platform_id
        comments.append(
            {
                "id": platform_id,
                "author": await _sender_display_name(client, message),
                "text": text,
                "date": _message_date_iso(message),
                "telegramMessageId": str(msg_id),
                **({"replyToId": reply_to_id} if reply_to_id else {}),
            }
        )
    return comments


async def fetch_comments_from_telegram(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    channel_message_id: int,
    settings: Settings,
    *,
    existing: list[dict[str, Any]] | None = None,
) -> tuple[int | None, list[dict[str, Any]]]:
    root_id = await get_discussion_root_message_id(
        client, channel_entity, channel_message_id, settings
    )
    if root_id is None:
        return None, []

    discussion_peer = _discussion_peer_id(discussion_chat_id)
    try:
        discussion_entity = await with_timeout(client.get_entity(discussion_peer), settings)
    except Exception:
        return root_id, []

    collected: list[Any] = []
    try:
        async for message in client.iter_messages(
            discussion_entity, reply_to=root_id, limit=200
        ):
            if getattr(message, "id", None) == root_id:
                continue
            collected.append(message)
    except Exception:
        collected = []

    comments = await map_telegram_messages_to_comments(
        client,
        collected,
        discussion_root_id=root_id,
        existing=existing,
    )
    return root_id, comments


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


def _find_new_platform_comments(
    previous: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    previous_ids = {str(item.get("id")) for item in previous if item.get("id")}
    new_items = [
        dict(item)
        for item in current
        if str(item.get("id") or "") not in previous_ids
        and not item.get("telegramMessageId")
    ]
    return new_items


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
        comments=comments,
        telegram_discussion_message_id=str(root_id_int),
    )


async def pull_comments_from_telegram(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
    channel_message_id: int,
    post_data: dict[str, Any],
    settings: Settings,
) -> CommentSyncResult:
    existing = list(post_data.get("comments") or [])
    root_id, from_tg = await fetch_comments_from_telegram(
        client,
        channel_entity,
        discussion_chat_id,
        channel_message_id,
        settings,
        existing=existing,
    )
    if root_id is None:
        return CommentSyncResult(comments=existing)
    merged = merge_comments(existing, from_tg)
    return CommentSyncResult(
        comments=merged,
        telegram_discussion_message_id=str(root_id),
    )


@asynccontextmanager
async def _with_telegram_client(profile: Profile, user_id: UUID, settings: Settings):
    telegram = profile.telegram or {}
    require_comments_enabled(telegram)
    api_id, api_hash = require_api_credentials(telegram, settings)
    session_string = decrypt_field(str(telegram.get("sessionString") or ""), settings)
    parsed = parse_channel_input(str(telegram.get("channel") or ""))
    if not parsed or not session_string:
        raise TelegramAuthError("Не удалось подготовить синхронизацию комментариев", 400)

    async with exclusive_telegram_access(
        user_id, listener_stop_timeout=settings.telegram_short_rpc_listener_stop_seconds
    ):
        client = build_client(api_id, api_hash, session_string)
        try:
            await connect_telegram_client(client, settings)
            channel_entity = await resolve_channel_entity(client, parsed, settings)
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
            post_data,
            settings,
        )
    return CommentSyncResult(error="Не удалось подключиться к Telegram")


async def sync_post_comments_push(
    profile: Profile,
    post_data: dict[str, Any],
    previous_comments: list[dict[str, Any]],
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

    new_comments = _find_new_platform_comments(
        previous_comments, list(post_data.get("comments") or [])
    )
    if not new_comments:
        return CommentSyncResult(comments=list(post_data.get("comments") or []))

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
    return CommentSyncResult(error="Не удалось подключиться к Telegram")


async def handle_live_discussion_message(
    client: Any,
    message: Any,
    user_id: UUID,
    session_factory: Any,
) -> None:
    """Upsert one discussion-group message into the matching platform post."""
    from app.services.telegram.post_sync import (
        apply_discussion_comment,
        find_post_for_discussion_reply,
    )

    reply_to = _reply_to_message_id(message)
    if reply_to is None:
        return

    async with session_factory() as session:
        post = await find_post_for_discussion_reply(session, user_id, reply_to)
        if post is None:
            return

        root_raw = post.data.get("telegramDiscussionMessageId")
        try:
            root_id = int(root_raw) if root_raw else reply_to
        except (TypeError, ValueError):
            root_id = reply_to

        comment = await map_single_discussion_message(
            client,
            message,
            discussion_root_id=root_id,
            existing=list(post.data.get("comments") or []),
        )
        if comment is None:
            return

        changed = await apply_discussion_comment(
            session,
            user_id,
            post,
            comment,
            discussion_root_id=str(root_id),
        )
        if changed:
            await session.commit()


async def reconcile_post_comments(
    client: Any,
    channel_entity: Any,
    discussion_chat_id: int | str,
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
    root_id, from_tg = await fetch_comments_from_telegram(
        client,
        channel_entity,
        discussion_chat_id,
        channel_msg_id,
        settings,
        existing=existing,
    )
    if root_id is None:
        return post_data, False

    merged_comments = merge_comments(existing, from_tg)
    updated = dict(post_data)
    updated["comments"] = merged_comments
    updated["telegramDiscussionMessageId"] = str(root_id)
    changed = merged_comments != existing or post_data.get(
        "telegramDiscussionMessageId"
    ) != str(root_id)
    return updated, changed


async def map_single_discussion_message(
    client: Any,
    message: Any,
    *,
    discussion_root_id: int,
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Map one live-sync discussion message to a platform comment dict."""
    comments = await map_telegram_messages_to_comments(
        client,
        [message],
        discussion_root_id=discussion_root_id,
        existing=existing,
    )
    return comments[0] if comments else None


__all__ = [
    "CommentSyncResult",
    "comments_enabled",
    "fetch_comments_from_telegram",
    "get_discussion_root_message_id",
    "handle_live_discussion_message",
    "map_single_discussion_message",
    "map_telegram_messages_to_comments",
    "merge_comments",
    "pull_comments_from_telegram",
    "reconcile_post_comments",
    "require_comments_enabled",
    "resolve_discussion_chat_id",
    "sync_new_comments_to_telegram",
    "sync_post_comments_pull",
    "sync_post_comments_push",
]
