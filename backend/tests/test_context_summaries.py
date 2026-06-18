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
from app.services.ai.context_config import HISTORY_WINDOW, SUMMARY_BUNDLE_CATCHUP_MESSAGES
from app.services.ai.context_meta import refresh_context_meta_after_reply
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
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
    joined = "\n".join(item["content"] for item in dialog)
    assert "SUMMARY_BUNDLE:" in joined
    assert "Крипто" in joined or "Bundle B" in joined


@pytest.mark.asyncio
async def test_refresh_context_meta_builds_rolling_summary_template() -> None:
    pairs = _pairs((HISTORY_WINDOW // 2) + 5)
    meta = await refresh_context_meta_after_reply(
        {},
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - 5


def test_update_rolling_summary_template_limits_growth() -> None:
    summary = update_rolling_summary_template(
        "",
        [("Вопрос про ETF", "Ответ про ETF"), ("Вопрос про риски", "Ответ про риски")],
    )
    assert "ETF" in summary
    assert "риски" in summary


def test_bundle_fingerprint_changes_when_channel_changes() -> None:
    assert bundle_fingerprint(CHANNEL) != bundle_fingerprint(CHANNEL_V2)
