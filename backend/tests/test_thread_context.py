"""Per-active-thread context isolation (branches + summaries)."""

from __future__ import annotations

import pytest

from app.services.ai.bundle import bundle_fingerprint
from app.services.ai.chat_history import active_thread_key
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_meta import refresh_context_meta_after_reply
from app.services.ai.thread_context import PARENT_GENERATIONS_KEY, resolve_thread_state

CHANNEL = {
    "core": {"topic": "Сводка 1"},
    "voice": {"tone": "Разговорный"},
    "rules": {},
    "rubrics": [],
}

CHANNEL_V2 = {
    **CHANNEL,
    "core": {"topic": "Сводка 2"},
}


def _linear_history(messages: list[tuple[str, str]]) -> list[dict]:
    return [
        {"role": "user" if role == "user" else "ai", "text": text}
        for role, text in messages
    ]


def _branched_history() -> list[dict]:
    """Two branches at user message [2]: long old line vs short new line."""
    return [
        {"role": "user", "text": "Ну"},
        {"role": "ai", "text": "Привет"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "ва",
                    "continuation": [
                        {"role": "ai", "text": "Ответ на ва"},
                        {"role": "user", "text": "ыва"},
                        {"role": "ai", "text": "Ответ на ыва"},
                    ],
                },
                {
                    "text": "ва ап",
                    "continuation": [],
                },
            ],
        },
    ]


def test_active_thread_key_distinguishes_branches() -> None:
    history = _branched_history()
    assert active_thread_key(history) == "2@1"

    history_branch_0 = [
        history[0],
        history[1],
        {
            **history[2],
            "activeUserBranch": 0,
        },
    ]
    assert active_thread_key(history_branch_0) == "2@0"


def _parent_profile_g1_then_g2(*, g2_matured: bool = True, g2_anchor: int = 5) -> dict:
    """G1 at turn 1, G2 at turn g2_anchor; on long branch G2 is head when matured."""
    fp1 = bundle_fingerprint(CHANNEL)
    fp2 = bundle_fingerprint(CHANNEL_V2)
    profile = {
        "stub_generation_id": "gen-g1",
        "generations": [
            {
                "id": "gen-g1",
                "fingerprint": fp1,
                "text": "## Канал\nТема: Сводка 1",
                "anchor_user_turn": 1,
            },
            {
                "id": "gen-g2",
                "fingerprint": fp2,
                "text": "## Канал\nТема: Сводка 2",
                "anchor_user_turn": g2_anchor,
            },
        ],
    }
    if g2_matured:
        profile["stub_generation_id"] = "gen-g2"
    return profile


def _fork_at_third_message_history() -> list[dict]:
    """Edit user message #3 → new branch with only 2 prior user turns."""
    return [
        {"role": "user", "text": "U1"},
        {"role": "ai", "text": "A1"},
        {"role": "user", "text": "U2"},
        {"role": "ai", "text": "A2"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "U3",
                    "continuation": [
                        {"role": "ai", "text": "A3"},
                        *[
                            {"role": role, "text": text}
                            for index in range(4, 11)
                            for role, text in (
                                ("user", f"U{index}"),
                                ("ai", f"A{index}"),
                            )
                        ],
                    ],
                },
                {"text": "U3 edited", "continuation": []},
            ],
        },
    ]


def test_resolve_thread_state_creates_isolated_state_for_new_branch() -> None:
    history = _branched_history()
    parent_profile = {
        "stub_generation_id": "gen-g1",
        "generations": [
            {
                "id": "gen-g1",
                "fingerprint": "fp-1",
                "text": "Bundle G1",
                "anchor_user_turn": 1,
            },
            {
                "id": "gen-g2",
                "fingerprint": "fp-2",
                "text": "Bundle G2",
                "anchor_user_turn": 5,
            },
        ],
    }
    long_meta = {
        "active_thread_key": "2@0",
        "thread_context": {
            "2@0": {
                "rolling_summary": "Саммари длинной ветки про ыва",
                "rolling_summary_idx": 2,
                "rolling_summary_profile": parent_profile,
                "global_fingerprint_at_last_refresh": "fp-2",
            }
        },
    }

    state, key, threads = resolve_thread_state(
        long_meta,
        history,
        global_fingerprint="fp-2",
    )
    assert key == "2@1"
    assert state["rolling_summary"] == ""
    assert len(state["rolling_summary_profile"]["generations"]) == 1
    assert state["rolling_summary_profile"]["generations"][0]["text"] == "Bundle G1"
    assert state["rolling_summary_profile"]["stub_generation_id"] == "gen-g1"
    assert "2@0" in threads
    assert "2@1" in threads


def test_fork_at_fourth_turn_floats_g2_on_edited_message() -> None:
    """Edit turn 4 while G2 exists globally (anchor 5 on parent) — float G2 on the edit turn."""
    history = [
        {"role": "user", "text": "u1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3"},
        {"role": "ai", "text": "a3"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "u4",
                    "continuation": [
                        {"role": "ai", "text": "a4"},
                        {"role": "user", "text": "u5"},
                        {"role": "ai", "text": "a5"},
                    ],
                },
                {"text": "u4 edited", "continuation": []},
            ],
        },
    ]
    fp2 = bundle_fingerprint(CHANNEL_V2)
    parent_profile = _parent_profile_g1_then_g2(g2_matured=False, g2_anchor=5)
    chat_meta = {
        "active_thread_key": "6@0",
        "thread_context": {
            "6@0": {
                "rolling_summary_profile": parent_profile,
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="u4 edited",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Сводка 1" in primer
    assert "Сводка 2" not in primer

    dialog = messages[3:]
    edited_turn = next(m for m in dialog if m["role"] == "user" and "u4 edited" in m["content"])
    assert "SUMMARY_BUNDLE:" in edited_turn["content"]
    assert "Сводка 2" in edited_turn["content"]


def test_fork_at_fifth_turn_keeps_g1_in_primer_and_floats_g2() -> None:
    """Edit user turn 5 while G2 exists but has not matured — G1 head, G2 floating."""
    history = [
        {"role": "user", "text": "ыпаып 1"},
        {"role": "ai", "text": "Привет"},
        {"role": "user", "text": "ыавпы1"},
        {"role": "ai", "text": "Не понял"},
        {"role": "user", "text": "аыпап1"},
        {"role": "ai", "text": "Давай по делу"},
        {"role": "user", "text": "ывп1"},
        {"role": "ai", "text": "Не залипай"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "выаыва1",
                    "continuation": [
                        {"role": "ai", "text": "Понял. Сводка 2"},
                        {"role": "user", "text": "ыва1"},
                        {"role": "ai", "text": "Принято"},
                    ],
                },
                {"text": "выаыва1 вы", "continuation": []},
            ],
        },
    ]
    fp2 = bundle_fingerprint(CHANNEL_V2)
    parent_profile = _parent_profile_g1_then_g2(g2_matured=True)
    chat_meta = {
        "active_thread_key": "8@0",
        "thread_context": {
            "8@0": {
                "rolling_summary": "Длинное саммари",
                "rolling_summary_idx": 10,
                "rolling_summary_profile": parent_profile,
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="выаыва1 вы",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Сводка 1" in primer
    assert "Сводка 2" not in primer

    dialog = messages[3:]
    turn_5 = next(m for m in dialog if m["role"] == "user" and "выаыва1 вы" in m["content"])
    assert "SUMMARY_BUNDLE:" in turn_5["content"]
    assert "Сводка 2" in turn_5["content"]


def test_fork_at_third_turn_floats_g2_on_edited_message() -> None:
    """Edit user turn 3 while G2 exists on parent (anchor 6) — float G2 on first assemble."""
    history = _fork_at_third_message_history()
    fp2 = bundle_fingerprint(CHANNEL_V2)
    chat_meta = {
        "active_thread_key": "6@0",
        "thread_context": {
            "6@0": {
                "rolling_summary": "Длинное саммари",
                "rolling_summary_idx": 10,
                "rolling_summary_profile": _parent_profile_g1_then_g2(
                    g2_matured=True,
                    g2_anchor=6,
                ),
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="U3 edited",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Сводка 2" not in primer
    assert "Сводка 1" in primer

    dialog = messages[3:]
    edited_turn = next(m for m in dialog if m["role"] == "user" and "U3 edited" in m["content"])
    assert "SUMMARY_BUNDLE:" in edited_turn["content"]
    assert "Сводка 2" in edited_turn["content"]


def test_assemble_uses_active_branch_summary_not_flat_stale() -> None:
    history = _branched_history()
    fp2 = bundle_fingerprint(CHANNEL_V2)
    chat_meta = {
        "active_thread_key": "2@0",
        "thread_context": {
            "2@0": {
                "rolling_summary": "Саммари длинной ветки про ыва",
                "rolling_summary_idx": 2,
                "rolling_summary_profile": _parent_profile_g1_then_g2(),
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="ва ап",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Саммари длинной ветки" not in primer
    assert "Сводка 1" in primer
    assert "Сводка 2" not in primer


def test_assemble_short_branch_does_not_float_old_bundle_anchor() -> None:
    history = _branched_history()
    fp2 = bundle_fingerprint(CHANNEL_V2)
    chat_meta = {
        "active_thread_key": "2@0",
        "thread_context": {
            "2@0": {
                "rolling_summary": "Длинное саммари",
                "rolling_summary_idx": 0,
                "rolling_summary_profile": {
                    "stub_generation_id": "gen-g2",
                    "generations": [
                        {
                            "id": "gen-g1",
                            "fingerprint": "fp-1",
                            "text": "Bundle G1",
                            "anchor_user_turn": 1,
                        },
                        {
                            "id": "gen-g2",
                            "fingerprint": "fp-2",
                            "text": "Bundle G2",
                            "anchor_user_turn": 8,
                        },
                    ],
                },
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="ва ап",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    dialog = messages[3:]
    for message in dialog:
        if message["role"] == "user":
            assert "Bundle G2" not in message["content"]
            assert "SUMMARY_BUNDLE:" not in message["content"]


@pytest.mark.asyncio
async def test_refresh_context_meta_stores_per_thread_summary() -> None:
    history_long = [
        {"role": "user", "text": "Ну"},
        {"role": "ai", "text": "Привет"},
        {
            "role": "user",
            "activeUserBranch": 0,
            "userBranches": [
                {"text": "ва", "continuation": [{"role": "ai", "text": "A1"}]},
                {"text": "ва ап", "continuation": []},
            ],
        },
    ]
    pairs_long = [
        ("user", "Ну"),
        ("assistant", "Привет"),
        ("user", "ва"),
        ("assistant", "A1"),
    ]

    meta = await refresh_context_meta_after_reply(
        {},
        history=history_long,
        valid_pairs=pairs_long,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta["active_thread_key"] == "2@0"
    assert "2@0" in meta["thread_context"]

    history_short = [
        history_long[0],
        history_long[1],
        {**history_long[2], "activeUserBranch": 1},
    ]
    pairs_short = [
        ("user", "Ну"),
        ("assistant", "Привет"),
        ("user", "ва ап"),
        ("assistant", "A2"),
    ]
    meta_short = await refresh_context_meta_after_reply(
        meta,
        history=history_short,
        valid_pairs=pairs_short,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta_short["active_thread_key"] == "2@1"
    assert meta_short["thread_context"]["2@0"]["rolling_summary"] == meta["rolling_summary"]
    assert meta_short["rolling_summary"] == meta_short["thread_context"]["2@1"]["rolling_summary"]


@pytest.mark.asyncio
async def test_refresh_preserves_parent_generations_snapshot_on_fork() -> None:
    """After reply on a forked branch, parent_generations_snapshot must survive meta refresh."""
    history = _fork_at_third_message_history()
    fp2 = bundle_fingerprint(CHANNEL_V2)
    parent_profile = _parent_profile_g1_then_g2(g2_matured=True, g2_anchor=6)
    chat_meta = {
        "active_thread_key": "6@0",
        "thread_context": {
            "6@0": {
                "rolling_summary_profile": parent_profile,
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }
    state, key, _ = resolve_thread_state(chat_meta, history, global_fingerprint=fp2)
    assert key == "4@1"
    assert state.get(PARENT_GENERATIONS_KEY)

    pairs = [
        ("user", "U1"),
        ("assistant", "A1"),
        ("user", "U2"),
        ("assistant", "A2"),
        ("user", "U3 edited"),
        ("assistant", "A3"),
    ]
    meta = await refresh_context_meta_after_reply(
        chat_meta,
        history=history,
        valid_pairs=pairs,
        current_bundle="## Канал\nТема: Сводка 2",
        current_fingerprint=fp2,
        llm=None,
    )
    fork_thread = meta["thread_context"]["4@1"]
    assert fork_thread.get(PARENT_GENERATIONS_KEY)
    assert len(fork_thread[PARENT_GENERATIONS_KEY]) >= 2
