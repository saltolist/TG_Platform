"""Tests for deterministic L2 Stop-evaluator."""

from __future__ import annotations

from uuid import uuid4

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


def test_evaluate_stop_accepts_when_context_present() -> None:
    state = _state()
    blocks = [(NoteCite(path="/post/1/", title="Post"), "Контекст")]
    verdict = evaluate_stop("Расскажи про пост", state, blocks)
    assert verdict.allowed
    assert verdict.reason == "context_present"


def test_evaluate_stop_requires_comments_tool() -> None:
    state = _state()
    verdict = evaluate_stop("Что пишут в комментариях?", state, [])
    assert not verdict.allowed
    assert verdict.reason == "missing_list_post_comments"

    state.visited.add("post:p1:comments")
    verdict2 = evaluate_stop("Что пишут в комментариях?", state, [])
    assert verdict2.allowed
