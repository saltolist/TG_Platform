"""Tests for deferred channel ingest coordination."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.telegram.sync_coordination import (
    drain_deferred_ingest_for_tests,
    run_channel_ingest,
    run_channel_ingest_or_defer,
)


@pytest.mark.asyncio
async def test_run_channel_ingest_or_defer_defers_when_busy() -> None:
    user_id = uuid4()
    ran_immediately = asyncio.Event()
    deferred_ran = asyncio.Event()
    release = asyncio.Event()

    async def immediate() -> None:
        ran_immediately.set()
        await release.wait()

    async def deferred() -> None:
        deferred_ran.set()

    task = asyncio.create_task(run_channel_ingest_or_defer(user_id, immediate, label="first"))
    await ran_immediately.wait()
    result = await run_channel_ingest_or_defer(user_id, deferred, label="second")
    assert result is None
    assert not deferred_ran.is_set()

    release.set()
    await task
    await drain_deferred_ingest_for_tests(user_id)
    assert deferred_ran.is_set()


@pytest.mark.asyncio
async def test_deferred_ingest_coalesces_to_latest() -> None:
    user_id = uuid4()
    labels: list[str] = []
    release = asyncio.Event()

    async def hold_lock() -> None:
        await release.wait()

    async def first_deferred() -> None:
        labels.append("first")

    async def second_deferred() -> None:
        labels.append("second")

    task = asyncio.create_task(run_channel_ingest_or_defer(user_id, hold_lock, label="hold"))
    await asyncio.sleep(0.01)
    await run_channel_ingest_or_defer(user_id, first_deferred, label="first")
    await run_channel_ingest_or_defer(user_id, second_deferred, label="second")

    release.set()
    await task
    await drain_deferred_ingest_for_tests(user_id)
    assert labels == ["second"]


@pytest.mark.asyncio
async def test_run_channel_ingest_waits_for_lock() -> None:
    user_id = uuid4()
    order: list[str] = []

    async def slow() -> None:
        order.append("slow-start")
        await asyncio.sleep(0.05)
        order.append("slow-end")

    async def fast() -> None:
        order.append("fast")

    first = asyncio.create_task(run_channel_ingest(user_id, slow))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(run_channel_ingest(user_id, fast))
    await asyncio.gather(first, second)

    assert order == ["slow-start", "slow-end", "fast"]
