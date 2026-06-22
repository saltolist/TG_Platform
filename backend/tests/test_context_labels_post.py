"""Tests for post chat compound context labels g.l-g.l-turn."""

from __future__ import annotations

from typing import Any

from app.services.ai.context_label import (
    format_post_context_label,
    parse_post_context_label,
)
from app.services.ai.context_labels_post import (
    advance_post_label_thread_after_reply,
    assemble_reply_messages_from_post_labels,
    empty_post_label_thread_state,
    plan_post_context_label_for_turn,
    planned_post_label_at_turn,
    primer_post_heads_from_state,
)
from app.services.ai.summary_catalog import (
    ensure_post_local_catalog_current,
    register_global_summary_version,
    register_local_summary_version,
    resolve_post_float_bundle_text,
)

CHANNEL = {
    "core": {"topic": "Финансы"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}
CHANNEL_V2 = {**CHANNEL, "core": {"topic": "Крипто"}}
CHANNEL_V3 = {**CHANNEL, "core": {"topic": "Новости"}}
POST = {
    "id": "post-uuid-1",
    "title": "Post",
    "text": "Текст поста",
    "status": "draft",
}
POST_V2 = {**POST, "text": "Новый текст поста"}


def test_format_and_parse_post_context_label() -> None:
    assert format_post_context_label(2, 3, 0, 0, "1") == "2.3-0.0-1"
    assert format_post_context_label(2, 3, 3, 3, "3.2(4.2)") == "2.3-3.3-3.2(4.2)"
    assert parse_post_context_label("4.2-7.4-3.2(4.2)") == (4, 2, 7, 4, "3.2(4.2)")


def test_channel_only_bump_matures_global_head_to_3_3() -> None:
    """Head 2.3 + channel fix → after maturation primer head becomes 3.3."""
    from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES

    state = {
        "head_global": 2,
        "head_local": 3,
        "pending_global_queue": [{"version": 3, "since_turn": 1}],
        "pending_local_queue": [],
    }
    matured = primer_post_heads_from_state(
        state,
        user_turn_count=1 + SUMMARY_BUNDLE_CATCHUP_MESSAGES,
        latest_global=3,
        latest_local=3,
        window_user_turns={1},
        history=None,
    )
    assert matured == (3, 3)


def test_post_scope_primer_uses_compound_label() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    log_labels: dict[str, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="Комментарий",
        history=[],
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [1.1-0.0-0]"
    assert "Текст поста" in messages[1]["content"]


def test_rebuild_primer_uses_latest_catalog_heads() -> None:
    """After rebuild with no stamped history, primer head reflects current catalog (12.3)."""
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 13):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Сводка {idx}"}},
            telegram=None,
        )
    catalog, _ = ensure_post_local_catalog_current(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST_V2
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post={**POST_V2, "text": "Версия 3"}
    )
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="12.3-0.0-1",
        history=[],
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [12.3-0.0-0]"
    assert log_labels[3] == "user [12.3-0.0-1]"
    assert "Версия 3" in messages[1]["content"]
    u1 = messages[3]
    assert "SUMMARY_BUNDLE:" not in u1["content"]


def test_post_channel_change_attaches_compound_float() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL_V2,
        telegram=None,
        post=POST,
    )
    history = [
        {"role": "user", "text": "u1", "contextLabel": "1.1-0.0-1"},
        {"role": "ai", "text": "a1"},
    ]
    meta = {
        "label_context": {
            "": {
                "head_global": 1,
                "head_local": 1,
                "pending_global_queue": [],
                "pending_local_queue": [],
            },
        },
    }
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="u2",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    assert messages is not None
    assert "Финансы" in messages[1]["content"]
    assert log_labels[3] == "user [1.1-0.0-1]"
    assert log_labels[5] == "user [1.1-2.0-2]"
    u2 = next(m for m in messages[3:] if "u2" in m["content"])
    assert "SUMMARY_BUNDLE:" in u2["content"]
    assert "Крипто" in u2["content"]


def test_plan_local_only_attach_sets_ga_zero() -> None:
    state = {
        "head_global": 11,
        "head_local": 2,
        "pending_global_queue": [],
        "pending_local_queue": [],
    }
    gh, lh, ga, la, _ = plan_post_context_label_for_turn(
        state,
        user_turn_count=3,
        turn_label="3",
        latest_global=11,
        latest_local=3,
    )
    assert (gh, lh) == (11, 2)
    assert (ga, la) == (0, 3)


def test_advance_stamps_local_float_when_state_head_ahead_of_stamps() -> None:
    """Stale head_local=3 in state must not drop stamp 0.3 on the float turn."""
    state = {
        "head_global": 11,
        "head_local": 3,
        "pending_global_queue": [],
        "pending_local_queue": [],
    }
    history = [
        {"role": "user", "text": "u1", "contextLabel": "11.2-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "11.2-0.0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3"},
    ]
    gh, lh, ga, la, _ = advance_post_label_thread_after_reply(
        state,
        user_turn_count=3,
        turn_label="3",
        latest_global=11,
        latest_local=3,
        window_user_turns={1, 2, 3},
        history=history,
    )
    assert (gh, lh, ga, la) == (11, 2, 0, 3)


def test_turn4_keeps_turn3_stamped_local_float_in_assembly() -> None:
    """After turn 3 stamped 11.2-0.3-3, turn 4 must not re-float v3 on turn 3."""
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 12):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Сводка {idx}"}},
            telegram=None,
        )
    catalog, _ = ensure_post_local_catalog_current(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST_V2
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post={**POST_V2, "text": "Версия 3"}
    )
    history = [
        {"role": "user", "text": "u1", "contextLabel": "11.2-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "11.2-0.0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextLabel": "11.2-0.3-3"},
        {"role": "ai", "text": "a3"},
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="u4",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[5] == "user [11.2-0.3-3]"
    u3 = next(m for m in messages[3:] if m["role"] == "user" and "u3" in m["content"])
    assert "SUMMARY_BUNDLE:" in u3["content"]
    assert "Версия 3" in u3["content"]
    u4 = next(m for m in messages[3:] if m["role"] == "user" and "u4" in m["content"])
    assert "SUMMARY_BUNDLE:" not in u4["content"]


def test_simultaneous_channel_and_post_bump_attaches_12_3() -> None:
    """Channel v12 + post v3 on same turn → 11.1-12.3-4.4 (not 11.3-12.0)."""
    state = {
        "head_global": 11,
        "head_local": 1,
        "pending_global_queue": [],
        "pending_local_queue": [],
    }
    gh, lh, ga, la, _ = plan_post_context_label_for_turn(
        state,
        user_turn_count=4,
        turn_label="4.4",
        latest_global=12,
        latest_local=3,
    )
    assert (gh, lh) == (11, 1)
    assert (ga, la) == (12, 3)
    assert (
        planned_post_label_at_turn(
            state,
            user_turn_count=4,
            turn_label="4.4",
            latest_global=12,
            latest_local=3,
            window_user_turns={1, 2, 3, 4},
            history=[
                {"role": "user", "text": "u1", "contextLabel": "11.1-0.0-1"},
                {"role": "ai", "text": "a1"},
                {"role": "user", "text": "u2", "contextLabel": "11.1-0.0-2"},
                {"role": "ai", "text": "a2"},
                {"role": "user", "text": "u3", "contextLabel": "11.1-0.0-3"},
                {"role": "ai", "text": "a3"},
            ],
        )
        == "11.1-12.3-4.4"
    )

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 13):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Сводка {idx}"}},
            telegram=None,
        )
    catalog, _ = ensure_post_local_catalog_current(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST_V2
    )
    catalog, _ = register_local_summary_version(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post={**POST_V2, "text": "Версия 3"}
    )
    history = [
        {"role": "user", "text": "u1", "contextLabel": "11.1-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "11.1-0.0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextLabel": "11.1-0.0-3"},
        {"role": "ai", "text": "a3"},
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="11.1-12.3-4.4",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    u4 = messages[-1]
    assert "SUMMARY_BUNDLE:" in u4["content"]
    assert "Сводка 12" in u4["content"]
    assert "Версия 3" in u4["content"]
    assert log_labels[7] == "user [11.1-12.3-4]"


def test_local_head_matures_after_post_float_like_global_chat() -> None:
    """``13.6-0.7-3`` → after float leaves window local head becomes 7 (``13.7-0.0-*``)."""
    from app.services.ai.context_turns import compute_window_user_turns
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm

    catalog, _ = register_global_summary_version(
        None, channel={**CHANNEL, "core": {"topic": "Сводка 13"}}, telegram=None
    )
    catalog, _ = ensure_post_local_catalog_current(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST
    )
    for idx in range(2, 8):
        catalog, _ = register_local_summary_version(
            catalog,
            post_id="post-uuid-1",
            channel=CHANNEL,
            telegram=None,
            post={**POST, "text": f"Версия {idx}"},
        )

    history: list[dict[str, Any]] = []
    for turn in range(1, 10):
        label = "13.6-0.7-3" if turn == 3 else "13.6-0.0-1"
        history.append({"role": "user", "text": f"u{turn}", "contextLabel": label})
        history.append({"role": "ai", "text": f"a{turn}"})

    valid = filter_alternating_roles(linearize_for_llm(history))
    window = compute_window_user_turns(valid)
    label = planned_post_label_at_turn(
        empty_post_label_thread_state(head_local=1),
        user_turn_count=9,
        turn_label="9",
        latest_global=13,
        latest_local=7,
        window_user_turns=window,
        history=history,
    )
    assert label == "13.7-0.0-9"


def test_simultaneous_bump_after_channel_only_float_uses_independent_local_snapshot() -> None:
    """Turn 6 channel-only float must not block turn 7 post attach (``13.8-15.9-7``)."""
    from app.services.ai.context_turns import compute_window_user_turns
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm

    history = [
        {"role": "user", "text": "u5", "contextLabel": "13.7-0.0-5"},
        {"role": "ai", "text": "a5"},
        {"role": "user", "text": "u6", "contextLabel": "13.8-14.0-6"},
        {"role": "ai", "text": "a6"},
    ]
    state = {
        "head_global": 13,
        "head_local": 8,
        "pending_global_queue": [{"version": 14, "since_turn": 6}],
        "pending_local_queue": [],
        "catalog_snapshot_at_fork": 14,
    }
    valid = filter_alternating_roles(linearize_for_llm(history))
    window = compute_window_user_turns(valid)
    label = planned_post_label_at_turn(
        state,
        user_turn_count=7,
        turn_label="7",
        latest_global=15,
        latest_local=9,
        window_user_turns=window,
        history=history,
    )
    assert label == "13.8-15.9-7"


def test_plan_post_channel_only_pending_attached_pair() -> None:
    state = {"head_global": 2, "head_local": 3, "pending_global_queue": [], "pending_local_queue": []}
    gh, lh, ga, la, _ = plan_post_context_label_for_turn(
        state,
        user_turn_count=4,
        turn_label="4",
        latest_global=3,
        latest_local=3,
    )
    assert (gh, lh) == (2, 3)
    assert (ga, la) == (3, 0)


def test_channel_only_bump_after_post_float_attaches_global_not_local() -> None:
    """Channel v13 with post still at v4 head → ``12.4-13.0-4``, not ``12.4-13.6-4``."""
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 13):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Сводка {idx}"}},
            telegram=None,
        )
    catalog, _ = ensure_post_local_catalog_current(
        catalog, post_id="post-uuid-1", channel=CHANNEL, telegram=None, post=POST
    )
    for idx in range(2, 5):
        catalog, _ = register_local_summary_version(
            catalog,
            post_id="post-uuid-1",
            channel=CHANNEL,
            telegram=None,
            post={**POST, "text": f"Версия {idx}"},
        )
    catalog, bumped_local = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel={**CHANNEL, "core": {"topic": "Сводка 13"}},
        telegram=None,
        post={**POST, "text": "Версия 4"},
    )
    assert bumped_local is None

    history = [
        {"role": "user", "text": "u1", "contextLabel": "12.4-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "12.4-0.0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextLabel": "12.4-0.5-3"},
        {"role": "ai", "text": "a3"},
    ]
    catalog, _ = register_global_summary_version(
        catalog,
        channel={**CHANNEL, "core": {"topic": "Сводка 13"}},
        telegram=None,
    )
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="12.4-13.0-4",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[7] == "user [12.4-13.0-4]"
    u4 = messages[-1]
    assert "Сводка 13" in u4["content"]
    assert "## Пост" not in u4["content"].split("SUMMARY_BUNDLE:", 1)[-1][:20]


def test_post_only_float_0_2_attaches_local_post_not_channel() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    catalog, _ = register_global_summary_version(catalog, channel=CHANNEL_V2, telegram=None)
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    catalog, _ = register_local_summary_version(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST_V2,
    )
    float_text = resolve_post_float_bundle_text(
        catalog,
        post_id="post-uuid-1",
        attached_global=0,
        attached_local=2,
    )
    assert "Новый текст поста" in float_text
    assert "Финансы" not in float_text
    assert "Крипто" not in float_text
    assert "## Канал" not in float_text

    history = [
        {"role": "user", "text": "u1", "contextLabel": "2.1-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "2.1-0.0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextLabel": "2.1-0.2-3"},
        {"role": "ai", "text": "a3"},
    ]
    messages = assemble_reply_messages_from_post_labels(
        ai_profile={},
        user_text="u4",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
    )
    assert messages is not None
    u3 = next(m for m in messages[3:] if m["role"] == "user" and "u3" in m["content"])
    assert "SUMMARY_BUNDLE:" in u3["content"]
    assert "Новый текст поста" in u3["content"]
    float_block = u3["content"].split("SUMMARY_BUNDLE:", 1)[-1]
    assert "Тема:" not in float_block
    assert "Крипто" not in float_block
