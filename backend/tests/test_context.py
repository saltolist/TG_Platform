"""Tests for AI context assembly (Phase 2, step 3.3)."""

from __future__ import annotations

from app.services.ai.bundle import build_summary_bundle
from app.services.ai.chat_history import (
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW


CHANNEL = {
    "core": {"topic": "Финансы", "audience": "Новички"},
    "voice": {"tone": "Разговорный"},
    "rules": {"must": "Без жаргона", "avoid": "Кликбейт"},
    "rubrics": [{"id": "r1", "title": "Разбор", "description": "Простые объяснения"}],
}

POST = {
    "text": "Текст поста про инвестиции",
    "metrics": {"views": "1 000", "reposts": 5, "reactions": [{"emoji": "🔥", "count": 10}]},
}


def test_flatten_visible_with_paths_uses_active_branch_only() -> None:
    history = [
        {
            "role": "user",
            "userBranches": [
                {
                    "text": "Старый вопрос",
                    "continuation": [
                        {"role": "ai", "text": "Старый ответ"},
                        {"role": "user", "text": "Продолжение старой ветки"},
                    ],
                },
                {
                    "text": "Новый вопрос",
                    "continuation": [{"role": "ai", "text": "Новый ответ"}],
                },
            ],
            "activeUserBranch": 1,
        }
    ]
    pairs = linearize_for_llm(history)
    joined = " ".join(content for _, content in pairs)
    assert "Старый вопрос" not in joined
    assert "Продолжение старой ветки" not in joined
    assert "Новый вопрос" in joined
    assert "Новый ответ" in joined


def test_linearize_strips_trailing_empty_ai_shell() -> None:
    history = [
        {"role": "user", "text": "Привет"},
        {"role": "ai", "text": ""},
    ]
    pairs = linearize_for_llm(history)
    assert pairs == [("user", "Привет")]


def test_filter_alternating_roles_skips_leading_assistant() -> None:
    pairs = [("assistant", "служебное"), ("user", "Вопрос"), ("assistant", "Ответ")]
    assert filter_alternating_roles(pairs) == [("user", "Вопрос"), ("assistant", "Ответ")]


def test_build_summary_bundle_includes_channel_and_post() -> None:
    bundle = build_summary_bundle(CHANNEL, post=POST)
    assert "Финансы" in bundle
    assert "Разбор" in bundle
    assert "Текст поста про инвестиции" in bundle
    assert "Просмотры: 1 000" in bundle


def test_assemble_reply_messages_includes_primer_and_window() -> None:
    history = [
        {"role": "user", "text": "Первый вопрос"},
        {"role": "ai", "text": "Первый ответ"},
        {"role": "user", "text": "Второй вопрос"},
        {"role": "ai", "text": ""},
    ]
    messages = assemble_reply_messages(
        ai_profile={"systemPrompt": "Системный промпт"},
        user_text="Второй вопрос",
        scope="global",
        history=history,
        channel_profile=CHANNEL,
    )

    assert messages[0] == {"role": "system", "content": "Системный промпт"}
    assert messages[1]["role"] == "user"
    assert "SUMMARY_BUNDLE:" in messages[1]["content"]
    assert "Финансы" in messages[1]["content"]
    assert messages[2] == {"role": "assistant", "content": PRIMER_ACK}

    dialog = messages[3:]
    assert len(dialog) <= PROMPT_WINDOW
    assert dialog[-1] == {"role": "user", "content": "Второй вопрос"}
    assert dialog[-2] == {"role": "assistant", "content": "Первый ответ"}


def test_assemble_reply_messages_post_scope_adds_post_to_bundle() -> None:
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Комментарий к посту",
        scope="post",
        channel_profile=CHANNEL,
        post_data=POST,
    )
    primer = messages[1]["content"]
    assert "Текст поста про инвестиции" in primer
    assert "[Чат поста" not in primer


def test_assemble_reply_messages_includes_rolling_summary_in_primer() -> None:
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Новый вопрос",
        scope="global",
        channel_profile=CHANNEL,
        chat_meta={"rolling_summary": "Ранее мы обсуждали ETF и риски."},
    )
    assert "CONTEXT_SUMMARY:" in messages[1]["content"]
    assert "ETF" in messages[1]["content"]
