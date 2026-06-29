"""Tests for platform model analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.models import AiModelUsageEvent, GlobalChat, GlobalNote, Post, Profile, User
from app.services.analytics.platform_models import (
    UsageRecordInput,
    get_platform_model_analytics,
    record_model_usage_event,
)
from app.services.profile_defaults import empty_ai_profile
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_record_and_aggregate_platform_model_usage(writer_user: User) -> None:
    async with TestSessionLocal() as session:
        profile = Profile(
            user_id=writer_user.id,
            ai={
                "llmModels": [
                    {
                        "id": "llm-1",
                        "provider": "OpenAI",
                        "model": "gpt-4o",
                        "active": True,
                    }
                ]
            },
        )
        session.add(profile)
        session.add(GlobalChat(user_id=writer_user.id, data={"title": "Chat", "history": []}))
        session.add(
            GlobalNote(user_id=writer_user.id, data={"id": "n1", "title": "Note", "body": ""})
        )
        session.add(Post(user_id=writer_user.id, position=0, data={"id": "p1", "title": "Post"}))
        await session.flush()

        now = datetime(2026, 6, 29, 15, 0, tzinfo=UTC)
        await record_model_usage_event(
            session,
            UsageRecordInput(
                user_id=writer_user.id,
                model_profile_id="llm-1",
                model_type="llm",
                provider="OpenAI",
                model="gpt-4o",
                scope="global",
                success=True,
                latency_ms=420,
                prompt_tokens=120,
                completion_tokens=80,
                cost_usd=0.0004,
                is_stub=False,
            ),
        )
        session.add(
            AiModelUsageEvent(
                user_id=writer_user.id,
                model_profile_id="llm-1",
                model_type="llm",
                provider="OpenAI",
                model="gpt-4o",
                scope="global",
                success=True,
                latency_ms=300,
                prompt_tokens=50,
                completion_tokens=30,
                total_tokens=80,
                cost_usd=0.0002,
                is_stub=True,
                created_at=now - timedelta(days=2),
            )
        )
        await session.commit()

        payload = await get_platform_model_analytics(
            session,
            user_id=writer_user.id,
            ai_profile=profile.ai or empty_ai_profile(),
            period=2,
            points=7,
            now=now,
        )

    assert payload["activity"] == {"chats": 1, "notes": 1, "posts": 1}
    assert len(payload["models"]) == 1
    model = payload["models"][0]
    assert model["id"] == "llm-LLM-llm-1"
    assert model["calls"] == 2
    assert model["tokens"] == 280
    assert model["success"] == 100
    assert len(model["trend"]) == 7
    assert sum(model["trend"]) == 2


@pytest.mark.asyncio
async def test_platform_models_endpoint(
    client: AsyncClient,
    writer_auth_headers: dict[str, str],
    writer_user: User,
) -> None:
    async with TestSessionLocal() as session:
        profile = Profile(
            user_id=writer_user.id,
            ai={
                "llmModels": [
                    {
                        "id": "llm-1",
                        "provider": "OpenAI",
                        "model": "gpt-4o",
                        "active": True,
                    }
                ]
            },
        )
        session.add(profile)
        await record_model_usage_event(
            session,
            UsageRecordInput(
                user_id=writer_user.id,
                model_profile_id="llm-1",
                model_type="llm",
                provider="OpenAI",
                model="gpt-4o",
                scope="global",
                success=True,
                latency_ms=100,
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=0.0,
                is_stub=True,
            ),
        )
        await session.commit()

    response = await client.get(
        "/api/v1/analytics/platform-models/?period=1&points=7",
        headers=writer_auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "models" in body
    assert "activity" in body
    assert body["models"][0]["calls"] >= 1
