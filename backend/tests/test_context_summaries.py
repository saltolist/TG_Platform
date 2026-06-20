"""Tests for rolling summary and bundle profile (ai-context-assembly.md)."""

from __future__ import annotations

import pytest

from app.services.ai.bundle import bundle_fingerprint
from app.services.ai.bundle_profile import (
    bundle_text_for_primer,
    ensure_bundle_profile,
    get_floating_bundle_injections,
)
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_config import HISTORY_WINDOW, PROMPT_WINDOW, SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.context_meta import (
    apply_rolling_summary_reconcile_to_chat_data,
    refresh_context_meta_after_reply,
)
from app.services.ai.context_turns import compute_window_user_turns
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
    reconcile_rolling_summary_fields,
    update_rolling_summary_template,
)

CHANNEL = {
    "core": {"topic": "Финансы"},
    "voice": {"tone": "Разговорный"},
    "rules": {"must": "Без жаргона"},
    "rubrics": [],
}

CHANNEL_V2 = {
    **CHANNEL,
    "core": {"topic": "Крипто"},
}


def _pairs(count: int) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for index in range(count):
        pairs.append(("user", f"Вопрос {index + 1}"))
        pairs.append(("assistant", f"Ответ {index + 1}"))
    return pairs


def test_exchanges_from_messages_pairs_user_and_assistant() -> None:
    messages = [
        ("user", "Привет"),
        ("assistant", "Здравствуй"),
        ("user", "Ещё"),
    ]
    assert exchanges_from_messages(messages) == [("Привет", "Здравствуй"), ("Ещё", "")]


def test_ensure_bundle_profile_creates_first_generation() -> None:
    profile = ensure_bundle_profile(
        None,
        current_bundle="Bundle A",
        current_fingerprint="fp-a",
        user_turn_count=1,
    )
    assert len(profile["generations"]) == 1
    assert profile["stub_generation_id"] == profile["generations"][0]["id"]


def test_ensure_bundle_profile_adds_generation_on_fingerprint_change() -> None:
    first = ensure_bundle_profile(
        None,
        current_bundle="Bundle A",
        current_fingerprint="fp-a",
        user_turn_count=1,
    )
    second = ensure_bundle_profile(
        first,
        current_bundle="Bundle B",
        current_fingerprint="fp-b",
        user_turn_count=3,
    )
    assert len(second["generations"]) == 2
    assert second["generations"][-1]["anchor_user_turn"] == 3


def test_bundle_matures_after_catchup_user_turns() -> None:
    profile = ensure_bundle_profile(
        None,
        current_bundle="Bundle A",
        current_fingerprint="fp-a",
        user_turn_count=1,
    )
    matured = ensure_bundle_profile(
        profile,
        current_bundle="Bundle B",
        current_fingerprint="fp-b",
        user_turn_count=3,
    )
    stub_text_early = bundle_text_for_primer(
        matured,
        current_bundle="Bundle B",
        user_turn_count=3,
    )
    assert "Bundle A" in stub_text_early

    stub_text_late = bundle_text_for_primer(
        matured,
        current_bundle="Bundle B",
        user_turn_count=3 + SUMMARY_BUNDLE_CATCHUP_MESSAGES,
    )
    assert "Bundle B" in stub_text_late


def test_floating_bundle_attached_to_current_user_message() -> None:
    """New bundle after channel update is merged into the user message, not a separate pair."""
    profile = ensure_bundle_profile(
        None,
        current_bundle="Bundle A",
        current_fingerprint="fp-a",
        user_turn_count=1,
    )

    history = [
        {"role": "user", "text": "Привет"},
        {"role": "ai", "text": "Ответ"},
    ]
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Второй вопрос",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta={
            "rolling_summary_profile": profile,
            "rolling_summary": "",
            "rolling_summary_idx": 0,
        },
    )
    dialog = messages[3:]
    assert all(m["content"] != "Понял, учту." for m in dialog if m["role"] == "assistant")
    user_with_bundle = next(m for m in dialog if m["role"] == "user" and "Второй вопрос" in m["content"])
    assert "SUMMARY_BUNDLE:" in user_with_bundle["content"]
    assert "Крипто" in user_with_bundle["content"]


def test_floating_bundle_injected_before_anchor_user_turn() -> None:
    profile = ensure_bundle_profile(
        None,
        current_bundle="Bundle A",
        current_fingerprint="fp-a",
        user_turn_count=1,
    )
    profile = ensure_bundle_profile(
        profile,
        current_bundle="Bundle B",
        current_fingerprint="fp-b",
        user_turn_count=3,
    )
    stub_id = str(profile["stub_generation_id"])
    floating = get_floating_bundle_injections(
        profile,
        primer_stub_id=stub_id,
        user_turn_count=4,
        window_user_turns={2, 3, 4},
    )
    assert 3 in floating
    assert "Bundle B" in floating[3]

    history = [
        {"role": "user" if role == "user" else "ai", "text": content}
        for role, content in _pairs(4)
    ]
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Вопрос 4",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        chat_meta={
            "rolling_summary_profile": profile,
            "rolling_summary": "",
            "rolling_summary_idx": 0,
        },
    )
    dialog = messages[3:]
    user_turn_3 = next(m for m in dialog if m["role"] == "user" and "Вопрос 3" in m["content"])
    assert "SUMMARY_BUNDLE:" in user_turn_3["content"]
    assert "Bundle B" in user_turn_3["content"] or "Крипто" in user_turn_3["content"]


def test_bundle_promotes_to_primer_when_anchor_leaves_window() -> None:
    """New bundle must not vanish when its anchor turn scrolls out of PROMPT_WINDOW."""
    profile = ensure_bundle_profile(
        None,
        current_bundle="Контекст канала пока не заполнен.",
        current_fingerprint="fp-empty",
        user_turn_count=1,
    )
    profile = ensure_bundle_profile(
        profile,
        current_bundle="## Канал\nНазвание: wewe",
        current_fingerprint="fp-filled",
        user_turn_count=3,
    )

    pairs = _pairs(6)
    window_turns = compute_window_user_turns(pairs)
    assert 3 not in window_turns
    assert 6 in window_turns

    updated = ensure_bundle_profile(
        profile,
        current_bundle="## Канал\nНазвание: wewe",
        current_fingerprint="fp-filled",
        user_turn_count=6,
        window_user_turns=window_turns,
    )
    primer = bundle_text_for_primer(
        updated,
        current_bundle="## Канал\nНазвание: wewe",
        user_turn_count=6,
        window_user_turns=window_turns,
    )
    assert "wewe" in primer
    assert "не заполнен" not in primer

    floating = get_floating_bundle_injections(
        updated,
        primer_stub_id=str(updated["stub_generation_id"]),
        user_turn_count=6,
        window_user_turns=window_turns,
    )
    assert floating == {}


def test_assemble_promotes_bundle_when_anchor_left_window() -> None:
    profile = ensure_bundle_profile(
        None,
        current_bundle="Контекст канала пока не заполнен.",
        current_fingerprint="fp-empty",
        user_turn_count=1,
    )
    profile = ensure_bundle_profile(
        profile,
        current_bundle="## Канал\nНазвание: wewe",
        current_fingerprint="fp-filled",
        user_turn_count=3,
    )

    history = [
        {"role": "user" if role == "user" else "ai", "text": content}
        for role, content in _pairs(5)
    ]
    messages = assemble_reply_messages(
        ai_profile={},
        user_text="Вопрос 6",
        scope="global",
        history=history,
        channel_profile=CHANNEL_V2,
        telegram_profile={"channelTitle": "wewe", "channel": "@wewe"},
        chat_meta={
            "rolling_summary_profile": profile,
            "rolling_summary": "Краткое саммари диалога.",
            "rolling_summary_idx": 0,
        },
    )
    primer = messages[1]["content"]
    assert "wewe" in primer or "Крипто" in primer
    assert "не заполнен" not in primer


@pytest.mark.asyncio
async def test_refresh_context_meta_builds_rolling_summary_template() -> None:
    pairs = _pairs((HISTORY_WINDOW // 2) + 5)
    meta = await refresh_context_meta_after_reply(
        {},
        history=[],
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - PROMPT_WINDOW
    assert meta["active_thread_key"] == ""
    assert "" in meta["thread_context"]


@pytest.mark.asyncio
async def test_refresh_context_meta_summarizes_when_pairs_leave_prompt_window() -> None:
    """Summary must start once prefix is non-empty (len > PROMPT_WINDOW), not after 9+ tuples."""
    pairs = _pairs(4)
    meta = await refresh_context_meta_after_reply(
        {},
        history=[],
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - PROMPT_WINDOW


@pytest.mark.asyncio
async def test_labels_path_summarizes_when_pairs_leave_prompt_window() -> None:
    from app.services.ai.context_labels import assemble_reply_messages_from_labels
    from app.services.ai.summary_catalog import register_global_summary_version

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    pairs = _pairs(4)
    meta = await refresh_context_meta_after_reply(
        {},
        history=[],
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
        summary_catalog=catalog,
        scope="global",
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - PROMPT_WINDOW

    history: list[dict[str, str]] = []
    for index in range(4):
        history.append({"role": "user", "text": f"Вопрос {index + 1}"})
        history.append({"role": "ai", "text": f"Ответ {index + 1}"})
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="Вопрос 5",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    assert "CONTEXT_SUMMARY:" in messages[1]["content"]


@pytest.mark.asyncio
async def test_reconcile_clears_summary_when_last_turn_deleted() -> None:
    pairs = _pairs(4)
    meta = await refresh_context_meta_after_reply(
        {},
        history=[],
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - PROMPT_WINDOW

    shortened = pairs[:-2]
    reconciled = reconcile_rolling_summary_fields(
        {
            "rolling_summary": meta["rolling_summary"],
            "rolling_summary_idx": meta["rolling_summary_idx"],
        },
        shortened,
    )
    assert reconciled["rolling_summary"] == ""
    assert reconciled["rolling_summary_idx"] == 0


def test_reconcile_noop_when_prefix_still_covers_idx() -> None:
    pairs = _pairs(4)
    prefix_len = len(pairs) - PROMPT_WINDOW
    state = {"rolling_summary": "Саммари диалога", "rolling_summary_idx": prefix_len}
    reconciled = reconcile_rolling_summary_fields(state, pairs)
    assert reconciled == state


def test_reconcile_label_thread_does_not_touch_head_version() -> None:
    pairs = _pairs(4)
    chat_data = {
        "active_thread_key": "",
        "label_context": {
            "": {
                "head_version": 2,
                "pending_version": 0,
                "pending_since_turn": 0,
                "pending_queue": [],
                "rolling_summary": "Старое саммари",
                "rolling_summary_idx": 3,
            }
        },
        "rolling_summary": "Старое саммари",
        "rolling_summary_idx": 3,
    }
    patch = apply_rolling_summary_reconcile_to_chat_data(chat_data, [])
    assert patch["rolling_summary"] == ""
    assert patch["rolling_summary_idx"] == 0
    assert patch["label_context"][""]["head_version"] == 2
    assert patch["label_context"][""]["pending_version"] == 0


def test_update_rolling_summary_template_limits_growth() -> None:
    summary = update_rolling_summary_template(
        "",
        [("Вопрос про ETF", "Ответ про ETF"), ("Вопрос про риски", "Ответ про риски")],
    )
    assert "ETF" in summary
    assert "риски" in summary


def test_bundle_fingerprint_changes_when_channel_changes() -> None:
    assert bundle_fingerprint(CHANNEL) != bundle_fingerprint(CHANNEL_V2)


def test_bundle_fingerprint_changes_when_telegram_changes() -> None:
    assert bundle_fingerprint(CHANNEL, telegram={"channelTitle": "A"}) != bundle_fingerprint(
        CHANNEL, telegram={"channelTitle": "B"}
    )
