"""Per-message bundleContext resolution."""

from __future__ import annotations

from app.services.ai.bundle import bundle_fingerprint
from app.services.ai.context import assemble_reply_messages
from app.services.ai.message_bundle import (
    apply_bundle_context_stamp_to_history,
    resolve_bundle_from_messages,
)
from app.services.ai.thread_context import find_ancestor_thread_key

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


def _profile(*, g2_matured: bool = False) -> dict:
    fp1 = bundle_fingerprint(CHANNEL)
    fp2 = bundle_fingerprint(CHANNEL_V2)
    return {
        "stub_generation_id": "gen-g2" if g2_matured else "gen-g1",
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
                "anchor_user_turn": 5,
            },
        ],
    }


def test_find_ancestor_thread_key_finds_sibling_zero() -> None:
    threads = {"8@0": {}, "12@1": {}}
    assert find_ancestor_thread_key("8@1", threads) == "8@0"


def test_resolve_bundle_from_messages_uses_stamped_floating_only() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {
            "role": "user",
            "text": "вып1 ыв",
            "bundleContext": {
                "headGenerationId": "gen-g1",
                "floatingGenerationId": "gen-g2",
            },
        },
    ]
    result = resolve_bundle_from_messages(
        history,
        _profile(),
        user_turn_count=2,
        window_user_turns={1, 2},
        fallback_primer="## Канал\nТема: Сводка 1",
        fallback_stub_id="gen-g1",
        fallback_floating={},
    )
    assert result is not None
    primer, stub_id, floating = result
    assert "Сводка 1" in primer
    assert stub_id == "gen-g1"
    assert 2 in floating
    assert "Сводка 2" in floating[2]


def test_matured_profile_head_not_overridden_by_stale_message_stamps() -> None:
    """After G2 matures, primer follows profile even if early messages still stamp G1."""
    history: list[dict] = []
    for index in range(1, 11):
        history.append(
            {
                "role": "user",
                "text": f"u{index}",
                "bundleContext": {"headGenerationId": "gen-g1"},
            }
        )
        history.append({"role": "ai", "text": f"a{index}"})
    history[2]["bundleContext"] = {
        "headGenerationId": "gen-g1",
        "floatingGenerationId": "gen-g2",
    }

    profile = _profile(g2_matured=True)
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="u11",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta={"rolling_summary_profile": profile},
    )
    primer = messages[1]["content"]
    assert "Сводка 2" in primer
    assert "Сводка 1" not in primer


def test_apply_bundle_context_stamp_to_history() -> None:
    history = [
        {"role": "user", "text": "a"},
        {"role": "ai", "text": "b"},
        {"role": "user", "text": "c"},
    ]
    stamped = apply_bundle_context_stamp_to_history(
        history,
        {
            "path": [2],
            "headGenerationId": "gen-g1",
            "floatingGenerationId": "gen-g2",
        },
    )
    assert stamped is not None
    assert stamped[2]["bundleContext"]["headGenerationId"] == "gen-g1"
    assert stamped[2]["bundleContext"]["floatingGenerationId"] == "gen-g2"


def test_fork_from_legacy_flat_meta_keeps_g1_in_primer() -> None:
    """Chats without thread_context must seed fork state from flat rolling_summary_profile."""
    history = [
        {"role": "user", "text": "u1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3"},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "u4"},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "u5",
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {"text": "u5 edited", "continuation": []},
            ],
        },
    ]
    fp2 = bundle_fingerprint(CHANNEL_V2)
    chat_meta = {
        "active_thread_key": "8@0",
        "rolling_summary": "Длинное саммари",
        "rolling_summary_profile": _profile(),
        "global_fingerprint_at_last_refresh": fp2,
    }

    messages = assemble_reply_messages(
        ai_profile={},
        user_text="u5 edited",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Сводка 1" in primer
    assert "Сводка 2" not in primer

    dialog = messages[3:]
    turn_5 = next(m for m in dialog if m["role"] == "user" and "u5 edited" in m["content"])
    assert "SUMMARY_BUNDLE:" in turn_5["content"]
    assert "Сводка 2" in turn_5["content"]


def test_assemble_prefers_message_bundle_context_on_fork() -> None:
    fp2 = bundle_fingerprint(CHANNEL_V2)
    history = [
        {"role": "user", "text": "u1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "u2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "u3"},
        {"role": "ai", "text": "a3"},
        {"role": "user", "text": "u4"},
        {"role": "ai", "text": "a4"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "u5",
                    "continuation": [{"role": "ai", "text": "a5"}],
                },
                {
                    "text": "u5 edited",
                    "bundleContext": {
                        "headGenerationId": "gen-g1",
                        "floatingGenerationId": "gen-g2",
                    },
                    "continuation": [],
                },
            ],
        },
    ]
    chat_meta = {
        "active_thread_key": "8@0",
        "thread_context": {
            "8@0": {
                "rolling_summary_profile": _profile(),
                "global_fingerprint_at_last_refresh": fp2,
            },
        },
    }
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="u5 edited",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta=chat_meta,
    )
    primer = messages[1]["content"]
    assert "Сводка 1" in primer
    assert "Сводка 2" not in primer
    dialog = messages[3:]
    turn_5 = next(m for m in dialog if m["role"] == "user" and "u5 edited" in m["content"])
    assert "SUMMARY_BUNDLE:" in turn_5["content"]
    assert "Сводка 2" in turn_5["content"]
