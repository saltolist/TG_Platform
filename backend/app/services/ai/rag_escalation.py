"""Tier A escalation signals and fast-paths (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.ai.rag import NODE_ATTACHMENT_TEXT, NODE_MEDIA_META
from app.services.ai.rag_manifest import build_post_manifest

_POINTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bсм\.?\b", re.IGNORECASE),
    re.compile(r"подробнее\s+в", re.IGNORECASE),
    re.compile(r"результат[ыа]?\s+в\s+файл", re.IGNORECASE),
    re.compile(r"полн(ая|ую)\s+таблиц", re.IGNORECASE),
    re.compile(r"таблиц[аеу]\s+—\s+в\s+заметк", re.IGNORECASE),
    re.compile(r"полностью\s+в", re.IGNORECASE),
)

_NUMERIC_QUERY_MARKERS = (
    "сколько",
    "процент",
    "цифр",
    "числ",
    "объём",
    "объем",
    "выручк",
    "доход",
)

_VISUAL_QUERY_MARKERS = (
    "покажи",
    "график",
    "скриншот",
    "картинк",
    "изображен",
    "фото",
)

_COMMENTS_QUERY_MARKERS = (
    "что пишут",
    "комментари",
    "отзыв",
    "реакци",
)

_VISUAL_CHUNK_MARKERS = (
    "jpg",
    "jpeg",
    "png",
    "webp",
    "gif",
    "скрин",
    "график",
    "картин",
    "изображ",
    "фото",
)

_FOLLOWUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bа\s+на\s+картинк", re.IGNORECASE),
    re.compile(r"\bа\s+во\s+втор", re.IGNORECASE),
    re.compile(r"\bа\s+в\s+файл", re.IGNORECASE),
    re.compile(r"\bа\s+там\b", re.IGNORECASE),
    re.compile(r"\bа\s+в\s+вложен", re.IGNORECASE),
)

_CHUNK_TOO_SHORT_FLOOR = 120


@dataclass(frozen=True)
class TierASignals:
    pointer_phrase: bool
    answer_type_mismatch: bool
    chunk_too_short: bool
    is_followup: bool


@dataclass(frozen=True)
class TierAResult:
    fast_path: str | None
    escalate_target: str | None
    signals: TierASignals
    neighbors: dict[str, Any]


def _empty_signals() -> TierASignals:
    return TierASignals(
        pointer_phrase=False,
        answer_type_mismatch=False,
        chunk_too_short=False,
        is_followup=False,
    )


def pointer_phrase(chunk_text: str) -> bool:
    text = (chunk_text or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _POINTER_PATTERNS)


def _chunk_has_digits(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _chunk_mentions_visual(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _VISUAL_CHUNK_MARKERS)


def _chunk_mentions_comments(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _COMMENTS_QUERY_MARKERS)


def answer_type_mismatch(user_text: str, chunk_text: str) -> bool:
    query = (user_text or "").lower()
    chunk = (chunk_text or "").strip()
    if not query or not chunk:
        return False

    if any(marker in query for marker in _NUMERIC_QUERY_MARKERS):
        return not _chunk_has_digits(chunk)
    if any(marker in query for marker in _VISUAL_QUERY_MARKERS):
        return not _chunk_mentions_visual(chunk)
    if any(marker in query for marker in _COMMENTS_QUERY_MARKERS):
        return not _chunk_mentions_comments(chunk)
    return False


def chunk_too_short(chunk_text: str, *, floor: int = _CHUNK_TOO_SHORT_FLOOR) -> bool:
    return len((chunk_text or "").strip()) < floor


def is_followup(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
) -> bool:
    from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm

    text = (user_text or "").strip()
    if not text:
        return False
    if not any(pattern.search(text) for pattern in _FOLLOWUP_PATTERNS):
        return False
    pairs = filter_alternating_roles(linearize_for_llm(history or []))
    return any(role == "assistant" and content.strip() for role, content in pairs)


def _covered_file_ids(results: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for item in results:
        node_type = item.get("node_type") or ""
        file_id = str(item.get("file_id") or "").strip()
        if not file_id:
            continue
        if node_type in (NODE_ATTACHMENT_TEXT, NODE_MEDIA_META):
            covered.add(file_id)
    return covered


def _known_ref_fast_path(
    top: dict[str, Any],
    results: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    referenced = top.get("referenced_ids") or []
    if not referenced:
        return None, None
    covered = _covered_file_ids(results)
    for ref_id in referenced:
        ref = str(ref_id).strip()
        if ref and ref not in covered:
            return "known_ref", f"attachment:{ref}"
    return None, None


def evaluate_tier_a(
    *,
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    results: list[dict[str, Any]],
    post_data: Mapping[str, Any] | None,
    min_similarity_escalate: float,
    escalate_on_miss: bool,
) -> TierAResult:
    neighbors = build_post_manifest(post_data) if post_data else {}

    if not results:
        fast_path = "miss" if escalate_on_miss else None
        return TierAResult(
            fast_path=fast_path,
            escalate_target=None,
            signals=_empty_signals(),
            neighbors=neighbors,
        )

    top = results[0]
    top_similarity = float(top.get("similarity") or 0.0)
    if top_similarity < min_similarity_escalate:
        fast_path = "miss" if escalate_on_miss else None
        return TierAResult(
            fast_path=fast_path,
            escalate_target=None,
            signals=_empty_signals(),
            neighbors=neighbors,
        )

    known_ref_path, known_ref_target = _known_ref_fast_path(top, results)
    if known_ref_path:
        return TierAResult(
            fast_path=known_ref_path,
            escalate_target=known_ref_target,
            signals=_empty_signals(),
            neighbors=neighbors,
        )

    chunk_text_value = str(top.get("chunk_text") or "")
    signals = TierASignals(
        pointer_phrase=pointer_phrase(chunk_text_value),
        answer_type_mismatch=answer_type_mismatch(user_text, chunk_text_value),
        chunk_too_short=chunk_too_short(chunk_text_value),
        is_followup=is_followup(user_text, history),
    )
    return TierAResult(
        fast_path=None,
        escalate_target=None,
        signals=signals,
        neighbors=neighbors,
    )
