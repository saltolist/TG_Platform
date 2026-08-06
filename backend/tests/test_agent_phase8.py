"""Phase-8 scale indexes, profile limits and resumable batch contracts."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.db.models import (
    AgentBatchItem,
    AgentBatchJob,
    AgentEvent,
    AgentRun,
    GlobalNote,
    Post,
    User,
)
from app.services.agent.runtime.events import create_run
from tests.conftest import TestSessionLocal


def test_exhaustive_contract_routes_to_batch_and_flag_rolls_back() -> None:
    from app.services.agent.runtime.turn_contract import build_turn_contract

    contract = build_turn_contract(
        user_text=(
            "Проанализируй все заметки и посты во всём workspace"
        ),
        history=[],
        scope="global",
    )
    assert contract["task_profile"] == "exhaustive_inventory"
    assert contract["execution_mode"] == "batch"
    assert contract["output_schema"] == "exhaustive_inventory.v1"
    assert contract["budgets"]["planner_calls"] == 0
    assert {item["kind"] for item in contract["source_requirements"]} == {"notes", "posts"}

    rollback = build_turn_contract(
        user_text=(
            "Проанализируй все заметки и посты во всём workspace"
        ),
        history=[],
        scope="global",
        batch_enabled=False,
    )
    assert rollback["execution_mode"] != "batch"


def test_semantic_member_inventory_does_not_bypass_the_agent() -> None:
    from app.services.agent.runtime.turn_contract import build_turn_contract

    contract = build_turn_contract(
        user_text="Перечисли все функциональные зоны TG Platform",
        history=[],
        scope="global",
    )

    assert contract["task_profile"] != "exhaustive_inventory"
    assert contract["execution_mode"] != "batch"


def test_profile_limits_bound_db_and_llm_calls() -> None:
    from app.services.agent.runtime.profile_limits import (
        evaluate_profile_limits,
        limits_for_profile,
    )

    exact = limits_for_profile("exact_lookup")
    batch = limits_for_profile("exhaustive_inventory")
    assert exact.db_p95_ms <= 100
    assert exact.max_llm_calls == 1
    assert batch.max_db_calls == 256
    assert batch.max_llm_calls == 0
    assert evaluate_profile_limits(
        "exact_lookup", db_p95_ms=101, db_calls=7, llm_calls=2
    ) == ["db_p95_ms", "db_calls", "llm_calls"]


@pytest.mark.asyncio
async def test_batch_checkpoint_resume_materializes_owned_objects_only(
    writer_user,
) -> None:
    from app.services.agent.runtime.batch import (
        create_batch_job,
        process_batch_page,
        resume_batch_job,
    )

    async with TestSessionLocal() as session:
        other_user = User(
            email=f"phase8-other-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="test",
        )
        session.add(other_user)
        await session.flush()
        run = await create_run(
            session,
            user_id=writer_user.id,
            thread_id="phase8-batch",
            scope="global",
        )
        for index in range(13):
            session.add(
                GlobalNote(
                    user_id=writer_user.id,
                    data={
                        "id": f"note-{index}",
                        "title": f"Note {index}",
                        "body": f"Body {index}",
                        "revision": index + 1,
                    },
                )
            )
        for index in range(12):
            session.add(
                Post(
                    user_id=writer_user.id,
                    position=index,
                    data={
                        "id": f"post-{index}",
                        "text": f"Post {index}",
                        "status": "published",
                        "revision": index + 1,
                    },
                )
            )
        session.add(
            GlobalNote(
                user_id=other_user.id,
                data={"id": "foreign-note", "title": "Foreign", "body": "secret"},
            )
        )
        session.add(
            Post(
                user_id=other_user.id,
                position=0,
                data={"id": "foreign-post", "text": "secret", "status": "published"},
            )
        )
        job, created = await create_batch_job(
            session,
            run=run,
            query="all",
            tenant_key="tenant-a",
            page_size=10,
        )
        assert created is True
        await session.commit()
        job_id = job.id

    async with TestSessionLocal() as session:
        first = await process_batch_page(session, job_id=job_id)
        assert first["processed_items"] == 10
        job = await session.get(AgentBatchJob, job_id)
        assert job is not None
        checkpoint = dict(job.cursor)
        job.status = "paused"
        await session.commit()

    async with TestSessionLocal() as session:
        job = await session.get(AgentBatchJob, job_id)
        assert job is not None
        await resume_batch_job(session, job)
        assert job.cursor == checkpoint
        await session.commit()

    outcome: dict = {"requeue": True}
    while outcome["requeue"]:
        async with TestSessionLocal() as session:
            outcome = await process_batch_page(session, job_id=job_id)
            await session.commit()

    async with TestSessionLocal() as session:
        job = await session.get(AgentBatchJob, job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.processed_items == 25
        assert job.result_summary == {
            "schema": "workspace.agent-batch/v1",
            "notes": 13,
            "posts": 12,
            "truncated": False,
        }
        assert job.db_calls <= job.max_db_calls
        assert job.llm_calls == 0
        items = list(
            (
                await session.scalars(
                    select(AgentBatchItem)
                    .where(AgentBatchItem.job_id == job_id)
                    .order_by(AgentBatchItem.sequence)
                )
            ).all()
        )
        assert len(items) == 25
        assert len({(item.object_kind, item.source_id) for item in items}) == 25
        assert not {"foreign-note", "foreign-post"} & {item.source_id for item in items}
        assert [item.sequence for item in items] == list(range(1, 26))


@pytest.mark.asyncio
async def test_batch_api_is_owner_scoped_and_paginated(
    client,
    writer_user,
    writer_auth_headers,
) -> None:
    from app.services.agent.runtime.batch import create_batch_job, process_batch_page

    async with TestSessionLocal() as session:
        run = await create_run(
            session,
            user_id=writer_user.id,
            thread_id="phase8-api",
            scope="global",
        )
        session.add(
            GlobalNote(
                user_id=writer_user.id,
                data={"id": "api-note", "title": "API note", "body": "body"},
            )
        )
        job, _ = await create_batch_job(
            session,
            run=run,
            query="all",
            tenant_key=None,
            page_size=10,
        )
        await session.commit()
        run_id = run.id
        job_id = job.id
    async with TestSessionLocal() as session:
        await process_batch_page(session, job_id=job_id)
        await session.commit()

    response = await client.get(
        f"/api/v1/ai/runs/{run_id}/batch/", headers=writer_auth_headers
    )
    assert response.status_code == 200
    assert response.json()["processed_items"] == 1
    items = await client.get(
        f"/api/v1/ai/runs/{run_id}/batch/items/?limit=1",
        headers=writer_auth_headers,
    )
    assert items.status_code == 200
    assert items.json()["items"][0]["source_id"] == "api-note"


@pytest.mark.asyncio
async def test_batch_task_completes_linked_run_and_emits_answer(
    writer_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agent.runtime.batch import create_batch_job
    from app.tasks.agent_batch import _process_agent_batch

    monkeypatch.setattr(
        "app.tasks.agent_batch.async_session_factory", TestSessionLocal
    )
    async with TestSessionLocal() as session:
        run = await create_run(
            session,
            user_id=writer_user.id,
            thread_id="phase8-task",
            scope="global",
        )
        session.add(
            Post(
                user_id=writer_user.id,
                position=0,
                data={"id": "task-post", "text": "Task post", "status": "published"},
            )
        )
        job, _ = await create_batch_job(
            session,
            run=run,
            query="all",
            tenant_key=None,
            page_size=10,
        )
        await session.commit()
        run_id = run.id
        job_id = job.id

    result = await _process_agent_batch(job_id)
    while result["requeue"]:
        result = await _process_agent_batch(job_id)
    assert result["status"] == "completed"
    async with TestSessionLocal() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.snapshot["output_schema"] == "exhaustive_inventory.v1"
        events = list(
            (
                await session.scalars(
                    select(AgentEvent)
                    .where(AgentEvent.run_id == run_id)
                    .order_by(AgentEvent.sequence)
                )
            ).all()
        )
        assert [event.event_type for event in events][-3:] == [
            "answer",
            "run_metrics",
            "run_completed",
        ]


@pytest.mark.asyncio
async def test_phase8_indexes_exist_and_hnsw_is_not_speculative() -> None:
    async with TestSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = 'note_embeddings'"
                )
            )
        ).all()
    definitions = {str(row.indexname): str(row.indexdef) for row in rows}
    assert "ix_note_embeddings_discovery_fts" in definitions
    assert "USING gin" in definitions["ix_note_embeddings_discovery_fts"]
    assert "ix_note_embeddings_retrieval_metadata" in definitions
    assert not any("hnsw" in value.lower() for value in definitions.values())


def test_batch_task_has_dedicated_queue() -> None:
    from app.celery_app import celery_app

    route = celery_app.conf.task_routes["app.tasks.agent_batch.execute_agent_batch_task"]
    assert route["queue"] == "agent-batch"


def test_batch_worker_skips_telegram_startup_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import publish

    called = False

    def fake_run_async(_coroutine) -> None:
        nonlocal called
        called = True

    monkeypatch.setenv("TG_CELERY_WORKER_KIND", "batch")
    monkeypatch.setattr(publish, "_run_async", fake_run_async)
    publish._on_worker_ready()
    assert called is False
