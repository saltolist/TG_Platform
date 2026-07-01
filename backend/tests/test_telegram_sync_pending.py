"""Tests for Redis-backed telegram sync-pending flags on posts."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.telegram.sync_pending import (
    clear_post_sync_pending,
    enrich_post_data,
    get_pending_post_ids,
    mark_post_sync_pending,
    reset_sync_pending_storage,
    telegram_sync_pending,
)


@pytest.fixture(autouse=True)
async def _reset_pending() -> None:
    await reset_sync_pending_storage()
    yield
    await reset_sync_pending_storage()


@pytest.mark.asyncio
async def test_mark_and_clear_pending_post() -> None:
    user_id = uuid4()
    post_id = "post-1"
    await mark_post_sync_pending(user_id, post_id)
    assert post_id in await get_pending_post_ids(user_id)
    enriched = enrich_post_data(
        {"id": post_id, "status": "published"}, await get_pending_post_ids(user_id)
    )
    assert enriched["telegramSyncPending"] is True
    await clear_post_sync_pending(user_id, post_id)
    assert post_id not in await get_pending_post_ids(user_id)


@pytest.mark.asyncio
async def test_telegram_sync_pending_context_clears_on_error() -> None:
    user_id = uuid4()
    post_id = "post-2"
    with pytest.raises(RuntimeError):
        async with telegram_sync_pending(user_id, post_id):
            assert post_id in await get_pending_post_ids(user_id)
            raise RuntimeError("boom")
    assert post_id not in await get_pending_post_ids(user_id)
