"""Incremental extraction of the "answer" string from a partial JSON stream.

answer_node asks the model for `{"answer":"...","claims":[...]}` and streams
the raw tokens as they arrive. To show the user readable text mid-stream we
must pull just the value of the "answer" field out of whatever prefix of that
JSON has accumulated so far — without waiting for the closing brace (that's the
whole point of streaming) and without ever leaking raw JSON syntax like
`{"answer":"` into the chat.

Pure function over the accumulated raw string, so it's trivially testable and
has no I/O. The full, authoritative parse (answer + claims) still happens once
at the end via extract_json_object — this is only for the live preview.
"""

from __future__ import annotations

import json

# Unicode escapes (\uXXXX) are rare in model output and awkward to decode from a
# truncated stream (a split \u12 prefix). We decode the common two-char escapes
# and pass anything else through best-effort; the final extract_json_object pass
# is the source of truth, so a cosmetically imperfect mid-stream frame is fine.
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def extract_partial_answer(raw: str) -> str | None:
    """Return the decoded "answer" value present in `raw` so far, or None.

    None means the answer string hasn't started yet (no `"answer"` key, or no
    opening quote after it). Once the value has started, returns the decoded
    text up to whatever has streamed in — stopping cleanly at the closing quote
    if it's already arrived, or at the end of the buffer if not. A dangling
    backslash (an escape split across token boundaries) is dropped rather than
    guessed, so it simply appears on the next frame.
    """
    key_at = raw.find('"answer"')
    if key_at == -1:
        return None
    # Find the ':' then the opening quote of the value.
    colon = raw.find(":", key_at + len('"answer"'))
    if colon == -1:
        return None
    quote = raw.find('"', colon + 1)
    if quote == -1:
        return None

    out: list[str] = []
    i = quote + 1
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\":
            if i + 1 >= n:
                # Escape sequence split across the stream boundary — wait for more.
                break
            nxt = raw[i + 1]
            out.append(_SIMPLE_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            # Closing quote of the value — answer complete.
            break
        out.append(ch)
        i += 1
    return "".join(out)


def extract_complete_answer(raw: str) -> str | None:
    """Return the answer only when its JSON string is fully closed."""

    key_at = raw.find('"answer"')
    if key_at == -1:
        return None
    colon = raw.find(":", key_at + len('"answer"'))
    if colon == -1:
        return None
    quote = raw.find('"', colon + 1)
    if quote == -1:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(raw[quote:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, str) else None
