"""Tests for Redis-backed commentsSyncPending flags."""

from __future__ import annotations

import uuid

import pytest

from app.services.telegram.comment_sync_pending import (
    clear_comments_sync_pending,
    enrich_post_data,
    enrich_posts_for_user,
    get_pending_comment_post_ids,
    mark_comments_sync_pending,
    reset_comment_sync_pending_storage,
)


@pytest.fixture(autouse=True)
async def _reset_storage() -> None:
    await reset_comment_sync_pending_storage()
    yield
    await reset_comment_sync_pending_storage()


@pytest.mark.asyncio
async def test_mark_and_clear_comment_sync_pending() -> None:
    user_id = uuid.uuid4()
    post_id = str(uuid.uuid4())

    await mark_comments_sync_pending(user_id, post_id)
    assert post_id in await get_pending_comment_post_ids(user_id)

    await clear_comments_sync_pending(user_id, post_id)
    assert post_id not in await get_pending_comment_post_ids(user_id)


@pytest.mark.asyncio
async def test_enrich_post_data_sets_comments_sync_pending() -> None:
    user_id = uuid.uuid4()
    post_id = str(uuid.uuid4())
    await mark_comments_sync_pending(user_id, post_id)

    enriched = enrich_post_data({"id": post_id, "text": "Hi"}, {post_id})
    assert enriched["commentsSyncPending"] is True

    cleared = enrich_post_data({"id": post_id, "text": "Hi"}, set())
    assert "commentsSyncPending" not in cleared


@pytest.mark.asyncio
async def test_enrich_posts_for_user() -> None:
    user_id = uuid.uuid4()
    post_a = str(uuid.uuid4())
    post_b = str(uuid.uuid4())
    await mark_comments_sync_pending(user_id, post_a)

    result = await enrich_posts_for_user(
        user_id,
        [
            {"id": post_a, "text": "A"},
            {"id": post_b, "text": "B"},
        ],
    )
    assert result[0].get("commentsSyncPending") is True
    assert "commentsSyncPending" not in result[1]
