"""Tests for deterministic L2 Stop-evaluator."""

from __future__ import annotations

from uuid import uuid4

from app.core.config import Settings
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_stop_evaluator import evaluate_stop
from app.services.ai.rag_tools import AgentState


def _state() -> AgentState:
    return AgentState(
        session=None,  # type: ignore[arg-type]
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        embedding_backend=None,  # type: ignore[arg-type]
    )


def _comparative_query() -> str:
    return (
        "Как считаешь, какое изображение подойдет моему посту про "
        "больше никаких переключений между сервисами?"
    )


def test_evaluate_stop_comparative_visual_rejects_partial_hydrate() -> None:
    state = _state()
    state.settings = Settings(rag_agent_max_vision=2)
    state.listed_image_attachment_refs = [
        "attachment:img1",
        "attachment:img2",
    ]
    state.visited.add("hydrate:vision:attachment:img1")
    verdict = evaluate_stop(_comparative_query(), state, [])
    assert not verdict.allowed
    assert verdict.reason == "missing_hydrate_attachment"


def test_evaluate_stop_comparative_visual_accepts_all_listed_hydrated() -> None:
    state = _state()
    state.settings = Settings(rag_agent_max_vision=2)
    state.listed_image_attachment_refs = [
        "attachment:img1",
        "attachment:img2",
    ]
    state.visited.add("hydrate:vision:attachment:img1")
    state.visited.add("hydrate:vision:attachment:img2")
    verdict = evaluate_stop(_comparative_query(), state, [])
    assert verdict.allowed
    assert verdict.reason == "attachments_hydrated"


def test_evaluate_stop_comparative_visual_accepts_single_listed_hydrated() -> None:
    state = _state()
    state.settings = Settings(rag_agent_max_vision=2)
    state.listed_image_attachment_refs = ["attachment:img1"]
    state.visited.add("hydrate:vision:attachment:img1")
    verdict = evaluate_stop(_comparative_query(), state, [])
    assert verdict.allowed
    assert verdict.reason == "attachments_hydrated"


def test_evaluate_stop_non_comparative_visual_accepts_one_hydrate() -> None:
    state = _state()
    state.listed_image_attachment_refs = [
        "attachment:img1",
        "attachment:img2",
    ]
    state.visited.add("hydrate:vision:attachment:img1")
    verdict = evaluate_stop("Что изображено на скриншоте?", state, [])
    assert verdict.allowed
    assert verdict.reason == "attachment_hydrated"


def test_evaluate_stop_rejects_why_question_without_note() -> None:
    state = _state()
    verdict = evaluate_stop(
        "Почему зашел мой пост про бутылки?",
        state,
        [],
    )
    assert not verdict.allowed
    assert verdict.reason == "missing_note_for_why_question"


def test_evaluate_stop_accepts_why_question_after_note_opened() -> None:
    state = _state()
    state.visited.add("note:n1")
    verdict = evaluate_stop(
        "Почему зашел мой пост про бутылки?",
        state,
        [],
    )
    assert verdict.allowed


def test_evaluate_stop_accepts_when_post_context_present() -> None:
    state = _state()
    blocks = [(NoteCite(path="/post/1/", title="Post"), "Контекст поста")]
    verdict = evaluate_stop("Расскажи про пост", state, blocks, scope="global")
    assert verdict.allowed
    assert verdict.reason == "post_opened"


def test_evaluate_stop_requires_post_for_post_query_in_global() -> None:
    state = _state()
    blocks = [(NoteCite(path="/note/global/n1/", title="N"), "Только заметка")]
    verdict = evaluate_stop(
        "Хочу подготовить серию постов заранее",
        state,
        blocks,
        scope="global",
    )
    assert not verdict.allowed
    assert verdict.reason == "missing_open_post"


def test_evaluate_stop_accepts_post_query_after_open_post() -> None:
    state = _state()
    state.visited.add("post:3")
    blocks = [(NoteCite(path="/post/3/", title="Welcome"), "Текст поста")]
    verdict = evaluate_stop(
        "Хочу подготовить серию постов заранее",
        state,
        blocks,
        scope="global",
    )
    assert verdict.allowed
    assert verdict.reason == "post_opened"


def test_evaluate_stop_requires_target_binding_for_named_post_query() -> None:
    from app.services.ai.rag_retrieval_brief import build_retrieval_brief

    state = _state()
    query = "Расскажи про мой приветственный пост"
    state.retrieval_brief = build_retrieval_brief(user_text=query, scope="global")
    state.visited.add("post:721c63fe")
    blocks = [(NoteCite(path="/post/721c63fe/", title="Draft"), "Черновик")]
    verdict = evaluate_stop(query, state, blocks, scope="global")
    assert not verdict.allowed
    assert verdict.reason == "missing_target_post_binding"


def test_evaluate_stop_accepts_named_post_query_with_target_binding() -> None:
    from app.services.ai.rag_retrieval_brief import build_retrieval_brief

    state = _state()
    query = "Расскажи про мой приветственный пост"
    state.retrieval_brief = build_retrieval_brief(user_text=query, scope="global")
    state.resolved_target_post_id = "3"
    state.visited.add("post:3")
    blocks = [(NoteCite(path="/post/3/", title="Welcome"), "Приветствую")]
    verdict = evaluate_stop(query, state, blocks, scope="global")
    assert verdict.allowed
    assert verdict.reason == "target_post_bound"


def test_evaluate_stop_rejects_visual_follow_up_without_open_note() -> None:
    from app.services.ai.rag_retrieval_brief import build_retrieval_brief

    state = _state()
    dialog = "Пользователь: Какое изображение подойдет моему приветственному посту?"
    query = "А для поста про больше никаких переключений?"
    state.retrieval_brief = build_retrieval_brief(
        user_text=query,
        scope="global",
        dialog_context=dialog,
    )
    state.resolved_target_post_id = "721c63fe-f7c6-4183-9a8d-da1979180467"
    state.visited.add("post:721c63fe-f7c6-4183-9a8d-da1979180467")
    state.visited.add("post:721c63fe-f7c6-4183-9a8d-da1979180467:notes")
    blocks = [
        (
            NoteCite(path="/post/721c63fe-f7c6-4183-9a8d-da1979180467/", title="Post"),
            "Текст поста",
        )
    ]
    verdict = evaluate_stop(query, state, blocks, scope="global")
    assert not verdict.allowed
    assert verdict.reason == "missing_open_note"


def test_evaluate_stop_accepts_evidence_gap_on_target() -> None:
    from app.services.ai.rag_retrieval_brief import build_retrieval_brief

    state = _state()
    query = "Какое изображение подойдет моему приветственному посту?"
    state.retrieval_brief = build_retrieval_brief(user_text=query, scope="global")
    state.resolved_target_post_id = "3"
    state.target_evidence_gap = "no_notes_on_target"
    state.visited.add("post:3")
    state.visited.add("post:3:notes")
    blocks = [(NoteCite(path="/post/3/", title="Приветствую 👋"), "Текст поста")]
    verdict = evaluate_stop(query, state, blocks, scope="global")
    assert verdict.allowed
    assert verdict.reason == "evidence_gap_on_target"


def test_evaluate_stop_requires_comments_tool() -> None:
    state = _state()
    verdict = evaluate_stop("Что пишут в комментариях?", state, [])
    assert not verdict.allowed
    assert verdict.reason == "missing_list_post_comments"

    state.visited.add("post:p1:comments")
    verdict2 = evaluate_stop("Что пишут в комментариях?", state, [])
    assert verdict2.allowed
