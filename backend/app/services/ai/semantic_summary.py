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
from app.services.ai.orchestrator import resolve_answer_llm, resolve_orchestrator_llm
from app.services.ai.providers import (
    ChatCompletionCapability,
    negotiate_chat_completion_capability,
)
from app.services.ai.rag import build_discovery_summary

SUMMARY_SCHEMA_VERSION = 2
DISCOVERY_SUMMARY_VERSION = SUMMARY_SCHEMA_VERSION
SELECTOR_SUMMARY_VERSION = 9
DISCOVERY_SUMMARY_MAX_CHARS = 480
SELECTOR_SUMMARY_MAX_CHARS = 160
SELECTOR_SUMMARY_TARGET_MAX_CHARS = 150
SEMANTIC_SUMMARY_GENERATION_ATTEMPTS = 3

_SUMMARY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["discovery_summary", "selector_summary"],
    "properties": {
        "discovery_summary": {
            "type": "string",
            "minLength": 12,
        },
        "selector_summary": {
            "type": "string",
            "minLength": 12,
        },
    },
}

_SYSTEM = (
    "Создай две точные смысловые проекции одного документа за один вызов. "
    "discovery_summary предназначена для embeddings и discovery: одно-два коротких "
    "предложения, жестко не более 360 Unicode-символов. "
    "selector_summary предназначена только для выбора контекста: ровно одно плотное "
    "законченное предложение, жестко не более 150 Unicode-символов. Она "
    "должна быть готовой самодостаточной карточкой, а не началом или обрезком текста. "
    "В ней приоритетны конкретные определения, классификации, перечисления, имена, "
    "связи, правила и ограничения; общую рекламу и вводные формулировки опускай. "
    "Если документ явно задает число типов, видов, частей, этапов или вариантов, сохрани "
    "название категории, количество и названия элементов вместо общего описания темы. "
    "Не заменяй точные роли и уровни объектов (например, корневой или вложенный), "
    "кардинальность, пороги и значения более широкой формулировкой. "
    "Сохраняй важные факты из середины и конца документа, если они раскрывают его тему. "
    "Не додумывай факты и не давай советы. Пиши на языке документа, без markdown. "
    "Не используй скобки и не заканчивай карточку сокращением. "
    "selector_summary обязательно закончи ровно одним знаком: точкой, вопросительным или "
    "восклицательным знаком. Перед ответом сократи оба поля до лимитов; система не будет "
    "обрезать твой ответ. "
    "Верни только JSON: {\"discovery_summary\":\"...\",\"selector_summary\":\"...\"}."
)


@dataclass(frozen=True)
class SemanticSummaryProjections:
    discovery_summary: str
    selector_summary: str
    model_key: str
    generation_status: str = "unknown"
    provider_discovery_chars: int | None = None
    provider_selector_chars: int | None = None

    @property
    def selector_summary_version(self) -> int:
        if self.selector_summary and self.model_key.startswith("llm:"):
            return SELECTOR_SUMMARY_VERSION
        return 0


def resolve_semantic_summary_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
) -> tuple[Any, str, str] | None:
    """Prefer the auxiliary model, then use the configured answer model."""

    return resolve_orchestrator_llm(user, ai_profile, settings) or resolve_answer_llm(
        user, ai_profile, settings
    )


def semantic_summary_model_key(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
) -> str:
    if not settings.rag_semantic_summaries_enabled:
        return f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    resolved = resolve_semantic_summary_llm(user, ai_profile, settings)
    if resolved is None:
        return f"extractive:v{DISCOVERY_SUMMARY_VERSION}"
    spec, model, _api_key = resolved
    return f"llm:{spec.name}:{model}:v{DISCOVERY_SUMMARY_VERSION}"


def _clean_card(value: str) -> str:
    card = str(value or "").strip()
    card = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", card, flags=re.IGNORECASE).strip()
    card = " ".join(card.split())
    return card


def _selector_card_is_complete(value: str) -> bool:
    if not value.endswith((".", "!", "?")):
        return False
    if len(value) > 1 and value[-2] in ".!?":
        return False
    pairs = (("(", ")"), ("[", "]"), ("{", "}"), ("«", "»"))
    return all(value.count(opening) == value.count(closing) for opening, closing in pairs)


def extractive_summary_projections(
    *,
    title: str,
    text_value: str,
    generation_status: str = "extractive",
    provider_discovery_chars: int | None = None,
    provider_selector_chars: int | None = None,
) -> SemanticSummaryProjections:
    return SemanticSummaryProjections(
        discovery_summary=build_discovery_summary(
            title, text_value, max_chars=DISCOVERY_SUMMARY_MAX_CHARS
        ),
        # Extractive text remains useful for discovery embeddings, but it is not
        # a semantic Selector card and must never be published as one.
        selector_summary="",
        model_key=f"extractive:v{SUMMARY_SCHEMA_VERSION}",
        generation_status=generation_status,
        provider_discovery_chars=provider_discovery_chars,
        provider_selector_chars=provider_selector_chars,
    )


@dataclass(frozen=True)
class _ProjectionParseResult:
    discovery_summary: str = ""
    selector_summary: str = ""
    failure: str | None = None
    discovery_chars: int | None = None
    selector_chars: int | None = None


def _parse_projection_response(raw: str) -> _ProjectionParseResult:
    value = str(raw or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return _ProjectionParseResult(failure="invalid_json")
    if not isinstance(payload, Mapping):
        return _ProjectionParseResult(failure="invalid_shape")
    discovery = _clean_card(str(payload.get("discovery_summary") or ""))
    selector = _clean_card(str(payload.get("selector_summary") or ""))
    discovery_chars = len(discovery)
    selector_chars = len(selector)
    if len(discovery) < 12 or len(selector) < 12:
        return _ProjectionParseResult(
            failure="missing_fields",
            discovery_chars=discovery_chars,
            selector_chars=selector_chars,
        )
    if discovery_chars > DISCOVERY_SUMMARY_MAX_CHARS:
        return _ProjectionParseResult(
            failure="discovery_too_long",
            discovery_chars=discovery_chars,
            selector_chars=selector_chars,
        )
    if selector_chars > SELECTOR_SUMMARY_MAX_CHARS:
        return _ProjectionParseResult(
            failure="selector_too_long",
            discovery_chars=discovery_chars,
            selector_chars=selector_chars,
        )
    if not _selector_card_is_complete(selector):
        return _ProjectionParseResult(
            failure="selector_incomplete",
            discovery_chars=discovery_chars,
            selector_chars=selector_chars,
        )
    return _ProjectionParseResult(
        discovery_summary=discovery,
        selector_summary=selector,
        discovery_chars=discovery_chars,
        selector_chars=selector_chars,
    )


async def build_semantic_summary_projections(
    *,
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings,
    object_kind: str,
    title: str,
    text_value: str,
) -> SemanticSummaryProjections:
    def fallback(
        status: str,
        *,
        discovery_chars: int | None = None,
        selector_chars: int | None = None,
    ) -> SemanticSummaryProjections:
        return extractive_summary_projections(
            title=title,
            text_value=text_value,
            generation_status=status,
            provider_discovery_chars=discovery_chars,
            provider_selector_chars=selector_chars,
        )

    model_key = semantic_summary_model_key(user, ai_profile, settings)
    resolved = (
        resolve_semantic_summary_llm(user, ai_profile, settings)
        if settings.rag_semantic_summaries_enabled
        else None
    )
    if resolved is None:
        return fallback(
            "model_unavailable"
            if settings.rag_semantic_summaries_enabled
            else "semantic_summaries_disabled"
        )

    from app.services.ai.llm import complete_chat_completion

    spec, model, api_key = resolved
    output_capability = negotiate_chat_completion_capability(spec)
    source = str(text_value or "").strip()[: settings.rag_semantic_summary_input_chars]
    prompt = f"Тип: {object_kind}\nЗаголовок: {title or '(без заголовка)'}\nТекст:\n{source}"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    parsed = _ProjectionParseResult(failure="not_attempted")
    for attempt in range(SEMANTIC_SUMMARY_GENERATION_ATTEMPTS):
        try:
            raw = await asyncio.wait_for(
                complete_chat_completion(
                    spec=spec,
                    model=model,
                    api_key=api_key,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=320,
                    output_capability=output_capability,
                    output_schema_name="semantic_summary_projections_v9",
                    output_json_schema=(
                        _SUMMARY_JSON_SCHEMA
                        if output_capability != ChatCompletionCapability.PLAIN
                        else None
                    ),
                ),
                timeout=settings.rag_semantic_summary_timeout_seconds,
            )
        except Exception:
            return fallback("provider_error")
        parsed = _parse_projection_response(raw)
        if not parsed.failure:
            return SemanticSummaryProjections(
                parsed.discovery_summary,
                parsed.selector_summary,
                model_key,
                "llm_valid" if attempt == 0 else "llm_valid_retry",
                parsed.discovery_chars,
                parsed.selector_chars,
            )
        messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Невалидная проекция: "
                    f"code={parsed.failure}, discovery_chars={parsed.discovery_chars}, "
                    f"selector_chars={parsed.selector_chars}. Создай новый JSON заново, "
                    "не обрезай предыдущий текст. selector_summary должна быть целым "
                    f"предложением не длиннее {SELECTOR_SUMMARY_TARGET_MAX_CHARS} "
                    "Unicode-символов, сохранить явные число, категорию и названные "
                    "элементы и закончиться ровно одним знаком."
                ),
            },
        ]
    return fallback(
        str(parsed.failure or "invalid_projection"),
        discovery_chars=parsed.discovery_chars,
        selector_chars=parsed.selector_chars,
    )


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
    "SELECTOR_SUMMARY_TARGET_MAX_CHARS",
    "SemanticSummaryProjections",
    "build_semantic_discovery_card",
    "build_semantic_summary_projections",
    "extractive_summary_projections",
    "resolve_semantic_summary_llm",
    "semantic_summary_model_key",
]
