"""Normalize web citation markers in assistant replies (Perplexity sonar numeric refs)."""

from __future__ import annotations

import re

# Perplexity sonar inline refs: [1], [2], [12]
PERPLEXITY_NUMERIC_CITE_RE = re.compile(r"\[\d+\]")


def strip_perplexity_numeric_citations(text: str) -> str:
    """Remove Perplexity-style numeric citation markers from reply text."""
    out = PERPLEXITY_NUMERIC_CITE_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out


def prepare_web_citations_for_reply(text: str, cites: list[object]) -> str:
    """Keep Perplexity numeric markers in text; the client renders them as inline chips."""
    return text
