from app.services.ai.web_citations import (
    prepare_web_citations_for_reply,
    strip_perplexity_numeric_citations,
)


def test_strip_perplexity_numeric_citations() -> None:
    text = "Ответ с источниками[1][2] и продолжением."
    assert strip_perplexity_numeric_citations(text) == "Ответ с источниками и продолжением."


def test_prepare_web_citations_for_reply_keeps_markers_when_cites_present() -> None:
    text = "Текст[3] конец."
    cites = [object()]
    assert prepare_web_citations_for_reply(text, cites) == text


def test_prepare_web_citations_for_reply_keeps_text_without_cites() -> None:
    text = "Текст[3] конец."
    assert prepare_web_citations_for_reply(text, []) == text
