from __future__ import annotations

from types import SimpleNamespace

from app.services.agent.runtime.result_quality import validate_result_contract
from app.services.agent.runtime.turn_contract import build_turn_contract


def test_this_post_resolves_to_post_four_from_previous_answer() -> None:
    history = [
        {"role": "user", "text": "А потом?"},
        {
            "role": "ai",
            "text": (
                'После поста 3 логично продолжить серию постом 4 — '
                '"Двусторонняя связь: всё синхронизируется само", который '
                "рассказывает о синхронизации. Затем будут посты 5 и 6."
            ),
        },
    ]
    contract = build_turn_contract(
        user_text="Какое-нибудь из изображений подойдет этому посту?",
        history=history,
        scope="global",
    )

    assert contract["target"]["kind"] == "dialog_artifact"
    assert contract["target"]["label"].startswith("Пост 4 — Двусторонняя связь")
    assert "Пост 4" in contract["search_query"]
    assert contract["target_contract"]["target_mode"] == "exact"
    assert contract["target_contract"]["ambiguities"] == []
    assert contract["target_contract"]["targets"][0]["source_user_text"] == "А потом?"


def test_post_anaphora_prefers_linked_assistant_artifact_over_workspace_entities() -> None:
    answer = (
        "Следующий пост стоит написать про то, как AI-менеджер ходит по пространству "
        "контента. Это продолжит пост 6, но глубже раскроет механику каскадного поиска."
    )
    ledger = (
        SimpleNamespace(
            turn_id="turn-1",
            user_text="Про что написать следующий пост?",
            entities=(
                SimpleNamespace(entity_type="post", post_id="p1", title="Первый"),
                SimpleNamespace(entity_type="post", post_id="p2", title="Второй"),
                SimpleNamespace(entity_type="note", note_id="n1", title="Серия"),
                SimpleNamespace(entity_type="assistant_artifact", content=answer),
            ),
            turn_contract=None,
        ),
    )

    contract = build_turn_contract(
        user_text="Напиши мне текст этого поста",
        history=[
            {"role": "user", "text": "Про что написать следующий пост?"},
            {"role": "ai", "text": answer},
        ],
        scope="global",
        dialog_ledger=ledger,
    )

    target = contract["target_contract"]
    assert target["target_mode"] == "exact"
    assert target["ambiguities"] == []
    assert len(target["targets"]) == 1
    assert target["targets"][0]["kind"] == "dialog_artifact"
    assert target["targets"][0]["role"] == "subject"
    assert target["targets"][0]["content"] == answer
    assert target["targets"][0]["source_turn_id"] == "turn-1"
    assert target["targets"][0]["source_user_text"] == "Про что написать следующий пост?"
    assert contract["target"]["label"] == "рекомендованный следующий пост"


def test_existing_posts_fix_corpus_to_feed_not_series_note() -> None:
    contract = build_turn_contract(
        user_text="Не пересекается ли он с имеющимися постами?",
        history=[{"role": "ai", "text": "Пост 3. AI, который знает ваш канал"}],
        scope="global",
    )

    assert contract["intent"] == "compare_with_feed_posts"
    assert contract["corpus"] == "feed_posts"
    assert contract["required_evidence_kinds"] == ["post_text"]
    assert contract["max_steps"] == 4


def test_style_request_preserves_full_working_artifact_and_layout() -> None:
    draft = "Пост 3\n\n" + ("Большой абзац с содержанием. " * 30) + "\n\nИтоговый абзац."
    history = [
        {"role": "ai", "text": draft},
        {"role": "user", "text": "Не пересекается ли он?"},
        {"role": "ai", "text": "С опубликованными постами не пересекается."},
    ]
    contract = build_turn_contract(
        user_text=(
            "Напиши текст этого поста в их стиле, именно в их верстке "
            "с разбитием абзацев и заголовками тем"
        ),
        history=history,
        scope="global",
    )

    assert contract["corpus"] == "feed_posts"
    assert contract["output"]["working_artifact"] == draft
    assert contract["output"]["min_chars"] >= int(len(draft) * 0.89)
    assert contract["output"]["require_section_headings"] is True


def test_recent_created_note_is_authoritative_exact_target() -> None:
    contract = build_turn_contract(
        user_text="Посмотри на эту заметку и скажи, что делать дальше",
        history=[
            {"role": "user", "text": "Я создал заметку по этой теме"},
            {"role": "ai", "text": "Хорошо."},
        ],
        scope="global",
        recent_note={
            "id": "new-note",
            "title": "Интерактивная пространственная система\nИнтерактивная пространственная система",
            "created_at": "2026-07-17T23:50:42+00:00",
        },
    )

    assert contract["corpus"] == "exact_note"
    assert contract["target"] == {
        "kind": "recent_note",
        "id": "new-note",
        "title": "Интерактивная пространственная система",
        "created_at": "2026-07-17T23:50:42+00:00",
        "authoritative": True,
    }
    assert contract["requires_workspace"] is True


def test_every_corpus_turn_discovers_notes_and_posts_without_request_markers() -> None:
    contract = build_turn_contract(
        user_text="Идти тестировать?",
        history=[],
        scope="global",
    )

    assert contract["task_profile"] == "topical_answer"
    assert contract["requires_workspace"] is True
    assert contract["execution_mode"] == "compact"
    assert {
        (source["kind"], source["required"])
        for source in contract["source_requirements"]
    } == {("notes", False), ("posts", False)}
    assert contract["answerability_without_evidence"] is True


def test_current_message_creation_targets_latest_note_immediately() -> None:
    contract = build_turn_contract(
        user_text="Я создал заметку по этой теме. Что дальше?",
        history=[],
        scope="global",
        recent_note={
            "id": "new-note",
            "title": "Интерактивная пространственная система",
            "created_at": "2026-07-17T23:50:42+00:00",
        },
    )

    assert contract["corpus"] == "exact_note"
    assert contract["target"]["id"] == "new-note"


def test_post_draft_result_validator_rejects_short_unstructured_text() -> None:
    contract = {
        "output": {
            "kind": "post_draft",
            "min_chars": 500,
            "min_paragraphs": 5,
            "min_section_headings": 2,
        }
    }
    issues = validate_result_contract("Короткий ответ без структуры.", contract)

    assert any(issue.startswith("text_too_short") for issue in issues)
    assert any(issue.startswith("too_few_paragraphs") for issue in issues)
    assert any(issue.startswith("too_few_headings") for issue in issues)


def test_referential_note_uses_durable_ledger_before_semantic_search() -> None:
    ledger = (
        SimpleNamespace(
            entities=(
                SimpleNamespace(
                    entity_type="note",
                    note_id="discussed-note",
                    title="Обсуждаемая заметка",
                ),
            )
        ),
    )
    contract = build_turn_contract(
        user_text="Какой еще пример там есть в этой заметке?",
        history=[],
        scope="global",
        recent_note={"id": "newer-unrelated-note", "title": "Другая"},
        dialog_ledger=ledger,
    )

    assert contract["corpus"] == "exact_note"
    assert contract["target"]["kind"] == "ledger_note"
    assert contract["target"]["id"] == "discussed-note"


def test_full_post_draft_falls_back_to_durable_ledger() -> None:
    draft = "Заголовок\n\n" + ("Полный текст предложения. " * 30) + "\n\nИтог."
    ledger = (
        SimpleNamespace(
            entities=(
                SimpleNamespace(
                    entity_type="post_draft",
                    content=draft,
                ),
            )
        ),
    )
    contract = build_turn_contract(
        user_text="Напиши этот пост именно в стиле моих постов",
        history=[{"role": "ai", "text": "Обрезанный фрагмент"}],
        scope="global",
        dialog_ledger=ledger,
    )

    assert contract["output"]["working_artifact"] == draft
    assert contract["output"]["min_chars"] >= int(len(draft) * 0.89)
    assert contract["output"]["match_sentence_length"] is True


def test_post_referent_uses_full_draft_before_short_comparison_answer() -> None:
    draft = "Пост 3. Полный черновик\n\n" + ("Большой абзац. " * 40) + "\n\nИтог."
    contract = build_turn_contract(
        user_text="Напиши текст этого поста в их стиле",
        history=[
            {"role": "ai", "text": draft},
            {"role": "user", "text": "Он пересекается с постами в ленте?"},
            {"role": "ai", "text": "Нет, не пересекается."},
        ],
        scope="global",
    )

    assert contract["target"]["content"] == draft


def test_inflected_note_title_keeps_referent_without_ledger() -> None:
    contract = build_turn_contract(
        user_text="Какой еще пример помимо тг там есть?",
        history=[
            {
                "role": "user",
                "text": "Расскажи про заметку с интерактивной пространственной системой",
            },
            {"role": "ai", "text": "В заметке есть несколько примеров."},
        ],
        scope="global",
        recent_note={
            "id": "spatial-note",
            "title": "Интерактивная пространственная система",
            "created_at": "2026-07-17T23:50:42+00:00",
        },
    )

    assert contract["corpus"] == "exact_note"
    assert contract["target"]["id"] == "spatial-note"


def test_result_validator_rejects_mismatched_sentence_length() -> None:
    contract = {
        "output": {
            "kind": "post_draft",
            "match_sentence_length": True,
        }
    }
    profile = {
        "target_sentence_chars": 80,
        "reference_sentence_count": 12,
    }
    text = "Раз два три. Четыре пять шесть. Семь восемь девять."

    issues = validate_result_contract(text, contract, style_profile=profile)

    assert any(issue.startswith("sentence_length_mismatch") for issue in issues)
