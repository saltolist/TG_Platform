"""Semantic discovery cards for posts and notes.

Cards improve candidate selection but are never answer evidence. Generation is
best-effort and runs inside the existing asynchronous embedding worker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core.config import Settings
from app.db.models import User
from app.services.ai.orchestrator import resolve_answer_llm, resolve_orchestrator_llm
from app.services.ai.providers import (
    ChatCompletionCapability,
    negotiate_chat_completion_capability,
)
from app.services.ai.rag import build_discovery_summary
from app.services.ai.semantic_chunking import (
    normalize_section_starts,
    render_numbered_paragraphs,
    semantic_paragraphs,
)

logger = logging.getLogger(__name__)

SUMMARY_SCHEMA_VERSION = 2
DISCOVERY_SUMMARY_VERSION = SUMMARY_SCHEMA_VERSION
SELECTOR_SUMMARY_VERSION = 19
SELECTOR_SEMANTIC_FLAGS_VERSION = 3
DISCOVERY_SUMMARY_MAX_CHARS = 480
SELECTOR_SUMMARY_MAX_CHARS = 240
SELECTOR_SUMMARY_TARGET_MAX_CHARS = 225
SEMANTIC_SUMMARY_GENERATION_ATTEMPTS = 5
COMPACT_SOURCE_PRESERVATION_MAX_CHARS = 1200
RECORD_ROLE_PRESERVATION_PREFIX_CHARS = 400

_EXPLICIT_NEGATION_RE = re.compile(
    r"(?:\b(?:does|did|is|are|was|were)\s+not\b|\bdoesn't\b|\bwithout\b|"
    r"\b(?:contains?|has|records?|states?)\s+no\b|\bneither\b|\bnot\s+"
    r"(?:stated|set|specified|identified|assigned|approved)\b|\bне\s+\w+|\bбез\s+\w+|"
    r"\bsin\s+\w+|\bno\s+\w+|\bsans\s+\w+|\bne\s+(?:\w+\s+){0,3}pas\b|"
    r"\bkein\w*\b|\bohne\s+\w+|\bnicht\s+\w+|\bsenza\s+\w+|\bnon\s+\w+|"
    r"\bsem\s+\w+|\b(?:não|nao)\s+\w+)",
    re.IGNORECASE,
)
_RECORD_MARKER_RES = {
    "draft_or_proposed": re.compile(
        r"\b(?:draft|proposed|proposal|чернов\w*|предлож\w*|borrador|propuest\w*|"
        r"brouillon|propos\w*|entwurf|vorgeschlag\w*|bozza|propost\w*|rascunho)\b",
        re.IGNORECASE,
    ),
    "final_or_signed": re.compile(
        r"\b(?:final|signed|approved|итогов\w*|финальн\w*|подписан\w*|утвержден\w*|"
        r"firmad\w*|finale?|signe\w*|unterzeichnet\w*|genehmigt\w*|assinad\w*|"
        r"aprova[rd]\w*)\b",
        re.IGNORECASE,
    ),
}
_EXPLICIT_ABSENCE_RE = re.compile(
    r"(?:"
    r"\b(?:does\s+not|doesn't|fails?\s+to)\s+(?:\w+\s+){0,4}"
    r"(?:state|set|specify|identify|name|give|provide|record|contain|list|mention|"
    r"assign|explain|establish|confirm|document|distinguish|select|choose)\b"
    r"|\b(?:contains?|names?|gives?|provides?|records?|states?|sets?|specifies?|"
    r"identifies?|assigns?|explains?|has|offers?|establishes?|documents?)\s+no\b"
    r"|\b(?:no|without)\b.{0,72}\b(?:choice|decision|selection|value|owner|authority|"
    r"deadline|date|time|limit|cause|reason|answer|indication|record)\b"
    r"|\b(?:choice|decision|selection|value|owner|authority|deadline|date|time|limit|"
    r"cause|reason|answer)\b.{0,48}\b(?:absent|missing|unknown|unspecified|unrecorded)\b"
    r"|\bне\s+(?:указывает|задает|содержит|формулирует|перечисляет|объясняет|"
    r"называет|говорит|приводит|фиксирует|устанавливает|подтверждает|определяет|регулирует)\b"
    r"|\bне\s+(?:задан|указан|установлен|определен|зафиксирован|приведен)\w*\b"
    r"|\b(?:решени\w*|ответ\w*|лимит\w*|владел\w*|дат\w*|причин\w*|значени\w*)\b"
    r".{0,48}\b(?:нет|отсутству\w*|неизвест\w*)\b"
    r"|\bбез\s+(?:указания|описания|объяснения|значения|даты|времени|лимита|решения|выбора)\b"
    r"|\bsin\s+(?:indicar|identificar|enumerar|explicar|precisar|decir|dar|registrar|establecer|fijar|definir)\b"
    r"|\bno\s+(?:indica|identifica|enumera|explica|precisa|dice|da|registra|"
    r"establece|fija|define|especifica|determina|informa)\b"
    r"|\b(?:nennt|gibt|enthaelt|enthalt|beschreibt|setzt)\b.{0,40}\bkein\w*\b"
    r"|\bohne\b.{0,40}\b(?:nennen|angeben|erklaeren|beschreiben|festlegen)\b"
    r"|\bsans\s+(?:donner|indiquer|identifier|pr[eé]ciser|expliquer|nommer|fixer|"
    r"[eé]tablir|r[eé]server)\b"
    r"|\bne\s+(?:donne|indique|identifie|precise|explique|nomme|fixe|etablit|"
    r"specifie|enregistre|reserve)\s+pas\b"
    r"|\bsenza\s+(?:indicare|identificare|specificare|spiegare|nominare|stabilire|definire)\b"
    r"|\bnon\s+(?:indica|identifica|specifica|spiega|nomina|stabilisce|definisce|registra)\b"
    r"|\bsem\s+(?:indicar|identificar|especificar|explicar|dizer|registrar|definir|informar)\b"
    r"|\b(?:não|nao)\s+(?:indica|identifica|especifica|explica|diz|registra|define|informa)\b"
    r")",
    re.IGNORECASE,
)
_OBSERVATIONAL_VALUE_RE = re.compile(
    r"\b(?:observed|measured|current(?:ly)?|actual|usage|throughput|load\s+test|sustained|"
    r"наблюдаем\w*|измерен\w*|текущ\w*|фактическ\w*|использован\w*|нагрузочн\w*)\b",
    re.IGNORECASE,
)

_ORDERED_ITEM_MARKER_RE = re.compile(
    r"(?P<label>[^\d\n]{1,48}?)\s+(?P<number>\d{1,3})\s*[.)\]:\-–—]"
)

_SUMMARY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "discovery_summary",
        "selector_summary",
        "claim_modalities",
        "semantic_section_starts",
    ],
    "properties": {
        "discovery_summary": {
            "type": "string",
            "minLength": 12,
        },
        "selector_summary": {
            "type": "string",
            "minLength": 12,
        },
        "claim_modalities": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "string",
                "enum": ["descriptive", "observational", "normative"],
            },
        },
        "semantic_section_starts": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "integer", "minimum": 1},
        },
    },
}

_SYSTEM = (
    "Создай две точные смысловые проекции одного документа за один вызов. "
    "discovery_summary предназначена для embeddings и discovery: одно-два коротких "
    "предложения, жестко не более 360 Unicode-символов. "
    "selector_summary предназначена только для выбора контекста. Создай ее целиком как "
    "самодостаточную смысловую карточку из одного-трех коротких утверждений о разных "
    "существенных аспектах документа. Каждое утверждение должно явно называть предмет и "
    "свой predicate: кто отвечает, что установлено, почему, когда, при каком условии или "
    "какая связь зафиксирована. Не превращай несколько аспектов в общее описание темы. "
    "Строго различай что или какие от как или почему: если документ лишь называет "
    "возможность, не утверждай, что он объясняет механизм. Карточка должна быть жестко "
    f"не более {SELECTOR_SUMMARY_TARGET_MAX_CHARS} Unicode-символов, быть законченной и не "
    "быть началом, цитатой или обрезком исходного текста. В ней приоритетны конкретные "
    "определения, классификации, перечисления, имена, связи, правила, условия и ограничения; "
    "общую рекламу и вводные формулировки опускай. Если документ содержит только один "
    "существенный факт, создай одно законченное утверждение: не дроби и не повторяй его, "
    "не добавляй второй аспект. Если документ явно задает конечный набор типов, видов, "
    "частей, этапов, вариантов или альтернатив, в обеих проекциях сохрани общую категорию, "
    "количество, названия или роли членов и решающие различия между ними. Если документ "
    "явно указывает применимость, целевое использование, ограничение или результат выбора "
    "для каждого члена, сохрани эту границу; не разрывай один сравниваемый набор на "
    "несвязанные темы. Карточка ведет к чтению источника, а не заменяет его. "
    "Если документ задает план, серию, очередь, roadmap, backlog или иную "
    "упорядоченную последовательность будущих результатов, selector_summary должна "
    "явно назвать эту роль документа, сохранить диапазон или число элементов и кратко "
    "назвать различающие темы элементов. Не заменяй план общим описанием предметной области. "
    "Не заменяй точные роли и уровни объектов (например, корневой или вложенный), "
    "кардинальность, пороги и значения более широкой формулировкой. "
    "Всегда сохраняй явное отрицание: если документ говорит, что решение, роль, значение, "
    "причина или срок отсутствуют либо не установлены, карточка должна сказать это явно. "
    "Простое упоминание значения в inventory или списке не превращай в draft/proposed, "
    "final/signed или approved решение. "
    "Сохраняй lifecycle-роли записей дословно по смыслу: draft/proposed не превращай в "
    "final/signed/approved и не опускай ни одну из этих ролей, если она есть в документе. "
    "Сохраняй важные факты из середины и конца документа, если они раскрывают его тему. "
    "Не додумывай факты и не давай советы. Пиши на языке документа, без markdown. "
    "Не используй скобки и не заканчивай карточку сокращением. "
    "selector_summary обязательно закончи ровно одной точкой или восклицательным знаком. "
    "Перед ответом переформулируй ее до лимита; не заполняй поле до границы. Система "
    "сохранит карточку дословно после нормализации пробелов и не будет обрезать твой ответ. "
    "Отдельно верни claim_modalities для явно утвержденных в документе отношений: "
    "descriptive для фактов, определений и связей; observational для наблюдений, "
    "измерений, факта наличия, прошлых использований и существующих файлов; normative "
    "только для явно заданной рекомендации, правила, политики, предпочтения, требования "
    "или будущего выбора. Не выводи normative из наблюдаемых примеров. Можно вернуть "
    "несколько значений, если документ действительно содержит разные модальности. "
    "Текст пользователя ниже размечен стабильными ids абзацев P0, P1 и далее. "
    "semantic_section_starts верни как возрастающий список номеров абзацев, с которых "
    "начинается новая самостоятельная смысловая часть: меняется предмет, цель, аргумент, "
    "вариант, этап или решаемый вопрос. Не дели связное объяснение, таблицу или список "
    "только ради размера и не считай Markdown-разметку обязательной. P0 не возвращай; "
    "если весь текст смыслово однороден, верни пустой список; максимум 12 границ. "
    "Верни только JSON: {\"discovery_summary\":\"...\",\"selector_summary\":\"...\","
    "\"claim_modalities\":[\"descriptive\"],\"semantic_section_starts\":[3]}."
)


@dataclass(frozen=True)
class SemanticSummaryProjections:
    discovery_summary: str
    selector_summary: str
    model_key: str
    generation_status: str = "unknown"
    provider_discovery_chars: int | None = None
    provider_selector_chars: int | None = None
    selector_semantic_flags: Mapping[str, Any] | None = None
    semantic_section_starts: tuple[int, ...] = ()

    @property
    def selector_summary_version(self) -> int:
        if self.selector_summary and self.model_key.startswith("llm:"):
            return SELECTOR_SUMMARY_VERSION
        return 0


@dataclass(frozen=True)
class _OrderedSequenceSignature:
    label: str
    first: int
    last: int
    count: int


def _ordered_sequence_signature(source: str) -> _OrderedSequenceSignature | None:
    """Detect repeated, consecutively numbered headings without domain keywords."""

    groups: dict[str, tuple[str, list[int]]] = {}
    for line in str(source or "").splitlines():
        candidate = line.strip().lstrip("#>*_- ").strip()
        match = _ORDERED_ITEM_MARKER_RE.match(candidate)
        if match is None:
            continue
        label = match.group("label").strip(" *_#>")
        normalized_label = " ".join(label.casefold().split())
        if not normalized_label:
            continue
        display_label, numbers = groups.setdefault(normalized_label, (label, []))
        number = int(match.group("number"))
        if not numbers or numbers[-1] != number:
            numbers.append(number)

    signatures: list[_OrderedSequenceSignature] = []
    for display_label, numbers in groups.values():
        # Three-level taxonomies are commonly summarized correctly by their
        # cardinality alone. Longer series need explicit boundary preservation
        # because omitting an offset such as 2-6 changes continuation semantics.
        if len(numbers) < 4:
            continue
        direction = 1 if numbers[-1] > numbers[0] else -1
        if not all(right - left == direction for left, right in zip(numbers, numbers[1:])):
            continue
        signatures.append(
            _OrderedSequenceSignature(
                label=display_label,
                first=numbers[0],
                last=numbers[-1],
                count=len(numbers),
            )
        )
    return max(signatures, key=lambda item: item.count, default=None)


def _selector_card_preserves_ordered_sequence(
    card: str,
    signature: _OrderedSequenceSignature | None,
) -> bool:
    if signature is None:
        return True
    value = str(card or "")
    return all(
        re.search(rf"(?<!\d){number}(?!\d)", value)
        for number in (signature.first, signature.last)
    )


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


def _selector_card_preserves_explicit_negation(source: str, card: str) -> bool:
    return not selector_card_has_explicit_negation(source) or selector_card_has_explicit_negation(
        card
    )


def _selector_card_preserves_record_markers(source: str, card: str) -> bool:
    return selector_card_record_marker_kinds(source) <= selector_card_record_marker_kinds(card)


def _selector_card_preserves_explicit_absence(source: str, card: str) -> bool:
    return not selector_card_has_explicit_absence(source) or selector_card_has_explicit_absence(
        card
    )


def selector_card_has_explicit_absence(value: str) -> bool:
    return bool(_EXPLICIT_ABSENCE_RE.search(str(value or "")))


def selector_card_record_marker_kinds(value: str) -> frozenset[str]:
    text = str(value or "")
    return frozenset(
        name for name, pattern in _RECORD_MARKER_RES.items() if pattern.search(text)
    )


def selector_semantic_flags(
    source: str,
    *,
    claim_modalities: Sequence[str] | None = None,
) -> dict[str, Any]:
    explicit_absence = selector_card_has_explicit_absence(source)
    modalities = tuple(
        dict.fromkeys(
            str(value)
            for value in (claim_modalities or ())
            if str(value) in {"descriptive", "observational", "normative"}
        )
    )
    observational_value = "observational" in modalities or bool(
        _OBSERVATIONAL_VALUE_RE.search(str(source or ""))
    )
    return {
        "v": SELECTOR_SEMANTIC_FLAGS_VERSION,
        "explicit_absence": explicit_absence,
        "observational_value": observational_value,
        "normative_value": "normative" in modalities,
        "claim_modalities": list(modalities),
        "record_roles": (
            []
            if explicit_absence or observational_value
            else sorted(selector_card_record_marker_kinds(source))
        ),
    }


def selector_card_has_explicit_negation(value: str) -> bool:
    return bool(_EXPLICIT_NEGATION_RE.search(str(value or "")))


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
    claim_modalities: tuple[str, ...] = ()
    semantic_section_starts: tuple[int, ...] = ()
    failure: str | None = None
    discovery_chars: int | None = None
    selector_chars: int | None = None


def _parse_projection_response(
    raw: str,
    *,
    paragraph_count: int = 0,
) -> _ProjectionParseResult:
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
    raw_modalities = payload.get("claim_modalities")
    if not isinstance(raw_modalities, list):
        return _ProjectionParseResult(failure="missing_claim_modalities")
    claim_modalities = tuple(
        dict.fromkeys(
            str(value)
            for value in raw_modalities
            if str(value) in {"descriptive", "observational", "normative"}
        )
    )
    if not claim_modalities or len(claim_modalities) != len(raw_modalities):
        return _ProjectionParseResult(failure="invalid_claim_modalities")
    raw_section_starts = payload.get("semantic_section_starts", [])
    if not isinstance(raw_section_starts, list) or any(
        type(value) is not int or value <= 0 for value in raw_section_starts
    ):
        return _ProjectionParseResult(failure="invalid_semantic_section_starts")
    semantic_section_starts = normalize_section_starts(
        raw_section_starts,
        paragraph_count=paragraph_count,
    )
    if len(semantic_section_starts) != len(raw_section_starts):
        return _ProjectionParseResult(failure="invalid_semantic_section_starts")
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
    if (
        not selector.endswith((".", "!"))
        or (len(selector) > 1 and selector[-2] in ".!?")
        or not _selector_card_is_complete(selector)
    ):
        return _ProjectionParseResult(
            failure="selector_incomplete",
            discovery_chars=discovery_chars,
            selector_chars=selector_chars,
        )
    return _ProjectionParseResult(
        discovery_summary=discovery,
        selector_summary=selector,
        claim_modalities=claim_modalities,
        semantic_section_starts=semantic_section_starts,
        discovery_chars=discovery_chars,
        selector_chars=selector_chars,
    )


def _projection_repair_instruction(
    parsed: _ProjectionParseResult,
    *,
    next_attempt: int,
    ordered_sequence: _OrderedSequenceSignature | None = None,
) -> str:
    failure = str(parsed.failure or "invalid_projection")
    target_chars = SELECTOR_SUMMARY_TARGET_MAX_CHARS
    word_limit_instruction = ""
    if failure == "selector_too_long":
        # A deterministic provider needs a materially different constraint on
        # every retry; replaying the same prompt at temperature zero cannot heal.
        target_chars = max(175, SELECTOR_SUMMARY_TARGET_MAX_CHARS - 20 * (next_attempt - 1))
        target_words = max(16, 36 - 4 * next_attempt)
        sentence_count = 3 if next_attempt <= 3 else 2
        words_per_sentence = 10 if next_attempt in {2, 4} else 8
        word_limit_instruction = (
            f" Используй не более {sentence_count} предложений, не более "
            f"{words_per_sentence} слов в каждом и не более {target_words} слов всего."
        )
    elif failure == "selector_ordered_sequence_lost":
        target_chars = 200
        word_limit_instruction = (
            " Используй одно предложение, не более 24 слов и только короткие названия "
            "различающихся тем элементов."
        )

    failure_instruction = {
        "selector_too_long": (
            "Переформулируй карточку короче целиком. Убирай вводные слова и повторы, "
            "но сохрани разные существенные predicates, точные значения, роли и отрицания."
        ),
        "selector_negation_lost": (
            "Повторно прочитай исходный текст и явно сохрани каждое смысловое отрицание "
            "прямой отрицательной конструкцией на языке документа. Хотя бы одно "
            "предложение selector_summary должно содержать такую отрицательную пропозицию."
        ),
        "selector_record_marker_lost": (
            "Явно сохрани каждую lifecycle-роль записи из источника: draft/proposed и "
            "final/signed/approved нельзя обобщать или опускать."
        ),
        "invalid_semantic_section_starts": (
            "Верни semantic_section_starts как возрастающий список уникальных номеров "
            "существующих абзацев P1 и далее, либо пустой список."
        ),
        "selector_ordered_sequence_lost": (
            "Исходный документ содержит упорядоченный ряд однотипных элементов. "
            "Явно назови роль этого ряда в документе, сохрани его границы "
            f"{ordered_sequence.first if ordered_sequence else '?'}-"
            f"{ordered_sequence.last if ordered_sequence else '?'} и кратко различи "
            "темы элементов; не заменяй ряд общим описанием предметной области."
        ),
        "selector_incomplete": (
            "Перепиши selector_summary законченными короткими предложениями без скобок и "
            "заверши ее ровно одной точкой или восклицательным знаком."
        ),
    }.get(
        failure,
        "Пересоздай обе проекции как валидный JSON строго по системному контракту.",
    )
    return (
        f"Repair attempt {next_attempt}/{SEMANTIC_SUMMARY_GENERATION_ATTEMPTS}. "
        f"Невалидная проекция: code={failure}, "
        f"discovery_chars={parsed.discovery_chars}, selector_chars={parsed.selector_chars}. "
        f"{failure_instruction} Создай новый JSON заново и не обрезай готовую фразу по "
        "границе. selector_summary должна быть целиком заново созданной законченной "
        "карточкой из одного-трех коротких утверждений и быть не длиннее "
        f"{target_chars} Unicode-символов.{word_limit_instruction} Сохрани предмет, "
        "predicate, явные значения, "
        "роли, условия и связи. Если документ явно не задает факт, сформулируй это прямой "
        "конструкцией отсутствия на языке документа, например not stated, no indica, "
        "sans donner, nicht angegeben, non specifica, nao informa или не указано."
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
    source_paragraphs = semantic_paragraphs(source)
    ordered_sequence = _ordered_sequence_signature(source)
    prompt = (
        f"Тип: {object_kind}\nЗаголовок: {title or '(без заголовка)'}\n"
        f"Абзацы:\n{render_numbered_paragraphs(source_paragraphs)}"
    )
    base_messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    messages = base_messages
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
                    output_schema_name="semantic_summary_projections_v19",
                    output_json_schema=(
                        _SUMMARY_JSON_SCHEMA
                        if output_capability != ChatCompletionCapability.PLAIN
                        else None
                    ),
                ),
                timeout=settings.rag_semantic_summary_timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "Semantic summary provider failed: provider=%s model=%s error=%s: %s",
                spec.name,
                model,
                type(exc).__name__,
                str(exc)[:240],
            )
            return fallback("provider_error")
        parsed = _parse_projection_response(
            raw,
            paragraph_count=len(source_paragraphs),
        )
        if (
            not parsed.failure
            and not _selector_card_preserves_ordered_sequence(
                parsed.selector_summary,
                ordered_sequence,
            )
        ):
            parsed = _ProjectionParseResult(
                failure="selector_ordered_sequence_lost",
                discovery_chars=parsed.discovery_chars,
                selector_chars=parsed.selector_chars,
            )
        if (
            not parsed.failure
            and len(source) <= COMPACT_SOURCE_PRESERVATION_MAX_CHARS
            and not _selector_card_preserves_record_markers(
                source[:RECORD_ROLE_PRESERVATION_PREFIX_CHARS],
                parsed.selector_summary,
            )
        ):
            parsed = _ProjectionParseResult(
                failure="selector_record_marker_lost",
                discovery_chars=parsed.discovery_chars,
                selector_chars=parsed.selector_chars,
            )
        if not parsed.failure:
            return SemanticSummaryProjections(
                discovery_summary=parsed.discovery_summary,
                selector_summary=parsed.selector_summary,
                model_key=model_key,
                generation_status="llm_valid" if attempt == 0 else "llm_valid_retry",
                provider_discovery_chars=parsed.discovery_chars,
                provider_selector_chars=parsed.selector_chars,
                selector_semantic_flags=selector_semantic_flags(
                    source,
                    claim_modalities=parsed.claim_modalities,
                ),
                semantic_section_starts=parsed.semantic_section_starts,
            )
        messages = [
            *base_messages,
            {
                "role": "user",
                "content": _projection_repair_instruction(
                    parsed,
                    next_attempt=attempt + 2,
                    ordered_sequence=ordered_sequence,
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
    "SELECTOR_SEMANTIC_FLAGS_VERSION",
    "SELECTOR_SUMMARY_TARGET_MAX_CHARS",
    "SemanticSummaryProjections",
    "build_semantic_discovery_card",
    "build_semantic_summary_projections",
    "extractive_summary_projections",
    "resolve_semantic_summary_llm",
    "semantic_summary_model_key",
    "selector_semantic_flags",
]
