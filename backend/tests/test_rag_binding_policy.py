"""Tests for universal L2 binding policy."""

from __future__ import annotations

from app.services.ai.rag import NODE_NOTE_CHUNK, NODE_POST_TEXT
from app.services.ai.rag_binding_policy import (
    can_bind_target_post,
    collect_invalid_plan_ids,
    is_invalid_plan_id,
    plan_has_off_target_discovery,
    should_block_post_scoped_tool,
)
from app.services.ai.rag_retrieval_brief import build_retrieval_brief
from app.services.ai.rag_retrieval_plan import RetrievalPlanStep


def test_is_invalid_plan_id_detects_placeholders() -> None:
    assert is_invalid_plan_id("PLACEHOLDER_FROM_SEARCH")
    assert is_invalid_plan_id("todo-id")
    assert not is_invalid_plan_id("721c63fe-f7c6-4183-9a8d-da1979180467")
    assert not is_invalid_plan_id("3")


def test_collect_invalid_plan_ids_from_steps() -> None:
    steps = [
        RetrievalPlanStep(
            tool="OpenPost",
            args={"post_id": "PLACEHOLDER_FROM_SEARCH_RESULT_0"},
            purpose="",
        )
    ]
    assert collect_invalid_plan_ids(steps) == ["OpenPost.post_id='PLACEHOLDER_FROM_SEARCH_RESULT_0'"]


def test_plan_has_off_target_discovery_note_chunk_only() -> None:
    steps = [
        RetrievalPlanStep(
            tool="SearchNodes",
            args={"query": "png", "node_types": ["note_chunk"]},
            purpose="",
        )
    ]
    assert plan_has_off_target_discovery(steps)


def test_can_bind_target_post_uses_target_resolution() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    allowed, reason = can_bind_target_post(
        brief=brief,
        scope="global",
        post_id="3",
        post_data={"text": "Приветствую 👋"},
        discovery_completed=False,
        seed_post_id=None,
        tier_a_post_id=None,
        l1_results=[],
        target_resolution_post_id="3",
        target_resolution_confidence="high",
    )
    assert allowed
    assert reason == "target_resolution"


def test_can_bind_target_post_rejects_resolution_mismatch() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    allowed, reason = can_bind_target_post(
        brief=brief,
        scope="global",
        post_id="721c63fe",
        post_data={"text": "Больше никаких переключений"},
        discovery_completed=False,
        seed_post_id=None,
        tier_a_post_id=None,
        l1_results=[],
        target_resolution_post_id="3",
        target_resolution_confidence="high",
    )
    assert not allowed
    assert reason == "target_resolution_mismatch"


def test_can_bind_target_post_blocks_l1_note_without_discovery() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    l1 = [{"node_type": NODE_NOTE_CHUNK, "post_id": "721c63fe", "note_id": "n1"}]
    allowed, reason = can_bind_target_post(
        brief=brief,
        scope="global",
        post_id="721c63fe",
        post_data={"text": "Больше никаких переключений"},
        discovery_completed=True,
        seed_post_id=None,
        tier_a_post_id=None,
        l1_results=l1,
    )
    assert not allowed
    assert reason == "l1_note_referent_mismatch"


def test_should_block_open_post_before_resolution() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    blocked, summary, code = should_block_post_scoped_tool(
        tool="OpenPost",
        post_id="721c63fe",
        brief=brief,
        scope="global",
        resolved_target_post_id=None,
        l1_results=[],
        target_resolution_post_id="3",
        target_resolution_confidence="high",
    )
    assert blocked
    assert "target resolution" in summary
    assert code == "binding_blocked"


def test_should_block_cross_post_open_note() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    blocked, summary, code = should_block_post_scoped_tool(
        tool="OpenNote",
        post_id="721c63fe",
        brief=brief,
        scope="global",
        resolved_target_post_id="3",
        l1_results=[],
    )
    assert blocked
    assert "cross_post=deny" in summary
    assert code == "binding_blocked"


def test_evaluate_plan_alignment_rejects_target_resolution_mismatch() -> None:
    from app.services.ai.rag_plan_alignment import evaluate_plan_alignment
    from app.services.ai.rag_retrieval_plan import RetrievalPlan

    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    plan = RetrievalPlan(
        goal="открыть welcome post",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe"},
                purpose="wrong post",
            )
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=[],
        scope="global",
        target_resolution_post_id="3",
        target_resolution_confidence="high",
    )
    assert not verdict.aligned
    assert verdict.reason == "target_resolution_mismatch"


def test_evaluate_plan_alignment_rejects_l1_note_media_in_plan() -> None:
    from app.services.ai.rag_plan_alignment import evaluate_plan_alignment
    from app.services.ai.rag_retrieval_plan import RetrievalPlan

    brief = build_retrieval_brief(
        user_text="Какое изображение подойдет мoемu приветственному постu?",
        scope="global",
    )
    l1 = [
        {
            "node_type": NODE_NOTE_CHUNK,
            "post_id": "721c63fe",
            "note_id": "ee175834",
            "chunk_text": "Варианты изображений",
            "similarity": 0.55,
        }
    ]
    plan = RetrievalPlan(
        goal="найти приветственный пост",
        steps=[
            RetrievalPlanStep(
                tool="SearchNodes",
                args={"query": "приветственный пост", "node_types": ["post_text"]},
                purpose="discovery",
            ),
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe"},
                purpose="wrong post from L1",
            ),
            RetrievalPlanStep(
                tool="OpenNote",
                args={
                    "note_id": "ee175834",
                    "post_id": "721c63fe",
                },
                purpose="note media",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=l1,
        scope="global",
    )
    assert not verdict.aligned
    assert verdict.reason == "l1_note_binding_only"
