"""Tests that post create/update enqueue RAG post_text jobs."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import sample_post, writer_auth_headers


@pytest.mark.asyncio
async def test_create_post_enqueues_post_text_job(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="RAG body")

    with patch(
        "app.api.v1.posts.enqueue_post_text_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        response = await client.post(
            "/api/v1/posts/",
            headers=writer_auth_headers,
            json=payload,
        )

    assert response.status_code == 201
    mock_enqueue.assert_awaited_once()
    assert mock_enqueue.await_args.args[2] == post_id


@pytest.mark.asyncio
async def test_update_post_text_enqueues_post_text_job(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Before")

    with patch(
        "app.api.v1.posts.enqueue_post_text_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        create = await client.post(
            "/api/v1/posts/",
            headers=writer_auth_headers,
            json=payload,
        )
        assert create.status_code == 201
        mock_enqueue.reset_mock()

        patch_resp = await client.patch(
            f"/api/v1/posts/{post_id}/",
            headers=writer_auth_headers,
            json={"text": "After"},
        )

    assert patch_resp.status_code == 200
    mock_enqueue.assert_awaited_once()
    assert mock_enqueue.await_args.args[2] == post_id


@pytest.mark.asyncio
async def test_update_post_media_enqueues_post_text_job(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Stable text")

    with patch(
        "app.api.v1.posts.enqueue_post_text_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        create = await client.post(
            "/api/v1/posts/",
            headers=writer_auth_headers,
            json=payload,
        )
        assert create.status_code == 201
        mock_enqueue.reset_mock()

        patch_resp = await client.patch(
            f"/api/v1/posts/{post_id}/",
            headers=writer_auth_headers,
            json={"media": [{"name": "new.jpg", "url": "/media/x.jpg", "type": "image/jpeg"}]},
        )

    assert patch_resp.status_code == 200
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_post_status_enqueues_post_text_job(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text="Stable text")

    with patch(
        "app.api.v1.posts.enqueue_post_text_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        create = await client.post(
            "/api/v1/posts/",
            headers=writer_auth_headers,
            json=payload,
        )
        assert create.status_code == 201
        mock_enqueue.reset_mock()

        patch_resp = await client.patch(
            f"/api/v1/posts/{post_id}/",
            headers=writer_auth_headers,
            json={"status": "published", "telegramMessageId": "42"},
        )

    assert patch_resp.status_code == 200
    mock_enqueue.assert_awaited_once()
    assert mock_enqueue.await_args.args[2] == post_id
