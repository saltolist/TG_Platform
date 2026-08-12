"""Deterministic checks for user-visible result requirements."""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Mapping


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def _is_heading(value: str) -> bool:
    return 2 <= len(value) <= 90 and not value.endswith((".", "?", "!", ",", ";"))


def _heading_count(text: str) -> int:
    paragraphs = _paragraphs(text)
    count = 0
    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0].strip()
        if _is_heading(first_line):
            count += 1
    return count


def _sentence_lengths(text: str) -> list[int]:
    lengths: list[int] = []
    for paragraph in _paragraphs(text):
        lines = paragraph.splitlines()
        if lines and _is_heading(lines[0].strip()):
            lines = lines[1:]
        body = " ".join(line.strip() for line in lines if line.strip())
        lengths.extend(
            len(sentence.strip())
            for sentence in re.split(r"(?<=[.!?])\s+", body)
            if len(re.findall(r"[\w-]+", sentence)) >= 3
        )
    return lengths


def build_style_profile(
    records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    texts = [
        str(record.get("content") or "").strip()
        for record in records.values()
        if str(record.get("kind") or "") == "post_text" and str(record.get("content") or "").strip()
    ]
    if not texts:
        return {}
    lengths = [len(text) for text in texts]
    paragraph_counts = [len(_paragraphs(text)) for text in texts]
    heading_counts = [_heading_count(text) for text in texts]
    sentence_lengths = [length for text in texts for length in _sentence_lengths(text)]
    return {
        "reference_count": len(texts),
        "target_chars": int(median(lengths)),
        "target_paragraphs": int(median(paragraph_counts)),
        "target_headings": int(median(heading_counts)),
        "target_sentence_chars": int(median(sentence_lengths)) if sentence_lengths else 0,
        "reference_sentence_count": len(sentence_lengths),
    }


def validate_result_contract(
    text: str,
    contract: Mapping[str, Any] | None,
    *,
    style_profile: Mapping[str, Any] | None = None,
) -> list[str]:
    output = dict((contract or {}).get("output") or {})
    if output.get("kind") != "post_draft":
        return []
    profile = dict(style_profile or {})
    issues: list[str] = []
    min_chars = int(output.get("min_chars") or 0)
    if output.get("match_reference_style") and profile.get("target_chars"):
        min_chars = max(min_chars, int(int(profile["target_chars"]) * 0.75))
    if min_chars and len(text.strip()) < min_chars:
        issues.append(f"text_too_short:{len(text.strip())}<{min_chars}")

    paragraphs = len(_paragraphs(text))
    min_paragraphs = int(output.get("min_paragraphs") or 0)
    if output.get("match_reference_style") and profile.get("target_paragraphs"):
        min_paragraphs = max(min_paragraphs, int(int(profile["target_paragraphs"]) * 0.75))
    if min_paragraphs and paragraphs < min_paragraphs:
        issues.append(f"too_few_paragraphs:{paragraphs}<{min_paragraphs}")

    headings = _heading_count(text)
    min_headings = int(output.get("min_section_headings") or 0)
    if output.get("match_reference_style") and profile.get("target_headings"):
        min_headings = max(min_headings, min(3, int(profile["target_headings"])))
    if min_headings and headings < min_headings:
        issues.append(f"too_few_headings:{headings}<{min_headings}")

    target_sentence_chars = int(profile.get("target_sentence_chars") or 0)
    generated_sentence_lengths = _sentence_lengths(text)
    if (
        output.get("match_sentence_length")
        and target_sentence_chars >= 10
        and int(profile.get("reference_sentence_count") or 0) >= 3
        and len(generated_sentence_lengths) >= 3
    ):
        actual_sentence_chars = int(median(generated_sentence_lengths))
        lower = max(8, int(target_sentence_chars * 0.65))
        upper = max(lower + 1, int(target_sentence_chars * 1.45))
        if actual_sentence_chars < lower or actual_sentence_chars > upper:
            issues.append(
                "sentence_length_mismatch:"
                f"{actual_sentence_chars} not in [{lower},{upper}]"
            )
    return issues
