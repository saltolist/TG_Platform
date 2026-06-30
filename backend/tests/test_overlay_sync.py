"""Tests for overlay notes sync API."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.constants import DEMO_EMAIL, GUEST_TOKEN_PREFIX
from app.core.security import hash_password
from app.db.models import User
from tests.conftest import TestSessionLocal


async def _seed_demo_user() -> None:
    async with TestSessionLocal() as session:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password("Demo!2026"),
            is_seed=True,
        )
        session.add(user)
        await session.commit()


@pytest.mark.asyncio
async def test_overlay_sync_requires_tenant_header(client: AsyncClient) -> None:
    await _seed_demo_user()
    login = await client.post(
        "/api/v1/auth/login/",
        json={"email": DEMO_EMAIL, "password": "Demo!2026"},
    )
    assert login.status_code == 200

    response = await client.put(
        "/api/v1/overlay/notes/",
        json={"global_notes": [{"id": "n1", "title": "T", "body": "B"}]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_overlay_sync_guest_persists_and_enqueues_job(
    client: AsyncClient, presentation_user: User
) -> None:
    guest_token = f"{GUEST_TOKEN_PREFIX}{uuid.uuid4()}"
    note = {"id": "overlay-note-1", "title": "Личная", "body": "Моя заметка"}
    response = await client.put(
        "/api/v1/overlay/notes/",
        headers={
            "Authorization": f"Bearer {guest_token}",
            "X-Tenant-Session": guest_token,
        },
        json={"global_notes": [note], "global_removed_ids": []},
    )
    assert response.status_code == 204

    async with TestSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT data FROM tenant_overlay_notes "
                    "WHERE user_id = :uid AND tenant_key = :tk AND note_id = :nid"
                ),
                {
                    "uid": str(presentation_user.id),
                    "tk": guest_token,
                    "nid": "overlay-note-1",
                },
            )
        ).fetchone()
        assert row is not None
        assert row.data["title"] == "Личная"

        job = (
            await session.execute(
                text(
                    "SELECT tenant_key, op FROM embedding_jobs "
                    "WHERE user_id = :uid AND note_id = :nid ORDER BY enqueued_at DESC LIMIT 1"
                ),
                {"uid": str(presentation_user.id), "nid": "overlay-note-1"},
            )
        ).fetchone()
        assert job is not None
        assert job.tenant_key == guest_token
        assert job.op == "upsert"


@pytest.mark.asyncio
async def test_overlay_sync_demo_user(client: AsyncClient) -> None:
    await _seed_demo_user()
    login = await client.post(
        "/api/v1/auth/login/",
        json={"email": DEMO_EMAIL, "password": "Demo!2026"},
    )
    assert login.status_code == 200
    demo_key = f"demo:{uuid.uuid4()}"

    response = await client.put(
        "/api/v1/overlay/notes/",
        headers={"X-Tenant-Session": demo_key},
        json={
            "global_notes": [{"id": "demo-n1", "title": "Demo", "body": "text"}],
        },
    )
    assert response.status_code == 204
