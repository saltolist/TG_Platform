"""Tests for Tier A escalation signals and fast-paths."""

from __future__ import annotations

from app.services.ai.rag import NODE_ATTACHMENT_TEXT, NODE_NOTE_CHUNK, NODE_POST_TEXT
from app.services.ai.rag_escalation import (
    TierASignals,
    answer_type_mismatch,
    chunk_too_short,
    evaluate_tier_a,
    is_followup,
    pointer_phrase,
)


def _hit(
    *,
    similarity: float = 0.9,
    chunk_text: str = "Достаточно длинный текст чанка для проверки сигналов без ложного chunk_too_short.",
    referenced_ids: list[str] | None = None,
    node_type: str = NODE_NOTE_CHUNK,
    file_id: str = "",
) -> dict:
    return {
        "note_id": "n1",
        "similarity": similarity,
        "chunk_text": chunk_text,
        "referenced_ids": referenced_ids or [],
        "node_type": node_type,
        "file_id": file_id,
    }


def test_fast_path_miss_empty_results() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.fast_path == "miss"
    assert result.signals == TierASignals(False, False, False, False)


def test_fast_path_miss_low_similarity() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[_hit(similarity=0.5)],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.fast_path == "miss"


def test_fast_path_miss_suppressed_when_escalate_on_miss_false() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=False,
    )
    assert result.fast_path is None


def test_fast_path_known_ref_uncovered_attachment() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[_hit(referenced_ids=["a1"])],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.fast_path == "known_ref"
    assert result.escalate_target == "attachment:a1"


def test_fast_path_known_ref_skipped_when_attachment_in_results() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[
            _hit(referenced_ids=["a1"]),
            {
                "note_id": "n1",
                "similarity": 0.8,
                "chunk_text": "pdf text",
                "referenced_ids": [],
                "node_type": NODE_ATTACHMENT_TEXT,
                "file_id": "a1",
            },
        ],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.fast_path is None
    assert result.signals.pointer_phrase is False


def test_pointer_phrase_detected() -> None:
    assert pointer_phrase("Подробнее в файле отчёта")
    assert not pointer_phrase("Обычный текст без указателей")


def test_answer_type_mismatch_numeric() -> None:
    assert answer_type_mismatch("Сколько было просмотров?", "Короткий анонс без цифр")
    assert not answer_type_mismatch("Сколько было просмотров?", "Было 1200 просмотров")


def test_chunk_too_short() -> None:
    assert chunk_too_short("Коротко")
    assert not chunk_too_short("x" * 150)


def test_is_followup_requires_history() -> None:
    assert not is_followup("А на картинке?", None)
    assert is_followup(
        "А на картинке?",
        [
            {"role": "user", "text": "Расскажи про пост"},
            {"role": "ai", "text": "В посте есть график."},
        ],
    )


def test_neighbors_from_post_data() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[_hit()],
        post_data={
            "notes": [{"id": "n1", "title": "T"}],
            "media": [],
            "comments": [],
        },
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.neighbors["notes"] == [{"id": "n1", "title": "T"}]


def test_neighbors_empty_without_post_data() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[_hit()],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
    )
    assert result.neighbors == {}


def test_fast_path_cross_post_in_post_chat() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[
            {
                "note_id": "other",
                "post_id": "other",
                "similarity": 0.9,
                "chunk_text": "Текст другого поста достаточной длины для прохождения порога.",
                "referenced_ids": [],
                "node_type": NODE_POST_TEXT,
                "file_id": "",
                "scope": "global",
            }
        ],
        post_data={"id": "current"},
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
        chat_scope="post",
        chat_post_id="current",
    )
    assert result.fast_path == "cross_post"
    assert result.escalate_target == "post:other"


def test_cross_post_skips_own_post_with_uuid_alias() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[
            {
                "note_id": "119",
                "post_id": "119",
                "similarity": 0.9,
                "chunk_text": "Пост про пластиковые бутылки с достаточно длинным текстом для порога.",
                "referenced_ids": [],
                "node_type": NODE_POST_TEXT,
                "file_id": "",
                "scope": "global",
            }
        ],
        post_data={"id": "119"},
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
        chat_scope="post",
        chat_post_id="119",
        chat_post_id_aliases=frozenset(
            {"119", "d7ecd734-87f9-40a6-87c8-ef0957dcc56a"}
        ),
    )
    assert result.fast_path is None


def test_fast_path_post_note_in_global_chat() -> None:
    result = evaluate_tier_a(
        user_text="вопрос",
        history=None,
        results=[
            {
                "note_id": "note-1",
                "post_id": "119",
                "similarity": 0.9,
                "chunk_text": "Почему этот пост зашел. У поста отличная душевная составляющая.",
                "referenced_ids": [],
                "node_type": NODE_NOTE_CHUNK,
                "file_id": "",
                "scope": "post",
            }
        ],
        post_data=None,
        min_similarity_escalate=0.72,
        escalate_on_miss=True,
        chat_scope="global",
        chat_post_id=None,
    )
    assert result.fast_path == "post_note"
    assert result.escalate_target == "note:note-1"
    assert result.escalate_post_id == "119"
