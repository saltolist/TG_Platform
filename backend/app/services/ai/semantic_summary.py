"""Semantic discovery cards for posts and notes.

Cards improve candidate selection but are never answer evidence. Generation is
best-effort and runs inside the existing asynchronous embedding worker.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.core.config import Settings
from app.db.models import User
from app.services.ai.orchestrator import resolve_orchestrator_llm
from app.services.ai.rag import build_discovery_summary

SUMMARY_SCHEMA_VERSION = 2
DISCOVERY_SUMMARY_VERSION = SUMMARY_SCHEMA_VERSION
SELECTOR_SUMMARY_VERSION = SUMMARY_SCHEMA_VERSION
DISCOVERY_SUMMARY_MAX_CHARS = 480
SELECTOR_SUMMARY_MAX_CHARS = 160

_SYSTEM = (
    "Создай две точные смысловые проекции одного документа за один вызов. "
    "discovery_summary (до 480 символов) предназначена для embeddings и discovery. "
    "selector_summary (до 160 символов) предназначена только для выбора контекста и "
    "сохраняет тему, назначение, ключевые сущности и существенные ограничения. "
    "Не додумывай факты и не давай советы. Пиши на языке документа, без markdown. "
    "Верни только JSON: {\"discovery_summary\":\"...\",\"selector_summary\":\"...\"}."
)


@dataclass(frozen=True)
class SemanticSummaryProjections:
    discovery_summary: str
    selector_summary: str
    model_key: str


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


def _clean_card(value: str, *, max_chars: int) -> str:
    card = str(value or "").strip()
    card = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", card, flags=re.IGNORECASE).strip()
    card = " ".join(card.split())
    if len(card) > max_chars:
        card = card[: max_chars - 1].rstrip() + "…"
    return card


def extractive_summary_projections(*, title: str, text_value: str) -> SemanticSummaryProjections:
    return SemanticSummaryProjections(
        discovery_summary=build_discovery_summary(
            title, text_value, max_chars=DISCOVERY_SUMMARY_MAX_CHARS
        ),
        selector_summary=build_discovery_summary(
            title, text_value, max_chars=SELECTOR_SUMMARY_MAX_CHARS
        ),
        model_key=f"extractive:v{SUMMARY_SCHEMA_VERSION}",
    )


def _parse_projection_response(raw: str) -> tuple[str, str] | None:
    value = str(raw or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    discovery = _clean_card(
        str(payload.get("discovery_summary") or ""), max_chars=DISCOVERY_SUMMARY_MAX_CHARS
    )
    selector = _clean_card(
        str(payload.get("selector_summary") or ""), max_chars=SELECTOR_SUMMARY_MAX_CHARS
    )
    if len(discovery) < 12 or len(selector) < 12:
        return None
    return discovery, selector


async def build_semantic_summary_projections(
    *,
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
    object_kind: str,
    title: str,
    text_value: str,
) -> SemanticSummaryProjections:
    fallback = extractive_summary_projections(title=title, text_value=text_value)
    model_key = semantic_summary_model_key(user, ai_profile, settings)
    resolved = (
        resolve_orchestrator_llm(user, ai_profile, settings)
        if settings.rag_semantic_summaries_enabled
        else None
    )
    if resolved is None:
        return fallback

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
                max_tokens=320,
            ),
            timeout=settings.rag_semantic_summary_timeout_seconds,
        )
    except Exception:
        return fallback
    parsed = _parse_projection_response(raw)
    if parsed is None:
        return fallback
    discovery, selector = parsed
    return SemanticSummaryProjections(discovery, selector, model_key)


async def build_semantic_discovery_card(
    *,
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
    object_kind: str,
    title: str,
    text_value: str,
) -> tuple[str, str]:
    projections = await build_semantic_summary_projections(
        user=user,
        ai_profile=ai_profile,
        settings=settings,
        object_kind=object_kind,
        title=title,
        text_value=text_value,
    )
    return projections.discovery_summary, projections.model_key


__all__ = [
    "DISCOVERY_SUMMARY_VERSION",
    "SELECTOR_SUMMARY_VERSION",
    "SemanticSummaryProjections",
    "build_semantic_discovery_card",
    "build_semantic_summary_projections",
    "extractive_summary_projections",
    "semantic_summary_model_key",
]
