"""Tests for L2 retrieval brief."""

from __future__ import annotations

from app.services.ai.rag import NODE_NOTE_CHUNK
from app.services.ai.rag_retrieval_brief import build_retrieval_brief


def _welcome_query() -> str:
    return (
        "Как считаешь, какое изображение подойдет моему приветственному посту?"
    )


def test_build_retrieval_brief_welcome_named_post_query() -> None:
    brief = build_retrieval_brief(
        user_text=_welcome_query(),
        scope="global",
        l1_results=[
            {
                "node_type": NODE_NOTE_CHUNK,
                "post_id": "721c63fe-draft",
                "note_id": "n1",
                "chunk_text": "Варианты изображений",
                "similarity": 0.55,
            }
        ],
    )
    assert brief.named_post_query is True
    assert brief.task == "comparative_visual"
    assert "post_text" in brief.evidence_needed
    assert "vision" in brief.evidence_needed
    assert "cross_post=deny" in brief.constraints
    assert any("named_post_query=true" in line for line in brief.ledger_lines)


def test_build_retrieval_brief_post_scope_sets_target() -> None:
    brief = build_retrieval_brief(
        user_text="Что написать в этом посте?",
        scope="post",
        seed_post_id="post-1",
    )
    assert brief.named_post_query is False
    assert "target_post_id=post-1" in brief.constraints


def test_build_retrieval_brief_visual_follow_up_from_dialog() -> None:
    dialog = (
        "Пользователь: Как считаешь, какое изображение подойдет моему приветственному посту?\n"
        "Ассистент: Для приветственного поста лучше подойдёт качественное фото…"
    )
    brief = build_retrieval_brief(
        user_text="А для поста про больше никаких переключений?",
        scope="global",
        dialog_context=dialog,
    )
    assert brief.task == "comparative_visual"
    assert "attachments" in brief.evidence_needed
    assert "vision" in brief.evidence_needed
    assert any("follow-up" in line for line in brief.ledger_lines)
