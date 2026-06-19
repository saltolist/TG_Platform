"""Tests for immutable contextLabel preservation in chat history."""

from __future__ import annotations

from app.services.ai.chat_history import merge_history_stamps
from app.services.ai.context_label import stamp_context_label_on_path
from app.services.ai.context_labels import assemble_reply_messages_from_labels
from app.services.ai.summary_catalog import register_global_summary_version

CHANNEL = {
    "core": {"topic": "Финансы"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}

CHANNEL_V4 = {**CHANNEL, "core": {"topic": "Сводка 4"}}


def test_merge_history_stamps_restores_missing_label() -> None:
    existing = [
        {"role": "user", "text": "3-4-2.2(5.2)(7.2)(9)", "contextLabel": "3-4-2.2(5.2)(7.2)(9)"},
        {"role": "ai", "text": "reply"},
    ]
    incoming = [
        {"role": "user", "text": "3-4-2.2(5.2)(7.2)(9)"},
        {"role": "ai", "text": "reply updated"},
    ]
    merged = merge_history_stamps(existing, incoming)
    assert merged[0]["contextLabel"] == "3-4-2.2(5.2)(7.2)(9)"


def test_merge_never_overwrites_existing_label_with_incoming() -> None:
    existing = [
        {"role": "user", "text": "4-5-9", "contextLabel": "4-5-2.2(5.2)(7.2)(9)"},
        {"role": "ai", "text": "reply"},
    ]
    incoming = [
        {"role": "user", "text": "4-5-9", "contextLabel": "4-0-2.2(5.2)(7.2)(9)"},
        {"role": "ai", "text": "reply"},
    ]
    merged = merge_history_stamps(existing, incoming, strip_incoming=True)
    assert merged[0]["contextLabel"] == "4-5-2.2(5.2)(7.2)(9)"


def test_strip_incoming_stamps_on_patch() -> None:
    existing = [
        {"role": "user", "text": "x", "contextLabel": "5-6-2.2(5.2)(7.2)(9)"},
    ]
    incoming = [
        {"role": "user", "text": "x", "contextLabel": "5-0-2.2(5.2)(7.2)(9)"},
    ]
    merged = merge_history_stamps(existing, incoming, strip_incoming=True)
    assert merged[0]["contextLabel"] == "5-6-2.2(5.2)(7.2)(9)"


def test_stamp_context_label_on_deep_branch_continuation() -> None:
    """Stamp must reach user messages nested in branch continuations (path length > 2)."""
    history = [
        {"role": "user", "text": "u1", "contextLabel": "6-0-1"},
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "b0", "continuation": []},
                {
                    "text": "6-0-2.2",
                    "continuation": [
                        {"role": "ai", "text": "a2"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {"text": "old", "continuation": []},
                                {
                                    "text": "6-0-2.2(5.2)",
                                    "continuation": [
                                        {"role": "ai", "text": "a3"},
                                        {"role": "user", "text": "6-7-2.2(5.2)(7.2)(9)"},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ]
    stamped = stamp_context_label_on_path(
        history,
        [2, 1, 1],
        head=6,
        attached=7,
        turn_label="2.2(5.2)(7.2)(9)",
    )
    assert stamped is not None
    target = stamped[2]["userBranches"][1]["continuation"][1]["userBranches"][1]["continuation"][1]
    assert target["contextLabel"] == "6-7-2.2(5.2)(7.2)(9)"


def test_stamp_skips_when_label_already_set() -> None:
    history = [
        {
            "role": "user",
            "text": "5-6-9",
            "contextLabel": "5-6-2.2(5.2)(7.2)(9)",
        }
    ]
    stamped = stamp_context_label_on_path(
        history,
        [0],
        head=5,
        attached=0,
        turn_label="2.2(5.2)(7.2)(9)",
    )
    assert stamped is not None
    assert stamped[0]["contextLabel"] == "5-6-2.2(5.2)(7.2)(9)"


def test_merge_preserves_labels_in_branch_continuation() -> None:
    existing = [
        {"role": "user", "text": "u1", "contextLabel": "4-0-1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "b0", "continuation": []},
                {
                    "text": "b1",
                    "continuation": [
                        {"role": "ai", "text": "a"},
                        {
                            "role": "user",
                            "text": "4-5-9",
                            "contextLabel": "4-5-2.2(5.2)(7.2)(9)",
                        },
                    ],
                },
            ],
        },
    ]
    incoming = [
        {"role": "user", "text": "u1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "b0", "continuation": []},
                {
                    "text": "b1",
                    "continuation": [
                        {"role": "ai", "text": "a"},
                        {
                            "role": "user",
                            "text": "4-5-9",
                            "contextLabel": "4-0-2.2(5.2)(7.2)(9)",
                        },
                    ],
                },
            ],
        },
    ]
    merged = merge_history_stamps(existing, incoming)
    cont = merged[1]["userBranches"][1]["continuation"]
    assert cont[1]["contextLabel"] == "4-5-2.2(5.2)(7.2)(9)"


def test_stamp_context_label_is_immutable() -> None:
    history = [{"role": "user", "text": "x", "contextLabel": "3-4-9"}]
    stamped = stamp_context_label_on_path(history, [0], head=3, attached=0, turn_label="9")
    assert stamped is not None
    assert stamped[0]["contextLabel"] == "3-4-9"


def test_stamp_context_label_does_not_downgrade_attached_version() -> None:
    history = [
        {
            "role": "user",
            "text": "4-5-9",
            "contextLabel": "4-5-2.2(5.2)(7.2)(9)",
        }
    ]
    stamped = stamp_context_label_on_path(
        history,
        [0],
        head=4,
        attached=0,
        turn_label="2.2(5.2)(7.2)(9)",
    )
    assert stamped is not None
    assert stamped[0]["contextLabel"] == "4-5-2.2(5.2)(7.2)(9)"


def test_floating_bundle_uses_immutable_stamped_label() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for topic in ("Сводка 2", "Сводка 3", "Сводка 4"):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": topic}},
            telegram=None,
        )
    history = [
        {"role": "user", "text": "u1", "contextLabel": "3-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "3-4-2.2(5.2)(7.2)(9)", "contextLabel": "3-4-2.2(5.2)(7.2)(9)"},
        {"role": "ai", "text": "a9"},
    ]
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="3-0-2.2(5.2)(7.2)(10)",
        scope="global",
        history=history,
        chat_meta={
            "label_context": {
                "": {
                    "head_version": 3,
                    "pending_version": 4,
                    "pending_since_turn": 2,
                }
            }
        },
        catalog=catalog,
    )
    assert messages is not None
    stamped_turn = next(
        m
        for m in messages[3:]
        if m["role"] == "user" and "3-4-2.2(5.2)(7.2)(9)" in m["content"]
    )
    assert "SUMMARY_BUNDLE:" in stamped_turn["content"]
    assert "Сводка 4" in stamped_turn["content"]
    current_turn = next(
        m for m in messages[3:] if m["role"] == "user" and "3-0-2.2(5.2)(7.2)(10)" in m["content"]
    )
    assert "SUMMARY_BUNDLE:" not in current_turn["content"]
