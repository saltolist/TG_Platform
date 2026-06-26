"""Tests for labeled summary formatting in LLM context."""

from __future__ import annotations

from app.services.ai.context_primer import (
    LABEL_CHANNEL_HEAD,
    LABEL_CHANNEL_UPDATED,
    LABEL_DIALOG_SUMMARY,
    LABEL_POST_HEAD,
    LABEL_POST_UPDATED,
    LABEL_USER_REQUEST,
    POST_SCOPE_SYSTEM_ADDENDUM,
    attach_floating_bundle_to_user_message,
    build_dialog_messages,
    build_primer_user_content,
    build_system_prompt,
    format_bundle_sections,
    format_channel_summary,
    wrap_user_request,
)


def test_format_channel_summary_head_and_updated() -> None:
    head = format_channel_summary("## Канал\nТема: Финансы")
    assert head.startswith(f"{LABEL_CHANNEL_HEAD}:")
    assert "Финансы" in head

    updated = format_channel_summary("## Канал\nТема: Крипто", updated=True)
    assert updated.startswith(f"{LABEL_CHANNEL_UPDATED}:")
    assert "Крипто" in updated


def test_format_bundle_sections_post_scope() -> None:
    text = format_bundle_sections(
        channel_text="## Канал\nТема: Финансы",
        post_text="Текст поста",
    )
    assert f"{LABEL_CHANNEL_HEAD}:" in text
    assert f"{LABEL_POST_HEAD}:" in text
    assert "Текст поста" in text


def test_format_bundle_sections_updated_layers() -> None:
    text = format_bundle_sections(
        channel_text="Канал v2",
        post_text="Пост v2",
        channel_updated=True,
        post_updated=True,
    )
    assert f"{LABEL_CHANNEL_UPDATED}:" in text
    assert f"{LABEL_POST_UPDATED}:" in text


def test_build_primer_user_content_adds_dialog_summary() -> None:
    content = build_primer_user_content(
        format_channel_summary("Канал"),
        "Ранее обсуждали ETF.",
    )
    assert f"{LABEL_CHANNEL_HEAD}:" in content
    assert f"{LABEL_DIALOG_SUMMARY}:" in content
    assert "ETF" in content


def test_wrap_user_request_and_floating_attachment() -> None:
    request = wrap_user_request("Как улучшить пост?")
    assert request.startswith(f"{LABEL_USER_REQUEST}:")
    assert "Как улучшить пост?" in request

    combined = attach_floating_bundle_to_user_message(
        format_channel_summary("Канал v2", updated=True),
        "Как улучшить пост?",
    )
    assert f"{LABEL_CHANNEL_UPDATED}:" in combined
    assert f"{LABEL_USER_REQUEST}:" in combined


def test_build_dialog_messages_wraps_user_turns() -> None:
    messages = build_dialog_messages(
        [("user", "Вопрос"), ("assistant", "Ответ")],
        valid_pairs=[("user", "Вопрос"), ("assistant", "Ответ")],
        floating_bundles={},
    )
    assert messages[0]["content"].startswith(f"{LABEL_USER_REQUEST}:")


def test_build_system_prompt_post_scope_addendum() -> None:
    prompt = build_system_prompt("Мой стиль", scope="post")
    assert POST_SCOPE_SYSTEM_ADDENDUM in prompt
    assert "Мой стиль" in prompt
