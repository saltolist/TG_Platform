"""Record and aggregate AI model usage for platform analytics."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AiModelUsageEvent, GlobalChat, GlobalNote, Post

MODEL_LIST_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("llmModels", "llm", "LLM"),
    ("webSearchModels", "web", "Web Search"),
    ("visionModels", "vision", "Компьютерное зрение"),
    ("imageGenerationModels", "imageGeneration", "Генерация изображений"),
    ("orchestratorModels", "orchestrator", "Оркестратор"),
    ("webReasonerModels", "webReasoner", "Web Reasoner"),
    ("ragReasonerModels", "ragReasoner", "RAG Reasoner"),
)

PERIOD_HOURS = (24, 24 * 7, 24 * 30, 24 * 90, None)
FULL_PERIOD_UNITS = (24, 7, 30, 90, 6)
NINETY_DAY_STEP = 3
LIFETIME_MONTHS = 6

_LLM_ERROR_PREFIXES = (
    "Не удалось получить ответ от модели",
    "Неверный или недействительный API ключ",
    "Превышен лимит запросов к провайдеру",
    "Не удалось связаться с провайдером LLM",
)

_DEFAULT_COST_PER_1K = Decimal("0.002")


@dataclass(frozen=True)
class UsageRecordInput:
    user_id: uuid.UUID
    model_profile_id: str
    model_type: str
    provider: str
    model: str
    scope: str
    success: bool
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    is_stub: bool


def estimate_tokens_from_text(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def estimate_tokens_from_messages(messages: list[dict[str, str]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens_from_text(content)
    return total


def is_successful_reply(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return not any(stripped.startswith(prefix) for prefix in _LLM_ERROR_PREFIXES)


def estimate_cost_usd(*, prompt_tokens: int, completion_tokens: int, is_stub: bool) -> float:
    if is_stub:
        return 0.0
    total = prompt_tokens + completion_tokens
    return float((_DEFAULT_COST_PER_1K * Decimal(total)) / Decimal(1000))


async def record_model_usage_event(session: AsyncSession, payload: UsageRecordInput) -> None:
    event = AiModelUsageEvent(
        user_id=payload.user_id,
        model_profile_id=payload.model_profile_id,
        model_type=payload.model_type,
        provider=payload.provider,
        model=payload.model,
        scope=payload.scope,
        success=payload.success,
        latency_ms=payload.latency_ms,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        total_tokens=payload.prompt_tokens + payload.completion_tokens,
        cost_usd=payload.cost_usd,
        is_stub=payload.is_stub,
    )
    session.add(event)
    await session.flush()


def _start_of_day(value: datetime) -> datetime:
    local = value.astimezone(UTC)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month(value: datetime) -> datetime:
    local = value.astimezone(UTC)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)


def _subtract_months(value: datetime, months: int) -> datetime:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    return value.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _period_start(period: int, now: datetime) -> datetime | None:
    if period < 0 or period > 4:
        return None
    if period == 4:
        return _subtract_months(_start_of_month(now), LIFETIME_MONTHS - 1)
    hours = PERIOD_HOURS[period]
    assert hours is not None
    if period == 0:
        end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        return end - timedelta(hours=hours - 1)
    return _start_of_day(_add_days(now, -(FULL_PERIOD_UNITS[period] - 1)))


def _display_index_to_span(point_index: int, point_count: int, total_units: int) -> tuple[int, int]:
    if total_units <= 1 or point_count <= 1:
        return 0, max(0, total_units - 1)
    start = round((point_index / (point_count - 1)) * (total_units - 1))
    if point_index >= point_count - 1:
        end = total_units - 1
    else:
        end = max(start, round(((point_index + 1) / (point_count - 1)) * (total_units - 1)) - 1)
    return start, end


def _full_bucket_index(period: int, created_at: datetime, now: datetime) -> int | None:
    created = created_at.astimezone(UTC)
    current = now.astimezone(UTC)

    if period == 0:
        end = current.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=FULL_PERIOD_UNITS[0] - 1)
        if created < start or created >= end + timedelta(hours=1):
            return None
        delta_hours = int((created.replace(minute=0, second=0, microsecond=0) - start).total_seconds() // 3600)
        return delta_hours

    if period == 1:
        start = _start_of_day(_add_days(current, -(FULL_PERIOD_UNITS[1] - 1)))
        day = _start_of_day(created)
        if day < start or day > _start_of_day(current):
            return None
        return (day - start).days

    if period == 2:
        start = _start_of_day(_add_days(current, -(FULL_PERIOD_UNITS[2] - 1)))
        day = _start_of_day(created)
        if day < start or day > _start_of_day(current):
            return None
        return (day - start).days

    if period == 3:
        total_span = FULL_PERIOD_UNITS[3]
        start = _start_of_day(_add_days(current, -(total_span - 1)))
        day = _start_of_day(created)
        if day < start or day > _start_of_day(current):
            return None
        day_offset = (day - start).days
        return day_offset // NINETY_DAY_STEP

    if period == 4:
        current_month = _start_of_month(current)
        month = _start_of_month(created)
        earliest = _subtract_months(current_month, LIFETIME_MONTHS - 1)
        if month < earliest or month > current_month:
            return None
        return (month.year - earliest.year) * 12 + (month.month - earliest.month)

    return None


def _aggregate_trend(
    *,
    period: int,
    points: int,
    bucket_calls: dict[int, int],
    now: datetime,
) -> list[int]:
    full_units = FULL_PERIOD_UNITS[period]
    if period == 3:
        full_units = FULL_PERIOD_UNITS[3] // NINETY_DAY_STEP
    count = max(1, points)
    trend = [0] * count
    for display_index in range(count):
        start, end = _display_index_to_span(display_index, count, full_units)
        trend[display_index] = sum(bucket_calls.get(bucket, 0) for bucket in range(start, end + 1))
    return trend


def _iter_configured_models(ai_profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, model_type, role in MODEL_LIST_FIELDS:
        models = ai_profile.get(field) or []
        if not isinstance(models, list):
            continue
        for entry in models:
            if not isinstance(entry, Mapping):
                continue
            provider = str(entry.get("provider") or "").strip()
            model = str(entry.get("model") or "").strip()
            if not provider or not model:
                continue
            profile_id = str(entry.get("id") or f"{model_type}-{provider}-{model}")
            rows.append(
                {
                    "id": f"{model_type}-{role}-{profile_id}",
                    "profile_id": profile_id,
                    "label": f"{provider} / {model}",
                    "role": role,
                    "type": model_type,
                    "active": bool(entry.get("active")),
                }
            )
    return rows


async def get_platform_activity_counts(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    chats = await session.scalar(
        select(func.count()).select_from(GlobalChat).where(GlobalChat.user_id == user_id)
    )
    notes = await session.scalar(
        select(func.count()).select_from(GlobalNote).where(GlobalNote.user_id == user_id)
    )
    posts = await session.scalar(select(func.count()).select_from(Post).where(Post.user_id == user_id))
    return {
        "chats": int(chats or 0),
        "notes": int(notes or 0),
        "posts": int(posts or 0),
    }


async def get_platform_model_analytics(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ai_profile: Mapping[str, Any],
    period: int,
    points: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    period_start = _period_start(period, current)

    query = select(AiModelUsageEvent).where(AiModelUsageEvent.user_id == user_id)
    if period_start is not None:
        query = query.where(AiModelUsageEvent.created_at >= period_start)
    result = await session.execute(query)
    events = list(result.scalars().all())

    configured = _iter_configured_models(ai_profile)
    stats: dict[str, dict[str, Any]] = {
        row["profile_id"]: {
            **row,
            "calls": 0,
            "tokens": 0,
            "cost": 0.0,
            "success_weight": 0,
            "latency_weight": 0,
            "bucket_calls": defaultdict(int),
        }
        for row in configured
    }

    for event in events:
        key = event.model_profile_id
        if key not in stats:
            stats[key] = {
                "id": f"{event.model_type}-unknown-{key}",
                "profile_id": key,
                "label": f"{event.provider} / {event.model}",
                "role": event.model_type,
                "type": event.model_type,
                "active": True,
                "calls": 0,
                "tokens": 0,
                "cost": 0.0,
                "success_weight": 0,
                "latency_weight": 0,
                "bucket_calls": defaultdict(int),
            }
        row = stats[key]
        row["calls"] += 1
        row["tokens"] += int(event.total_tokens)
        row["cost"] += float(event.cost_usd)
        if event.success:
            row["success_weight"] += 1
        row["latency_weight"] += int(event.latency_ms)
        bucket = _full_bucket_index(period, event.created_at, current)
        if bucket is not None:
            row["bucket_calls"][bucket] += 1

    models: list[dict[str, Any]] = []
    for row in stats.values():
        calls = int(row["calls"])
        success = round((row["success_weight"] / calls) * 100) if calls else 0
        latency = round(row["latency_weight"] / calls) if calls else 0
        trend = _aggregate_trend(
            period=period,
            points=points,
            bucket_calls=row["bucket_calls"],
            now=current,
        )
        models.append(
            {
                "id": row["id"],
                "label": row["label"],
                "role": row["role"],
                "type": row["type"],
                "active": row["active"],
                "calls": calls,
                "tokens": int(row["tokens"]),
                "cost": round(float(row["cost"]), 6),
                "success": success,
                "latency": latency,
                "share": 0,
                "trend": trend,
            }
        )

    models.sort(key=lambda item: item["calls"], reverse=True)
    totals_by_type: dict[str, int] = defaultdict(int)
    total_calls = sum(model["calls"] for model in models)
    for model in models:
        totals_by_type[model["type"]] += model["calls"]
    for model in models:
        type_total = totals_by_type[model["type"]]
        model["share"] = round((model["calls"] / type_total) * 100) if type_total else 0

    activity = await get_platform_activity_counts(session, user_id)
    return {"models": models, "activity": activity}
