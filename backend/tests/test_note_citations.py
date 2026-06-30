from app.services.ai.note_citations import (
    NoteCite,
    detach_note_citations,
    inject_missing_note_citations,
    normalize_note_citation_markdown,
    prepare_note_citations_for_reply,
    strip_invalid_note_citations,
)


def test_normalize_cite_path_metadata() -> None:
    text = "Ответ cite-path: /note/global/1/ cite-title: Работа\nдальше."
    assert normalize_note_citation_markdown(text) == "Ответ [Работа](/note/global/1/)\nдальше."


def test_detach_moves_inline_citation_to_paragraph_end() -> None:
    text = "В [Работа](/note/global/1/) заметке сказано."
    assert detach_note_citations(text) == "В заметке сказано. [Работа](/note/global/1/)"


def test_detach_moves_citations_from_multiple_sentences_to_paragraph_end() -> None:
    text = "В [A](/note/global/1/) первом. Во [B](/note/global/2/) втором."
    assert detach_note_citations(text) == (
        "В первом. Во втором. [A](/note/global/1/) [B](/note/global/2/)"
    )


def test_inject_missing_citation_when_title_mentioned() -> None:
    cites = [NoteCite(path="/note/global/1/", title="Работа")]
    text = "Нужно подготовить отчёт."
    assert inject_missing_note_citations(text, cites) == (
        "Нужно подготовить отчёт. [Работа](/note/global/1/)"
    )

    text = "Согласно заметке Работа, нужно сделать отчёт."
    assert inject_missing_note_citations(text, cites) == (
        "Согласно заметке Работа, нужно сделать отчёт. [Работа](/note/global/1/)"
    )


def test_prepare_note_citations_for_reply() -> None:
    cites = [NoteCite(path="/note/global/1/", title="Работа")]
    text = "В [Работа](/note/global/1/) тексте есть факты."
    assert prepare_note_citations_for_reply(text, cites) == (
        "В тексте есть факты. [Работа](/note/global/1/)"
    )


def test_strip_invalid_note_citations_removes_hallucinated_paths() -> None:
    cites = [NoteCite(path="/note/global/1/", title="Работа")]
    text = "Факт.[Работа](/note/global/1/) Выдумка.[Другое](/note/global/999/)"
    assert strip_invalid_note_citations(text, cites) == (
        "Факт.[Работа](/note/global/1/) Выдумка."
    )


def test_strip_invalid_note_citations_removes_all_when_no_context() -> None:
    text = "Текст.[Заметка](/note/global/1/)"
    assert strip_invalid_note_citations(text, []) == "Текст."


def test_prepare_note_citations_for_reply_strips_invalid_before_inject() -> None:
    cites = [NoteCite(path="/note/global/1/", title="Работа")]
    text = "Нужно сделать отчёт.[Фейк](/note/global/999/)"
    assert prepare_note_citations_for_reply(text, cites) == (
        "Нужно сделать отчёт. [Работа](/note/global/1/)"
    )
