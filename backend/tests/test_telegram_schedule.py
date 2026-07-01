"""Tests for scheduled publishing via Celery + Redis (Phase 3 / Step 4b).

No real broker is involved: ``publish_scheduled_post.apply_async`` and
``celery_app.control.revoke`` are monkeypatched to simple recorders so these
tests exercise the enqueue/revoke/reconcile *logic* in ``posts.py`` and
``app/tasks/publish.py`` without needing a running Redis instance. The actual
Telegram-sending behaviour of the task's inner call (``publish_flow.publish_post``)
is covered separately in ``test_telegram_publish.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.v1 import posts as posts_module
from app.db.models import Post, Profile
from app.tasks import publish as publish_task_module
from tests.conftest import TestSessionLocal, sample_post

API_ID = "12345678"
API_HASH = "abcdef1234567890abcdef1234567890"
SESSION_VALUE = "fake-session-string"


class FakeAsyncResult:
    _counter = 0

    def __init__(self) -> None:
        FakeAsyncResult._counter += 1
        self.id = f"fake-task-{FakeAsyncResult._counter}"


class CeleryRecorder:
    def __init__(self) -> None:
        self.apply_async_calls: list[dict[str, Any]] = []
        self.revoked: list[str] = []

    def reset(self) -> None:
        self.apply_async_calls = []
        self.revoked = []

    def fake_apply_async(self, args: list[str] | None = None, eta: Any = None, **kwargs: Any) -> FakeAsyncResult:
        self.apply_async_calls.append({"args": args, "eta": eta})
        return FakeAsyncResult()

    def fake_revoke(self, task_id: str, **kwargs: Any) -> None:
        self.revoked.append(task_id)


RECORDER = CeleryRecorder()


@pytest.fixture(autouse=True)
def _patch_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    RECORDER.reset()
    monkeypatch.setattr(posts_module.publish_scheduled_post, "apply_async", RECORDER.fake_apply_async)
    monkeypatch.setattr(posts_module.celery_app.control, "revoke", RECORDER.fake_revoke)
    yield


def _connected_telegram_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": API_ID,
        "apiHash": API_HASH,
        "phone": "",
        "sessionName": "",
        "sessionString": SESSION_VALUE,
        "channel": "@mychannel",
        "channelTitle": "My Channel",
        "channelId": "-100555",
        "channelStatus": "connected",
        "syncMode": "publish-only",
        "lastSync": "2026-01-01T00:00:00+00:00",
        "importedPosts": 0,
        "importStatus": "idle",
        "importError": "",
        "lastTelegramMessageId": "",
        "syncStatus": "idle",
        "syncError": "",
        "syncRevision": 0,
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


async def _create_draft(
    client: AsyncClient, headers: dict[str, str], *, text: str = "Scheduled post", **overrides: Any
) -> dict[str, Any]:
    post_id = str(uuid.uuid4())
    payload = sample_post(post_id, text=text)
    payload.update(overrides)
    resp = await client.post("/api/v1/posts/", headers=headers, json=payload)
    assert resp.status_code == 201
    return resp.json()


def _future_iso(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_schedule_enqueues_task_with_eta_and_stores_task_id(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers)
    scheduled_at = _future_iso()

    resp = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": scheduled_at},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "scheduled"
    assert body["date"] == scheduled_at
    assert body["_celeryTaskId"]

    assert len(RECORDER.apply_async_calls) == 1
    call = RECORDER.apply_async_calls[0]
    assert call["args"][0] == post["id"]
    assert call["eta"] is not None


@pytest.mark.asyncio
async def test_schedule_requires_connected_channel(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    post = await _create_draft(client, writer_auth_headers)
    resp = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": _future_iso()},
    )
    assert resp.status_code == 400
    assert RECORDER.apply_async_calls == []


@pytest.mark.asyncio
async def test_reschedule_revokes_old_task_before_creating_new_one(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers)

    first = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": _future_iso(3600)},
    )
    assert first.status_code == 200
    first_task_id = first.json()["_celeryTaskId"]

    second = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": _future_iso(7200)},
    )
    assert second.status_code == 200
    second_task_id = second.json()["_celeryTaskId"]

    assert second_task_id != first_task_id
    assert RECORDER.revoked == [first_task_id]
    assert len(RECORDER.apply_async_calls) == 2


@pytest.mark.asyncio
async def test_cancel_via_patch_to_draft_revokes_celery_task(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers)

    scheduled = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": _future_iso()},
    )
    task_id = scheduled.json()["_celeryTaskId"]

    cancelled = await client.patch(
        f"/api/v1/posts/{post['id']}/",
        headers=writer_auth_headers,
        json={"status": "draft"},
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "draft"
    assert "_celeryTaskId" not in body
    assert RECORDER.revoked == [task_id]


@pytest.mark.asyncio
async def test_schedule_rejects_already_published_post(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    await _seed_connected_profile(client, writer_auth_headers)
    post = await _create_draft(client, writer_auth_headers, status="published", telegramMessageId="123")

    resp = await client.post(
        f"/api/v1/posts/{post['id']}/schedule/",
        headers=writer_auth_headers,
        json={"scheduledAt": _future_iso()},
    )
    assert resp.status_code == 400
    assert RECORDER.apply_async_calls == []


def test_worker_startup_reconciles_overdue_scheduled_posts(
    monkeypatch: pytest.MonkeyPatch, writer_user
) -> None:
    """No event loop is running here (plain sync test) so ``asyncio.run`` inside
    the reconcile helper behaves exactly as it would in a real Celery worker
    process."""
    monkeypatch.setattr(publish_task_module, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(publish_task_module.publish_scheduled_post, "apply_async", RECORDER.fake_apply_async)
    RECORDER.reset()

    overdue_id = uuid.uuid4()
    future_id = uuid.uuid4()
    already_sent_id = uuid.uuid4()

    async def _seed() -> None:
        async with TestSessionLocal() as session:
            session.add(Profile(user_id=writer_user.id, telegram={}))
            session.add(
                Post(
                    id=overdue_id,
                    user_id=writer_user.id,
                    position=0,
                    data={
                        "id": str(overdue_id),
                        "status": "scheduled",
                        "text": "Overdue",
                        "date": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                    },
                )
            )
            session.add(
                Post(
                    id=future_id,
                    user_id=writer_user.id,
                    position=1,
                    data={
                        "id": str(future_id),
                        "status": "scheduled",
                        "text": "Future",
                        "date": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    },
                )
            )
            session.add(
                Post(
                    id=already_sent_id,
                    user_id=writer_user.id,
                    position=2,
                    data={
                        "id": str(already_sent_id),
                        "status": "scheduled",
                        "text": "Already sent",
                        "date": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                        "telegramMessageId": "999",
                    },
                )
            )
            await session.commit()

    import asyncio

    asyncio.run(_seed())
    asyncio.run(publish_task_module._reconcile_overdue_scheduled_posts())

    reconciled_ids = {call["args"][0] for call in RECORDER.apply_async_calls}
    assert reconciled_ids == {str(overdue_id)}
