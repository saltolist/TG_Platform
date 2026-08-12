"""L0 gate: rule-based skip for RAG retrieval (no embed, no vector search)."""

from __future__ import annotations

import re

_NON_SUBSTANTIVE_PHRASES = frozenset(
    {
        "привет",
        "здравствуй",
        "здравствуйте",
        "добрый день",
        "добрый вечер",
        "доброе утро",
        "спасибо",
        "благодарю",
        "спс",
        "ок",
        "окей",
        "хорошо",
        "понял",
        "поняла",
        "ясно",
        "супер",
        "класс",
        "круто",
        "договорились",
        "угу",
        "ага",
        "ладно",
        "да",
        "нет",
        "hi",
        "hello",
        "thanks",
        "thank you",
        "ok",
        "okay",
    }
)

_STYLE_EDIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bпокороч[еи]\b", re.IGNORECASE),
    re.compile(r"\bсократ[иь]\b", re.IGNORECASE),
    re.compile(r"\bперепиш[иь]\b", re.IGNORECASE),
    re.compile(r"\bпереформулиру[йь]\b", re.IGNORECASE),
    re.compile(r"\bсмени\b.*\bтон\b", re.IGNORECASE),
    re.compile(r"\bпоменя[йь]\b.*\bтон\b", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bтон\b", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bкороч[еи]\b", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bдлинн[еи]е\b", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bпроще\b", re.IGNORECASE),
    re.compile(r"\bдобавь\b.*\bэмодзи\b", re.IGNORECASE),
    re.compile(r"\bубери\b.*\bэмодзи\b", re.IGNORECASE),
    re.compile(r"\bисправь\b.*\bопечатк", re.IGNORECASE),
    re.compile(r"\bисправь\b.*\bорфограф", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bофициальн", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bнеформальн", re.IGNORECASE),
    re.compile(r"\bсделай\b.*\bделов", re.IGNORECASE),
    re.compile(r"\brewrite\b", re.IGNORECASE),
    re.compile(r"\bshorten\b", re.IGNORECASE),
    re.compile(r"\bmake\b.*\bshorter\b", re.IGNORECASE),
)

_MAX_NON_SUBSTANTIVE_WORDS = 4


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _is_non_substantive(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return True
    if "?" in text:
        return False
    words = normalized.split()
    if len(words) > _MAX_NON_SUBSTANTIVE_WORDS:
        return False
    if normalized in _NON_SUBSTANTIVE_PHRASES:
        return True
    # Single-word acknowledgements from the set, possibly with punctuation.
    stripped = re.sub(r"[^\w\s]", "", normalized)
    return stripped in _NON_SUBSTANTIVE_PHRASES


def _is_style_edit(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    # A real question alongside a style cue should still run RAG.
    if "?" in text:
        return False
    return any(pattern.search(normalized) for pattern in _STYLE_EDIT_PATTERNS)


def l0_skip_reason(user_text: str) -> str | None:
    """Return skip reason (``non_substantive`` | ``style_edit``) or None to run RAG."""
    if _is_non_substantive(user_text):
        return "non_substantive"
    if _is_style_edit(user_text):
        return "style_edit"
    return None


def should_skip_rag(user_text: str) -> bool:
    return l0_skip_reason(user_text) is not None
