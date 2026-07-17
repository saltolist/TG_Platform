"""Unit tests for the incremental "answer" extractor used by answer_node's
streaming path (workspace_graph.py). Pure function, no I/O."""

from app.services.agent.runtime.answer_stream import extract_partial_answer


def test_returns_none_before_answer_key():
    assert extract_partial_answer("") is None
    assert extract_partial_answer('{"clai') is None
    assert extract_partial_answer('{"answer"') is None  # key but no colon/quote yet


def test_returns_empty_string_at_opening_quote():
    assert extract_partial_answer('{"answer":"') == ""


def test_streams_partial_value_before_closing_quote():
    assert extract_partial_answer('{"answer":"Срок — ию') == "Срок — ию"


def test_stops_at_closing_quote_ignoring_trailing_json():
    raw = '{"answer":"Срок — июль.","claims":[]}'
    assert extract_partial_answer(raw) == "Срок — июль."


def test_decodes_escaped_quote_and_newline():
    assert extract_partial_answer('{"answer":"он сказал \\"да\\"') == 'он сказал "да"'
    assert extract_partial_answer('{"answer":"строка1\\nстрока2') == "строка1\nстрока2"


def test_drops_dangling_backslash_split_across_tokens():
    # A '\' at the very end is an escape whose second char hasn't streamed yet;
    # it must not be emitted as a literal backslash — wait for the next frame.
    assert extract_partial_answer('{"answer":"готово\\') == "готово"
    # Next frame completes the escape.
    assert extract_partial_answer('{"answer":"готово\\n') == "готово\n"


def test_handles_whitespace_between_key_and_value():
    assert extract_partial_answer('{ "answer" : "hi') == "hi"
