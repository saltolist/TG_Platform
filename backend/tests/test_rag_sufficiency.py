"""Tests for Tier B LLM sufficiency check."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.rag_escalation import TierASignals
from app.services.ai.rag_sufficiency import (
    TierBResult,
    build_tier_b_messages,
    evaluate_tier_b,
    parse_tier_b_response,
)


def _signals(**kwargs: bool) -> TierASignals:
    return TierASignals(
        pointer_phrase=kwargs.get("pointer_phrase", False),
        answer_type_mismatch=kwargs.get("answer_type_mismatch", False),
        chunk_too_short=kwargs.get("chunk_too_short", False),
        is_followup=kwargs.get("is_followup", False),
    )


def test_build_tier_b_messages_shape() -> None:
    messages = build_tier_b_messages(
        user_text="Сколько выручки?",
        chunk_text="Краткий анонс без цифр.",
        signals=_signals(answer_type_mismatch=True),
        neighbors={"notes": [{"id": "n1", "title": "Отчёт"}], "media": [], "comments_count": 0},
    )
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    payload = json.loads(messages[1]["content"])
    assert payload["question"] == "Сколько выручки?"
    assert payload["chunk"] == "Краткий анонс без цифр."
    assert payload["signals"]["answer_type_mismatch"] is True
    assert payload["neighbors"]["notes"] == [{"id": "n1", "title": "Отчёт"}]


def test_build_tier_b_messages_truncates_long_chunk() -> None:
    messages = build_tier_b_messages(
        user_text="Вопрос",
        chunk_text="x" * 2000,
        signals=_signals(),
        neighbors={"notes": [], "media": [], "comments_count": 0},
    )
    payload = json.loads(messages[1]["content"])
    assert len(payload["chunk"]) == 1500


def test_parse_tier_b_response_clean_json() -> None:
    result = parse_tier_b_response('{"sufficient": false, "open_next": ["note:n1"]}')
    assert result == TierBResult(sufficient=False, open_next=["note:n1"], error=None)


def test_parse_tier_b_response_code_fence() -> None:
    raw = '```json\n{"sufficient": true, "open_next": []}\n```'
    result = parse_tier_b_response(raw)
    assert result.sufficient is True
    assert result.open_next == []
    assert result.error is None


def test_parse_tier_b_response_extra_prose() -> None:
    raw = 'Вот ответ: {"sufficient": false, "open_next": ["media:mk-1", "comments"]}'
    result = parse_tier_b_response(raw)
    assert result.sufficient is False
    assert result.open_next == ["media:mk-1", "comments"]


def test_parse_tier_b_response_garbage_fail_open() -> None:
    result = parse_tier_b_response("not json at all")
    assert result.sufficient is True
    assert result.open_next == []
    assert result.error == "no_json"


def test_parse_tier_b_response_missing_sufficient_fail_open() -> None:
    result = parse_tier_b_response('{"open_next": ["note:n1"]}')
    assert result.sufficient is True
    assert result.open_next == []
    assert result.error == "missing_field"


def test_parse_tier_b_response_invalid_open_next_defaults_empty() -> None:
    result = parse_tier_b_response('{"sufficient": false, "open_next": "note:n1"}')
    assert result.sufficient is False
    assert result.open_next == []
    assert result.error is None


@pytest.mark.asyncio
async def test_evaluate_tier_b_happy_path() -> None:
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"sufficient": false, "open_next": ["note:n1"]}',
    ):
        result = await evaluate_tier_b(
            user_text="Сколько?",
            chunk_text="Анонс",
            signals=_signals(answer_type_mismatch=True),
            neighbors={"notes": [{"id": "n1", "title": "Отчёт"}], "media": [], "comments_count": 0},
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
        )
    assert result.sufficient is False
    assert result.open_next == ["note:n1"]
    assert result.error is None


@pytest.mark.asyncio
async def test_evaluate_tier_b_call_failed_fail_open() -> None:
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network"),
    ):
        result = await evaluate_tier_b(
            user_text="Вопрос",
            chunk_text="Чанк",
            signals=_signals(),
            neighbors={"notes": [], "media": [], "comments_count": 0},
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
        )
    assert result.sufficient is True
    assert result.open_next == []
    assert result.error == "call_failed"
