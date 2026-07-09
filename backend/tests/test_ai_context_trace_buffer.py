"""Tests for in-memory AI context trace buffer."""

from __future__ import annotations

from app.services.ai.ai_context_trace_buffer import (
    clear_context_exchanges,
    list_context_exchanges,
    lookup_keys,
    make_stored_exchange,
    store_context_exchange,
)


def test_lookup_keys_post_chat() -> None:
    keys = lookup_keys(
        scope="post",
        chat_id=None,
        post_id="post-1",
        post_chat_id="chat-abc",
    )
    assert keys == ["chat-abc", "post:post-1:chat-abc"]


def test_store_and_list_by_post_chat_id() -> None:
    clear_context_exchanges()
    store_context_exchange(
        make_stored_exchange(
            scope="post",
            chat_id=None,
            post_id="post-1",
            post_chat_id="chat-abc",
            user_text="первое сообщение",
            provider="DeepSeek",
            model="chat",
            pipeline="AI PIPELINE …",
            request="AI REQUEST …",
            response="AI RESPONSE …",
        )
    )
    items = list_context_exchanges("chat-abc")
    assert len(items) == 1
    assert items[0].user_text == "первое сообщение"
    assert "AI PIPELINE" in items[0].pipeline

    by_composite = list_context_exchanges("post:post-1:chat-abc")
    assert len(by_composite) == 1
    clear_context_exchanges("chat-abc")
    assert list_context_exchanges("chat-abc") == []
