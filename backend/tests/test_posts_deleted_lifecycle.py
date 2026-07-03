"""Restore deleted posts to drafts and permanently remove them from the DB."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Post
from tests.conftest import TestSessionLocal, sample_post, writer_auth_headers


@pytest.mark.asyncio
async def test_restore_deleted_post_to_draft(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Deleted post")
    payload["status"] = "deleted"
    payload["deletedAt"] = "2026-01-01T00:00:00+00:00"
    payload["telegramMessageId"] = "999"
    payload["metrics"] = {"views": "10", "reposts": 0, "reactions": []}
    payload["source"] = "telegram"

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    patch = await client.patch(
        f"/api/v1/posts/{post_id}/",
        headers=writer_auth_headers,
        json={"status": "draft", "created": "2026-07-01T12:00:00+00:00"},
    )
    assert patch.status_code == 200
    data = patch.json()
    assert data["status"] == "draft"
    assert data["created"] == "2026-07-01T12:00:00+00:00"
    assert "deletedAt" not in data
    assert "telegramMessageId" not in data
    assert "metrics" not in data
    assert "source" not in data
    assert data["text"] == "Deleted post"
    assert data.get("comments") == []


@pytest.mark.asyncio
async def test_delete_post_clears_comments(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="With comments")
    payload["status"] = "published"
    payload["comments"] = [
        {
            "id": "c1",
            "author": "A",
            "text": "hello",
            "date": "2026-01-01T00:00:00+00:00",
            "telegramMessageId": "101",
        }
    ]
    payload["commentsThreadAvailable"] = True
    payload["telegramDiscussionMessageId"] = "500"
    payload["metrics"] = {
        "views": "100",
        "reposts": 2,
        "reactions": [{"emoji": "🔥", "count": 5}],
    }

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    delete = await client.delete(f"/api/v1/posts/{post_id}/", headers=writer_auth_headers)
    assert delete.status_code == 204

    async with TestSessionLocal() as session:
        row = await session.scalar(select(Post).where(Post.id == uuid.UUID(post_id)))
        assert row is not None
        data = row.data
        assert data["status"] == "deleted"
        assert data.get("comments") == []
        assert "metrics" not in data
        assert "telegramDiscussionMessageId" not in data
        assert "commentsThreadAvailable" not in data


@pytest.mark.asyncio
async def test_restore_deleted_post_clears_stale_comments(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Deleted post")
    payload["status"] = "deleted"
    payload["deletedAt"] = "2026-01-01T00:00:00+00:00"
    payload["comments"] = [
        {
            "id": "c1",
            "author": "A",
            "text": "stale",
            "date": "2026-01-01T00:00:00+00:00",
        }
    ]

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    patch = await client.patch(
        f"/api/v1/posts/{post_id}/",
        headers=writer_auth_headers,
        json={"status": "draft", "created": "2026-07-01T12:00:00+00:00"},
    )
    assert patch.status_code == 200
    assert patch.json().get("comments") == []


@pytest.mark.asyncio
async def test_permanent_delete_removed_from_db(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Gone forever")
    payload["status"] = "deleted"
    payload["deletedAt"] = "2026-01-01T00:00:00+00:00"

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    delete = await client.delete(
        f"/api/v1/posts/{post_id}/?permanent=true",
        headers=writer_auth_headers,
    )
    assert delete.status_code == 204

    async with TestSessionLocal() as session:
        row = await session.scalar(select(Post).where(Post.id == uuid.UUID(post_id)))
        assert row is None


@pytest.mark.asyncio
async def test_permanent_delete_rejects_non_deleted_post(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Still a draft")

    create = await client.post("/api/v1/posts/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201

    delete = await client.delete(
        f"/api/v1/posts/{post_id}/?permanent=true",
        headers=writer_auth_headers,
    )
    assert delete.status_code == 400
