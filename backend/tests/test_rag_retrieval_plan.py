"""Tests for L2 structured retrieval planning."""

from __future__ import annotations

from app.services.ai.rag_escalation import TierAResult, TierASignals
from app.services.ai.rag_retrieval_plan import (
    build_plan_messages,
    decide_structured_plan,
    format_l1_hits_for_plan,
    parse_retrieval_plan,
)


def _tier_a(**kwargs) -> TierAResult:
    defaults = {
        "fast_path": None,
        "escalate_target": None,
        "escalate_post_id": None,
        "signals": TierASignals(
            pointer_phrase=False,
            answer_type_mismatch=False,
            chunk_too_short=False,
            is_followup=False,
        ),
        "neighbors": {},
    }
    defaults.update(kwargs)
    return TierAResult(**defaults)


def test_parse_retrieval_plan_nested_steps() -> None:
    raw = (
        '{"goal": "найти приветственный пост", "steps": ['
        '{"tool": "ListPosts", "args": {"status": "all"}, "purpose": "каталог"},'
        '{"tool": "OpenPost", "args": {"post_id": "3"}, "purpose": "текст"}'
        "]}"
    )
    plan = parse_retrieval_plan(raw, max_steps=4)
    assert plan is not None
    assert plan.goal == "найти приветственный пост"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "ListPosts"
    assert plan.steps[1].args["post_id"] == "3"


def test_decide_structured_plan_off_mode() -> None:
    decision = decide_structured_plan(
        planning_mode="off",
        user_text="серия постов заранее",
        scope="global",
        hints=[],
        tier_a=_tier_a(fast_path="miss"),
        tier_b=None,
        l1_results=[],
    )
    assert decision.use_plan is False
    assert decision.reason == "planning_mode=off"


def test_decide_structured_plan_auto_post_query_without_post_hit() -> None:
    decision = decide_structured_plan(
        planning_mode="auto",
        user_text="есть приветственный пост в серии?",
        scope="global",
        hints=[],
        tier_a=_tier_a(fast_path="miss"),
        tier_b=None,
        l1_results=[
            {
                "node_type": "note_chunk",
                "note_id": "n1",
                "chunk_text": "заметка",
                "similarity": 0.4,
            }
        ],
    )
    assert decision.use_plan is True
    assert "post_related_query" in decision.reason


def test_decide_structured_plan_auto_simple_reactive() -> None:
    decision = decide_structured_plan(
        planning_mode="auto",
        user_text="какая стратегия распределения активов?",
        scope="global",
        hints=[],
        tier_a=_tier_a(),
        tier_b=None,
        l1_results=[
            {
                "node_type": "note_chunk",
                "note_id": "n1",
                "chunk_text": "60% акции",
                "similarity": 0.86,
            }
        ],
    )
    assert decision.use_plan is False
    assert decision.reason == "simple_l2_reactive"


def test_format_l1_hits_for_plan_empty() -> None:
    assert "не нашёл" in format_l1_hits_for_plan([])


def test_build_plan_messages_handles_json_braces_in_prompt() -> None:
    messages = build_plan_messages(
        user_text="есть приветственный пост?",
        l1_summary=format_l1_hits_for_plan([]),
        hints=[],
        scope="global",
        max_steps=4,
    )
    system = messages[0]["content"]
    assert '"goal"' in system
    assert "1–4 шагов" in system
    assert "пересоставит план" in system


def test_build_replan_messages_includes_transcript() -> None:
    from app.services.ai.rag_retrieval_plan import build_replan_messages

    messages = build_replan_messages(
        user_text="вопрос",
        transcript=["ListPosts({'status': 'all'}): id=3"],
        hints=[],
        scope="global",
        max_steps=2,
        trigger="after_ListPosts",
    )
    user_content = messages[1]["content"]
    assert "after_ListPosts" in user_content
    assert "id=3" in user_content
    assert "Ход выполнения" in user_content
