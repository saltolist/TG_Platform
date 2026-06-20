"""Tests for context labels 1-2-3 and summary catalog."""

from __future__ import annotations

from typing import Any

from app.services.ai.context_label import (
    enumerate_active_user_turns,
    format_context_label,
    parse_context_label,
    parse_turn_label,
    stamp_context_label_on_path,
    turn_label_for_node,
)
from app.services.ai.context_labels import (
    assemble_reply_messages_from_labels,
    mature_head_version,
    plan_context_label_for_turn,
    primer_head_from_thread,
    seed_label_thread_from_parent,
)
from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.summary_catalog import (
    catalog_from_profile,
    register_global_summary_version,
    resolve_bundle_text,
)

CHANNEL = {
    "core": {"topic": "Финансы"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}

CHANNEL_V2 = {**CHANNEL, "core": {"topic": "Крипто"}}


def test_format_and_parse_context_label() -> None:
    assert format_context_label(1, 0, "3") == "1-0-3"
    assert format_context_label(1, 2, "3.1") == "1-2-3.1"
    assert format_context_label(1, 0, "3.2(4)") == "1-0-3.2(4)"
    assert format_context_label(1, 0, "3.2(4.2(5))") == "1-0-3.2(4.2(5))"
    assert parse_context_label("1-2-3.1") == (1, 2, "3.1")
    assert parse_context_label("1-0-3.2(4.2(5))") == (1, 0, "3.2(4.2(5))")


def test_parse_turn_label_nested() -> None:
    assert parse_turn_label("3") == "3"
    assert parse_turn_label("3.2") == "3.2"
    assert parse_turn_label("3.2(4)") == "3.2(4)"
    assert parse_turn_label("3.2(4.2(5))") == "3.2(4.2(5))"
    assert parse_turn_label("3.2(4") is None
    assert parse_turn_label("3.2(4.2(5)") is None


def test_turn_label_for_node_nested() -> None:
    assert turn_label_for_node(global_turn=3, branch_index=1, branched=True, path_prefix=None) == "3.2"
    assert turn_label_for_node(global_turn=4, branch_index=0, branched=False, path_prefix="3.2") == "3.2(4)"
    assert (
        turn_label_for_node(global_turn=4, branch_index=0, branched=True, path_prefix="3.2")
        == "3.2(4)"
    )
    assert (
        turn_label_for_node(global_turn=4, branch_index=1, branched=True, path_prefix="3.2")
        == "3.2(4.2)"
    )
    assert (
        turn_label_for_node(global_turn=5, branch_index=0, branched=False, path_prefix="3.2(4.2)")
        == "3.2(4.2(5))"
    )


def test_register_global_summary_version_monotonic() -> None:
    catalog, v1 = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    assert v1 == 1
    same, none = register_global_summary_version(catalog, channel=CHANNEL, telegram=None)
    assert none is None
    updated, v2 = register_global_summary_version(same, channel=CHANNEL_V2, telegram=None)
    assert v2 == 2
    assert len(updated["global"]) == 2


def test_turn_labels_with_branches() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "c1", "continuation": []},
                {"text": "c2", "continuation": []},
            ],
        },
    ]
    entries = enumerate_active_user_turns(history)
    assert entries[1]["turn_label"] == "2.2"


def test_turn_labels_nested_continuation() -> None:
    history = [
        {"role": "user", "text": "u1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2"},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "u3-main", "continuation": []},
                {
                    "text": "u3-branch",
                    "continuation": [
                        {"role": "ai", "text": "a3"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {"text": "u4-main", "continuation": []},
                                {
                                    "text": "u4-branch",
                                    "continuation": [
                                        {"role": "ai", "text": "a4"},
                                        {"role": "user", "text": "u5"},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ]
    labels = [entry["turn_label"] for entry in enumerate_active_user_turns(history)]
    assert labels == ["1", "2", "3.2", "3.2(4.2)", "3.2(4.2(5))"]


def test_stamp_context_label_migrates_legacy_parent_label_to_branch_zero() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "contextLabel": "4-0-2",
            "userBranches": [
                {"text": "c1", "continuation": []},
                {"text": "c2", "continuation": []},
            ],
        },
    ]
    stamped = stamp_context_label_on_path(history, [2], head=4, attached=0, turn_label="2.2")
    assert stamped is not None
    msg = stamped[2]
    assert msg.get("contextLabel") is None
    assert msg["userBranches"][0]["contextLabel"] == "4-0-2"
    assert msg["userBranches"][1]["contextLabel"] == "4-0-2.2"


def test_stamp_context_label_on_branched_fork() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "c1", "continuation": [], "contextLabel": "4-0-2"},
                {"text": "c2", "continuation": []},
            ],
        },
    ]
    stamped = stamp_context_label_on_path(history, [2], head=4, attached=0, turn_label="2.2")
    assert stamped is not None
    msg = stamped[2]
    assert msg.get("contextLabel") is None
    assert msg["userBranches"][0]["contextLabel"] == "4-0-2"
    assert msg["userBranches"][1]["contextLabel"] == "4-0-2.2"


def test_read_stamped_context_label_uses_active_branch() -> None:
    from app.services.ai.context_label import read_stamped_context_label

    message = {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {"text": "c1", "contextLabel": "4-0-2"},
            {"text": "c2", "contextLabel": "4-0-2.2"},
        ],
    }
    assert read_stamped_context_label(message, branch_index=0) == "4-0-2"
    assert read_stamped_context_label(message, branch_index=1) == "4-0-2.2"


def test_stamp_context_label_on_path() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {"role": "user", "text": "c"},
    ]
    stamped = stamp_context_label_on_path(history, [2], head=1, attached=2, turn_label="2")
    assert stamped is not None
    assert stamped[2]["contextLabel"] == "1-2-2"


def test_assemble_from_labels_uses_catalog_versions() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="Вопрос",
        scope="global",
        history=[{"role": "user", "text": "Привет"}, {"role": "ai", "text": "Ответ"}],
        chat_meta={"label_context": {"": {"head_version": 1, "pending_version": 2, "pending_since_turn": 1}}},
        catalog=catalog,
    )
    assert messages is not None
    primer = messages[1]["content"]
    assert "Финансы" in primer


def test_mature_head_when_pending_turn_leaves_prompt_window() -> None:
    """Pending v11 becomes head once anchor turn 5 scrolls out of PROMPT_WINDOW."""
    from app.services.ai.context_labels import advance_label_thread_after_reply, mature_head_version

    state = {
        "head_version": 10,
        "pending_version": 11,
        "pending_since_turn": 5,
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }
    # Last 5 messages in an 8-turn dialog — turns 7 and 8 only (anchor 5 gone).
    window = {7, 8}
    matured = mature_head_version(state, user_turn_count=8, window_user_turns=window)
    assert matured["head_version"] == 11
    assert matured["pending_version"] == 0

    head, attached, next_state = advance_label_thread_after_reply(
        state,
        user_turn_count=8,
        turn_label="2.2(8)",
        latest_catalog_version=11,
        window_user_turns=window,
    )
    assert head == 11
    assert attached == 0
    assert next_state["head_version"] == 11


def test_fork_seeds_parent_head_not_pending_future() -> None:
    parent = {"head_version": 1, "pending_version": 3, "pending_since_turn": 8}
    child = seed_label_thread_from_parent(parent, user_turn_count=4)
    assert child["pending_version"] == 0


def test_fork_suppresses_parent_only_catalog_gap() -> None:
    """Parent head=3 on long branch; branch 0 label head=2 — do not auto-attach v3."""
    parent = {"head_version": 3, "pending_version": 0, "pending_since_turn": 0}
    history = [
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "u", "contextLabel": "2-0-3.2(4)"},
                {"text": "u edited", "continuation": []},
            ],
        },
    ]
    child = seed_label_thread_from_parent(
        parent,
        user_turn_count=4,
        history=history,
        latest_catalog_version=3,
    )
    head, attached, _ = plan_context_label_for_turn(
        child,
        user_turn_count=4,
        turn_label="3.2(4.2)",
        latest_catalog_version=3,
    )
    assert head == 2
    assert attached == 0


def test_fork_attaches_catalog_version_newer_than_shared_head() -> None:
    """Branch 0 and parent both at head=3; catalog v4 must attach on edit fork."""
    parent = {"head_version": 3, "pending_version": 0, "pending_since_turn": 0}
    history = [
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "u", "contextLabel": "3-0-3.2(4)"},
                {"text": "u edited", "continuation": []},
            ],
        },
    ]
    child = seed_label_thread_from_parent(
        parent,
        user_turn_count=4,
        history=history,
        latest_catalog_version=4,
    )
    head, attached, _ = plan_context_label_for_turn(
        child,
        user_turn_count=4,
        turn_label="3.2(4.2)",
        latest_catalog_version=4,
    )
    assert head == 3
    assert attached == 4


def test_plan_context_label_first_turn_no_attach() -> None:
    from app.services.ai.context_labels import empty_label_thread_state

    state = empty_label_thread_state()
    head, attached, matured = plan_context_label_for_turn(
        state,
        user_turn_count=1,
        turn_label="1",
        latest_catalog_version=1,
    )
    assert head == 1
    assert attached == 0
    assert matured["head_version"] == 1
    assert matured.get("pending_version", 0) == 0


def test_plan_context_label_stable_head_no_attach() -> None:
    state = {"head_version": 1, "pending_version": 0, "pending_since_turn": 0}
    for turn in (2, 3, 4):
        head, attached, _ = plan_context_label_for_turn(
            state,
            user_turn_count=turn,
            turn_label=str(turn),
            latest_catalog_version=1,
        )
        assert head == 1
        assert attached == 0


def test_read_context_label_normalizes_redundant_attach() -> None:
    from app.services.ai.context_label import read_context_label

    parsed = read_context_label({"role": "user", "contextLabel": "1-1-4"})
    assert parsed == (1, 0, "4")


def test_plan_context_label_attaches_pending_version() -> None:
    state = {"head_version": 1, "pending_version": 0, "pending_since_turn": 0}
    head, attached, _ = plan_context_label_for_turn(
        state,
        user_turn_count=2,
        turn_label="2",
        latest_catalog_version=2,
    )
    assert head == 1
    assert attached == 2


def test_plan_context_label_does_not_reattach_on_later_turns() -> None:
    state = {"head_version": 1, "pending_version": 2, "pending_since_turn": 2}
    head, attached, _ = plan_context_label_for_turn(
        state,
        user_turn_count=3,
        turn_label="3",
        latest_catalog_version=2,
    )
    assert head == 1
    assert attached == 0


def test_pending_queue_matures_oldest_version_first() -> None:
    """Two profile bumps: head must advance 1→2→3 in order, not skip v2."""
    history = [
        {"role": "user", "text": "u1", "contextLabel": "1-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "1-0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextLabel": "1-0-3"},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "u4", "contextLabel": "1-2-4"},
        {"role": "ai", "text": "a4"},
        {"role": "user", "text": "u5", "contextLabel": "1-0-5"},
        {"role": "ai", "text": "a5"},
        {"role": "user", "text": "u6", "contextLabel": "1-0-6"},
        {"role": "ai", "text": "a6"},
        {"role": "user", "text": "u7", "contextLabel": "1-3-7"},
        {"role": "ai", "text": "a7"},
        {"role": "user", "text": "u8", "contextLabel": "1-0-8"},
        {"role": "ai", "text": "a8"},
    ]
    # Legacy broken state: only the latest pending survived in thread meta.
    state = {"head_version": 1, "pending_version": 3, "pending_since_turn": 7}

    matured_at_8 = mature_head_version(state, user_turn_count=8, history=history)
    assert matured_at_8["head_version"] == 1

    matured_at_9 = mature_head_version(state, user_turn_count=9, history=history)
    assert matured_at_9["head_version"] == 2
    assert matured_at_9["pending_version"] == 3

    head, attached, _ = plan_context_label_for_turn(
        matured_at_9,
        user_turn_count=9,
        turn_label="9",
        latest_catalog_version=3,
        history=history,
    )
    assert head == 2
    assert attached == 0

    matured_at_12 = mature_head_version(state, user_turn_count=12, history=history)
    assert matured_at_12["head_version"] == 3
    assert matured_at_12["pending_version"] == 0


def test_pending_queue_appends_without_dropping_earlier_version() -> None:
    state = {"head_version": 1, "pending_version": 2, "pending_since_turn": 4}
    head, attached, next_state = plan_context_label_for_turn(
        state,
        user_turn_count=7,
        turn_label="7",
        latest_catalog_version=3,
    )
    assert head == 1
    assert attached == 3
    queue = next_state["pending_queue"]
    assert [item["version"] for item in queue] == [2, 3]
    assert queue[0]["since_turn"] == 4
    assert queue[1]["since_turn"] == 7


def test_primer_head_advances_through_pending_queue() -> None:
    history: list[dict[str, Any]] = []
    labels = {
        1: "1-0-1",
        4: "1-2-4",
        7: "1-3-7",
    }
    for turn in range(1, 8):
        history.append({"role": "user", "text": f"u{turn}", "contextLabel": labels.get(turn, "1-0-1")})
        history.append({"role": "ai", "text": f"a{turn}"})

    state = {"head_version": 1, "pending_version": 3, "pending_since_turn": 7}
    assert (
        primer_head_from_thread(
            state,
            user_turn_count=8,
            latest_catalog_version=3,
            history=history,
        )
        == 1
    )
    assert (
        primer_head_from_thread(
            state,
            user_turn_count=4 + SUMMARY_BUNDLE_CATCHUP_MESSAGES,
            latest_catalog_version=3,
            history=history,
        )
        == 2
    )
    assert (
        primer_head_from_thread(
            state,
            user_turn_count=7 + SUMMARY_BUNDLE_CATCHUP_MESSAGES,
            latest_catalog_version=3,
            history=history,
        )
        == 3
    )


def test_edit_does_not_mature_head_while_float_still_in_window() -> None:
    """
    One message before head replacement: editing the last turn must not promote
    pending to primer while its floating bundle is still visible in the window.
    """
    history: list[dict[str, Any]] = []
    for turn in range(1, 9):
        label = "1-2-4" if turn == 4 else "1-0-1"
        history.append({"role": "user", "text": f"u{turn}", "contextLabel": label})
        history.append({"role": "ai", "text": f"a{turn}"})

    # Fork edit on turn 8 (same turn count, not a new message).
    history[-2] = {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {"text": "u8", "contextLabel": "1-0-8"},
            {"text": "u8 edited", "continuation": []},
        ],
    }

    state = {
        "head_version": 1,
        "pending_version": 2,
        "pending_since_turn": 4,
        "pending_queue": [{"version": 2, "since_turn": 4}],
    }
    from app.services.ai.context_turns import compute_window_user_turns
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm

    valid = filter_alternating_roles(linearize_for_llm(history))
    valid[-1] = ("user", "u8 edited")
    window = compute_window_user_turns(valid)

    matured = mature_head_version(
        state,
        user_turn_count=8,
        window_user_turns=window,
        history=history,
    )
    assert matured["head_version"] == 1

    head = primer_head_from_thread(
        state,
        user_turn_count=8,
        latest_catalog_version=2,
        window_user_turns=window,
        history=history,
    )
    assert head == 1


def test_new_linear_turn_matures_after_float_leaves_window() -> None:
    """Head advances on a new user-turn once catchup is satisfied and float is gone."""
    history: list[dict[str, Any]] = []
    for turn in range(1, 10):
        label = "1-2-4" if turn == 4 else "1-0-1"
        history.append({"role": "user", "text": f"u{turn}", "contextLabel": label})
        history.append({"role": "ai", "text": f"a{turn}"})

    state = {
        "head_version": 1,
        "pending_queue": [{"version": 2, "since_turn": 4}],
    }
    from app.services.ai.context_turns import compute_window_user_turns
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm

    valid = filter_alternating_roles(linearize_for_llm(history))
    window = compute_window_user_turns(valid)
    matured = mature_head_version(
        state,
        user_turn_count=9,
        window_user_turns=window,
        history=history,
    )
    assert matured["head_version"] == 2


def test_sticky_floating_bundle_on_stamped_message_only() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    history = [
        {"role": "user", "text": "u1", "contextLabel": "1-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "1-2-2"},
        {"role": "ai", "text": "a2"},
    ]
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="u3",
        scope="global",
        history=history,
        chat_meta={
            "label_context": {
                "": {
                    "head_version": 1,
                    "pending_version": 2,
                    "pending_since_turn": 2,
                }
            }
        },
        catalog=catalog,
    )
    assert messages is not None
    dialog = messages[3:]
    u2_msg = next(m for m in dialog if m["role"] == "user" and "u2" in m["content"])
    u3_msg = next(m for m in dialog if m["role"] == "user" and "u3" in m["content"])
    assert "SUMMARY_BUNDLE:" in u2_msg["content"]
    assert "Крипто" in u2_msg["content"]
    assert "SUMMARY_BUNDLE:" not in u3_msg["content"]


def test_resolve_bundle_text_by_version() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    text = resolve_bundle_text(catalog, scope="global", post_id=None, version=1)
    assert "Финансы" in text


def test_fill_llm_log_labels_for_window() -> None:
    from app.services.ai.context_labels import assemble_reply_messages_from_labels, fill_llm_log_labels

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    history = [
        {"role": "user", "text": "Привет", "contextLabel": "1-0-1"},
        {"role": "ai", "text": "Ответ"},
    ]
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="Вопрос",
        scope="global",
        history=history,
        chat_meta={"label_context": {"": {"head_version": 1, "pending_version": 0, "pending_since_turn": 0}}},
        catalog=catalog,
    )
    assert messages is not None
    labels: dict[int, str] = {}
    fill_llm_log_labels(
        labels,
        messages,
        head_version=1,
        history=history,
        thread_state={"head_version": 1, "pending_version": 0, "pending_since_turn": 0},
        latest_version=1,
        user_turn_count=2,
        valid_pairs=[("user", "Привет"), ("assistant", "Ответ"), ("user", "Вопрос")],
    )
    assert labels[1] == "user/primer [1-0-0]"
    assert labels[3] == "user [1-0-1]"
    assert labels[5] == "user [1-0-2]"


POST = {
    "id": "post-uuid-1",
    "title": "Post",
    "text": "Текст поста про инвестиции",
    "status": "draft",
}


def test_latest_scope_version_post_does_not_fall_back_to_global() -> None:
    from app.services.ai.summary_catalog import latest_global_version, latest_scope_version

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    assert latest_global_version(catalog) == 2
    assert latest_scope_version(catalog, scope="post", post_id="post-uuid-1") == 0


def test_post_scope_primer_uses_local_bundle_not_global_head() -> None:
    from app.services.ai.summary_catalog import ensure_post_local_catalog_current

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    catalog, local_v1 = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    assert local_v1 == 1

    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="Комментарий",
        scope="post",
        post_id="post-uuid-1",
        history=[],
        chat_meta={},
        catalog=catalog,
    )
    assert messages is not None
    primer = messages[1]["content"]
    assert "Текст поста про инвестиции" in primer
    assert "Финансы" in primer
    assert "Крипто" not in primer


def test_post_scope_channel_change_registers_local_and_attaches_pending() -> None:
    from app.services.ai.summary_catalog import ensure_post_local_catalog_current

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    catalog, local_v2 = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL_V2,
        telegram=None,
        post=POST,
    )
    assert local_v2 == 2

    history = [
        {"role": "user", "text": "u1", "contextLabel": "1-0-1"},
        {"role": "ai", "text": "a1"},
    ]
    meta = {
        "label_context": {
            "": {"head_version": 1, "pending_version": 0, "pending_since_turn": 0, "pending_queue": []},
        },
    }
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="u2",
        scope="post",
        post_id="post-uuid-1",
        history=history,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    assert "Финансы" in messages[1]["content"]
    assert "Крипто" not in messages[1]["content"]
    u2 = next(m for m in messages[3:] if m["role"] == "user" and "u2" in m["content"])
    assert "SUMMARY_BUNDLE:" in u2["content"]
    assert "Крипто" in u2["content"]


def test_catalog_from_profile_orm_shape() -> None:
    class _Profile:
        summary_catalog = {"global": [{"version": 1, "text": "x", "fingerprint": "fp"}]}

    catalog = catalog_from_profile(_Profile())
    assert catalog["global"][0]["version"] == 1
