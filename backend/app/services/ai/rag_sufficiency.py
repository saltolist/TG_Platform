"""Tier B LLM sufficiency check for agentic RAG escalation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_escalation import TierASignals
from app.services.ai.rag_json import extract_json_object

logger = logging.getLogger(__name__)

_CHUNK_MAX_CHARS = 1500

_TIER_B_SYSTEM = (
    "Ты оцениваешь, достаточно ли найденного фрагмента базы знаний для ответа на вопрос пользователя. "
    "Учитывай булевы сигналы эвристик и манифест непройденных соседних узлов (заметки, медиа, комментарии). "
    "Верни только JSON без пояснений: "
    '{"sufficient": true|false, "open_next": ["note:<id>", "media:<id>", "comments", ...]}. '
    "Если контекста достаточно — sufficient=true и open_next=[]. "
    "Если недостаточно — sufficient=false и перечисли в open_next узлы, которые стоит открыть дальше."
)

@dataclass(frozen=True)
class TierBResult:
    sufficient: bool
    open_next: list[str]
    error: str | None = None


def _fail_open(error: str) -> TierBResult:
    return TierBResult(sufficient=True, open_next=[], error=error)


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _parse_open_next(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def parse_tier_b_response(raw: str) -> TierBResult:
    """Parse LLM response into TierBResult; fail-open on any error."""
    text = (raw or "").strip()
    if not text:
        return _fail_open("no_json")

    payload = extract_json_object(text)
    if payload is None:
        return _fail_open("no_json")

    sufficient = _coerce_bool(payload.get("sufficient"))
    if sufficient is None:
        return _fail_open("missing_field")

    return TierBResult(
        sufficient=sufficient,
        open_next=_parse_open_next(payload.get("open_next")),
        error=None,
    )


def build_tier_b_messages(
    *,
    user_text: str,
    chunk_text: str,
    signals: TierASignals,
    neighbors: Mapping[str, Any],
) -> list[dict[str, str]]:
    chunk = (chunk_text or "").strip()
    if len(chunk) > _CHUNK_MAX_CHARS:
        chunk = chunk[:_CHUNK_MAX_CHARS]

    payload = {
        "question": user_text.strip(),
        "chunk": chunk,
        "signals": {
            "pointer_phrase": signals.pointer_phrase,
            "answer_type_mismatch": signals.answer_type_mismatch,
            "chunk_too_short": signals.chunk_too_short,
            "is_followup": signals.is_followup,
        },
        "neighbors": dict(neighbors),
    }
    return [
        {"role": "system", "content": _TIER_B_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def evaluate_tier_b(
    *,
    user_text: str,
    chunk_text: str,
    signals: TierASignals,
    neighbors: Mapping[str, Any],
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> TierBResult:
    from app.services.ai.llm import complete_chat_completion

    messages = build_tier_b_messages(
        user_text=user_text,
        chunk_text=chunk_text,
        signals=signals,
        neighbors=neighbors,
    )
    try:
        raw = await complete_chat_completion(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        )
    except Exception as exc:
        logger.warning("RAG Tier B LLM call failed: %s", exc)
        return _fail_open("call_failed")

    result = parse_tier_b_response(raw)
    if result.error:
        logger.warning("RAG Tier B parse failed (%s): %r", result.error, (raw or "")[:200])
    return result
