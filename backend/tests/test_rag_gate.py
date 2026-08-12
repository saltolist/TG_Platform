"""Tests for L0 RAG gate (rule-based skip)."""

from __future__ import annotations

import pytest

from app.services.ai.rag_gate import l0_skip_reason, should_skip_rag


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "привет",
        "Спасибо!",
        "ок",
        "понял",
        "договорились",
        "hi",
        "thanks",
    ],
)
def test_l0_skip_non_substantive(text: str) -> None:
    assert l0_skip_reason(text) == "non_substantive"
    assert should_skip_rag(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "перепиши покороче",
        "Сократи текст",
        "Сделай тон более официальным",
        "Исправь опечатки",
        "Убери эмодзи",
        "make it shorter",
    ],
)
def test_l0_skip_style_edit(text: str) -> None:
    assert l0_skip_reason(text) == "style_edit"


@pytest.mark.parametrize(
    "text",
    [
        "Что по дедлайнам?",
        "покороче — а сколько было просмотров у поста?",
        "Расскажи про заметку про ETF",
        "перепиши покороче?",
        "Какие посты мы планировали на март",
    ],
)
def test_l0_does_not_skip_real_questions(text: str) -> None:
    assert l0_skip_reason(text) is None
    assert should_skip_rag(text) is False
