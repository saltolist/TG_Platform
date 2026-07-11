"""Tests for L2 plan alignment gate."""

from __future__ import annotations

from app.services.ai.rag import NODE_NOTE_CHUNK
from app.services.ai.rag_plan_alignment import evaluate_plan_alignment
from app.services.ai.rag_retrieval_brief import build_retrieval_brief
from app.services.ai.rag_retrieval_plan import RetrievalPlan, RetrievalPlanStep


def _welcome_query() -> str:
    return (
        "Как считаешь, какое изображение подойдет моему приветственному посту?"
    )


def _l1_note_only() -> list[dict]:
    return [
        {
            "node_type": NODE_NOTE_CHUNK,
            "post_id": "721c63fe-draft",
            "note_id": "n1",
            "chunk_text": "Варианты изображений для поста",
            "similarity": 0.55,
        }
    ]


def test_evaluate_plan_alignment_rejects_l1_note_binding_only() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=_l1_note_only(),
    )
    plan = RetrievalPlan(
        goal="подобрать изображение для приветственного поста",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe-draft"},
                purpose="из L1 note",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=_l1_note_only(),
        scope="global",
    )
    assert not verdict.aligned
    assert verdict.reason == "l1_note_binding_only"
    assert verdict.fix_hint is not None


def test_evaluate_plan_alignment_rejects_placeholder_ids() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=_l1_note_only(),
    )
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
                args={"post_id": "PLACEHOLDER_FROM_SEARCH_RESULT_0"},
                purpose="open",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=_l1_note_only(),
        scope="global",
    )
    assert not verdict.aligned
    assert verdict.reason == "invalid_plan_ids"


def test_evaluate_plan_alignment_rejects_off_target_discovery() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=_l1_note_only(),
    )
    plan = RetrievalPlan(
        goal="найти note с png",
        steps=[
            RetrievalPlanStep(
                tool="SearchNodes",
                args={"query": "png", "node_types": ["note_chunk"]},
                purpose="",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=_l1_note_only(),
        scope="global",
    )
    assert not verdict.aligned
    assert verdict.reason == "discovery_off_target"


def test_evaluate_plan_alignment_accepts_discovery_first() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=_l1_note_only(),
    )
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
                args={"post_id": "3"},
                purpose="открыть welcome",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=_l1_note_only(),
        scope="global",
    )
    assert verdict.aligned
    assert verdict.reason == "plan_aligned"


def test_evaluate_plan_alignment_accepts_post_scope_seed() -> None:
    brief = build_retrieval_brief(
        user_text="Какое изображение лучше?",
        scope="post",
        seed_post_id="post-1",
    )
    plan = RetrievalPlan(
        goal="сравнить картинки",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "post-1"},
                purpose="текущий пост",
            ),
            RetrievalPlanStep(
                tool="ListPostNotes",
                args={"post_id": "post-1"},
                purpose="заметки",
            ),
            RetrievalPlanStep(
                tool="ListNoteAttachments",
                args={"note_id": "n1", "post_id": "post-1"},
                purpose="вложения",
            ),
            RetrievalPlanStep(
                tool="HydrateAttachment",
                args={"ref": "attachment:img1", "mode": "vision"},
                purpose="vision",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=[],
        seed_post_id="post-1",
        scope="post",
    )
    assert verdict.aligned


def test_evaluate_plan_alignment_rejects_premature_hydrate() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=_l1_note_only(),
    )
    plan = RetrievalPlan(
        goal="сравнить изображения",
        steps=[
            RetrievalPlanStep(
                tool="HydrateAttachment",
                args={"ref": "attachment:img1", "mode": "vision"},
                purpose="vision",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=_l1_note_only(),
        scope="global",
    )
    assert not verdict.aligned
    assert verdict.reason == "premature_hydrate"


def test_evaluate_plan_alignment_rejects_list_notes_without_open_note() -> None:
    dialog = (
        "Пользователь: Как считаешь, какое изображение подойдет моему приветственному посту?"
    )
    brief = build_retrieval_brief(
        user_text="А для поста про больше никаких переключений?",
        scope="global",
        dialog_context=dialog,
    )
    plan = RetrievalPlan(
        goal="открыть пост и проверить заметки",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe-f7c6-4183-9a8d-da1979180467"},
                purpose="target post",
            ),
            RetrievalPlanStep(
                tool="ListPostNotes",
                args={"post_id": "721c63fe-f7c6-4183-9a8d-da1979180467"},
                purpose="список заметок",
            ),
            RetrievalPlanStep(
                tool="ListPostComments",
                args={"post_id": "721c63fe-f7c6-4183-9a8d-da1979180467"},
                purpose="комментарии",
            ),
        ],
    )
    verdict = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=[],
        scope="global",
        discovery_completed=True,
    )
    assert not verdict.aligned
    assert verdict.reason == "missing_note_open"
