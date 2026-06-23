"""Tests for rolling summary (ai-context-assembly.md)."""

from __future__ import annotations

import pytest

from app.services.ai.bundle import bundle_fingerprint
from app.services.ai.context import assemble_reply_messages
from app.services.ai.context_config import HISTORY_WINDOW, PROMPT_WINDOW
from app.services.ai.context_meta import (
    apply_rolling_summary_reconcile_to_chat_data,
    refresh_context_meta_after_reply,
)
from app.services.ai.rolling_summary import (
    exchanges_from_messages,
    is_meta_rolling_summary_response,
    reconcile_rolling_summary_fields,
    rolling_summary_for_assembly,
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



@pytest.mark.asyncio
async def test_refresh_context_meta_builds_rolling_summary_template() -> None:
    from app.services.ai.summary_catalog import register_global_summary_version

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    pairs = _pairs((HISTORY_WINDOW // 2) + 5)
    meta = await refresh_context_meta_after_reply(
        {},
        history=[],
        valid_pairs=pairs,
        current_bundle="Bundle",
        current_fingerprint="fp",
        llm=None,
        summary_catalog=catalog,
    )
    assert meta["rolling_summary"]
    assert meta["rolling_summary_idx"] == len(pairs) - PROMPT_WINDOW
    assert meta["active_thread_key"] == ""
    assert "" in meta["label_context"]


@pytest.mark.asyncio
async def test_refresh_context_meta_summarizes_when_pairs_leave_prompt_window() -> None:
    """Summary must start once prefix is non-empty (len > PROMPT_WINDOW), not after 9+ tuples."""
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


def test_is_meta_rolling_summary_response() -> None:
    assert is_meta_rolling_summary_response("Нет реплик для включения. Текущее саммари пусто.")
    assert not is_meta_rolling_summary_response("Я спрашивал про ETF. Ответ: кратко про ETF.")


def test_rolling_summary_for_assembly_bootstraps_empty_fork_thread() -> None:
    pairs = _pairs(4)
    text = rolling_summary_for_assembly({"rolling_summary": "", "rolling_summary_idx": 0}, pairs)
    assert text
    assert "Вопрос 1" in text


def test_rolling_summary_for_assembly_filters_stored_meta_text() -> None:
    pairs = _pairs(4)
    text = rolling_summary_for_assembly(
        {
            "rolling_summary": "Нет реплик для включения. Текущее саммари пусто.",
            "rolling_summary_idx": 0,
        },
        pairs,
    )
    assert "Нет реплик" not in text
    assert "Вопрос 1" in text


def test_assemble_bootstraps_context_summary_on_new_fork_before_reply() -> None:
    from app.services.ai.context_labels import assemble_reply_messages_from_labels
    from app.services.ai.summary_catalog import register_global_summary_version

    catalog, _ = register_global_summary_version(None, channel=CHANNEL, telegram=None)
    history = [
        {"role": "user", "text": "msg1", "contextLabel": "1-0-1"},
        {"role": "ai", "text": "a1"},
        {"role": "user", "text": "msg2", "contextLabel": "1-0-2"},
        {"role": "ai", "text": "a2"},
        {"role": "user", "text": "msg3", "contextLabel": "1-0-3"},
        {"role": "ai", "text": "a3"},
        {
            "role": "user",
            "activeUserBranch": 1,
            "userBranches": [
                {
                    "text": "msg4",
                    "contextLabel": "1-0-4",
                    "continuation": [{"role": "ai", "text": "a4"}],
                },
                {"text": "msg4-edited"},
            ],
        },
    ]
    meta = {
        "label_context": {
            "": {
                "head_version": 1,
                "rolling_summary": "Саммари длинной ветки",
                "rolling_summary_idx": 4,
            }
        }
    }
    messages = assemble_reply_messages_from_labels(
        ai_profile={},
        user_text="msg4-edited",
        scope="global",
        history=history,
        chat_meta=meta,
        catalog=catalog,
    )
    assert messages is not None
    assert "CONTEXT_SUMMARY:" in messages[1]["content"]
    assert "msg1" in messages[1]["content"]


def test_bundle_fingerprint_changes_when_channel_changes() -> None:
    assert bundle_fingerprint(CHANNEL) != bundle_fingerprint(CHANNEL_V2)


def test_bundle_fingerprint_changes_when_telegram_changes() -> None:
    assert bundle_fingerprint(CHANNEL, telegram={"channelTitle": "A"}) != bundle_fingerprint(
        CHANNEL, telegram={"channelTitle": "B"}
    )
