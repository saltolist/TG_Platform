"""Tests for LLM context terminal logging helpers."""

from __future__ import annotations

from app.services.ai.context_log import (
    format_active_thread,
    format_context_stamp_json,
    format_history_tree,
    format_llm_messages,
    get_chat_filter,
    init_chat_filter,
    set_chat_filter,
    should_log_llm_context,
)


def test_format_history_tree_shows_all_user_branches() -> None:
    history = [
        {
            "role": "user",
            "userBranches": [
                {
                    "text": "Старый вопрос",
                    "continuation": [{"role": "ai", "text": "Старый ответ"}],
                },
                {
                    "text": "Новый вопрос",
                    "continuation": [{"role": "ai", "text": "Новый ответ"}],
                },
            ],
            "activeUserBranch": 1,
        }
    ]
    tree = format_history_tree(history)
    assert "branch 0" in tree
    assert "branch 1 *ACTIVE*" in tree
    assert "Старый вопрос" in tree
    assert "Новый вопрос" in tree
    assert "Старый ответ" in tree
    assert "Новый ответ" in tree


def test_format_active_thread_uses_only_active_branch() -> None:
    history = [
        {
            "role": "user",
            "userBranches": [
                {
                    "text": "Старый вопрос",
                    "continuation": [{"role": "ai", "text": "Старый ответ"}],
                },
                {
                    "text": "Новый вопрос",
                    "continuation": [{"role": "ai", "text": "Новый ответ"}],
                },
            ],
            "activeUserBranch": 1,
        }
    ]
    thread = format_active_thread(history)
    assert "Новый вопрос" in thread
    assert "Новый ответ" in thread
    assert "Старый вопрос" not in thread
    assert "Старый ответ" not in thread


def test_format_llm_messages_labels_primer() -> None:
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Профиль канала:\nChannel info"},
        {"role": "assistant", "content": "Понял, учту при ответах."},
        {"role": "user", "content": "Hello"},
    ]
    formatted = format_llm_messages(messages)
    assert "[0] system" in formatted
    assert "[1] user/primer" in formatted
    assert "[2] assistant/primer-ack" in formatted
    assert "Профиль канала:" in formatted
    assert "Hello" in formatted


def test_chat_filter_runtime() -> None:
    init_chat_filter("")
    assert get_chat_filter() == ""
    set_chat_filter("gc1")
    assert get_chat_filter() == "gc1"
    set_chat_filter("")
    assert get_chat_filter() == ""


def test_should_log_llm_context_global_chat() -> None:
    assert should_log_llm_context(
        enabled=True,
        chat_filter="chat-abc",
        scope="global",
        chat_id="chat-abc",
        post_id=None,
        post_chat_id=None,
    )
    assert not should_log_llm_context(
        enabled=True,
        chat_filter="chat-abc",
        scope="global",
        chat_id="other",
        post_id=None,
        post_chat_id=None,
    )


def test_should_log_llm_context_post_chat_by_chat_id() -> None:
    assert should_log_llm_context(
        enabled=True,
        chat_filter="pc1",
        scope="post",
        chat_id=None,
        post_id="21",
        post_chat_id="pc1",
    )


def test_should_log_llm_context_post_chat_full_filter() -> None:
    assert should_log_llm_context(
        enabled=True,
        chat_filter="post:21:pc1",
        scope="post",
        chat_id=None,
        post_id="21",
        post_chat_id="pc1",
    )
    assert not should_log_llm_context(
        enabled=True,
        chat_filter="post:99:pc1",
        scope="post",
        chat_id=None,
        post_id="21",
        post_chat_id="pc1",
    )


def test_should_log_llm_context_requires_chat_filter() -> None:
    assert not should_log_llm_context(
        enabled=True,
        chat_filter="",
        scope="global",
        chat_id="chat-abc",
        post_id=None,
        post_chat_id=None,
    )
    assert not should_log_llm_context(
        enabled=False,
        chat_filter="chat-abc",
        scope="global",
        chat_id="chat-abc",
        post_id=None,
        post_chat_id=None,
    )


def test_format_history_tree_shows_context_stamp_json() -> None:
    stamp = {
        "address": {"channel": 1, "post": 1, "msg": 1},
        "head": {"channel": 5, "post": 2},
        "attached": {"channel": 5, "post": 2},
    }
    history = [
        {
            "role": "user",
            "text": "Hello",
            "contextStamp": stamp,
        }
    ]
    tree = format_history_tree(history)
    assert "contextStamp:" in tree
    assert '"channel": 1' in tree
    assert '"msg": 1' in tree


def test_format_llm_messages_includes_context_stamp_json() -> None:
    stamp = {
        "address": {"channel": 3, "post": 0, "msg": 2},
        "head": {"channel": 3, "post": 0},
        "attached": {"channel": 3, "post": 0},
    }
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Hi"},
    ]
    formatted = format_llm_messages(
        messages,
        message_labels={1: "user [3-0-2]"},
        message_stamps={1: stamp},
    )
    assert "[1] user [3-0-2]" in formatted
    assert "contextStamp:" in formatted
    assert format_context_stamp_json(stamp) in formatted
