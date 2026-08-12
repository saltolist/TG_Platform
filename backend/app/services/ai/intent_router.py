"""Rule-based intent classification for AI reply routing."""

from __future__ import annotations

from typing import Literal

from app.services.analytics.channel_metrics import VALID_PERIODS

Intent = Literal["content", "post_analytics", "channel_analytics"]

_ANALYTICS_MARKERS = (
    "просмотр",
    "охват",
    "реакци",
    "вовлечённост",
    "вовлеченност",
    "er ",
    "как зашёл",
    "как зашел",
    "статистик",
    "аналитик",
)

_CHANNEL_SCOPE_MARKERS = (
    "канал",
    "все посты",
    "топ пост",
    "выстрелил",
    "рост подписчик",
)

_PERIOD_PHRASES: dict[str, str] = {
    "сутки": "24h",
    "день": "24h",
    "сегодня": "24h",
    "неделю": "7d",
    "недели": "7d",
    "месяц": "30d",
    "квартал": "90d",
    "всё время": "all",
    "все время": "all",
}


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def classify_intent(user_text: str, *, has_post_context: bool) -> Intent:
    """Classify user message intent before RAG embedding."""
    text = (user_text or "").strip()
    if not text or not _contains_marker(text, _ANALYTICS_MARKERS):
        return "content"

    has_channel_scope = _contains_marker(text, _CHANNEL_SCOPE_MARKERS)
    if has_channel_scope:
        return "channel_analytics"
    if has_post_context:
        return "post_analytics"
    return "post_analytics"


def parse_period(user_text: str, *, default: str = "30d") -> str:
    lowered = (user_text or "").lower()
    for phrase, period in _PERIOD_PHRASES.items():
        if phrase in lowered and period in VALID_PERIODS:
            return period
    return default if default in VALID_PERIODS else "30d"
