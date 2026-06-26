"""
Regression test for the @demochannel-style summary + branch scenario.

Replays chat ef224683-6f9a-4bef-9d5b-39caf5897a3e:
  turn 1   linear start under catalog head v10
  turn 2   edit → fork 2.2 (branch 0 keeps 10-0-2, active branch 1)
  turns 3–4 continuation on branch 2.2
  turn 5   profile bump → catalog v11, floating attached on this turn only
  turns 6–7 head still v10
  turn 8   pending v11 matures (anchor turn 5 left PROMPT_WINDOW) → head v11
"""

from __future__ import annotations

from typing import Any

from app.services.ai.chat_history import (
    clamp_active_branch_index,
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_label import (
    enumerate_active_user_turns,
    read_stamped_context_label,
    resolve_turn_label,
    stamp_context_label_on_path,
)
from app.services.ai.context_labels import (
    advance_label_thread_after_reply,
    assemble_reply_messages_from_labels,
    flatten_label_thread_meta,
    primer_head_from_thread,
    resolve_label_thread_state,
)
from app.services.ai.context_turns import compute_window_user_turns
from app.services.ai.summary_catalog import register_global_summary_version

CHANNEL = {
    "core": {"topic": "placeholder"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}


def _catalog_through_version(version: int) -> dict[str, Any]:
    catalog: dict[str, Any] | None = None
    for index in range(1, version + 1):
        channel = {**CHANNEL, "core": {"topic": f"Сводка {index}"}}
        catalog, _ = register_global_summary_version(catalog, channel=channel, telegram=None)
    assert catalog is not None
    return catalog


def _append_ai_to_active(history: list[dict[str, Any]], text: str = "ai") -> list[dict[str, Any]]:
    if not history:
        return [{"role": "ai", "text": text}]
    history = [dict(message) for message in history]
    last = history[-1]
    if last.get("role") == "user" and last.get("userBranches"):
        branch_index = clamp_active_branch_index(last)
        branches = [dict(branch) for branch in last["userBranches"]]
        branch = dict(branches[branch_index])
        continuation = list(branch.get("continuation") or [])
        continuation.append({"role": "ai", "text": text})
        branch["continuation"] = continuation
        branches[branch_index] = branch
        history[-1] = {**last, "userBranches": branches}
        return history
    return [*history, {"role": "ai", "text": text}]


def _append_user_to_active(history: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    if not history:
        return [{"role": "user", "text": text}]
    history = [dict(message) for message in history]
    last = history[-1]
    if last.get("role") == "user" and last.get("userBranches"):
        branch_index = clamp_active_branch_index(last)
        branches = [dict(branch) for branch in last["userBranches"]]
        branch = dict(branches[branch_index])
        continuation = list(branch.get("continuation") or [])
        continuation.append({"role": "user", "text": text})
        branch["continuation"] = continuation
        branches[branch_index] = branch
        history[-1] = {**last, "userBranches": branches}
        return history
    return [*history, {"role": "user", "text": text}]


def _turn2_fork() -> dict[str, Any]:
    """Edit turn 2: branch 0 = original 10-0-2, branch 1 = active 10-0-2.2."""
    return {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {"text": "10-0-2", "continuation": []},
            {"text": "10-0-2.2", "continuation": []},
        ],
    }


def _finalize_ai_reply(
    meta: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    latest_catalog_version: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Stamp contextLabel on the last user-turn and persist label_context (as ai/reply finalize)."""
    valid_pairs = filter_alternating_roles(linearize_for_llm(history))
    user_turn_count = count_user_turns(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)
    thread_state, thread_key, threads = resolve_label_thread_state(
        meta,
        history,
        latest_catalog_version=latest_catalog_version,
    )
    turn_entries = enumerate_active_user_turns(history)
    last_entry = turn_entries[-1]
    turn_label = resolve_turn_label(history, user_turn_count)

    head, attached, updated_thread = advance_label_thread_after_reply(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    stamped = stamp_context_label_on_path(
        history,
        last_entry["path"],
        head=head,
        attached=attached,
        turn_label=str(last_entry["turn_label"]),
    )
    assert stamped is not None

    threads[thread_key] = updated_thread
    meta = {**meta, **flatten_label_thread_meta(updated_thread, thread_key=thread_key, threads=threads)}

    refreshed = enumerate_active_user_turns(stamped)[-1]
    label = read_stamped_context_label(
        refreshed["message"],
        branch_index=refreshed["branch_index"] if refreshed.get("branched") else None,
    )
    assert label is not None
    return stamped, meta, label


def _stamped_label_on_turn(history: list[dict[str, Any]], turn: int) -> str:
    for entry in enumerate_active_user_turns(history):
        if entry["turn"] != turn:
            continue
        branch_index = entry["branch_index"] if entry.get("branched") else None
        label = read_stamped_context_label(entry["message"], branch_index=branch_index)
        assert label is not None, f"turn {turn} has no contextLabel"
        return label
    raise AssertionError(f"turn {turn} not found")


def test_ef224683_branch_edit_summary_v11_maturation_replay() -> None:
    """
    Full dialog replay: fork at turn 2, floating v11 at turn 5, head v11 from turn 8.

    User message text mirrors the manual debug codes from the live chat; stamps are
    computed by the server and must not be copied from message text.
    """
    catalog = _catalog_through_version(11)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    steps: list[tuple[str, int, str]] = [
        ("10-0-1", 10, "10-0-1"),
        ("__fork__", 10, "10-0-2.2"),
        ("10-0-2.2(3)", 10, "10-0-2.2(3)"),
        ("10-0-2.2(4)", 10, "10-0-2.2(4)"),
        ("10-11-2.2(5)", 11, "10-11-2.2(5)"),
        ("10-0-2.2(6)", 11, "10-0-2.2(6)"),
        ("10-0-2.2(7)", 11, "10-0-2.2(7)"),
        ("11-0-2.2(8)", 11, "11-0-2.2(8)"),
    ]

    for user_text, latest_version, expected_label in steps:
        if user_text == "__fork__":
            history = [*history, _turn2_fork()]
        else:
            history = _append_user_to_active(history, user_text)

        history, meta, label = _finalize_ai_reply(
            meta,
            history,
            latest_catalog_version=latest_version,
        )
        assert label == expected_label
        history = _append_ai_to_active(history)

    assert _stamped_label_on_turn(history, 1) == "10-0-1"
    assert _stamped_label_on_turn(history, 2) == "10-0-2.2"
    assert _stamped_label_on_turn(history, 5) == "10-11-2.2(5)"
    assert _stamped_label_on_turn(history, 8) == "11-0-2.2(8)"

    thread_state, thread_key, _ = resolve_label_thread_state(meta, history)
    assert thread_key == "2@1"
    assert thread_state["head_version"] == 11
    assert thread_state["pending_version"] == 0

    fork_message = history[2]
    assert fork_message["userBranches"][1]["contextLabel"] == "10-0-2.2"
    assert read_stamped_context_label(fork_message["userBranches"][1]["continuation"][1]) == "10-0-2.2(3)"


def test_ef224683_turn8_primer_uses_matured_head_v11() -> None:
    """After turn 8 reply, LLM primer must use catalog v11 (not v10)."""
    catalog = _catalog_through_version(11)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    steps: list[tuple[str, int]] = [
        ("10-0-1", 10),
        ("__fork__", 10),
        ("10-0-2.2(3)", 10),
        ("10-0-2.2(4)", 10),
        ("10-11-2.2(5)", 11),
        ("10-0-2.2(6)", 11),
        ("10-0-2.2(7)", 11),
        ("11-0-2.2(8)", 11),
    ]

    for user_text, latest_version in steps:
        if user_text == "__fork__":
            history = [*history, _turn2_fork()]
        else:
            history = _append_user_to_active(history, user_text)
        history, meta, _ = _finalize_ai_reply(meta, history, latest_catalog_version=latest_version)
        history = _append_ai_to_active(history)

    valid_pairs = filter_alternating_roles(linearize_for_llm(history))
    user_turn_count = count_user_turns(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)
    thread_state, _, _ = resolve_label_thread_state(meta, history)
    head = primer_head_from_thread(
        thread_state,
        user_turn_count=user_turn_count,
        latest_catalog_version=11,
        window_user_turns=window_user_turns,
    )
    assert head == 11

    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="next question",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    primer = messages[1]["content"]
    assert "Сводка 11" in primer
    assert "Сводка 10" not in primer


def _cd249b55_history_after_edit_fork() -> list[dict[str, Any]]:
    """Turn 4 edit on branch 3.2 — active branch 1 (4.2), branch 0 keeps 2-0-3.2(4)."""
    return [
        {"role": "user", "text": "2-0-1", "contextLabel": "2-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "2-0-2", "contextLabel": "2-0-2"},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "2-0-3", "contextLabel": "2-0-3"},
                {
                    "text": "2-0-3.2",
                    "contextLabel": "2-0-3.2",
                    "continuation": [
                        {"role": "ai", "text": "a3"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "2-0-3.2(4)",
                                    "contextLabel": "2-0-3.2(4)",
                                    "continuation": [],
                                },
                                {"text": "2-0-3.2(4.2)", "continuation": []},
                            ],
                        },
                    ],
                },
            ],
        },
    ]


def test_cd249b55_edit_fork_inherits_head_from_branch_zero_label() -> None:
    """
    Chat cd249b55: edit 2-0-3.2(4) → branch 4.2 must stamp 2-0-3.2(4.2), not 3-0-…

    Parent thread may have head=3 after v3 matured on the long branch; the new fork
    must inherit head=2 from branch 0's contextLabel at the fork node.
    """
    catalog = _catalog_through_version(3)
    history = _cd249b55_history_after_edit_fork()
    meta = {
        "active_thread_key": "4@1,4.3@1",
        "label_context": {
            "4@1": {"head_version": 2, "pending_version": 0, "pending_since_turn": 0},
            "4@1,4.3@1": {
                "head_version": 3,
                "pending_version": 0,
                "pending_since_turn": 0,
                "rolling_summary": "",
                "rolling_summary_idx": 0,
            },
        },
    }

    entries = enumerate_active_user_turns(history)
    assert entries[-1]["turn_label"] == "3.2(4.2)"

    stamped, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=3)
    assert label == "2-0-3.2(4.2)"

    thread_state, thread_key, _ = resolve_label_thread_state(meta, stamped)
    assert thread_key == "4@1,4.1@1"
    assert thread_state["head_version"] == 2

    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="next",
        scope="global",
        history=stamped,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    assert "Сводка 2" in messages[1]["content"]
    assert "Сводка 3" not in messages[1]["content"]


def _65aa088c_history_after_edit_fork() -> list[dict[str, Any]]:
    """Edit 3-0-3.2(4) → branch 4.2; branch 0 keeps 3-0-3.2(4), head v3 in primer."""
    return [
        {"role": "user", "text": "3-0-1", "contextLabel": "3-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "3-0-2", "contextLabel": "3-0-2"},
        {"role": "ai", "text": "a2"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "3-0-3", "contextLabel": "3-0-3"},
                {
                    "text": "3-0-3.2",
                    "contextLabel": "3-0-3.2",
                    "continuation": [
                        {"role": "ai", "text": "a3"},
                        {
                            "role": "user",
                            "activeUserBranch": 1,
                            "userBranches": [
                                {
                                    "text": "3-0-3.2(4)",
                                    "contextLabel": "3-0-3.2(4)",
                                    "continuation": [],
                                },
                                {"text": "3-0-3.2(4.2)", "continuation": []},
                            ],
                        },
                    ],
                },
            ],
        },
    ]


def test_65aa088c_edit_fork_attaches_new_catalog_version() -> None:
    """
    Chat 65aa088c: edit on 3.2(4) with catalog v4 while primer head is v3.

    v4 is not in the prompt window but must float on the edited turn (3-4-3.2(4.2)).
    """
    catalog = _catalog_through_version(4)
    history = _65aa088c_history_after_edit_fork()
    meta = {
        "active_thread_key": "4@1,4.3@1",
        "label_context": {
            "4@1": {"head_version": 3, "pending_version": 0, "pending_since_turn": 0},
            "4@1,4.3@1": {
                "head_version": 3,
                "pending_version": 0,
                "pending_since_turn": 0,
                "rolling_summary": "",
                "rolling_summary_idx": 0,
            },
        },
    }

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="3-0-3.2(4.2)",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert "Сводка 3" in messages[1]["content"]
    assert "Сводка 4" not in messages[1]["content"]

    dialog = messages[3:]
    edited_turn = next(m for m in dialog if m["role"] == "user" and "3-0-3.2(4.2)" in m["content"])
    assert "Обновлённый профиль канала:" in edited_turn["content"] or "Обновлённый пост:" in edited_turn["content"]
    assert "Сводка 4" in edited_turn["content"]
    assert log_labels[7] == "user [3-4-3.2(4.2)]"

    stamped, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=4)
    assert label == "3-4-3.2(4.2)"


def _426f71d9_history_after_edit_fork() -> list[dict[str, Any]]:
    """Edit turn 2 → branch 2.2; branch 0 keeps 4-0-2, primer head v4."""
    return [
        {"role": "user", "text": "4-0-1", "contextLabel": "4-0-1"},
        {"role": "ai", "text": "a1"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {"text": "4-0-2", "contextLabel": "4-0-2"},
                {"text": "4-0-2.2", "continuation": []},
            ],
        },
    ]


def test_426f71d9_top_level_fork_attaches_new_catalog_version() -> None:
    """
    Chat 426f71d9: top-level edit at turn 2 with catalog v5 while primer head is v4.

    Parent thread may already show head=5 on branch 0; branch-0 label is still 4-0-2.
    """
    catalog = _catalog_through_version(5)
    history = _426f71d9_history_after_edit_fork()
    meta = {
        "active_thread_key": "2@0",
        "label_context": {
            "": {"head_version": 4, "pending_version": 0, "pending_since_turn": 0},
            "2@0": {"head_version": 5, "pending_version": 0, "pending_since_turn": 0},
        },
    }

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="4-0-2.2",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert "Сводка 4" in messages[1]["content"]
    assert "Сводка 5" not in messages[1]["content"]

    dialog = messages[3:]
    edited_turn = next(m for m in dialog if m["role"] == "user" and "4-0-2.2" in m["content"])
    assert "Обновлённый профиль канала:" in edited_turn["content"] or "Обновлённый пост:" in edited_turn["content"]
    assert "Сводка 5" in edited_turn["content"]
    assert log_labels[5] == "user [4-5-2.2]"

    stamped, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=5)
    assert label == "4-5-2.2"


def test_linear_multi_bump_head_matures_in_order() -> None:
    """
    Two profile bumps in one linear chat: head must advance 1→2→3 without skipping v2.

    Mirrors chats like 112fdc02 where only the latest pending_version was kept.
    """
    catalog = _catalog_through_version(3)
    meta: dict[str, Any] = {"label_context": {"": {"head_version": 1, "pending_version": 0, "pending_since_turn": 0}}}
    history: list[dict[str, Any]] = []

    steps: list[tuple[str, int, str]] = [
        ("u1", 1, "1-0-1"),
        ("u2", 1, "1-0-2"),
        ("u3", 1, "1-0-3"),
        ("u4", 2, "1-2-4"),
        ("u5", 2, "1-0-5"),
        ("u6", 2, "1-0-6"),
        ("u7", 3, "2-3-7"),   # v2 matures (turn 4 left window), v3 attached
        ("u8", 3, "2-0-8"),
        ("u9", 3, "2-0-9"),
        ("u10", 3, "3-0-10"),  # v3 matures (turn 7 left window)
        ("u11", 3, "3-0-11"),
        ("u12", 3, "3-0-12"),
    ]

    for user_text, latest_version, expected_label in steps:
        history = _append_user_to_active(history, user_text)
        history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=latest_version)
        assert label == expected_label, f"turn {user_text}: got {label}, want {expected_label}"
        history = _append_ai_to_active(history)

    thread_state, _, _ = resolve_label_thread_state(meta, history)
    assert thread_state["head_version"] == 3
    assert thread_state["pending_version"] == 0

    valid_pairs = filter_alternating_roles(linearize_for_llm(history))
    window_user_turns = compute_window_user_turns(valid_pairs)
    head = primer_head_from_thread(
        thread_state,
        user_turn_count=12,
        latest_catalog_version=3,
        window_user_turns=window_user_turns,
        history=history,
    )
    assert head == 3

    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="next",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    assert "Сводка 3" in messages[1]["content"]
    assert "Сводка 2" not in messages[1]["content"]


def test_c13ee3f2_edit_turn5_keeps_head_while_float_in_window() -> None:
    """
    Chat c13ee3f2: v4 attached at turn 3, edit turn 5 → 5.2.

    Primer must stay head v3 while turn 3 float is still in the LLM window.
    """
    catalog = _catalog_through_version(4)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    for text, latest in [("3-0-1", 3), ("3-0-2", 3), ("3-4-3", 4), ("3-0-4", 4)]:
        history = _append_user_to_active(history, text)
        history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=latest)
        history = _append_ai_to_active(history)

    history = _append_user_to_active(history, "3-0-5")
    history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=4)
    assert label == "3-0-5"
    assert meta["label_context"][""]["head_version"] == 3

    history = history[:-1]
    history[-1] = {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {
                "text": "3-0-5",
                "contextLabel": "3-0-5",
                "continuation": [{"role": "ai", "text": "a5"}],
            },
            {"text": "3-0-5.2", "continuation": []},
        ],
    }

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="3-0-5.2",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [3-0-0]"
    assert log_labels[7] == "user [3-0-5.2]"
    assert "Сводка 3" in messages[1]["content"]
    assert "Сводка 4" not in messages[1]["content"]
    dialog = messages[3:]
    float_turn = next(m for m in dialog if m["role"] == "user" and "3-4-3" in m["content"])
    assert "Обновлённый профиль канала:" in float_turn["content"] or "Обновлённый пост:" in float_turn["content"]

    history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=4)
    assert label == "3-0-5.2"
    fork_key = meta["active_thread_key"]
    assert meta["label_context"][fork_key]["head_version"] == 3


def test_c13ee3f2_repairs_stale_fork_head_in_meta() -> None:
    """Legacy meta with head=4 on fork thread is demoted while turn-3 float is in window."""
    catalog = _catalog_through_version(4)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    for text, latest in [("3-0-1", 3), ("3-0-2", 3), ("3-4-3", 4), ("3-0-4", 4)]:
        history = _append_user_to_active(history, text)
        history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=latest)
        history = _append_ai_to_active(history)

    history = _append_user_to_active(history, "3-0-5")
    history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=4)
    history = _append_ai_to_active(history)

    history = history[:-1]
    history[-1] = {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {
                "text": "3-0-5",
                "contextLabel": "3-0-5",
                "continuation": [{"role": "ai", "text": "a5"}],
            },
            {"text": "3-0-5.2", "continuation": []},
        ],
    }

    meta["label_context"]["8@1"] = {
        "head_version": 4,
        "pending_version": 0,
        "pending_since_turn": 0,
        "pending_queue": [],
    }
    meta["active_thread_key"] = "8@1"

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="3-0-5.2",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [3-0-0]"
    assert log_labels[7] == "user [3-0-5.2]"
    assert "Сводка 3" in messages[1]["content"]
    assert "Сводка 4" not in messages[1]["content"]


def _finalize_ai_reply_production(
    meta: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    latest_catalog_version: int,
    assistant_text: str = "ai reply",
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Like _finalize_ai_reply but uses production valid_pairs (with assistant appended)."""
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm, count_user_turns
    from app.services.ai.context_turns import maturation_window_user_turns
    from app.services.ai.context_label import resolve_turn_label

    valid_pairs = filter_alternating_roles(linearize_for_llm(history))
    if valid_pairs and valid_pairs[-1][0] == "user":
        valid_pairs = [*valid_pairs, ("assistant", assistant_text)]
    user_turn_count = count_user_turns(valid_pairs)
    window_user_turns = maturation_window_user_turns(valid_pairs)
    thread_state, thread_key, threads = resolve_label_thread_state(
        meta,
        history,
        latest_catalog_version=latest_catalog_version,
    )
    turn_entries = enumerate_active_user_turns(history)
    last_entry = turn_entries[-1]
    turn_label = resolve_turn_label(history, user_turn_count)

    head, attached, updated_thread = advance_label_thread_after_reply(
        thread_state,
        user_turn_count=user_turn_count,
        turn_label=turn_label,
        latest_catalog_version=latest_catalog_version,
        window_user_turns=window_user_turns,
        history=history,
    )
    stamped = stamp_context_label_on_path(
        history,
        last_entry["path"],
        head=head,
        attached=attached,
        turn_label=str(last_entry["turn_label"]),
    )
    assert stamped is not None

    threads[thread_key] = updated_thread
    meta = {**meta, **flatten_label_thread_meta(updated_thread, thread_key=thread_key, threads=threads)}

    refreshed = enumerate_active_user_turns(stamped)[-1]
    label = read_stamped_context_label(
        refreshed["message"],
        branch_index=refreshed["branch_index"] if refreshed.get("branched") else None,
    )
    assert label is not None
    return stamped, meta, label


def test_c2aa3653_finalize_does_not_mature_while_float_in_window() -> None:
    """Linear finalize must not promote head while turn-4 float is still in window."""
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    for text, latest in [("4-0-1", 4), ("4-0-2", 4), ("4-0-3", 4), ("4-5-4", 5), ("4-0-5", 5)]:
        history = _append_user_to_active(history, text)
        history, meta, label = _finalize_ai_reply_production(meta, history, latest_catalog_version=latest)
        history = _append_ai_to_active(history)

    history = _append_user_to_active(history, "4-0-6")
    history, meta, label = _finalize_ai_reply_production(meta, history, latest_catalog_version=5)
    assert label == "4-0-6"
    assert meta["label_context"][""]["head_version"] == 4


def test_c2aa3653_edit_turn6_keeps_head_while_float_in_window() -> None:
    """Chat c2aa3653: v5 attached at turn 4, edit turn 6 → 6.2; primer stays v4."""
    catalog = _catalog_through_version(5)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    for text, latest in [("4-0-1", 4), ("4-0-2", 4), ("4-0-3", 4), ("4-5-4", 5), ("4-0-5", 5)]:
        history = _append_user_to_active(history, text)
        history, meta, label = _finalize_ai_reply_production(meta, history, latest_catalog_version=latest)
        history = _append_ai_to_active(history)

    history = _append_user_to_active(history, "4-0-6")
    history, meta, label = _finalize_ai_reply_production(meta, history, latest_catalog_version=5)
    history = _append_ai_to_active(history)

    history = history[:-1]
    history[-1] = {
        "role": "user",
        "activeUserBranch": 1,
        "userBranches": [
            {
                "text": "4-0-6",
                "contextLabel": "4-0-6",
                "continuation": [{"role": "ai", "text": "a6"}],
            },
            {"text": "4-0-6.2", "continuation": []},
        ],
    }

    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="4-0-6.2",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[1] == "user/primer [4-0-0]"
    assert log_labels[7] == "user [4-0-6.2]"
    assert "Сводка 4" in messages[1]["content"]
    assert "Сводка 5" not in messages[1]["content"]
    dialog = messages[3:]
    float_turn = next(m for m in dialog if m["role"] == "user" and "4-5-4" in m["content"])
    assert "Обновлённый профиль канала:" in float_turn["content"] or "Обновлённый пост:" in float_turn["content"]

    history, meta, label = _finalize_ai_reply_production(meta, history, latest_catalog_version=5)
    assert label == "4-0-6.2"
    fork_key = meta["active_thread_key"]
    assert meta["label_context"][fork_key]["head_version"] == 4


def test_delete_turn_with_float_reattaches_on_rewrite() -> None:
    """Deleting a turn with floating bundle must allow re-attach on the next write."""
    catalog = _catalog_through_version(5)
    meta: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    for text, latest in [("4-0-1", 4), ("4-0-2", 4), ("4-0-3", 4), ("4-5-4", 5)]:
        history = _append_user_to_active(history, text)
        history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=latest)
        assert label == ("4-5-4" if text == "4-5-4" else f"4-0-{text[-1]}")
        history = _append_ai_to_active(history)

    history = history[:-2]

    history = _append_user_to_active(history, "4-0-4")
    log_labels: dict[int, str] = {}
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="4-0-4",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
        log_labels=log_labels,
    )
    assert messages is not None
    assert log_labels[7] == "user [4-5-4]"
    assert "Обновлённый профиль канала:" in messages[-1]["content"] or "Обновлённый пост:" in messages[-1]["content"]
    assert "Сводка 5" in messages[-1]["content"]

    history, meta, label = _finalize_ai_reply(meta, history, latest_catalog_version=5)
    assert label == "4-5-4"
    assert meta["label_context"][""]["head_version"] == 4
