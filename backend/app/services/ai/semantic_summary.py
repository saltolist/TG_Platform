"""Semantic discovery cards for posts and notes.

Cards improve candidate selection but are never answer evidence. Generation is
best-effort and runs inside the existing asynchronous embedding worker.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

from app.core.config import Settings
from app.db.models import User
from app.services.ai.orchestrator import resolve_orchestrator_llm
from app.services.ai.rag import build_discovery_summary

DISCOVERY_SUMMARY_VERSION = 1
DISCOVERY_SUMMARY_MAX_CHARS = 480

_SYSTEM = (
    "Создай точную смысловую карточку документа для поиска. Одним абзацем опиши, "
    "о чём документ, его назначение, ключевые темы, сущности и ограничения. "
    "Не додумывай факты и не давай советы. Если текста недостаточно, прямо назови "
    "его коротким или служебным. Пиши на языке документа, без markdown и вводных фраз."
)


def semantic_summary_model_key(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
) -> str:
    if not settings.rag_semantic_summaries_enabled:
        return f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    resolved = resolve_orchestrator_llm(user, ai_profile, settings)
    if resolved is None:
        return f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    spec, model, _api_key = resolved
    return f"llm:{spec.name}:{model}:v{DISCOVERY_SUMMARY_VERSION}"


def _clean_card(value: str) -> str:
    card = str(value or "").strip()
    card = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", card, flags=re.IGNORECASE).strip()
    card = " ".join(card.split())
    if len(card) > DISCOVERY_SUMMARY_MAX_CHARS:
        card = card[: DISCOVERY_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return card


async def build_semantic_discovery_card(
    *,
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
    object_kind: str,
    title: str,
    text_value: str,
) -> tuple[str, str]:
    fallback = build_discovery_summary(
        title,
        text_value,
        max_chars=min(320, DISCOVERY_SUMMARY_MAX_CHARS),
    )
    model_key = semantic_summary_model_key(user, ai_profile, settings)
    resolved = (
        resolve_orchestrator_llm(user, ai_profile, settings)
        if settings.rag_semantic_summaries_enabled
        else None
    )
    if resolved is None:
        return fallback, model_key

    from app.services.ai.llm import complete_chat_completion

    spec, model, api_key = resolved
    source = str(text_value or "").strip()[: settings.rag_semantic_summary_input_chars]
    prompt = f"Тип: {object_kind}\nЗаголовок: {title or '(без заголовка)'}\nТекст:\n{source}"
    try:
        raw = await asyncio.wait_for(
            complete_chat_completion(
                spec=spec,
                model=model,
                api_key=api_key,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=220,
            ),
            timeout=settings.rag_semantic_summary_timeout_seconds,
        )
    except Exception:
        return fallback, f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    card = _clean_card(raw)
    if len(card) < 12:
        return fallback, f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    return card, model_key


__all__ = [
    "DISCOVERY_SUMMARY_VERSION",
    "build_semantic_discovery_card",
    "semantic_summary_model_key",
]
