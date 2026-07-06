"""Tests for bidirectional Telegram comment sync (Phase 3 / Step 5b)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db import session as db_session_module
from app.db.models import Post, Profile
from app.services.telegram import mtproto_client
from app.services.telegram.comments_flow import (
    DiscussionCommentBuffer,
    apply_comments_thread_probe,
    apply_initial_comments_thread_flag,
    dedupe_platform_comments,
    drain_scheduled_comment_pushes,
    get_discussion_root_message_id,
    handle_live_discussion_messages,
    merge_comments,
    merge_patch_comments,
    map_telegram_messages_to_comments,
    normalize_post_comments,
    refresh_channel_comments_settings,
    removed_comment_telegram_message_ids,
)
from app.services.telegram.reconcile_flow import reconcile_channel_window
from tests.conftest import TestSessionLocal, sample_post, writer_auth_headers

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"
TELEGRAM_MESSAGE_ID = "501"
DISCUSSION_ROOT_ID = 9001
DISCUSSION_CHAT_ID = "123456789"


class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class CommentScenario:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.discussion_messages: list[Any] = []
        self.fail_send: Exception | None = None


SCENARIO = CommentScenario()


class CommentFakeTelegramClient:
    def __init__(self, session: Any, api_id: int, api_hash: str, **kwargs: Any) -> None:
        self.session = session

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_entity(self, handle: Any) -> SimpleNamespace:
        if str(handle).startswith("-100"):
            return SimpleNamespace(id=123456789, title="Discussion", megagroup=True)
        return SimpleNamespace(id=555, title="Comment Channel", broadcast=True)

    async def __call__(self, request: Any) -> Any:
        cls_name = type(request).__name__
        if cls_name == "GetDiscussionMessageRequest":
            root = SimpleNamespace(
                id=DISCUSSION_ROOT_ID,
                peer_id=SimpleNamespace(channel_id=123456789),
                message="Discussion root",
            )
            return SimpleNamespace(
                messages=[root],
                chats=[
                    SimpleNamespace(id=555, broadcast=True, title="Channel"),
                    SimpleNamespace(id=123456789, megagroup=True, title="Discussion"),
                ],
            )
        if cls_name == "GetFullChannelRequest":
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=int(DISCUSSION_CHAT_ID))
            )
        raise AssertionError(f"Unexpected request: {cls_name}")

    async def iter_messages(self, entity: Any, reply_to: int | None = None, limit: int = 200):
        for message in SCENARIO.discussion_messages:
            reply = getattr(message, "reply_to", None)
            if reply_to is None or reply is None:
                continue
            if reply.reply_to_msg_id == reply_to:
                yield message

    async def send_message(self, entity: Any, text: str, reply_to: int | None = None) -> Any:
        if SCENARIO.fail_send is not None:
            raise SCENARIO.fail_send
        msg_id = 7000 + len(SCENARIO.sent)
        SCENARIO.sent.append({"text": text, "reply_to": reply_to, "msg_id": msg_id})
        return SimpleNamespace(id=msg_id)

    async def send_file(self, entity: Any, file: Any, caption: str = "", reply_to: int | None = None):
        return await self.send_message(entity, caption, reply_to=reply_to)


@pytest.fixture(autouse=True)
async def _patch_comment_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    SCENARIO.sent = []
    SCENARIO.discussion_messages = []
    SCENARIO.fail_send = None
    monkeypatch.setattr(mtproto_client, "StringSession", FakeStringSession)
    monkeypatch.setattr(mtproto_client, "TelegramClient", CommentFakeTelegramClient)
    monkeypatch.setattr(db_session_module, "async_session_factory", TestSessionLocal)

    # The real clock-sync probe opens an httpx client that outlives the test's
    # event loop (NullPool + session-scoped loop), causing a flaky
    # "Event loop is closed" teardown in whichever comment test runs second.
    # Comment sync doesn't depend on it, so stub it out for these tests.
    async def _no_offset() -> None:
        return None

    monkeypatch.setattr(
        "app.services.telegram.net.measure_http_time_offset_seconds", _no_offset
    )

    # telegram_sync_pending caches a module-global Redis client. With a
    # session-scoped event loop, a client created in one test is bound to that
    # test's loop and raises "attached to a different loop" in the next test
    # that pushes comments. Reset it before and after each test so it re-binds.
    from app.services.telegram.sync_pending import reset_sync_pending_storage

    await reset_sync_pending_storage()
    yield
    await reset_sync_pending_storage()


def _connected_telegram_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "",
        "sessionName": "",
        "sessionString": SESSION_VALUE,
        "channel": "@commentchannel",
        "channelTitle": "Comment Channel",
        "channelId": "-100555",
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 1,
        "importStatus": "done",
        "importError": "",
        "lastTelegramMessageId": TELEGRAM_MESSAGE_ID,
        "syncStatus": "idle",
        "syncError": "",
        "syncRevision": 0,
        "discussionChatId": DISCUSSION_CHAT_ID,
        "commentsEnabled": True,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    payload.update(overrides)
    return payload


async def _seed_connected_profile(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> None:
    resp = await client.put(
        "/api/v1/profile/telegram/",
        headers=headers,
        json=_connected_telegram_payload(**overrides),
    )
    assert resp.status_code == 200


async def _create_published_post(
    client: AsyncClient, headers: dict[str, str], *, comments: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Channel post")
    payload["status"] = "published"
    payload["telegramMessageId"] = TELEGRAM_MESSAGE_ID
    payload["source"] = "telegram"
    if comments is not None:
        payload["comments"] = comments
    resp = await client.post("/api/v1/posts/", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


async def _post_after_comment_push(
    client: AsyncClient, post_id: str, headers: dict[str, str]
) -> dict[str, Any]:
    await drain_scheduled_comment_pushes()
    response = await client.get(f"/api/v1/posts/{post_id}/", headers=headers)
    assert response.status_code == 200
    return response.json()


def _discussion_message(
    msg_id: int,
    *,
    text: str,
    reply_to: int,
    author: str,
) -> SimpleNamespace:
    message = SimpleNamespace(
        id=msg_id,
        message=text,
        date=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        reply_to=SimpleNamespace(reply_to_msg_id=reply_to),
        media=None,
    )

    async def get_sender(_self: Any = message) -> SimpleNamespace:
        return SimpleNamespace(first_name=author, last_name="", title="", username="")

    message.get_sender = get_sender
    return message


@pytest.mark.asyncio
async def test_normalize_post_comments_drops_null_reply_to_id() -> None:
    normalized = normalize_post_comments(
        [
            {
                "id": "local-1",
                "author": "Вы",
                "text": "Pending",
                "date": "2026-01-01T00:00:00Z",
                "replyToId": None,
            }
        ]
    )
    assert normalized[0]["id"] == "local-1"
    assert "replyToId" not in normalized[0]


def test_apply_comments_thread_probe_clears_optimistic_true_when_absent() -> None:
    post = {
        "status": "published",
        "telegramMessageId": "501",
        "commentsThreadAvailable": True,
    }
    updated, changed = apply_comments_thread_probe(post, None, confirmed_absent=True)
    assert changed is True
    assert updated["commentsThreadAvailable"] is False
    assert "commentsThreadLiveOptimistic" not in updated


def test_apply_comments_thread_probe_keeps_optimistic_true_when_inconclusive() -> None:
    post = {
        "status": "published",
        "telegramMessageId": "501",
        "commentsThreadAvailable": True,
    }
    updated, changed = apply_comments_thread_probe(post, None, confirmed_absent=False)
    assert changed is False
    assert updated is post


def test_apply_initial_comments_thread_flag_optimistic_for_enabled_channel() -> None:
    post = {"status": "published", "telegramMessageId": "501"}
    telegram = {"commentsEnabled": True, "discussionChatId": "123"}
    updated = apply_initial_comments_thread_flag(post, telegram)
    assert updated["commentsThreadAvailable"] is True
    assert updated["commentsThreadLiveOptimistic"] is True


def test_apply_initial_comments_thread_flag_false_when_comments_disabled() -> None:
    post = {"status": "published", "telegramMessageId": "501"}
    telegram = {"commentsEnabled": False, "discussionChatId": ""}
    updated = apply_initial_comments_thread_flag(post, telegram)
    assert updated["commentsThreadAvailable"] is False
    assert "commentsThreadLiveOptimistic" not in updated


def test_probe_comments_thread_for_post_keeps_live_optimistic_when_absent() -> None:
    from app.services.telegram.comments_flow import probe_comments_thread_for_post

    post = {
        "status": "published",
        "telegramMessageId": "501",
        "commentsThreadAvailable": True,
        "commentsThreadLiveOptimistic": True,
    }
    telegram = {"commentsEnabled": True, "discussionChatId": "123"}

    async def fake_probe(*_args, **_kwargs):
        return None, True

    import app.services.telegram.comments_flow as comments_flow

    original = comments_flow.probe_discussion_root
    comments_flow.probe_discussion_root = fake_probe
    try:
        result = asyncio.run(
            probe_comments_thread_for_post(
                AsyncMock(),
                object(),
                post,
                telegram,
                get_settings(),
            )
        )
    finally:
        comments_flow.probe_discussion_root = original

    assert result is post


def test_refresh_post_comments_thread_flag_keeps_live_optimistic_when_absent() -> None:
    from app.services.telegram.comments_flow import refresh_post_comments_thread_flag

    post = {
        "status": "published",
        "telegramMessageId": "501",
        "commentsThreadLiveOptimistic": True,
    }

    async def fake_probe(*_args, **_kwargs):
        return None, True

    import app.services.telegram.comments_flow as comments_flow

    original = comments_flow.probe_discussion_root
    comments_flow.probe_discussion_root = fake_probe
    try:
        updated, changed = asyncio.run(
            refresh_post_comments_thread_flag(
                AsyncMock(),
                object(),
                post,
                get_settings(),
            )
        )
    finally:
        comments_flow.probe_discussion_root = original

    assert changed is False
    assert updated is post


@pytest.mark.asyncio
async def test_probe_comments_thread_for_post_leaves_inconclusive_unchanged() -> None:
    from app.services.telegram.comments_flow import probe_comments_thread_for_post

    post = {"status": "published", "telegramMessageId": "501"}
    telegram = {"commentsEnabled": True, "discussionChatId": "123"}
    client = AsyncMock()
    channel_entity = object()

    async def fake_probe(*_args, **_kwargs):
        return None, False

    import app.services.telegram.comments_flow as comments_flow

    original = comments_flow.probe_discussion_root
    comments_flow.probe_discussion_root = fake_probe
    try:
        result = await probe_comments_thread_for_post(
            client,
            channel_entity,
            post,
            telegram,
            get_settings(),
        )
    finally:
        comments_flow.probe_discussion_root = original

    assert result is post
    assert "commentsThreadAvailable" not in result


@pytest.mark.asyncio
async def test_merge_comments_keeps_pending_platform_comments() -> None:
    existing = [
        {"id": "local-1", "author": "Вы", "text": "Pending", "date": "2026-01-01T00:00:00Z"},
        {
            "id": "tg-100",
            "author": "Old",
            "text": "Old text",
            "date": "2026-01-01T01:00:00Z",
            "telegramMessageId": "100",
        },
    ]
    from_tg = [
        {
            "id": "tg-100",
            "author": "Alice",
            "text": "Updated",
            "date": "2026-01-01T02:00:00Z",
            "telegramMessageId": "100",
        },
        {
            "id": "tg-101",
            "author": "Bob",
            "text": "New from TG",
            "date": "2026-01-01T03:00:00Z",
            "telegramMessageId": "101",
        },
    ]
    merged = merge_comments(existing, from_tg)
    assert any(item["id"] == "local-1" for item in merged)
    updated = next(item for item in merged if item.get("telegramMessageId") == "100")
    assert updated["text"] == "Updated"
    assert any(item.get("telegramMessageId") == "101" for item in merged)


def test_merge_comments_links_pending_platform_comment_to_telegram() -> None:
    existing = [
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:00Z",
        }
    ]
    from_tg = [
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:01Z",
            "telegramMessageId": "7000",
        }
    ]
    merged = merge_comments(existing, from_tg)
    assert len(merged) == 1
    assert merged[0]["id"] == "local-1"
    assert merged[0]["author"] == "Вы"
    assert merged[0]["telegramMessageId"] == "7000"


def test_merge_comments_preserves_self_author_for_linked_comment() -> None:
    existing = [
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:00Z",
            "telegramMessageId": "7000",
        }
    ]
    from_tg = [
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:01Z",
            "telegramMessageId": "7000",
        }
    ]
    merged = merge_comments(existing, from_tg)
    assert len(merged) == 1
    assert merged[0]["author"] == "Вы"


def test_full_pull_prunes_synced_comment_missing_in_telegram() -> None:
    existing = [
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Deleted in TG",
            "date": "2026-07-02T12:00:00Z",
            "telegramMessageId": "7000",
        },
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Still pending",
            "date": "2026-07-02T12:01:00Z",
        },
    ]
    from_tg = [
        {
            "id": "tg-7001",
            "author": "Alice",
            "text": "Still in TG",
            "date": "2026-07-02T12:02:00Z",
            "telegramMessageId": "7001",
        }
    ]

    partial = merge_comments(existing, from_tg)
    assert any(item.get("telegramMessageId") == "7000" for item in partial)

    full = merge_comments(existing, from_tg, prune_missing_synced=True)
    assert not any(item.get("telegramMessageId") == "7000" for item in full)
    assert any(item["id"] == "local-1" for item in full)
    assert any(item.get("telegramMessageId") == "7001" for item in full)


def test_comments_pull_is_complete_empty_with_stored_synced_is_inconclusive() -> None:
    from app.services.telegram.comments_flow import comments_pull_is_complete

    existing = [
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Was in TG",
            "date": "2026-07-02T12:00:00Z",
            "telegramMessageId": "7000",
        }
    ]
    assert comments_pull_is_complete([], existing) is False
    assert comments_pull_is_complete([], []) is True


def test_empty_telegram_pull_does_not_prune_stored_synced_comments() -> None:
    existing = [
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Still in DB",
            "date": "2026-07-02T12:00:00Z",
            "telegramMessageId": "7000",
        }
    ]
    merged = merge_comments(existing, [], prune_missing_synced=False)
    assert len(merged) == 1
    assert merged[0]["telegramMessageId"] == "7000"


def test_dedupe_platform_comments_collapses_live_sync_race() -> None:
    comments = [
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:00Z",
        },
        {
            "id": "tg-7000",
            "author": "Пользователь",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:01Z",
            "telegramMessageId": "7000",
        },
    ]
    deduped = dedupe_platform_comments(comments)
    assert len(deduped) == 1
    assert deduped[0]["id"] == "local-1"
    assert deduped[0]["author"] == "Вы"
    assert deduped[0]["telegramMessageId"] == "7000"


@pytest.mark.asyncio
async def test_sync_new_comments_skips_push_when_live_sync_already_added_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.telegram.comments_flow import sync_new_comments_to_telegram

    sent: list[dict[str, Any]] = []

    async def fake_send(*_args: Any, **_kwargs: Any) -> str:
        sent.append({})
        return "9999"

    monkeypatch.setattr(
        "app.services.telegram.comments_flow._send_comment_message",
        fake_send,
    )
    monkeypatch.setattr(
        "app.services.telegram.comments_flow.get_discussion_root_message_id",
        lambda *_args, **_kwargs: DISCUSSION_ROOT_ID,
    )
    monkeypatch.setattr(
        "app.services.telegram.comments_flow.with_timeout",
        lambda awaitable, _settings: awaitable,
    )

    client = SimpleNamespace(
        get_entity=AsyncMock(return_value=SimpleNamespace()),
    )
    post_data = {
        "telegramDiscussionMessageId": str(DISCUSSION_ROOT_ID),
        "comments": [
            {
                "id": "local-1",
                "author": "Вы",
                "text": "Hello TG",
                "date": "2026-07-02T12:00:00Z",
            },
            {
                "id": "tg-7000",
                "author": "Пользователь",
                "text": "Hello TG",
                "date": "2026-07-02T12:00:01Z",
                "telegramMessageId": "7000",
            },
        ],
    }
    pending = post_data["comments"][0]
    result = await sync_new_comments_to_telegram(
        client,
        SimpleNamespace(),
        "-100123",
        42,
        post_data,
        [pending],
        uuid.uuid4(),
        get_settings(),
    )
    assert sent == []
    assert len(result.comments or []) == 1
    assert result.comments[0]["telegramMessageId"] == "7000"


def test_removed_comment_telegram_message_ids() -> None:
    previous = [
        {"id": "local-1", "author": "Вы", "text": "Hi", "telegramMessageId": "101"},
        {"id": "local-2", "author": "Вы", "text": "Pending"},
    ]
    current = [{"id": "local-2", "author": "Вы", "text": "Pending"}]
    assert removed_comment_telegram_message_ids(previous, current) == ["101"]


def test_merge_comments_updates_media() -> None:
    existing = [
        {
            "id": "tg-100",
            "author": "Alice",
            "text": "",
            "date": "2026-01-01T01:00:00Z",
            "telegramMessageId": "100",
        }
    ]
    from_tg = [
        {
            "id": "tg-100",
            "author": "Alice",
            "text": "",
            "date": "2026-01-01T02:00:00Z",
            "telegramMessageId": "100",
            "media": [
                {
                    "name": "sticker.webp",
                    "url": "/media/u/100.webp",
                    "type": "image/webp",
                    "kind": "sticker",
                }
            ],
        }
    ]
    merged = merge_comments(existing, from_tg)
    updated = next(item for item in merged if item.get("telegramMessageId") == "100")
    assert updated["media"][0]["kind"] == "sticker"


@pytest.mark.asyncio
async def test_map_telegram_messages_to_comments_with_media(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()

    async def fake_save(_client: Any, message: Any, _user_id: uuid.UUID, _settings: Any) -> dict[str, str]:
        return {
            "name": "party.tgs",
            "url": f"/media/{_user_id}/{message.id}.json",
            "type": "application/json",
            "kind": "animated_sticker",
        }

    monkeypatch.setattr(
        "app.services.telegram.comments_flow.save_message_media",
        fake_save,
    )
    sticker_message = _discussion_message(
        150,
        text="",
        reply_to=DISCUSSION_ROOT_ID,
        author="StickerUser",
    )
    sticker_message.media = SimpleNamespace()
    comments = await map_telegram_messages_to_comments(
        SimpleNamespace(),
        [sticker_message],
        discussion_root_id=DISCUSSION_ROOT_ID,
        user_id=user_id,
        settings=get_settings(),
    )
    assert len(comments) == 1
    assert comments[0]["media"][0]["kind"] == "animated_sticker"


@pytest.mark.asyncio
async def test_map_telegram_messages_to_comments_reply_chain() -> None:
    parent = _discussion_message(100, text="Parent", reply_to=DISCUSSION_ROOT_ID, author="Alice")
    child = _discussion_message(101, text="Reply", reply_to=100, author="Bob")

    comments = await map_telegram_messages_to_comments(
        SimpleNamespace(),
        [parent, child],
        discussion_root_id=DISCUSSION_ROOT_ID,
        user_id=uuid.uuid4(),
        settings=get_settings(),
    )
    assert len(comments) == 2
    by_id = {item["telegramMessageId"]: item for item in comments}
    assert by_id["100"]["author"] == "Alice"
    assert by_id["101"]["replyToId"] == by_id["100"]["id"]


@pytest.mark.asyncio
async def test_patch_new_comment_pushes_to_telegram(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)

    response = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={
            "comments": [
                {
                    "id": "new-local",
                    "author": "Вы",
                    "text": "Hello TG",
                    "date": "2026-07-02T12:00:00Z",
                }
            ]
        },
    )
    assert response.status_code == 200
    body = await _post_after_comment_push(client, post["id"], writer_auth_headers)
    assert body["comments"][0]["telegramMessageId"] == "7000"
    assert "commentSyncError" not in body
    assert SCENARIO.sent[0]["reply_to"] == DISCUSSION_ROOT_ID

    # A comment whose earlier push failed stays without telegramMessageId and
    # must be retried on the next PATCH, even though it is not brand new.
    stuck = {
        "id": "stuck-local",
        "author": "Вы",
        "text": "Retry me",
        "date": "2026-07-02T12:05:00Z",
    }
    retry_response = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={"comments": [body["comments"][0], stuck]},
    )
    assert retry_response.status_code == 200
    retry_body = await _post_after_comment_push(client, post["id"], writer_auth_headers)
    retried = next(c for c in retry_body["comments"] if c["id"] == "stuck-local")
    assert retried["telegramMessageId"] == "7001"
    assert "commentSyncError" not in retry_body
    # The already-synced comment must not be re-sent.
    assert len(SCENARIO.sent) == 2


def test_merge_patch_comments_preserves_telegram_message_id() -> None:
    previous = [
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:00Z",
            "telegramMessageId": "7000",
        }
    ]
    stale_patch = [
        {
            "id": "local-1",
            "author": "Вы",
            "text": "Hello TG",
            "date": "2026-07-02T12:00:00Z",
        }
    ]
    merged = merge_patch_comments(previous, stale_patch)
    assert merged[0]["telegramMessageId"] == "7000"


@pytest.mark.asyncio
async def test_patch_stale_comment_retry_does_not_repush_to_telegram(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)

    first = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={
            "comments": [
                {
                    "id": "local-1",
                    "author": "Вы",
                    "text": "Hello TG",
                    "date": "2026-07-02T12:00:00Z",
                }
            ]
        },
    )
    assert first.status_code == 200
    await drain_scheduled_comment_pushes()
    assert len(SCENARIO.sent) == 1

    stale = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={
            "comments": [
                {
                    "id": "local-1",
                    "author": "Вы",
                    "text": "Hello TG",
                    "date": "2026-07-02T12:00:00Z",
                }
            ]
        },
    )
    assert stale.status_code == 200
    assert stale.json()["comments"][0]["telegramMessageId"] == "7000"
    assert len(SCENARIO.sent) == 1


@pytest.mark.asyncio
async def test_patch_comment_without_discussion_returns_error(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_connected_profile(
        client,
        writer_auth_headers,
        discussionChatId="",
        commentsEnabled=False,
    )
    post = await _create_published_post(client, writer_auth_headers)

    response = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={
            "comments": [
                {
                    "id": "new-local",
                    "author": "Вы",
                    "text": "Blocked",
                    "date": "2026-07-02T12:00:00Z",
                }
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["commentSyncError"]
    assert not body["comments"][0].get("telegramMessageId")


@pytest.mark.asyncio
async def test_sync_comments_endpoint_pulls_from_telegram(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)
    SCENARIO.discussion_messages = [
        _discussion_message(
            8100,
            text="From TG",
            reply_to=DISCUSSION_ROOT_ID,
            author="Carol",
        )
    ]

    response = await client.post(
        f"/api/v1/posts/{post['id']}/sync-comments/",
        headers=writer_auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item.get("telegramMessageId") == "8100" for item in body.get("comments") or [])
    assert body.get("telegramDiscussionMessageId") == str(DISCUSSION_ROOT_ID)
    assert body.get("commentsThreadAvailable") is True

    list_resp = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert list_resp.status_code == 200
    listed = next(item for item in list_resp.json() if item["id"] == post["id"])
    assert listed.get("telegramSyncPending") is not True


@pytest.mark.asyncio
async def test_get_discussion_root_returns_none_without_discussion_peer() -> None:
    """Posts published before discussions were enabled must not get a fake root id."""

    class NoDiscussionClient(CommentFakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            cls_name = type(request).__name__
            if cls_name == "GetDiscussionMessageRequest":
                channel_msg = SimpleNamespace(
                    id=501,
                    peer_id=SimpleNamespace(channel_id=555),
                    message="Channel only",
                )
                return SimpleNamespace(
                    messages=[channel_msg],
                    chats=[SimpleNamespace(id=555, broadcast=True, title="Channel")],
                )
            return await super().__call__(request)

    from app.core.config import get_settings

    client = NoDiscussionClient(None, 1, "hash")
    channel_entity = SimpleNamespace(id=555, broadcast=True)
    root_id = await get_discussion_root_message_id(
        client, channel_entity, 501, get_settings()
    )
    assert root_id is None


@pytest.mark.asyncio
async def test_get_discussion_root_returns_none_for_old_post_when_channel_has_discussions() -> None:
    """A public channel with discussions must not treat the channel post id as the root."""

    class OldPrivatePostClient(CommentFakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            cls_name = type(request).__name__
            if cls_name == "GetDiscussionMessageRequest":
                channel_msg = SimpleNamespace(
                    id=501,
                    peer_id=SimpleNamespace(channel_id=555),
                    message="Published while private",
                )
                return SimpleNamespace(
                    messages=[channel_msg],
                    chats=[
                        SimpleNamespace(id=555, broadcast=True, title="Channel"),
                        SimpleNamespace(id=123456789, megagroup=True, title="Discussion"),
                    ],
                )
            return await super().__call__(request)

    from app.core.config import get_settings
    from app.services.telegram.comments_flow import probe_discussion_root

    client = OldPrivatePostClient(None, 1, "hash")
    channel_entity = SimpleNamespace(id=555, broadcast=True)
    root_id, confirmed_absent = await probe_discussion_root(
        client, channel_entity, 501, get_settings()
    )
    assert root_id is None
    assert confirmed_absent is True


def test_post_needs_comments_thread_probe_detects_bogus_discussion_root() -> None:
    from app.services.telegram.comments_flow import post_needs_comments_thread_probe

    post = {
        "status": "published",
        "telegramMessageId": "501",
        "telegramDiscussionMessageId": "501",
        "commentsThreadAvailable": True,
    }
    assert post_needs_comments_thread_probe(post) is True


@pytest.mark.asyncio
async def test_probe_discussion_root_treats_msg_id_invalid_as_absent() -> None:
    from app.core.config import get_settings
    from app.services.telegram.comments_flow import probe_discussion_root

    class MsgIdInvalidClient:
        async def __call__(self, request: Any) -> Any:
            raise Exception("RPCError 400: MSG_ID_INVALID (caused by GetDiscussionMessageRequest)")

    root_id, confirmed_absent = await probe_discussion_root(
        MsgIdInvalidClient(),
        SimpleNamespace(id=555, broadcast=True),
        501,
        get_settings(),
    )
    assert root_id is None
    assert confirmed_absent is True


@pytest.mark.asyncio
async def test_reconcile_marks_post_without_discussion_thread(
    client: AsyncClient, writer_auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(
        client,
        writer_auth_headers,
        comments=[{"id": "stale", "author": "X", "text": "stale", "date": "2026-01-01T00:00:00Z"}],
    )

    async with TestSessionLocal() as session:
        profile = (await session.execute(select(Profile))).scalar_one()
        writer_user_id = profile.user_id
        row = await session.get(Post, uuid.UUID(post["id"]))
        assert row is not None
        data = dict(row.data)
        data["commentsThreadAvailable"] = True
        data["telegramDiscussionMessageId"] = TELEGRAM_MESSAGE_ID
        row.data = data
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "data")
        await session.commit()

    class NoDiscussionClient(CommentFakeTelegramClient):
        async def __call__(self, request: Any) -> Any:
            cls_name = type(request).__name__
            if cls_name == "GetDiscussionMessageRequest":
                channel_msg = SimpleNamespace(
                    id=int(TELEGRAM_MESSAGE_ID),
                    peer_id=SimpleNamespace(channel_id=555),
                    message="Channel only",
                )
                return SimpleNamespace(
                    messages=[channel_msg],
                    chats=[
                        SimpleNamespace(id=555, broadcast=True, title="Channel"),
                        SimpleNamespace(id=123456789, megagroup=True, title="Discussion"),
                    ],
                )
            return await super().__call__(request)

    channel_entity = SimpleNamespace(id=555, broadcast=True)
    tg_client = NoDiscussionClient(None, 1, "hash")

    async def fake_fetch_by_ids(_client: Any, _entity: Any, message_ids: list[int]) -> dict[int, Any]:
        return {
            int(TELEGRAM_MESSAGE_ID): SimpleNamespace(
                id=int(TELEGRAM_MESSAGE_ID),
                message="Channel post",
                date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                media=None,
            )
        }

    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow._fetch_messages_by_ids",
        fake_fetch_by_ids,
    )

    async def always_acquire(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow.try_acquire_reconcile_slot",
        always_acquire,
    )

    from app.core.config import get_settings

    await reconcile_channel_window(
        tg_client,
        channel_entity,
        writer_user_id,
        get_settings(),
        TestSessionLocal,
        force=True,
        include_new_scan=False,
        include_comments=True,
    )

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, uuid.UUID(post["id"]))
        assert refreshed is not None
        assert refreshed.data.get("commentsThreadAvailable") is False
        assert "telegramDiscussionMessageId" not in refreshed.data


@pytest.mark.asyncio
async def test_refresh_channel_comments_settings_enables_discussion() -> None:
    telegram = {"commentsEnabled": False, "discussionChatId": ""}
    client = CommentFakeTelegramClient(None, 1, "hash")
    from app.core.config import get_settings

    refreshed = await refresh_channel_comments_settings(
        client,
        SimpleNamespace(id=555, broadcast=True),
        telegram,
        get_settings(),
    )
    assert refreshed["commentsEnabled"] is True
    assert refreshed["discussionChatId"] == DISCUSSION_CHAT_ID


@pytest.mark.asyncio
async def test_reconcile_refreshes_comments_settings(
    client: AsyncClient, writer_auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_connected_profile(
        client,
        writer_auth_headers,
        discussionChatId="",
        commentsEnabled=False,
    )
    async with TestSessionLocal() as session:
        profile = (await session.execute(select(Profile))).scalar_one()
        user_id = profile.user_id

    channel_entity = SimpleNamespace(id=555, broadcast=True)
    tg_client = CommentFakeTelegramClient(None, 1, "hash")

    async def fake_fetch_by_ids(_client: Any, _entity: Any, message_ids: list[int]) -> dict[int, Any]:
        return {}

    async def always_acquire(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow._fetch_messages_by_ids",
        fake_fetch_by_ids,
    )
    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow.try_acquire_reconcile_slot",
        always_acquire,
    )

    from app.core.config import get_settings

    await reconcile_channel_window(
        tg_client,
        channel_entity,
        user_id,
        get_settings(),
        TestSessionLocal,
        force=True,
        include_new_scan=False,
        include_comments=True,
    )

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        assert profile.telegram.get("commentsEnabled") is True
        assert profile.telegram.get("discussionChatId") == DISCUSSION_CHAT_ID


@pytest.mark.asyncio
async def test_reconcile_pulls_comments(
    client: AsyncClient, writer_auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_published_post(client, writer_auth_headers)
    SCENARIO.discussion_messages = [
        _discussion_message(
            8200,
            text="Reconcile comment",
            reply_to=DISCUSSION_ROOT_ID,
            author="Dan",
        )
    ]

    async with TestSessionLocal() as session:
        profile = (await session.execute(select(Profile))).scalar_one()
        writer_user_id = profile.user_id

    channel_entity = SimpleNamespace(id=555, broadcast=True)
    tg_client = CommentFakeTelegramClient(None, 1, "hash")

    async def fake_fetch_by_ids(_client: Any, _entity: Any, message_ids: list[int]) -> dict[int, Any]:
        return {
            int(TELEGRAM_MESSAGE_ID): SimpleNamespace(
                id=int(TELEGRAM_MESSAGE_ID),
                message="Channel post",
                date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                media=None,
            )
        }

    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow._fetch_messages_by_ids",
        fake_fetch_by_ids,
    )
    async def always_acquire(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(
        "app.services.telegram.reconcile_flow.try_acquire_reconcile_slot",
        always_acquire,
    )

    from app.core.config import get_settings

    settings = get_settings()
    stats = await reconcile_channel_window(
        tg_client,
        channel_entity,
        writer_user_id,
        settings,
        TestSessionLocal,
        force=True,
        include_new_scan=False,
        include_comments=True,
    )
    assert stats.updated >= 1

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, uuid.UUID(post["id"]))
        assert refreshed is not None
        comments = refreshed.data.get("comments") or []
        assert any(item.get("telegramMessageId") == "8200" for item in comments)


async def _prepare_discussion_post(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a published post already linked to a discussion thread root."""
    await _seed_connected_profile(client, headers)
    post = await _create_published_post(client, headers)
    post_id = uuid.UUID(post["id"])
    async with TestSessionLocal() as session:
        row = await session.get(Post, post_id)
        assert row is not None
        data = dict(row.data)
        data["telegramDiscussionMessageId"] = str(DISCUSSION_ROOT_ID)
        row.data = data
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "data")
        profile = (await session.execute(select(Profile))).scalar_one()
        user_id = profile.user_id
        await session.commit()
    return post_id, user_id


@pytest.mark.asyncio
async def test_handle_live_discussion_messages_batches_one_revision(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    post_id, user_id = await _prepare_discussion_post(client, writer_auth_headers)

    async with TestSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None
        base_sync_revision = int(profile.telegram.get("syncRevision") or 0)
        base_comments_revision = int(profile.telegram.get("commentsRevision") or 0)

    tg_client = CommentFakeTelegramClient(None, 1, "hash")
    messages = [
        _discussion_message(9101, text="c1", reply_to=DISCUSSION_ROOT_ID, author="Alice"),
        _discussion_message(9102, text="c2", reply_to=DISCUSSION_ROOT_ID, author="Bob"),
        _discussion_message(9103, text="c3", reply_to=DISCUSSION_ROOT_ID, author="Alice"),
    ]

    await handle_live_discussion_messages(tg_client, messages, user_id, TestSessionLocal)

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        tg_ids = {c.get("telegramMessageId") for c in (refreshed.data.get("comments") or [])}
        assert {"9101", "9102", "9103"} <= tg_ids

        profile = await session.get(Profile, user_id)
        assert profile is not None
        # A batch of 3 comments bumps commentsRevision exactly once and never
        # touches syncRevision (so the frontend won't refetch the whole feed).
        assert int(profile.telegram.get("commentsRevision") or 0) == base_comments_revision + 1
        assert int(profile.telegram.get("syncRevision") or 0) == base_sync_revision


@pytest.mark.asyncio
async def test_handle_live_discussion_messages_updates_edited_comment(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    post_id, user_id = await _prepare_discussion_post(client, writer_auth_headers)

    tg_client = CommentFakeTelegramClient(None, 1, "hash")
    await handle_live_discussion_messages(
        tg_client,
        [
            _discussion_message(
                9301,
                text="Original comment",
                reply_to=DISCUSSION_ROOT_ID,
                author="Alice",
            )
        ],
        user_id,
        TestSessionLocal,
    )

    await handle_live_discussion_messages(
        tg_client,
        [
            _discussion_message(
                9301,
                text="Edited comment",
                reply_to=DISCUSSION_ROOT_ID,
                author="Alice",
            )
        ],
        user_id,
        TestSessionLocal,
    )

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        comments = refreshed.data.get("comments") or []
        assert len(comments) == 1
        assert comments[0]["telegramMessageId"] == "9301"
        assert comments[0]["text"] == "Edited comment"


def test_merge_comments_updates_text_html() -> None:
    existing = [
        {
            "id": "tg-100",
            "author": "Alice",
            "text": "Old text",
            "textHtml": "<p>Old text</p>",
            "date": "2026-01-01T01:00:00Z",
            "telegramMessageId": "100",
        }
    ]
    from_tg = [
        {
            "id": "tg-100",
            "author": "Alice",
            "text": "New text",
            "textHtml": "<p><b>New</b> text</p>",
            "date": "2026-01-01T02:00:00Z",
            "telegramMessageId": "100",
        }
    ]
    merged = merge_comments(existing, from_tg)
    assert merged[0]["text"] == "New text"
    assert merged[0]["textHtml"] == "<p><b>New</b> text</p>"


@pytest.mark.asyncio
async def test_discussion_comment_buffer_flushes_batch(
    client: AsyncClient, writer_auth_headers: dict[str, str]
) -> None:
    post_id, user_id = await _prepare_discussion_post(client, writer_auth_headers)

    tg_client = CommentFakeTelegramClient(None, 1, "hash")
    buffer = DiscussionCommentBuffer(
        tg_client,
        user_id,
        TestSessionLocal,
        settings=get_settings(),
        debounce_seconds=0.0,
    )
    for msg_id in (9201, 9202):
        await buffer.add(
            _discussion_message(
                msg_id, text=f"buf-{msg_id}", reply_to=DISCUSSION_ROOT_ID, author="Carol"
            )
        )
    await buffer.flush()

    async with TestSessionLocal() as session:
        refreshed = await session.get(Post, post_id)
        assert refreshed is not None
        tg_ids = {c.get("telegramMessageId") for c in (refreshed.data.get("comments") or [])}
        assert {"9201", "9202"} <= tg_ids
