"""Shared paragraph identities for model-guided semantic chunking."""

from __future__ import annotations

import re
from collections.abc import Sequence

_CODE_FENCE_RE = re.compile(r"(?:```|~~~)[\s\S]*?(?:```|~~~)", re.MULTILINE)
_PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n+")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_HORIZONTAL_RULE_RE = re.compile(
    r"^(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$"
)


def semantic_paragraphs(text: str) -> tuple[str, ...]:
    """Return stable raw paragraphs used by both the model and the indexer."""

    without_code = _CODE_FENCE_RE.sub("", str(text or ""))
    paragraphs = (
        paragraph.strip() for paragraph in _PARAGRAPH_BREAK_RE.split(without_code)
    )
    return tuple(
        paragraph
        for paragraph in paragraphs
        if paragraph and not _HORIZONTAL_RULE_RE.fullmatch(paragraph)
    )


def render_numbered_paragraphs(paragraphs: Sequence[str]) -> str:
    return "\n\n".join(
        f"[P{index}] {paragraph}" for index, paragraph in enumerate(paragraphs)
    )


def normalize_section_starts(
    values: Sequence[int],
    *,
    paragraph_count: int,
    limit: int = 12,
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                int(value)
                for value in values
                if type(value) is int and 0 < int(value) < paragraph_count
            }
        )[: max(0, int(limit))]
    )


def markdown_heading_starts(paragraphs: Sequence[str]) -> tuple[int, ...]:
    return tuple(
        index
        for index, paragraph in enumerate(paragraphs)
        if index > 0 and _MARKDOWN_HEADING_RE.match(str(paragraph or "").lstrip())
    )


def semantic_sections(
    paragraphs: Sequence[str],
    section_starts: Sequence[int],
) -> tuple[str, ...]:
    starts = (0, *normalize_section_starts(
        section_starts,
        paragraph_count=len(paragraphs),
        limit=max(0, len(paragraphs) - 1),
    ))
    ends = (*starts[1:], len(paragraphs))
    return tuple(
        "\n\n".join(str(item).strip() for item in paragraphs[start:end] if str(item).strip())
        for start, end in zip(starts, ends)
        if start < end
    )


__all__ = [
    "markdown_heading_starts",
    "normalize_section_starts",
    "render_numbered_paragraphs",
    "semantic_paragraphs",
    "semantic_sections",
]
