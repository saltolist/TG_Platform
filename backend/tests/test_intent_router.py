"""Tests for rule-based intent routing."""

from __future__ import annotations

from app.services.ai.intent_router import classify_intent, parse_period


def test_classify_intent_content_default() -> None:
    assert classify_intent("Расскажи про ETF", has_post_context=False) == "content"
    assert classify_intent("Привет", has_post_context=True) == "content"


def test_classify_intent_post_analytics_with_post_context() -> None:
    assert (
        classify_intent("Сколько просмотров у поста?", has_post_context=True) == "post_analytics"
    )


def test_classify_intent_post_analytics_global_without_channel_markers() -> None:
    assert (
        classify_intent("Как зашёл пост про скидки?", has_post_context=False) == "post_analytics"
    )


def test_classify_intent_channel_analytics() -> None:
    assert (
        classify_intent("Как растёт канал по просмотрам?", has_post_context=False)
        == "channel_analytics"
    )


def test_parse_period_phrases() -> None:
    assert parse_period("Покажи за неделю") == "7d"
    assert parse_period("За месяц") == "30d"
    assert parse_period("За сутки") == "24h"
    assert parse_period("Без периода") == "30d"
