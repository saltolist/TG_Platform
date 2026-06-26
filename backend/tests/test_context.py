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
    "id": "post-1",
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

    # Base platform prompt is always present; user prompt is appended after it
    assert messages[0]["role"] == "system"
    assert "Системный промпт" in messages[0]["content"]
    assert "TG Platform" in messages[0]["content"]

    # Primer: скрытая двойка — user с bundle, затем assistant-подтверждение.
    primer_user = messages[1]
    assert primer_user["role"] == "user"
    assert "Профиль канала:" in primer_user["content"]
    assert "Финансы" in primer_user["content"]
    assert messages[2] == {"role": "assistant", "content": PRIMER_ACK}

    # Диалоговое окно: не превышает PROMPT_WINDOW, текст user-запроса присутствует.
    dialog = messages[3:]
    assert len(dialog) <= PROMPT_WINDOW
    last_user = next(m for m in reversed(dialog) if m["role"] == "user")
    assert "Второй вопрос" in last_user["content"]


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
    assert "Пост:" in primer
    assert "конкретного поста канала" in messages[0]["content"]
    assert "[Чат поста" not in primer


def test_assemble_reply_messages_includes_rolling_summary_in_primer() -> None:
    # rolling_summary попадает в primer как CONTEXT_SUMMARY когда:
    # - есть вытесненные пары (история длиннее PROMPT_WINDOW)
    # - rolling_summary_idx указывает сколько пар уже учтено
    history = []
    for i in range(PROMPT_WINDOW + 1):
        history.append({"role": "user", "text": f"вопрос {i}"})
        history.append({"role": "ai", "text": f"ответ {i}"})

    # В label-пути rolling_summary хранится внутри label_context (THREAD_LABEL_STATE_KEY).
    chat_meta = {
        "active_thread_key": "",
        "label_context": {
            "": {
                "rolling_summary": "Ранее мы обсуждали ETF и риски.",
                "rolling_summary_idx": PROMPT_WINDOW,
            }
        },
    }
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Новый вопрос",
        scope="global",
        channel_profile=CHANNEL,
        history=history,
        chat_meta=chat_meta,
    )
    primer_content = messages[1]["content"]
    assert "Профиль канала:" in primer_content
    assert "Финансы" in primer_content
    assert "Сводка по диалогу:" in primer_content
    assert "ETF" in primer_content
