"""resolve_schedule_time: LLM-based date/time extraction for schedule_post.

Deterministic: the LLM call is mocked to return a fixed JSON string, so no
real model traffic. Focus is the surrounding contract — what routes to a
resolved UTC instant vs. a clarifying question — not the model's own
date-parsing quality.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.agent.runtime import budget
from app.services.agent.scheduling.time_resolver import resolve_schedule_time


def _ctx(user_timezone: str | None = "Europe/Moscow") -> SimpleNamespace:
    return SimpleNamespace(
        deadline_monotonic=None,
        user_timezone=user_timezone,
        reasoner_spec="spec",
        reasoner_model="m",
        reasoner_api_key="k",
    )


def _mock_llm(monkeypatch, raw: str) -> None:
    async def fake(**kwargs):
        return raw

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)


@pytest.mark.asyncio
async def test_resolved_absolute_datetime_converts_to_utc(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Moscow")
    future_local = datetime.now(zone) + timedelta(days=10)
    _mock_llm(
        monkeypatch,
        f'{{"resolved": true, "datetime": "{future_local.strftime("%Y-%m-%dT%H:%M:%S")}"}}',
    )
    result = await resolve_schedule_time(_ctx(), instruction="16 июля в 20:00")
    assert result.resolved is True
    assert result.clarifying_question is None
    parsed_utc = datetime.fromisoformat(result.scheduled_at_utc)
    assert parsed_utc.tzinfo is not None
    # Same instant, expressed in UTC — hour shifts by the Moscow UTC offset.
    # future_local is truncated to seconds (%H:%M:%S) since that's the LLM's
    # output granularity; drop microseconds before comparing.
    expected_local = future_local.replace(microsecond=0, tzinfo=zone)
    assert parsed_utc.astimezone(zone) == expected_local


@pytest.mark.asyncio
async def test_unresolved_returns_clarifying_question(monkeypatch) -> None:
    _mock_llm(monkeypatch, '{"resolved": false, "question": "Уточните день и время."}')
    result = await resolve_schedule_time(_ctx(), instruction="на следующей неделе")
    assert result.resolved is False
    assert result.scheduled_at_utc is None
    assert result.clarifying_question == "Уточните день и время."


@pytest.mark.asyncio
async def test_missing_question_falls_back_to_default_prompt(monkeypatch) -> None:
    _mock_llm(monkeypatch, '{"resolved": false}')
    result = await resolve_schedule_time(_ctx(), instruction="попозже")
    assert result.resolved is False
    assert result.clarifying_question


@pytest.mark.asyncio
async def test_past_datetime_is_rejected_as_unresolved(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Moscow")
    past_local = datetime.now(zone) - timedelta(days=1)
    _mock_llm(
        monkeypatch,
        f'{{"resolved": true, "datetime": "{past_local.strftime("%Y-%m-%dT%H:%M:%S")}"}}',
    )
    result = await resolve_schedule_time(_ctx(), instruction="вчера в 10:00")
    assert result.resolved is False
    assert "уже прошло" in (result.clarifying_question or "")


@pytest.mark.asyncio
async def test_far_future_datetime_is_rejected_as_unresolved(monkeypatch) -> None:
    zone = ZoneInfo("Europe/Moscow")
    far_future_local = datetime.now(zone) + timedelta(days=400)
    _mock_llm(
        monkeypatch,
        f'{{"resolved": true, "datetime": "{far_future_local.strftime("%Y-%m-%dT%H:%M:%S")}"}}',
    )
    result = await resolve_schedule_time(_ctx(), instruction="через год с лишним")
    assert result.resolved is False
    assert result.clarifying_question


@pytest.mark.asyncio
async def test_unparseable_datetime_is_unresolved(monkeypatch) -> None:
    _mock_llm(monkeypatch, '{"resolved": true, "datetime": "not-a-date"}')
    result = await resolve_schedule_time(_ctx(), instruction="сегодня вечером")
    assert result.resolved is False
    assert result.clarifying_question


@pytest.mark.asyncio
async def test_no_reasoner_configured_asks_instead_of_calling(monkeypatch) -> None:
    called = False

    async def fake(**kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(budget.llm, "complete_chat_completion", fake)
    ctx = SimpleNamespace(
        deadline_monotonic=None,
        user_timezone="Europe/Moscow",
        reasoner_spec=None,
        reasoner_model="",
        reasoner_api_key="",
    )
    result = await resolve_schedule_time(ctx, instruction="через полчаса")
    assert result.resolved is False
    assert called is False


@pytest.mark.asyncio
async def test_unknown_timezone_falls_back_to_utc(monkeypatch) -> None:
    zone = ZoneInfo("UTC")
    future_local = datetime.now(zone) + timedelta(days=5)
    _mock_llm(
        monkeypatch,
        f'{{"resolved": true, "datetime": "{future_local.strftime("%Y-%m-%dT%H:%M:%S")}"}}',
    )
    result = await resolve_schedule_time(_ctx(user_timezone="Not/AZone"), instruction="через 5 дней")
    assert result.resolved is True
