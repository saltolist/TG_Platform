"""Tests for extract_last_proposed_edit (chat 2b9447dd regression)."""

from __future__ import annotations

from app.services.ai.chat_history import extract_last_proposed_edit


def test_extract_from_preview_after_reject() -> None:
    """A resolved (rejected) turn keeps the proposed patch under `preview`."""
    history = [
        {"role": "user", "text": "Добавь цифру 3"},
        {
            "role": "ai",
            "text": "Предложенное действие отклонено.",
            "proposal": {
                "command": "edit_post",
                "preview": {"patch": {"textHtml": "Текст.3"}},
            },
            "proposalDecision": "reject",
        },
    ]
    assert extract_last_proposed_edit(history) == "Текст.3"


def test_extract_from_payload_before_decision() -> None:
    """A still-pending proposal carries the patch under `payload`."""
    history = [
        {"role": "user", "text": "Добавь цифру 3"},
        {
            "role": "ai",
            "text": "",
            "proposal": {
                "command": "edit_post",
                "payload": {"patch": {"textHtml": "Текст.3"}},
            },
        },
    ]
    assert extract_last_proposed_edit(history) == "Текст.3"


def test_falls_back_to_plain_text_without_html() -> None:
    history = [
        {
            "role": "ai",
            "text": "",
            "proposal": {
                "command": "edit_post",
                "preview": {"patch": {"text": "Текст.3"}},
            },
        },
    ]
    assert extract_last_proposed_edit(history) == "Текст.3"


def test_returns_none_without_proposal() -> None:
    history = [
        {"role": "user", "text": "Привет"},
        {"role": "ai", "text": "Привет!"},
    ]
    assert extract_last_proposed_edit(history) is None


def test_ignores_non_edit_post_commands() -> None:
    history = [
        {
            "role": "ai",
            "text": "",
            "proposal": {
                "command": "delete_post",
                "preview": {"patch": {"textHtml": "irrelevant"}},
            },
        },
    ]
    assert extract_last_proposed_edit(history) is None


def test_returns_most_recent_proposal_when_several() -> None:
    history = [
        {
            "role": "ai",
            "text": "",
            "proposal": {
                "command": "edit_post",
                "preview": {"patch": {"textHtml": "Первый вариант"}},
            },
        },
        {"role": "user", "text": "Нет, по-другому"},
        {
            "role": "ai",
            "text": "",
            "proposal": {
                "command": "edit_post",
                "preview": {"patch": {"textHtml": "Второй вариант"}},
            },
        },
    ]
    assert extract_last_proposed_edit(history) == "Второй вариант"


def test_empty_history_returns_none() -> None:
    assert extract_last_proposed_edit([]) is None
