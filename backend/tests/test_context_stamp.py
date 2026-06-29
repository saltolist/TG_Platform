"""Tests for v2 context stamp mechanics (msg-ver-branch + contextStamp JSON)."""

from __future__ import annotations

from typing import Any

from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.context_stamp_address import (
    resolve_address_for_path,
    resolve_current_address,
)
from app.services.ai.context_stamp_assembly import assemble_reply_messages_from_stamps
from app.services.ai.context_stamp_label import (
    build_context_stamp,
    format_stamp_label,
    parse_stamp_label,
    read_context_stamp,
    stamp_context_stamp_on_path,
)
from app.services.ai.context_stamp_maturation import mature_branch_heads
from app.services.ai.context_stamp_planner import (
    advance_branch_after_reply,
    initialize_heads_if_empty,
    plan_attach_for_msg,
    queue_catalog_bumps,
)
from app.services.ai.context_stamp_types import empty_branch_state
from app.services.ai.summary_catalog import (
    ensure_post_local_catalog_current,
    latest_global_version,
    latest_local_version,
    register_global_summary_version,
    register_local_summary_version,
)

CHANNEL = {
    "core": {"topic": "Финансы"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}
POST = {
    "id": "post-uuid-1",
    "title": "Post",
    "text": "Текст поста v1",
    "status": "draft",
}
POST_V2 = {**POST, "text": "Текст поста v2"}
POST_V3 = {**POST, "text": "Текст поста v3"}


def _catalog_channel_v5_post_v2() -> dict[str, Any]:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 6):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Канал v{idx}"}},
            telegram=None,
        )
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
    return catalog


def _stamp(
    *,
    msg: int,
    msg_version: int = 1,
    branch: int = 1,
    head_ch: int,
    head_post: int,
    attach_ch: int = 0,
    attach_post: int = 0,
    catalog_ch: int = 5,
    catalog_post: int = 2,
) -> dict[str, Any]:
    address = {"msg": msg, "msgVersion": msg_version, "branch": branch}
    return build_context_stamp(
        scope="post",
        address=address,
        head={"channel": head_ch, "post": head_post},
        attach={"channel": attach_ch, "post": attach_post},
        catalog_channel=catalog_ch,
        catalog_post=catalog_post,
    )


def test_format_and_parse_stamp_label() -> None:
    stamp = build_context_stamp(
        scope="post",
        address={"msg": 3, "msgVersion": 1, "branch": 1},
        head={"channel": 5, "post": 2},
        attach={"channel": 0, "post": 3},
        catalog_channel=5,
        catalog_post=3,
    )
    assert format_stamp_label(stamp) == "5.2-0.3-1.3"
    assert parse_stamp_label("5.2-0.3-1.3") == {
        "msg": 3,
        "msgVersion": 1,
        "branch": 1,
    }
    assert parse_stamp_label("3-1-1") == {"msg": 3, "msgVersion": 1, "branch": 1}
    assert parse_stamp_label("1.1-0.0-1") == {"msg": 1, "msgVersion": 1, "branch": 1}


def test_build_context_stamp_global_zeros_post() -> None:
    stamp = build_context_stamp(
        scope="global",
        address={"msg": 1, "msgVersion": 1, "branch": 1},
        head={"channel": 5, "post": 2},
        attach={"channel": 0, "post": 3},
        catalog_channel=5,
        catalog_post=0,
    )
    assert stamp["summary"]["head"]["post"] == 0
    assert stamp["summary"]["attach"]["post"] == 0
    assert stamp["scope"] == "global"
    assert format_stamp_label(stamp) == "5-0-1.1"


def test_format_global_stamp_label_with_attach() -> None:
    stamp = build_context_stamp(
        scope="global",
        address={"msg": 5, "msgVersion": 1, "branch": 2},
        head={"channel": 6, "post": 0},
        attach={"channel": 7, "post": 0},
        catalog_channel=7,
        catalog_post=0,
    )
    assert format_stamp_label(stamp) == "6-7-2.5"
    assert parse_stamp_label("6-7-2.5") == {"msg": 5, "msgVersion": 1, "branch": 2}
    assert parse_stamp_label("6-0-0-1.1") == {"msg": 1, "msgVersion": 1, "branch": 1}


def test_initialize_heads_first_message() -> None:
    state = empty_branch_state(post_head=2)
    initialized = initialize_heads_if_empty(
        state,
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    assert initialized["head"] == {"channel": 5, "post": 2}


def test_advance_first_reply_row3() -> None:
    state = initialize_heads_if_empty(
        empty_branch_state(post_head=2),
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    head, attach, _ = advance_branch_after_reply(
        state,
        current_msg=1,
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    assert head == {"channel": 5, "post": 2}
    assert attach == {"channel": 0, "post": 0}


def test_attach_post_on_catalog_bump_row6() -> None:
    state = initialize_heads_if_empty(
        empty_branch_state(post_head=2),
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    _, _, state = advance_branch_after_reply(
        state, current_msg=1, latest_channel=5, latest_post=2, scope="post"
    )
    _, _, state = advance_branch_after_reply(
        state, current_msg=2, latest_channel=5, latest_post=2, scope="post"
    )
    state = queue_catalog_bumps(
        state,
        current_msg=3,
        latest_channel=5,
        latest_post=3,
        scope="post",
    )
    attach, _ = plan_attach_for_msg(state, current_msg=3, scope="post")
    assert attach == {"channel": 0, "post": 3}


def test_channel_catalog_bump_not_blocked_by_post_attach_same_version() -> None:
    """Post attach v14 on msg5 must not block channel attach v14 on msg7."""
    history: list[dict[str, Any]] = [
        {
            "role": "user",
            "text": "11.10-0.0-1.1",
            "contextStamp": _stamp(msg=1, head_ch=11, head_post=10, catalog_ch=11, catalog_post=10),
        },
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "text": "11.10-0.0-1.2",
            "contextStamp": _stamp(msg=2, head_ch=11, head_post=10, catalog_ch=11, catalog_post=10),
        },
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "text": "11.10-12.0-2.4",
            "contextStamp": _stamp(
                msg=4,
                branch=2,
                head_ch=11,
                head_post=10,
                attach_ch=12,
                catalog_ch=12,
                catalog_post=10,
            ),
        },
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "text": "11.10-13.14-3.5",
            "contextStamp": _stamp(
                msg=5,
                branch=3,
                head_ch=11,
                head_post=10,
                attach_ch=13,
                attach_post=14,
                catalog_ch=13,
                catalog_post=14,
            ),
        },
        {"role": "ai", "text": "a5"},
        {
            "role": "user",
            "text": "11.11-0.15-3.6",
            "contextStamp": _stamp(
                msg=6,
                branch=3,
                head_ch=11,
                head_post=11,
                attach_post=15,
                catalog_ch=13,
                catalog_post=15,
            ),
        },
        {"role": "ai", "text": "a6"},
    ]
    derived = empty_branch_state(post_head=15)
    derived["head"] = {"channel": 11, "post": 11}
    _, attach, _ = advance_branch_after_reply(
        derived,
        current_msg=7,
        latest_channel=14,
        latest_post=18,
        scope="post",
        history=history,
        window_user_turns={3, 4, 5, 6, 7},
    )
    assert attach == {"channel": 14, "post": 18}


def _branch3_history_through_msg6() -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "text": "11.10-0.0-1.1",
            "contextStamp": _stamp(msg=1, head_ch=11, head_post=10, catalog_ch=11, catalog_post=10),
        },
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "text": "11.10-0.0-1.2",
            "contextStamp": _stamp(msg=2, head_ch=11, head_post=10, catalog_ch=11, catalog_post=10),
        },
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "activeUserBranch": 0,
            "userBranches": [
                {
                    "text": "11.10-0.11-1.3",
                    "contextStamp": _stamp(
                        msg=3,
                        head_ch=11,
                        head_post=10,
                        attach_post=11,
                        catalog_ch=11,
                        catalog_post=11,
                    ),
                    "continuation": [
                        {"role": "ai", "text": "a3"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "11.10-0.12-1.4",
                                    "contextStamp": _stamp(
                                        msg=4,
                                        head_ch=11,
                                        head_post=10,
                                        catalog_ch=11,
                                        catalog_post=10,
                                    ),
                                    "continuation": [{"role": "ai", "text": "a4"}],
                                },
                                {
                                    "text": "11.10-12.0-2.4",
                                    "contextStamp": _stamp(
                                        msg=4,
                                        msg_version=2,
                                        branch=2,
                                        head_ch=11,
                                        head_post=10,
                                        attach_ch=12,
                                        catalog_ch=12,
                                        catalog_post=10,
                                    ),
                                    "continuation": [
                                        {"role": "ai", "text": "a4'"},
                                        {
                                            "role": "user",
                                            "activeUserBranch": 1,
                                            "userBranches": [
                                                {
                                                    "text": "11.10-13.13-2.5",
                                                    "contextStamp": _stamp(
                                                        msg=5,
                                                        branch=2,
                                                        head_ch=11,
                                                        head_post=10,
                                                        attach_ch=13,
                                                        catalog_ch=13,
                                                        catalog_post=13,
                                                    ),
                                                    "continuation": [{"role": "ai", "text": "a5"}],
                                                },
                                                {
                                                    "text": "11.10-13.14-3.5",
                                                    "contextStamp": _stamp(
                                                        msg=5,
                                                        msg_version=2,
                                                        branch=3,
                                                        head_ch=11,
                                                        head_post=10,
                                                        attach_ch=13,
                                                        attach_post=14,
                                                        catalog_ch=13,
                                                        catalog_post=14,
                                                    ),
                                                    "continuation": [
                                                        {"role": "ai", "text": "a5'"},
                                                        {
                                                            "role": "user",
                                                            "text": "11.11-0.15-3.6",
                                                            "contextStamp": _stamp(
                                                                msg=6,
                                                                branch=3,
                                                                head_ch=11,
                                                                head_post=11,
                                                                attach_post=15,
                                                                catalog_ch=13,
                                                                catalog_post=15,
                                                            ),
                                                        },
                                                        {"role": "ai", "text": "a6"},
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "text": "11.10-13.15-4.3",
                    "contextStamp": _stamp(
                        msg=3,
                        msg_version=2,
                        branch=4,
                        head_ch=11,
                        head_post=10,
                        attach_ch=13,
                        attach_post=15,
                        catalog_ch=13,
                        catalog_post=15,
                    ),
                    "continuation": [{"role": "ai", "text": "a3'"}],
                },
            ],
        },
    ]


def test_linear_msg7_keeps_branch_when_registry_lost() -> None:
    """Linear msg7 must stay on branch 3; missing registry must not allocate branch 7."""
    history = _branch3_history_through_msg6()
    continuation = (
        history[4]["userBranches"][0]["continuation"][1]["userBranches"][1]["continuation"][1][
            "userBranches"
        ][1]["continuation"]
    )
    continuation.append(
        {
            "role": "user",
            "text": "11.12-14.18-3.7",
        }
    )
    stamp_context: dict[str, Any] = {
        "branches": {"3": empty_branch_state(post_head=15)},
        "next_branch_id": 7,
        "branch_registry": {},
    }
    address, path = resolve_current_address(history, stamp_context=stamp_context)  # type: ignore[arg-type]
    assert path == [4, 1, 1, 3]
    assert address == {"msg": 7, "msgVersion": 1, "branch": 3}
    assert stamp_context["branch_registry"]["4.1.1@1"] == 3
    assert stamp_context["next_branch_id"] == 7


def test_corrupt_registry_entry_reconciled_from_stamp() -> None:
    history = _branch3_history_through_msg6()
    continuation = (
        history[4]["userBranches"][0]["continuation"][1]["userBranches"][1]["continuation"][1][
            "userBranches"
        ][1]["continuation"]
    )
    continuation.append({"role": "user", "text": "11.12-14.18-3.7"})
    stamp_context: dict[str, Any] = {
        "branches": {"3": empty_branch_state(post_head=15), "7": empty_branch_state(post_head=15)},
        "next_branch_id": 8,
        "branch_registry": {"4@0": 1, "4.1@1": 2, "4.1.1@1": 7},
    }
    address, _ = resolve_current_address(history, stamp_context=stamp_context)  # type: ignore[arg-type]
    assert address == {"msg": 7, "msgVersion": 1, "branch": 3}
    assert stamp_context["branch_registry"]["4.1.1@1"] == 3


def test_edit_fork_allocates_branch_only_when_unstamped() -> None:
    history: list[dict[str, Any]] = [
        {
            "role": "user",
            "text": "7.3-0.0-1.1",
            "contextStamp": _stamp(msg=1, head_ch=7, head_post=3, catalog_ch=7, catalog_post=3),
        },
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "7.3-0.0-1.2", "continuation": [{"role": "ai", "text": "a2"}]},
                {"text": "7.3-8.0-2.2"},
            ],
        },
    ]
    stamp_context: dict[str, Any] = {
        "branches": {"1": empty_branch_state(post_head=3)},
        "next_branch_id": 2,
        "branch_registry": {"0@0": 1},
    }
    address, _ = resolve_current_address(history, stamp_context=stamp_context)  # type: ignore[arg-type]
    assert address == {"msg": 2, "msgVersion": 2, "branch": 2}
    assert stamp_context["branch_registry"]["2@1"] == 2
    assert stamp_context["next_branch_id"] == 3


def test_mature_head_after_n_messages() -> None:
    state = initialize_heads_if_empty(
        empty_branch_state(post_head=2),
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    state = queue_catalog_bumps(
        state,
        current_msg=1,
        latest_channel=6,
        latest_post=2,
        scope="post",
    )
    matured = mature_branch_heads(
        state,
        current_msg=1 + SUMMARY_BUNDLE_CATCHUP_MESSAGES,
        scope="post",
    )
    assert matured["head"]["channel"] == 6


def test_stamp_context_stamp_on_path() -> None:
    history = [{"role": "user", "text": "u1"}]
    stamp = _stamp(msg=1, head_ch=5, head_post=2)
    applied = stamp_context_stamp_on_path(history, [0], stamp)
    assert applied is not None
    assert applied[0]["contextLabel"] == "5.2-0.0-1.1"
    assert read_context_stamp(applied[0]) is not None


def test_stamp_context_stamp_never_overwrites_existing() -> None:
    original = _stamp(msg=4, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5)
    history = [
        {"role": "user", "text": "7.3-0.0-1.4", "contextStamp": original, "contextLabel": "7.3-0.0-1.4"},
        {"role": "ai", "text": "a4"},
    ]
    wrong = _stamp(msg=4, head_ch=8, head_post=5, catalog_ch=8, catalog_post=5)
    applied = stamp_context_stamp_on_path(history, [0], wrong)
    assert applied is not None
    assert format_stamp_label(read_context_stamp(applied[0])) == "7.3-0.0-1.4"
    assert applied[0]["contextLabel"] == "7.3-0.0-1.4"


def test_stamp_context_stamp_never_overwrites_branch_zero_on_edit() -> None:
    branch0 = _stamp(msg=5, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5)
    history = [
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "7.3-0.0-1.5", "contextStamp": branch0, "contextLabel": "7.3-0.0-1.5"},
                {"text": "7.3-8.0-2.5"},
            ],
        }
    ]
    branch1_stamp = _stamp(
        msg=5,
        msg_version=2,
        branch=2,
        head_ch=7,
        head_post=3,
        attach_ch=8,
        catalog_ch=8,
        catalog_post=5,
    )
    applied = stamp_context_stamp_on_path(history, [0], branch1_stamp)
    assert applied is not None
    assert format_stamp_label(read_context_stamp(applied[0], branch_index=0)) == "7.3-0.0-1.5"
    assert format_stamp_label(read_context_stamp(applied[0], branch_index=1)) == "7.3-8.0-2.5"


def test_assemble_primer_row3() -> None:
    catalog = _catalog_channel_v5_post_v2()
    log_labels: dict[int, str] = {}
    log_stamps: dict[int, dict[str, Any]] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u1",
        history=[],
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
        log_stamps=log_stamps,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [5.2-0.0-0]"
    assert "Канал v5" in messages[1]["content"]
    assert "Текст поста v2" in messages[1]["content"]
    assert messages[-1]["content"].strip().endswith("u1")
    assert log_stamps[len(messages) - 1]["address"]["msg"] == 1


def test_assemble_float_from_stamp_row6() -> None:
    catalog = _catalog_channel_v5_post_v2()
    catalog, _ = register_local_summary_version(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST_V3,
    )
    history = [
        {
            "role": "user",
            "text": "u1",
            "contextLabel": "1-1-1",
            "contextStamp": _stamp(msg=1, head_ch=5, head_post=2, catalog_post=2),
        },
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "text": "u2",
            "contextLabel": "2-1-1",
            "contextStamp": _stamp(msg=2, head_ch=5, head_post=2, catalog_post=2),
        },
        {"role": "ai", "text": "a2"},
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u3",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    last_user = messages[-1]["content"]
    assert "Обновлённый пост:" in last_user
    assert "Текст поста v3" in last_user
    assert "u3" in last_user
    assert log_labels[len(messages) - 1] == "user/float [5.2-0.3-1.3]"


def test_turn4_does_not_reattach_post_after_turn3_float() -> None:
    state = initialize_heads_if_empty(
        empty_branch_state(post_head=2),
        latest_channel=5,
        latest_post=2,
        scope="post",
    )
    history = [
        {"role": "user", "text": "u1", "contextStamp": _stamp(msg=1, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextStamp": _stamp(msg=2, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "text": "u3",
            "contextStamp": _stamp(
                msg=3,
                head_ch=5,
                head_post=2,
                attach_post=3,
                catalog_post=3,
            ),
        },
        {"role": "ai", "text": "a3"},
    ]
    _, attach, _ = advance_branch_after_reply(
        state,
        current_msg=4,
        latest_channel=5,
        latest_post=3,
        scope="post",
        history=history,
    )
    assert attach == {"channel": 0, "post": 0}


def test_assemble_turn4_keeps_turn3_float_not_turn4() -> None:
    catalog = _catalog_channel_v5_post_v2()
    catalog, _ = register_local_summary_version(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST_V3,
    )
    history = [
        {
            "role": "user",
            "text": "u1",
            "contextStamp": _stamp(msg=1, head_ch=5, head_post=2, catalog_post=2),
        },
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "text": "u2",
            "contextStamp": _stamp(msg=2, head_ch=5, head_post=2, catalog_post=2),
        },
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "text": "u3",
            "contextLabel": "3-1-1",
            "contextStamp": _stamp(
                msg=3,
                head_ch=5,
                head_post=2,
                attach_post=3,
                catalog_ch=5,
                catalog_post=3,
            ),
        },
        {"role": "ai", "text": "a3"},
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u4",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    u3 = next(m for m in messages[3:] if m["role"] == "user" and "u3" in m["content"])
    u4 = next(m for m in messages[3:] if m["role"] == "user" and "u4" in m["content"])
    assert "Обновлённый пост:" in u3["content"]
    assert "Текст поста v3" in u3["content"]
    assert "Обновлённый пост:" not in u4["content"]
    assert log_labels[5] == "user/float [5.2-0.3-1.3]"
    assert log_labels[len(messages) - 1] == "user [5.2-0.0-1.4]"


def test_read_context_stamp_branch_does_not_inherit_parent() -> None:
    parent_stamp = _stamp(msg=5, head_ch=6, head_post=2)
    message = {
        "role": "user",
        "activeUserBranch": 1,
        "contextStamp": parent_stamp,
        "userBranches": [
            {"text": "branch 0", "contextStamp": parent_stamp},
            {"text": "branch 1 edited"},
        ],
    }
    assert read_context_stamp(message, branch_index=0) is not None
    assert read_context_stamp(message, branch_index=1) is None


def test_stamp_context_stamp_on_branch() -> None:
    history = [
        {
            "role": "user",
            "activeUserBranch": 1,
            "contextStamp": _stamp(msg=5, head_ch=6, head_post=2),
            "userBranches": [
                {"text": "original", "contextStamp": _stamp(msg=5, head_ch=6, head_post=2)},
                {"text": "edited"},
            ],
        }
    ]
    new_stamp = _stamp(
        msg=5,
        msg_version=2,
        branch=2,
        head_ch=6,
        head_post=2,
        attach_ch=6,
        catalog_ch=7,
    )
    applied = stamp_context_stamp_on_path(history, [0], new_stamp)
    assert applied is not None
    assert read_context_stamp(applied[0], branch_index=1) is not None
    assert format_stamp_label(read_context_stamp(applied[0], branch_index=1)) == "6.2-6.0-2.5"
    assert read_context_stamp(applied[0], branch_index=0) is not None
    assert format_stamp_label(read_context_stamp(applied[0], branch_index=0)) == "6.2-0.0-1.5"


def test_assemble_edit_fork_row10() -> None:
    catalog = _catalog_channel_v5_post_v2()
    catalog, _ = register_global_summary_version(
        catalog,
        channel={**CHANNEL, "core": {"topic": "Канал v6"}},
        telegram=None,
    )
    history = [
        {"role": "user", "text": "u1", "contextStamp": _stamp(msg=1, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextStamp": _stamp(msg=2, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3", "contextStamp": _stamp(msg=3, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "u4", "contextStamp": _stamp(msg=4, head_ch=5, head_post=2)},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "contextStamp": _stamp(msg=5, head_ch=5, head_post=2, catalog_ch=6),
            "userBranches": [
                {
                    "text": "u5 v1",
                    "contextStamp": _stamp(msg=5, head_ch=5, head_post=2, catalog_ch=6),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {"text": "u5 v2 edited"},
            ],
        },
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u5 v2 edited",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    last_user = messages[-1]["content"]
    assert "u5 v2 edited" in last_user
    assert log_labels[len(messages) - 1] == "user/float [5.2-6.0-2.5]"
    assert "Обновлённый профиль канала:" in last_user or "Канал v6" in last_user


def test_assemble_ignores_legacy_compound_labels() -> None:
    catalog = _catalog_channel_v5_post_v2()
    catalog, _ = register_local_summary_version(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST_V3,
    )
    history = [
        {"role": "user", "text": "u1", "contextLabel": "5.2-0.0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2", "contextLabel": "5.2-0.0-2"},
        {"role": "ai", "text": "a2"},
    ]
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u3",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
    )
    assert messages is not None
    last_user = messages[-1]["content"]
    assert "Обновлённый пост:" not in last_user
    assert last_user.strip().endswith("u3")


def test_assemble_global_post_zero() -> None:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 6):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Канал v{idx}"}},
            telegram=None,
        )
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="u1",
        history=[],
        chat_meta={},
        catalog=catalog,
        scope="global",
    )
    assert messages is not None
    assert "Пост:" not in messages[1]["content"]


def _catalog_ch7_post3_to_ch8_post5() -> dict[str, Any]:
    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    for idx in range(2, 8):
        catalog, _ = register_global_summary_version(
            catalog,
            channel={**CHANNEL, "core": {"topic": f"Канал v{idx}"}},
            telegram=None,
        )
    catalog, _ = ensure_post_local_catalog_current(
        catalog,
        post_id="post-uuid-1",
        channel=CHANNEL,
        telegram=None,
        post=POST,
    )
    for post in (POST_V2, POST_V3, {**POST, "text": "Текст поста v4"}, {**POST, "text": "Текст поста v5"}):
        catalog, _ = register_local_summary_version(
            catalog,
            post_id="post-uuid-1",
            channel=CHANNEL,
            telegram=None,
            post=post,
        )
    catalog, _ = register_global_summary_version(
        catalog,
        channel={**CHANNEL, "core": {"topic": "Канал v8"}},
        telegram=None,
    )
    return catalog


def test_golden_scenario_ch7_edit_fork() -> None:
    """User scenario: 7.3-0.0-1.x → edit 7.3-8.0-2.5 → 7.5-0.0-2.6."""
    catalog = _catalog_ch7_post3_to_ch8_post5()
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "7.3-0.0-1.1", "contextStamp": _stamp(msg=1, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "7.3-0.0-1.2", "contextStamp": _stamp(msg=2, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5)},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "text": "7.3-0.5-1.3",
            "contextStamp": _stamp(
                msg=3,
                head_ch=7,
                head_post=3,
                attach_post=5,
                catalog_ch=7,
                catalog_post=5,
            ),
        },
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "7.3-0.0-1.4", "contextStamp": _stamp(msg=4, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5)},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "7.3-0.0-1.5",
                    "contextStamp": _stamp(msg=5, head_ch=7, head_post=3, catalog_ch=7, catalog_post=5),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {"text": "7.3-8.0-2.5"},
            ],
        },
    ]

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="7.3-8.0-2.5",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [7.3-0.0-0]"
    assert log_labels[len(messages) - 1] == "user/float [7.3-8.0-2.5]"
    assert "Канал v8" in messages[-1]["content"]

    branch_state = initialize_heads_if_empty(
        empty_branch_state(post_head=3),
        latest_channel=8,
        latest_post=5,
        scope="post",
    )
    head, attach, _ = advance_branch_after_reply(
        branch_state,
        current_msg=5,
        latest_channel=8,
        latest_post=5,
        scope="post",
        is_edit_fork=True,
        history=history,
        window_user_turns={1, 2, 3, 4, 5},
    )
    assert head == {"channel": 7, "post": 3}
    assert attach == {"channel": 8, "post": 0}
    assert format_stamp_label(
        _stamp(
            msg=5,
            msg_version=2,
            branch=2,
            head_ch=head["channel"],
            head_post=head["post"],
            attach_ch=attach["channel"],
            catalog_ch=8,
            catalog_post=5,
        )
    ) == "7.3-8.0-2.5"

    stamped = stamp_context_stamp_on_path(
        history,
        [len(history) - 1],
        _stamp(
            msg=5,
            msg_version=2,
            branch=2,
            head_ch=7,
            head_post=3,
            attach_ch=8,
            catalog_ch=8,
            catalog_post=5,
        ),
    )
    assert stamped is not None
    branch_history = stamped
    branch_history[-1]["userBranches"][1]["continuation"] = [{"role": "ai", "text": "a5p"}]

    log_labels = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="7.5-0.0-2.6",
        history=branch_history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [7.3-0.0-0]"
    assert "8.5" not in log_labels[1]
    assert log_labels[len(messages) - 1] == "user [7.3-0.0-2.6]"


def test_nested_edit_msg6_primer_keeps_fork_head_87() -> None:
    """Edit msg 6 on branch 2 must lock primer to branch-0 head 8.7, not 8.5."""
    catalog = _catalog_ch7_post3_to_ch8_post5()
    msg6_stamp = _stamp(
        msg=6,
        msg_version=1,
        branch=2,
        head_ch=8,
        head_post=7,
        catalog_ch=9,
        catalog_post=7,
    )
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "8.5-0.0-1.1", "contextStamp": _stamp(msg=1, head_ch=8, head_post=5, catalog_ch=8, catalog_post=5)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "8.5-0.0-1.2", "contextStamp": _stamp(msg=2, head_ch=8, head_post=5, catalog_ch=8, catalog_post=5)},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "8.5-0.0-1.3", "contextStamp": _stamp(msg=3, head_ch=8, head_post=5, catalog_ch=8, catalog_post=5)},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "8.5-0.0-1.4", "contextStamp": _stamp(msg=4, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7)},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "8.5-9.0-1.5",
                    "contextStamp": _stamp(
                        msg=5,
                        head_ch=8,
                        head_post=5,
                        attach_ch=9,
                        catalog_ch=9,
                        catalog_post=7,
                    ),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {
                    "text": "8.5-9.0-2.5",
                    "contextStamp": _stamp(
                        msg=5,
                        msg_version=2,
                        branch=2,
                        head_ch=8,
                        head_post=5,
                        attach_ch=9,
                        catalog_ch=9,
                        catalog_post=7,
                    ),
                    "continuation": [
                        {"role": "ai", "text": "a5p"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "8.7-0.0-2.6",
                                    "contextStamp": msg6_stamp,
                                    "contextLabel": "8.7-0.0-2.6",
                                },
                                {"text": "8.7-0.0-3.6"},
                            ],
                        },
                        {"role": "ai", "text": "a6"},
                    ],
                },
            ],
        },
    ]
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="8.7-0.0-3.6",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [8.7-0.0-0]"
    assert "8.5-0.0-0" not in log_labels[1]
    assert log_labels[len(messages) - 1] == "user [8.7-0.0-3.6]"
    assert "0.7" not in log_labels[len(messages) - 1]


def _catalog_ch8_post7_ch9() -> dict[str, Any]:
    catalog = _catalog_ch7_post3_to_ch8_post5()
    for post in (
        {**POST, "text": "Текст поста v6"},
        {**POST, "text": "Текст поста v7"},
    ):
        catalog, _ = register_local_summary_version(
            catalog,
            post_id="post-uuid-1",
            channel=CHANNEL,
            telegram=None,
            post=post,
        )
    catalog, _ = register_global_summary_version(
        catalog,
        channel={**CHANNEL, "core": {"topic": "Канал v9"}},
        telegram=None,
    )
    return catalog


def test_edit_fork_skips_attach_when_version_already_in_chat() -> None:
    """Post v7 floated on msg 3 — edit msg 6 must not re-attach 0.7."""
    catalog = _catalog_ch8_post7_ch9()
    msg6_stamp = _stamp(
        msg=6,
        msg_version=1,
        branch=2,
        head_ch=8,
        head_post=7,
        catalog_ch=9,
        catalog_post=7,
    )
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "8.5-0.0-1.1", "contextStamp": _stamp(msg=1, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "8.5-0.0-1.2", "contextStamp": _stamp(msg=2, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7)},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "text": "8.5-0.7-1.3",
            "contextStamp": _stamp(
                msg=3,
                head_ch=8,
                head_post=5,
                attach_post=7,
                catalog_ch=8,
                catalog_post=7,
            ),
        },
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "8.5-0.0-1.4", "contextStamp": _stamp(msg=4, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7)},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "8.5-9.0-1.5",
                    "contextStamp": _stamp(
                        msg=5,
                        head_ch=8,
                        head_post=5,
                        attach_ch=9,
                        catalog_ch=9,
                        catalog_post=7,
                    ),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {
                    "text": "8.5-9.0-2.5",
                    "contextStamp": _stamp(
                        msg=5,
                        msg_version=2,
                        branch=2,
                        head_ch=8,
                        head_post=5,
                        attach_ch=9,
                        catalog_ch=9,
                        catalog_post=7,
                    ),
                    "continuation": [
                        {"role": "ai", "text": "a5p"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "8.7-0.0-2.6",
                                    "contextStamp": msg6_stamp,
                                    "contextLabel": "8.7-0.0-2.6",
                                },
                                {"text": "8.7-0.0-3.6"},
                            ],
                        },
                        {"role": "ai", "text": "a6"},
                    ],
                },
            ],
        },
    ]
    head, attach, _ = advance_branch_after_reply(
        empty_branch_state(post_head=7),
        current_msg=6,
        latest_channel=9,
        latest_post=7,
        scope="post",
        is_edit_fork=True,
        history=history,
        window_user_turns={1, 3, 4, 5, 6},
    )
    assert head == {"channel": 8, "post": 7}
    assert attach == {"channel": 0, "post": 0}

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="8.7-0.0-3.6",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[len(messages) - 1] == "user [8.7-0.0-3.6]"
    assert "0.7" not in log_labels[len(messages) - 1]


def test_edit_fork_attaches_simultaneous_catalog_bumps() -> None:
    """Edit msg6 after catalog post v9 bump: post attaches, head stays locked at 9.7."""
    catalog = _catalog_ch8_post7_ch9()
    catalog, _ = register_global_summary_version(
        catalog,
        channel={**CHANNEL, "core": {"topic": "Канал v10"}},
        telegram=None,
    )
    for post in (
        {**POST, "text": "Текст поста v8"},
        {**POST, "text": "Текст поста v9"},
    ):
        catalog, _ = register_local_summary_version(
            catalog,
            post_id="post-uuid-1",
            channel=CHANNEL,
            telegram=None,
            post=post,
        )
    msg6_stamp = _stamp(
        msg=6,
        msg_version=1,
        branch=2,
        head_ch=9,
        head_post=7,
        catalog_ch=9,
        catalog_post=7,
    )
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "9.7-0.0-1.1", "contextStamp": _stamp(msg=1, head_ch=9, head_post=7, catalog_ch=9, catalog_post=7)},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "9.7-0.0-1.2", "contextStamp": _stamp(msg=2, head_ch=9, head_post=7, catalog_ch=9, catalog_post=7)},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "9.7-0.0-1.3", "contextStamp": _stamp(msg=3, head_ch=9, head_post=7, catalog_ch=9, catalog_post=7)},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "9.7-0.0-1.4", "contextStamp": _stamp(msg=4, head_ch=9, head_post=7, catalog_ch=9, catalog_post=7)},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "9.7-0.0-1.5",
                    "contextStamp": _stamp(msg=5, head_ch=9, head_post=7, catalog_ch=9, catalog_post=7),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {
                    "text": "9.7-10.0-2.5",
                    "contextStamp": _stamp(
                        msg=5,
                        msg_version=2,
                        branch=2,
                        head_ch=9,
                        head_post=7,
                        attach_ch=10,
                        catalog_ch=10,
                        catalog_post=7,
                    ),
                    "continuation": [
                        {"role": "ai", "text": "a5p"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "9.7-0.0-2.6",
                                    "contextStamp": msg6_stamp,
                                    "contextLabel": "9.7-0.0-2.6",
                                },
                                {"text": "9.7-0.9-3.6"},
                            ],
                        },
                        {"role": "ai", "text": "a6"},
                    ],
                },
            ],
        },
    ]
    head, attach, _ = advance_branch_after_reply(
        empty_branch_state(post_head=7),
        current_msg=6,
        latest_channel=10,
        latest_post=9,
        scope="post",
        is_edit_fork=True,
        history=history,
        window_user_turns={1, 2, 3, 4, 5, 6},
    )
    assert head == {"channel": 9, "post": 7}
    assert attach == {"channel": 0, "post": 9}

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_stamps(
        ai_profile={},
        user_text="9.7-0.9-3.6",
        history=history,
        chat_meta={},
        catalog=catalog,
        post_id="post-uuid-1",
        scope="post",
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [9.7-0.0-0]"
    assert log_labels[len(messages) - 1] == "user/float [9.7-0.9-3.6]"
    assert "9.9" not in log_labels[1]


def test_edit_fork_only_changes_branch_digit() -> None:
    """On edit, msg stays the same; only branch (third segment) increments."""
    catalog = _catalog_ch8_post7_ch9()
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "8.5-0.0-1.1", "contextStamp": _stamp(msg=1, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7)},
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "8.5-0.0-1.5",
                    "contextStamp": _stamp(msg=5, head_ch=8, head_post=5, catalog_ch=8, catalog_post=7),
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {"text": "8.5-9.0-2.5"},
            ],
        },
    ]
    head, attach, _ = advance_branch_after_reply(
        empty_branch_state(post_head=5),
        current_msg=5,
        latest_channel=9,
        latest_post=7,
        scope="post",
        is_edit_fork=True,
        history=history,
        window_user_turns={1, 5},
    )
    label = format_stamp_label(
        _stamp(
            msg=5,
            msg_version=2,
            branch=2,
            head_ch=head["channel"],
            head_post=head["post"],
            attach_ch=attach["channel"],
            catalog_ch=9,
            catalog_post=7,
        )
    )
    assert label == "8.5-9.0-2.5"
    assert label.split("-")[-1] == "2.5"
    assert label.split("-")[-1].startswith("2.")
