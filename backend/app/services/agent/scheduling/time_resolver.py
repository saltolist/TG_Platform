"""Resolve schedule_post's target time from free-form text.

The workspace_agent classifier (600-token budget) only routes a request to
the schedule_post command — it never attempts to parse "сегодня через
полчаса" or "16 июля в 20:00" into an actual instant. Without this step every
schedule_post proposal reached the user with no scheduled_at, so approving it
always failed with "Некорректная дата публикации" (chat 4a3ed2f5).

This module makes a dedicated, correctly-budgeted LLM call whose only job is
date/time extraction, grounded in the user's *local* current time (from
RuntimeContext.user_timezone) so relative phrases resolve unambiguously. When
the model can't produce a confident absolute time, it returns a clarifying
question instead of a payload — callers must not create a proposal in that
case (see resolve_schedule_time_node in workspace_graph.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.agent.runtime.budget import call_llm_with_deadline
from app.services.agent.runtime.context import RuntimeContext
from app.services.ai.rag_json import extract_json_object

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "UTC"

# A schedule further out than this is almost always a misread ("через 5" heard
# as years instead of minutes) rather than a real intent — treat it as
# unresolved and ask instead of silently scheduling a year out.
_MAX_HORIZON = timedelta(days=365)

# Grace window: a resolved time slightly in the past (clock skew between the
# model's arithmetic and "now", or a request literally at the boundary like
# "прямо сейчас") is nudged forward rather than rejected outright.
_PAST_GRACE = timedelta(minutes=1)


@dataclass(frozen=True)
class ScheduleResolution:
    """Outcome of trying to pin schedule_post's target time down.

    Exactly one of scheduled_at_utc / clarifying_question is set on the
    resolved / unresolved paths respectively.
    """

    resolved: bool
    scheduled_at_utc: str | None = None
    clarifying_question: str | None = None


def _safe_zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


_SYSTEM_PROMPT = (
    "Ты извлекаешь дату и время публикации из запроса пользователя на отложенную "
    "публикацию поста. Тебе даны текущая локальная дата и время пользователя. "
    "Разбери запрос и верни JSON:\n"
    '{"resolved": true, "datetime": "YYYY-MM-DDTHH:MM:SS"} — если время можно '
    "определить однозначно (относительное — «через полчаса», «сегодня вечером» "
    "(прими вечер как 19:00, если точнее не сказано), «завтра в 10» — или "
    "абсолютное — «16 июля в 20:00», «31.12 в полночь»). datetime — в локальном "
    "времени пользователя, БЕЗ смещения часового пояса.\n"
    '{"resolved": false, "question": "..."} — если время не указано вообще или '
    "указано слишком расплывчато, чтобы выбрать конкретную минуту (например "
    "«на следующей неделе», «попозже», «в выходные» без уточнения дня и часа). "
    "question — короткий уточняющий вопрос на русском, который нужно задать "
    "пользователю, чтобы получить точную дату и время.\n"
    "Никаких пояснений вне JSON."
)


async def resolve_schedule_time(
    ctx: RuntimeContext,
    *,
    instruction: str,
    dialog_context: str = "",
) -> ScheduleResolution:
    """Parse `instruction` into an absolute UTC instant, or a clarifying question.

    Grounds the model in the user's actual local "now" (day of week, date,
    time) rather than letting it guess — a Cyrillic weekday name for the
    wrong day of week is the single most common way relative-time parsing
    silently resolves to the wrong date.
    """
    zone = _safe_zone(ctx.user_timezone)
    now_local = datetime.now(zone)
    weekday_ru = [
        "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    ][now_local.weekday()]

    if not ctx.reasoner_spec or not ctx.reasoner_model or not ctx.reasoner_api_key:
        return ScheduleResolution(
            resolved=False,
            clarifying_question="Уточните дату и время публикации (например: 16.07 в 20:00).",
        )

    prompt_parts = [
        f"Текущее локальное время пользователя: {now_local.strftime('%Y-%m-%d %H:%M')} "
        f"({weekday_ru}), часовой пояс {ctx.user_timezone or DEFAULT_TIMEZONE}."
    ]
    if dialog_context.strip():
        prompt_parts.append(f"Диалог:\n{dialog_context.strip()}")
    prompt_parts.append(f"Запрос:\n{instruction}")

    raw = await call_llm_with_deadline(
        ctx,
        phase="action.schedule_time",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(prompt_parts)},
        ],
        spec=ctx.reasoner_spec,
        model=ctx.reasoner_model,
        api_key=ctx.reasoner_api_key,
        temperature=0.0,
        max_tokens=200,
    )
    parsed = extract_json_object(raw) or {}
    if not parsed.get("resolved"):
        question = str(parsed.get("question") or "").strip()
        return ScheduleResolution(
            resolved=False,
            clarifying_question=question
            or "Уточните дату и время публикации (например: 16.07 в 20:00).",
        )

    raw_dt = str(parsed.get("datetime") or "").strip()
    try:
        local_dt = datetime.fromisoformat(raw_dt).replace(tzinfo=zone)
    except ValueError:
        logger.warning("time_resolver produced unparseable datetime: %r", raw_dt)
        return ScheduleResolution(
            resolved=False,
            clarifying_question="Не удалось разобрать дату и время. Уточните, пожалуйста "
            "(например: 16.07 в 20:00).",
        )

    if local_dt < now_local - _PAST_GRACE:
        return ScheduleResolution(
            resolved=False,
            clarifying_question="Указанное время уже прошло. На когда отложить публикацию?",
        )
    if local_dt > now_local + _MAX_HORIZON:
        return ScheduleResolution(
            resolved=False,
            clarifying_question="Слишком далёкая дата — уточните, пожалуйста, когда "
            "именно опубликовать пост.",
        )

    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    return ScheduleResolution(resolved=True, scheduled_at_utc=utc_dt.isoformat())
