"""Compiled WorkspaceAgent graph with durable checkpointing."""

from __future__ import annotations

import logging
import asyncio
import json
import re
import uuid
from typing import Any, Literal, Mapping

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.db.models import AgentRun, User
from app.services.agent.actions.proposals import create_proposal
from app.services.agent.media.jobs import create_media_job, enqueue_media_job
from app.services.agent.media.registry import lookup_capability, resolve_profile_media_model
from app.services.agent.research.graph import (
    research_seed_node,
    research_planner_node,
    research_tool_node,
    research_verify_node,
    research_pack_node,
    route_research_plan,
    route_research_seed,
    route_research_after_tool,
    route_research_verify,
)
from app.services.agent.research.evidence_pack import EVIDENCE_PACK_SCHEMA
from app.services.agent.research.catalog import NOTE_PROPERTIES, POST_PROPERTIES
from app.services.agent.research.material_plan import empty_material_plan
from app.services.agent.research.trust import UNTRUSTED_SYSTEM_NOTE, wrap_untrusted_block
from app.services.agent.runtime.answer_stream import extract_complete_answer, extract_partial_answer
from app.services.agent.runtime.artifacts import ArtifactHandle
from app.services.agent.runtime.budget import (
    PhaseDeadlineExceeded,
    call_llm_with_deadline,
    stream_llm_with_deadline,
)
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready, get_checkpointer
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.message_context import (
    evidence_id_aliases,
    supplied_object_refs,
)
from app.services.agent.runtime.output_contract import (
    is_factual_profile,
    resolve_output_schema,
    validate_answer_output,
)
from app.services.agent.resources.registry import get_resource_descriptor, resource_kinds
from app.services.ai.providers import (
    ChatCompletionCapability,
    negotiate_chat_completion_capability,
)
from app.services.agent.runtime.result_quality import (
    build_style_profile,
    validate_result_contract,
)
from app.services.agent.runtime.rollout import runtime_rollout_flags
from app.services.agent.runtime.state import AgentGraphState
from app.services.agent.runtime.turn_contract import (
    EVIDENCE_REQUIREMENT_SCHEMA,
    render_turn_contract,
    source_discovery_required,
    source_evidence_required,
    source_selection_cardinality,
)

logger = logging.getLogger(__name__)
_compiled_graphs: dict[int, tuple[object, Any]] = {}

_INVENTORY_UNIT_VERSION = 1
_READ_QUERY_IR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "type",
        "task_profile",
        "selection_mode",
        "requires_evidence",
        "answer_shape",
        "answer_obligations",
        "required_sources",
        "workspace_dependency",
        "search_query",
    ],
    "properties": {
        "type": {"type": "string", "const": "read"},
        "task_profile": {
            "type": "string",
            "enum": [
                "topical_answer",
                "recommendation",
                "workspace_synthesis",
                "comparison",
                "exhaustive_inventory",
            ],
        },
        "selection_mode": {
            "type": "string",
            "enum": [
                "record",
                "composition",
                "cross_record_comparison",
                "member_inventory",
                "cross_record_inventory",
            ],
        },
        "requires_evidence": {"type": "boolean", "const": True},
        "answer_shape": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "expected_member_count", "inventory_unit"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["freeform", "scalar", "record", "inventory"],
                },
                "expected_member_count": {
                    "anyOf": [
                        {"type": "integer", "minimum": 0},
                        {"type": "null"},
                    ],
                },
                "inventory_unit": {
                    "anyOf": [
                        {"type": "string", "enum": ["record", "value"]},
                        {"type": "null"},
                    ],
                },
            },
        },
        "answer_obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "origin"],
                "properties": {
                    "description": {"type": "string", "minLength": 1, "maxLength": 400},
                    "origin": {
                        "type": "string",
                        "enum": [
                            "fact",
                            "candidate_plan",
                            "unfinished_state",
                            "constraint_signal",
                            "decision_history",
                            "workflow_premise",
                            "comparison_side",
                            "member_predicate",
                            "mapping_premise",
                            "mapping_member",
                            "synthesis_operation",
                        ],
                    },
                },
            },
        },
        "required_sources": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "notes",
                    "posts",
                    "analytics",
                    "comments",
                    "attachments",
                    "images",
                    "channel",
                ],
            },
        },
        "workspace_dependency": {
            "type": "object",
            "additionalProperties": False,
            "required": ["basis", "empty_workspace", "anchor"],
            "properties": {
                "basis": {"type": "string", "const": "workspace_state"},
                "empty_workspace": {"type": "string", "const": "answer_changes"},
                "anchor": {
                    "type": "string",
                    "enum": ["explicit_workspace_reference", "decision_prerequisite"],
                },
            },
        },
        "search_query": {"type": "string", "minLength": 1},
    },
}


def _workspace_classifier_transport(
    spec: Any,
    *,
    typed_read: bool = False,
) -> ChatCompletionCapability:
    """Use bounded JSON transport for the polymorphic Query IR when available."""

    capabilities = set(
        getattr(spec, "chat_capabilities", (ChatCompletionCapability.PLAIN,))
    )
    if typed_read and ChatCompletionCapability.STRICT_JSON_SCHEMA in capabilities:
        return ChatCompletionCapability.STRICT_JSON_SCHEMA
    if ChatCompletionCapability.JSON_MODE in capabilities:
        return ChatCompletionCapability.JSON_MODE
    return ChatCompletionCapability.PLAIN


async def _resolve_inventory_unit(
    ctx: RuntimeContext,
    *,
    call: Mapping[str, Any],
    user_text: str,
    spec: Any,
    model: str,
    api_key: str,
    timeout_s: float,
) -> dict[str, Any]:
    """Freeze whether inventory members are records or values before discovery."""

    result = dict(call)
    shape = dict(result.get("answer_shape") or {})
    if str(shape.get("kind") or "") != "inventory":
        return result
    capability = negotiate_chat_completion_capability(spec)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["v", "inventory_unit", "done"],
        "properties": {
            "v": {"type": "integer", "const": _INVENTORY_UNIT_VERSION},
            "inventory_unit": {"type": "string", "enum": ["record", "value"]},
            "done": {"type": "boolean", "const": True},
        },
    }
    try:
        raw = await call_llm_with_deadline(
            ctx,
            phase="bootstrap.inventory_unit",
            phase_timeout_s=max(1.0, timeout_s),
            telemetry={
                "model_role": "reasoner",
                "retry": False,
                "schema_result": "pending",
            },
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify one frozen Query IR field. Return only v,inventory_unit,done. "
                        "Use inventory_unit=record only when the answer enumerates workspace "
                        "records themselves, such as which notes, posts, files, comments, or "
                        "materials match. Use inventory_unit=value when the answer enumerates "
                        "facts, functions, types, zones, mechanisms, reasons, stages, or other "
                        "values contained inside one or more materials. Never inspect or infer "
                        "candidate membership."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": user_text,
                            "proposed_selection_mode": result.get("selection_mode"),
                            "proposed_answer_shape": shape,
                            "answer_obligations": result.get("answer_obligations") or [],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            spec=spec,
            model=model,
            api_key=api_key,
            temperature=0.0,
            max_tokens=80,
            output_capability=capability,
            output_schema_name="inventory_unit_v1",
            output_json_schema=(
                schema if capability != ChatCompletionCapability.PLAIN else None
            ),
        )
        from app.services.ai.rag_json import extract_json_object

        payload = extract_json_object(raw) or {}
        if (
            set(payload) != {"v", "inventory_unit", "done"}
            or payload.get("v") != _INVENTORY_UNIT_VERSION
            or payload.get("done") is not True
            or payload.get("inventory_unit") not in {"record", "value"}
        ):
            return {**result, "inventory_unit_resolution_failure": "decoder_error"}
        shape["inventory_unit"] = str(payload["inventory_unit"])
        return {**result, "answer_shape": shape}
    except Exception as exc:
        return {
            **result,
            "inventory_unit_resolution_failure": type(exc).__name__,
        }


WORKSPACE_SYSTEM = """Ты единственный WorkspaceAgent платформы.
Верни один JSON tool call:
- {"type":"read","task_profile":"topical_answer|recommendation|workspace_synthesis|comparison|exhaustive_inventory","selection_mode":"record|composition|cross_record_comparison|member_inventory|cross_record_inventory","requires_evidence":true,"answer_shape":{"kind":"freeform|scalar|record|inventory","expected_member_count":null,"inventory_unit":"record|value|null"},"answer_obligations":[{"description":"source-neutral atomic premise required by the exact answer","origin":"fact|candidate_plan|unfinished_state|constraint_signal|decision_history|workflow_premise|comparison_side|member_predicate|mapping_premise|mapping_member"}],"required_sources":["notes|posts|analytics|comments|attachments|images|channel"],"source_requirements":[{"kind":"posts","query_goal":"самостоятельная цель этого источника","claim_modality":"descriptive|normative","coverage":"relevant|complete","discovery_mode":"semantic_relevance|catalog_window","order_dependency":"irrelevant|required","statuses":["draft|scheduled|published"],"order_by":"position|created_at","order_direction":"asc|desc","candidate_limit":4,"evidence_granularity":"catalog|semantic_card|full_text","evidence_requirements":[{"subject":"posts","property":"самостоятельный проверяемый аспект ответа","operator":"exists","scope":"source"}]}]} — ответ невозможен без фактов workspace;
- {"type":"finish","requires_evidence":false,"required_sources":[]} — на сообщение можно полноценно ответить по его тексту, диалогу и общим знаниям;
- {"type":"reuse_context","context_refs":["note:ID|post:ID"]} — нужны детали уже использованных материалов; открывай только эти проверенные refs по ID;
- {"type":"post_proposal","command":"create_post|edit_post|schedule_post|publish_post|cancel_schedule|delete_post|restore_post","payload":{...}} — только когда передан блок "Текущий пост";
- {"type":"media_proposal","kind":"image|video","prompt":"...","options":{},"cost_ceiling":number}.
Не выполняй мутации напрямую. Выбирай только тип вызова, без keyword routing.
Не предлагай функций, которых нет в перечисленных tools. В частности, в платформе
нет действия «связать заметку с постами или файлами»; заметки и файлы уже являются
частью workspace и доступны AI после сохранения.
Ходы, на которые можно полноценно ответить без новых фактов workspace, завершаются без поиска. Для factual "read" required_sources — это источники, без которых grounded-ответ будет неполным; включи туда КАЖДЫЙ такой источник. Выбирай "read", когда пользователь просит найти, перечислить, посчитать, проверить или описать свои объекты/метрики. Косвенная, условная или подразумеваемая формулировка все равно является factual "read", если истинность ответа зависит от значения, причины, роли, ограничения или состояния объекта workspace. Совет, оценка, продолжение или правка предыдущего ответа без новых фактов — "finish". Общий совет, выбор формата, best practice или рекомендация не становятся workspace-зависимыми только потому, что в workspace существуют объекты этого вида. Наличие, расширение файла, прошлое использование, частота или другие наблюдаемые примеры не доказывают норму, предпочтение, лучший вариант или будущий выбор, если пользователь не просил вывести решение именно из своих материалов, истории или метрик. В таком независимом случае выбери finish.
Для каждого обязательного источника заполни source_requirements. Кроме kind верни predicate_kind="structural|semantic|mixed", coverage="relevant|complete", discovery_mode="semantic_relevance|catalog_window", evidence_granularity="catalog|semantic_card|full_text" и evidence_requirements. Каждый evidence_requirement имеет property (какое фактическое свойство нужно доказать), operator="exists|count|filter|equals|contains" и scope="source|target|member|corpus|aggregate". Для semantic и mixed источника разбей query_goal на минимальные независимо проверяемые аспекты точного ответа и верни по одному evidence_requirement на каждый аспект. Один requirement должен выражать одну фальсифицируемую часть ответа: если значение, выбор, отличие, причина, ограничение или другая часть может оказаться неверной независимо от соседней части, раздели их, даже когда они ожидаются в одном источнике. Не объединяй удаляемо-независимые части в одну широкую property; формулировка с несколькими частями вопроса должна дать несколько requirements, когда потеря любой части делает точный ответ неполным. Не используй безликие property вроде grounded_evidence, relevant_context или наличие источника: property должна называть требуемое отношение, состояние, этап, ограничение или другую фактическую часть ответа. Не добавляй аспекты ради подробности; если удаление аспекта не делает точный ответ неполным, он не является требованием. structural означает, что ответ определяется каталогом/метаданными без толкования текста; semantic требует понимания содержания; mixed требует и полного структурного охвата, и смыслового отбора. Обязательный context-источник рекомендации или синтеза нельзя объявлять structural только потому, что у его объектов есть названия: если на решение способны повлиять тема, смысл, содержание, последовательность или связь с другой предпосылкой, выбери semantic или mixed и разреши смысловой отбор объектов. coverage="relevant" означает, что достаточно относящегося к вопросу подмножества; coverage="complete" означает, что ответ должен охватить каждый объект указанного корпуса. Выбирай complete для полного перечня, подсчёта по всей категории, описания каждого объекта и других задач, где пропуск хотя бы одного объекта делает ответ неверным. evidence_granularity="catalog" достаточно для количества, названий, статусов и наличия; "semantic_card" — для общей темы или назначения каждого объекта; "full_text" — для точных деталей, сравнений, цитат и редактирования. Не подменяй complete семантическим top-k.
Для каждого read верни answer_obligations как массив из 1-12 объектов {"description":"...","origin":"..."}. description — короткая source-neutral атомарная evidence premise, которую обязан доказать точный ответ. origin — её семантический тип из закрытого списка: fact для обычного факта; candidate_plan для явно зафиксированного будущего кандидата, плана, очереди или серии; unfinished_state для незавершённого либо уже запланированного результата; constraint_signal для явно записанного ограничения, предпочтения или сигнала; decision_history для bounded наблюдения выполненного результата; workflow_premise для этапа, интерфейса или механизма процесса; comparison_side для независимо проверяемой стороны сравнения; member_predicate для положительного inclusion predicate; mapping_premise и mapping_member для двух ролей cross-record mapping. Не используй candidate_plan для общего обзора предмета или перечня возможностей без явно зафиксированного будущего намерения. Не используй decision_history для простой давности: эта premise должна зависеть от статуса/позиции bounded history. Это не пункты будущего ответа и не итоговый вывод: не утверждай заранее неизвестный факт и не добавляй возможности, механизмы, этапы или сущности, которых нет в текущем запросе и диалоге. Каждая premise должна быть независимо фальсифицируема и проверяема по локальному фрагменту материала. Если одна часть запроса может быть истинной, когда другая ложна, это разные premises, даже когда один документ способен доказать обе. Для сравнения выделяй факты о каждой альтернативе и запрошенный критерий/различие; для связи или mapping — независимые стороны связи и факты, которые устанавливают их соответствие; для процесса — отдельно запрошенные этапы и механизмы, без которых процесс неполон. Для кажущегося противоречия всегда выделяй три premises: подтверждение первого утверждения, подтверждение второго и механизм их совместимости или конфликта; итог «есть ли противоречие» не является отдельной premise. Не объединяй premises только потому, что ожидаешь найти их в одной записи: record/composition и финальную cardinality применит runtime после чтения. Не создавай отдельную premise для чистого вывода, который детерминированно следует из уже перечисленных фактов. Для member_inventory верни ровно одну premise с origin=member_predicate — положительный inclusion predicate члена ответа; противоположный, посторонний или тестовый класс означает match=false. Для cross_record_inventory верни положительные inclusion predicates обеих сторон mapping с origins mapping_premise и mapping_member: что делает запись premise-планом/индексом/очередью и что делает другую запись соответствующим member относительно этого premise. Не подменяй их утверждениями о существовании источников, множественным итогом или общим отношением, которое невозможно проверить для одного потенциального члена. Соответствующие source requirement property должны повторять конкретный predicate своей стороны и никогда не быть grounded_evidence. Не называй тип источника. Один документ может доказать несколько premises, а несколько документов могут независимо подтверждать одну premise.
Дополнительно разрешён origin=synthesis_operation: им обязательно помечай запрошенный вывод, отношение, сопоставление или причинный синтез, который должен быть построен из других premises и не требует собственного материала. Для workspace_synthesis отделяй входные факты от операции над ними: например, «описать A» и «описать B» — fact, а «объяснить, как A связано с B» — synthesis_operation, если связь выводится из A и B. Не маркируй такую операцию как fact. Если материал должен явно сообщить самостоятельный факт связи, который не следует из сторон, оставь его fact. Для сравнения чистый итог сравнения также помечай synthesis_operation; независимо проверяемые стороны и критерии остаются evidence-premises.
Не заменяй фактические premises критериями качества ответа вроде «релевантно запросу», «основано на актуальных материалах» или «не противоречит политике»: для рекомендации premises должны называть наблюдаемые decision inputs — явно зафиксированный план/ограничение, незавершённое состояние, уже покрытый результат, запрошенный сигнал эффективности. В why/how/«как устроено» premise обязана повторять названные в вопросе сущности и условие как открытую проверяемую связь (например, «механизм, посредством которого A достигается без B»), а не оставаться местоименной фразой «как это работает». Когда вопрос спрашивает, как несколько компонентов складываются в систему, одного существования каждого компонента недостаточно: выделяй проверяемые интерфейсы, причинные связи или потоки между названными компонентами, не изобретая их фактическую реализацию.
Для каждого read также верни selection_mode. record означает, что точный ответ должен быть заземлён одной идентифицированной самодостаточной записью, даже если в вопросе несколько полей или причин. Не используй record для выбора или сравнения нескольких явно названных альтернатив: до discovery нельзя предполагать, что одна запись содержит обе стороны; используй composition либо cross_record_comparison. composition означает, что ответ требует ограниченного набора предпосылок, но одна самодостаточная запись может доказать несколько obligations. cross_record_comparison означает ограниченную проверку связи, различия, совместимости или конфликта между утверждениями из разных записей: исходные независимо проверяемые claims должны остаться разными evidence premises, даже если обзорная запись пересказывает их вместе; этот режим не требует полного корпуса. member_inventory означает смысловую классификацию каждого члена одного конечного корпуса. cross_record_inventory означает сопоставление записи-плана, индекса, очереди или другого premise-набора со всеми подходящими членами другого конечного корпуса; используй его и для свободной формы ответа, если пропуск одного подходящего члена изменит результат сопоставления. Не используй inventory-режим только потому, что в workspace много кандидатов.
Для каждого source_requirement обязательно верни claim_modality. descriptive означает, что нужны явно зафиксированные факты, состояния, наблюдения или связи. normative означает, что ответ требует явно зафиксированной рекомендации, нормы, правила, политики, предпочтения, обязательного формата или будущего выбора. Наблюдаемый пример, существующий файл или прошлое использование не удовлетворяют normative. Если сам вопрос просит рекомендацию, но она не должна быть зафиксирована в workspace, выбери finish; не создавай фиктивное normative-требование ради персонализации общего совета.
Для read всегда верни task_profile и answer_shape. Используй task_profile="topical_answer" для сопоставления уже заданного конечного набора альтернатив, записей или состояний по запрошенному критерию, включая вопрос, какой из этих вариантов подходит и почему другой не подходит. Выбирай topical_answer даже при оценочном выводе, если ответ должен установить значения и различия именно этих уже упомянутых альтернатив. task_profile="recommendation" означает открытый выбор, совет или решение о следующем результате, где множество возможных действий не исчерпывается уже заданными альтернативами. Несколько частей одного сравнения не превращают его в workspace_synthesis: несколько записей могут оказаться нужны как доказательства, но task_profile описывает операцию ответа, а не заранее угаданное количество источников. kind="inventory" означает перечисление членов уже существующей фактической категории, а не список предлагаемых идей, вариантов или рекомендаций. Для inventory всегда верни inventory_unit: record, когда сами заметки, посты или другие workspace-объекты являются перечисляемыми членами ответа; value, когда перечисляемые функции, типы, зоны, причины, этапы или другие значения находятся внутри одного или нескольких материалов. Если пользователь явно задал точное число членов цифрами или словами на любом языке, запиши это число в expected_member_count, иначе null. Не выводи число из количества найденных источников, candidate_limit или предположений. Для не-inventory inventory_unit=null. Для одиночного значения используй scalar, для одного объекта с несколькими полями record, иначе freeform; у них expected_member_count всегда null.
Используй task_profile="workspace_synthesis", когда нужно собрать единый ответ, процесс или объяснение из нескольких независимых фактических предпосылок workspace (например, связать план с выполненными результатами или описать сквозной workflow). Это отличается от topical_answer: topical_answer подходит для одного факта, свойства или прямого описания, которое может быть доказано одной сильной записью. Несколько частей, полей или придаточных в вопросе не делают его синтезом, если одна связная запись способна прямо и самодостаточно ответить на них все; тогда используй topical_answer и вырази части отдельными evidence_requirements. Наличие нескольких видов источников в доступном workspace само по себе не делает задачу синтезом: выбирай workspace_synthesis только если ожидаются разные записи или объекты, каждый даёт незаменимую предпосылку, и только их межобъектная связь образует точный ответ. Для открытого синтеза используй answer_shape.kind="freeform"; не превращай его в inventory только потому, что ответ можно оформить списком шагов.
discovery_mode="semantic_relevance" означает смысловой top-k по query_goal. Для semantic и mixed источника верни order_dependency="required" только когда изменение порядка, позиции, lifecycle-состояния или границы недавней истории способно изменить точный ответ; во всех остальных случаях верни "irrelevant". discovery_mode="catalog_window" допустим только при order_dependency="required" и хотя бы одном evidence_requirement со scope="member|corpus|aggregate": упорядоченная история является отношением между членами окна, а не свойством одного источника. Для окна обязательно верни statuses, order_by, order_direction и candidate_limit от 1 до 12, а coverage оставь "relevant". Тематическая близость, описание рабочего процесса или наличие нескольких постов сами по себе не создают зависимости от порядка. Сам реши, когда нужна недавняя или иная ограниченная часть истории и какого размера достаточно. Окно — только граница дешёвого сравнения semantic cards, а не список для автоматического полного чтения или ответа. Не используй catalog_window для требования обо всей истории и не запрашивай полный корпус, если решение зависит только от ограниченной актуальной части.
Для рекомендации, планирования, приоритизации или выбора следующего результата не считай ход независимым от workspace только потому, что пользователь не перечислил источники. Сам выведи необходимые предпосылки и места, где они могут быть зафиксированы: например, планы, ограничения, очереди или незавершённые заготовки могут жить в разных доступных видах источников. Это примеры предпосылок, а не предписание вида источника: не делай notes, posts или analytics обязательными только из-за типа задачи. Сделай обязательным только тот источник, без которого рекомендация могла бы противоречить текущей работе, повторить уже сделанное или пропустить явную предпосылку. Каждую независимую предпосылку оформи отдельным source_requirement с самостоятельным query_goal. Источники должны затем сопоставляться по смыслу: история результатов полезна лишь в той мере, в какой она подтверждает выполнение, продолжение или конфликт с найденной предпосылкой. Если подходящих объектов в обязательном context-источнике нет, downstream должен иметь право выбрать ноль и не заполнять результат шумом. Если пропуск любого члена плана, очереди или backlog может изменить выбор, для соответствующего источника ставь coverage="complete": это требует полного обнаружения и смысловой оценки его каталога, но не выбора и не полного чтения каждого объекта. Для выбора следующего артефакта учитывай все lifecycle-состояния, в которых он может уже существовать или быть запланирован: для posts это обычно statuses=["draft", "scheduled", "published"]. Published показывает уже выполненное, draft — незавершённое, scheduled — уже принятое продолжение; не своди такой контекст к одной категории, если исходный запрос явно не ограничивает её. Используй bounded catalog_window с явными order/limit, ограниченным актуальным окном, а не полную историю. Косвенный источник делай обязательным только когда он даёт незаменимую предпосылку решения; тематический фон и дубли создают шум. Это семантическое выявление зависимостей, а не keyword routing: если рекомендация действительно не зависит от данных workspace, выбери finish. Для каждого source_requirement верни query_goal без предполагаемого ответа и без ключевых слов вместо вопроса.
Если передан блок "Диалог" — используй его, чтобы понять контекст запроса. Короткая правка твоего предыдущего ответа без новых фактических вопросов (перефразируй, покороче, на другом языке, другим тоном) — это "finish", даже если предыдущий ответ был по фактам workspace: факты уже собраны и лежат в диалоге, повторный поиск не нужен.
Если передан блок "Текущий пост" и пользователь просит изменить его текст (убрать/добавить/переформулировать что-то в посте) — верни ровно {"type":"post_proposal","command":"edit_post","payload":{}}. Полный текст поста и его id проставляются отдельным детерминированным шагом — тебе НЕ нужно возвращать ни текст, ни id здесь, только классифицировать запрос как edit_post. Если блока "Текущий пост" нет, НЕ выбирай post_proposal: запрос на изменение серии или постов означает, что сначала нужно найти соответствующие материалы workspace, поэтому выбирай read.

Перед возвратом read или finish выполни контрфактуальный route gate и добавь поле
"workspace_dependency": {"basis":"workspace_state|dialog_or_general_knowledge", "empty_workspace":"answer_changes|answer_unchanged", "anchor":"explicit_workspace_reference|decision_prerequisite|general_advice"}.
Ответь сначала на вопрос: если убрать все сохранённые заметки, посты, вложения и метрики,
останется ли полноценный ответ на текущий запрос из его текста, диалога и общих знаний?
Выбирай finish и значения dialog_or_general_knowledge/answer_unchanged, когда ответ не
зависит от пользовательского workspace; наличие похожих объектов, примеров или расширений
файлов само по себе не меняет ответ. Выбирай read и workspace_state/answer_changes только
когда без фактов workspace ответ неполон или его содержание существенно изменится.
Не делай read из желания персонализировать общий совет и не делай finish для фактического
вопроса о состоянии, содержимом или истории workspace. Поля должны отражать именно эту
проверку, а не повторять выбранный type.
anchor="explicit_workspace_reference" допустим только когда запрос или диалог явно просит
ответ по сохранённым данным, своей истории, правилам, политике либо конкретным объектам
workspace. Не считай упоминание предметной области таким указанием: вопрос о формате постов
не ссылается на workspace лишь потому, что в workspace есть посты или изображения.
anchor="decision_prerequisite" используй для recommendation/synthesis, когда фактический план,
ограничение, очередь или выполненная работа способны изменить решение. Для общего совета,
нормы или best practice без явной workspace-опоры используй general_advice и finish.

Для "read" добавь поле "search_query" — самодостаточный resolved goal для поиска и последующего Context Selector. Это должен быть один грамматический вопрос, который сохраняет точный предмет, запрошенный predicate, отрицание, условность и причинность исходного запроса; разреши в нем анафоры из диалога, но не превращай вопрос в список ключевых слов и не расширяй его соседними темами. В search_query назови только активный референт: имена объектов, явно исключенных или противопоставленных в диалоге, не упоминай даже с отрицанием. Не отвечай на вопрос внутри search_query, не добавляй гипотезы, предполагаемые факты или альтернативные predicates. Для cross-record сравнения вырази обе уже запрошенные стороны как явные retrieval predicates и затем само сравнение: что указал draft/proposed record, что указал final/signed record и совпадают ли значения; не добавляй сами значения. Если анафор нет и это не сравнение, сохрани исходный вопрос, ограничившись грамматической нормализацией и явным названием уже указанного предмета. Для "finish" поле не требуется и может быть пустым. Не пытайся превратить материалы прошлого ответа в один целевой DB-объект."""


def _apply_classifier_dependency_gate(call: Mapping[str, Any]) -> dict[str, Any]:
    """Honor the reasoner's explicit empty-workspace counterfactual."""

    result = dict(call or {})
    if str(result.get("type") or "") not in {"read", "finish"}:
        return result
    dependency = result.get("workspace_dependency")
    if not isinstance(dependency, Mapping):
        return result
    basis = str(dependency.get("basis") or "").strip()
    empty_workspace = str(dependency.get("empty_workspace") or "").strip()
    workspace_anchor = str(dependency.get("anchor") or "").strip()
    if basis == "dialog_or_general_knowledge" and empty_workspace == "answer_unchanged":
        return {
            **result,
            "type": "finish",
            "requires_evidence": False,
            "required_sources": [],
            "source_requirements": [],
            "search_query": "",
            "workspace_dependency_gate": "finish_empty_workspace_unchanged",
        }
    source_modalities = [
        str(item.get("claim_modality") or "")
        for item in result.get("source_requirements") or ()
        if isinstance(item, Mapping)
    ]
    if (
        str(result.get("type") or "") == "read"
        and str(result.get("task_profile") or "") == "topical_answer"
        and bool(source_modalities)
        and all(value == "normative" for value in source_modalities)
        and workspace_anchor != "explicit_workspace_reference"
    ):
        return {
            **result,
            "type": "finish",
            "requires_evidence": False,
            "required_sources": [],
            "source_requirements": [],
            "search_query": "",
            "workspace_dependency_gate": "finish_unanchored_normative_advice",
        }
    return result

WORKSPACE_CONTRACT_REPAIR_SYSTEM = """Исправь только внутреннюю согласованность уже выбранного read-контракта.
Верни один полный исправленный JSON tool call в том же формате, без markdown и пояснений.
Сохрани исходный запрос, type="read" и все уже обязательные виды источников. Не добавляй источники для фона.
Для каждого обязательного источника сохрани самостоятельный query_goal и согласуй predicate_kind,
claim_modality, coverage, discovery_mode, statuses/order/candidate_limit, evidence_granularity и evidence_requirements.
Обязательный context-источник означает, что его нужно исследовать, а не что из него обязательно
нужно выбрать хотя бы один объект. Если релевантных объектов нет, downstream должен иметь право
выбрать ноль; не заполняй результат шумом. Но если содержимое context-источника способно повлиять
на рекомендацию или синтез, нельзя одновременно объявлять его чисто structural и запрещать выбор
объектов через max=0: выбери semantic или mixed с положительным max. Structural допустим только
когда независимую цель источника полностью доказывают конкретные поля каталога или метаданные."""

_CLASSIFIER_SOURCE_KINDS = resource_kinds(classifier_visible=True)
_CATALOG_WINDOW_DIRECTIONS = frozenset({"asc", "desc"})
_CATALOG_WINDOW_MAX_CANDIDATES = 12
_DECISION_TASK_PROFILES = frozenset({"workspace_synthesis", "recommendation"})
_ANSWER_OBLIGATION_ORIGINS = frozenset(
    {
        "fact",
        "candidate_plan",
        "unfinished_state",
        "constraint_signal",
        "decision_history",
        "ordered_decision_history",
        "workflow_premise",
        "comparison_side",
        "member_predicate",
        "mapping_premise",
        "mapping_member",
        "synthesis_operation",
    }
)
_DECISION_POST_SELECTION_MAX = 5
_CLASSIFIER_CONTRACT_REPAIR_TIMEOUT_MS = 15_000
_CATALOG_STRUCTURAL_PROPERTIES_BY_KIND = {
    "notes": frozenset(
        {
            "id",
            "ref",
            "title",
            "status",
            "revision",
            "parent",
            "parent_post_id",
            "created_at",
            "total_members",
            "total_notes",
            *(value.partition(".")[2] for value in NOTE_PROPERTIES),
        }
    ),
    "posts": frozenset(
        {
            "id",
            "ref",
            "title",
            "status",
            "revision",
            "position",
            "created_at",
            "total_members",
            "total_posts",
            *(value.partition(".")[2] for value in POST_PROPERTIES),
        }
    ),
}


def _catalog_can_prove_requirements(
    kind: str,
    requirements: list[dict[str, Any]],
) -> bool:
    supported = _CATALOG_STRUCTURAL_PROPERTIES_BY_KIND.get(kind)
    if supported is None:
        return True
    return bool(requirements) and all(
        str(item.get("property") or "") in supported for item in requirements
    )
_ORDERED_DECISION_HISTORY_QUERY_GOAL = (
    "Определи, какие позиции этой ограниченной упорядоченной истории подтверждают "
    "уже выполненное, запланированное или незавершённое продолжение, либо конфликт "
    "с другими предпосылками текущего решения; учитывай статус каждой позиции. "
    "Позиции могут содержать явно выраженные темы, интересы, отклики, ограничения "
    "или иные самостоятельные сигналы, которые способны изменить решение. Выбери "
    "ноль, если ни одна позиция не влияет на решение; одна только давность не делает "
    "позицию релевантной."
)
_ORDERED_DECISION_HISTORY_OBLIGATION = (
    "уже выполненное, запланированное или незавершённое продолжение, тема, "
    "интерес, отклик, ограничение либо конфликт, способные изменить текущее решение"
)
_RECOMMENDATION_CANDIDATE_PLAN_OBLIGATION = (
    "явно зафиксированный будущий кандидат, план, очередь или серия, способные "
    "определить следующий результат"
)


def _classified_scope_statuses(
    kind: str,
    classified: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate the reasoner's resource filter against the posts capability."""

    raw = classified.get("statuses")
    if not isinstance(raw, (list, tuple)):
        scope = classified.get("scope")
        raw = scope.get("statuses") if isinstance(scope, Mapping) else ()
    descriptor = get_resource_descriptor(kind)
    supported_statuses = descriptor.catalog_statuses if descriptor is not None else ()
    if not supported_statuses or not isinstance(raw, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(
            status
            for item in raw
            if (status := str(item or "").strip().lower()) in supported_statuses
        )
    )


_EXPLICIT_POST_STATUS_FILTER_RE = re.compile(
    r"(?:"
    r"\b(?:drafts?|scheduled|published|unpublished|completed|statuses?)\b|"
    r"\b(?:brouillons?|planifi(?:e|es|ee|ees)|publi(?:e|es|ee|ees))\b|"
    r"\b(?:черновик\w*|запланированн\w*|отложенн\w*|опубликованн\w*|неопубликованн\w*)\b"
    r")",
    re.IGNORECASE,
)


def _has_explicit_post_status_filter(query: str) -> bool:
    """Distinguish a lifecycle predicate from an action such as "publish"."""

    return bool(_EXPLICIT_POST_STATUS_FILTER_RE.search(str(query or "")))


_EXPLICIT_ATTACHMENT_PREDICATE_RE = re.compile(
    r"\b(?:вложен\w*|прикрепл\w*|attachment\w*|file\w*|файл\w*|image\w*|изображен\w*|фото\w*)\b",
    re.IGNORECASE,
)
_COMPLETE_INVENTORY_RE = re.compile(
    r"(?:\b(?:все|всё|кажд\w*|перечисл\w*|список|сколько|count|every|list\s+all|all)\b)",
    re.IGNORECASE,
)
_EXPLICIT_INVENTORY_COUNT_RE = re.compile(
    r"\b(?:какие|какой|какая|какое|назов\w*|перечисл\w*|укаж\w*|"
    r"what|which|list|name)\b"
    r"[^?\n]{0,36}?\b(?P<count>\d{1,2}|один|одна|одно|два|две|три|четыре|пять|"
    r"шесть|семь|восемь|девять|десять|one|two|three|four|five|six|seven|eight|"
    r"nine|ten)\b",
    re.IGNORECASE,
)
_EXPLICIT_INVENTORY_COUNTS = {
    "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
    "восемь": 8, "девять": 9, "десять": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RECORD_MEMBER_WORD_RE = re.compile(
    r"\b(?:замет\w*|пост(?:ы|а|ов|у|ом|е|ам|ами|ах)?|материал\w*|файл\w*|изображен\w*|"
    r"note\w*|post\w*|material\w*|file\w*|image\w*)\b",
    re.IGNORECASE,
)


def _explicit_inventory_cardinality(query: str) -> tuple[int, str] | None:
    """Extract only an explicit list cardinality, independent of the LLM."""

    match = _EXPLICIT_INVENTORY_COUNT_RE.search(str(query or ""))
    if match is None:
        return None
    raw = str(match.group("count") or "").casefold()
    count = int(raw) if raw.isdigit() else _EXPLICIT_INVENTORY_COUNTS.get(raw)
    if count is None or not 1 <= count <= 100:
        return None
    # A record noun immediately after the number means the members are
    # workspace objects; otherwise the question enumerates values inside them.
    tail_words = re.findall(r"[\wА-Яа-яЁё-]+", str(query or "")[match.end():])[:3]
    tail = " ".join(tail_words)
    unit = "record" if _RECORD_MEMBER_WORD_RE.search(tail) else "value"
    return count, unit
_COMPOSITION_RE = re.compile(
    r"(?:\b(?:сравн\w*|сопостав\w*|свяж\w*|связ\w*|объедин\w*|соответств\w*|между|сквозн\w*|складыва\w*|план\w*.*пост\w*|post\w*.*note\w*|note\w*.*post\w*)\b)",
    re.IGNORECASE,
)
_CROSS_RECORD_AUDIT_RE = re.compile(
    r"\b(?:сопостав\w*|сравн\w*|соответств\w*|аудит\w*|match\w*|map\w*|audit\w*)\b",
    re.IGNORECASE,
)
_CROSS_RECORD_COMPARISON_RE = re.compile(
    r"\b(?:противореч\w*|совместим\w*|согласу\w*|конфликт\w*|расхожд\w*|"
    r"contradic\w*|compatib\w*|consisten\w*|conflict\w*|disagree\w*|"
    r"coh[eé]ren\w*|widerspr\w*|vereinbar\w*|konflikt\w*)\b",
    re.IGNORECASE,
)


def _classifier_query_source_kinds(query: str) -> tuple[str, ...]:
    """Return only source kinds explicitly named by the frozen user query."""

    lowered = str(query or "").casefold()
    kinds: list[str] = []
    if re.search(r"(?:\b(?:замет(?:ка|ки|ок|ке|ку|кой|ками|ках)|notes?)\b)", lowered):
        kinds.append("notes")
    if re.search(
        r"(?:\b(?:пост(?:ы|ов|ам|ами|ах|а|у|ом|е)?|posts?)\b)", lowered
    ):
        kinds.append("posts")
    if _EXPLICIT_ATTACHMENT_PREDICATE_RE.search(lowered):
        # Attachments are still not admitted as an independent source here. They
        # must enter through a verified parent relation in the catalog assembler.
        # The marker is used only to prevent a model hallucination from creating
        # an attachment obligation for an unrelated query.
        kinds.append("attachments")
    return tuple(dict.fromkeys(kinds))


def _canonical_post_statuses(query: str) -> tuple[str, ...]:
    """Compile explicit lifecycle words without accepting model-added filters."""

    lowered = str(query or "").casefold()
    statuses: list[str] = []
    object_word = r"(?:пост\w*|материал\w*|публикац\w*|posts?|materials?|publications?)"
    if re.search(
        rf"\b(?:drafts?|brouillons?|черновик\w*)\b(?:\W+\w+){{0,2}}\W+{object_word}\b",
        lowered,
    ):
        statuses.append("draft")
    if re.search(
        rf"\b(?:scheduled|planifi\w*|запланированн\w*|отложенн\w*)\b(?:\W+\w+){{0,2}}\W+{object_word}\b",
        lowered,
    ):
        statuses.append("scheduled")
    if re.search(
        rf"\b(?:published|publi\w*|опубликованн\w*)\b(?:\W+\w+){{0,2}}\W+{object_word}\b",
        lowered,
    ):
        statuses.append("published")
    return tuple(dict.fromkeys(statuses))


def _atomic_query_obligations(query: str) -> tuple[str, ...]:
    """Compile stable semantic premises from clauses in the frozen query."""

    normalized = " ".join(str(query or "").strip().rstrip("?.!").split())
    if not normalized:
        return ()
    body = normalized.split(":", 1)[-1].strip()
    comma_parts = [part.strip(" ,;") for part in body.split(",") if part.strip(" ,;")]
    comma_clause_mode = len(comma_parts) >= 3
    if len(comma_parts) > 1 and re.match(
        r"^(?:that|what|whether|how|which|who|why|where|when|"
        r"что|будто|как|какой|какие|кто|почему|где|когда|"
        r"que|quoi|si|comment|quel|quelle|qui|pourquoi|où|quand|"
        r"dass|ob|wie|welche|wer|warum|wo|wann|"
        r"che|se|come|quale|chi|perché|dove|quando)\b",
        comma_parts[1],
        flags=re.IGNORECASE,
    ):
        # A reporting preamble ("the source says, that ...") is not an
        # independently falsifiable obligation. Keep it attached to its
        # complement so the classifier receives a self-contained claim.
        comma_parts[:2] = [f"{comma_parts[0]}, {comma_parts[1]}"]
    obligations: list[str] = []
    if comma_clause_mode:
        tail = comma_parts[-1]
        tail_parts = re.split(r"\s+(?:и|and)\s+", tail, maxsplit=1, flags=re.IGNORECASE)
        obligations.extend(comma_parts[:-1])
        obligations.extend(part.strip() for part in tail_parts if part.strip())
    else:
        clause_parts = re.split(
            r"\s+(?:и|а\s+также|но|and|as\s+well\s+as|but)\s+"
            r"(?=(?:как|какие|какой|какими|что|почему|где|когда|кто|сколько|"
            r"how|which|what|why|where|when|who)\b)",
            body,
            maxsplit=11,
            flags=re.IGNORECASE,
        )
        obligations.extend(part.strip() for part in clause_parts if part.strip())

    # Coordinated predicates are independent workflow stages even when they
    # share an object ("prepare and publish a post"). Split only when both
    # sides have an infinitive shape; ordinary noun coordination remains one
    # obligation. The shared suffix is copied to both clauses so each remains
    # self-contained and falsifiable.
    coordinated: list[str] = []
    predicate_patterns = (
        re.compile(
            r"(?P<left>\b[\w-]+(?:ть|ти|чь)(?:ся)?)\s+"
            r"(?:и|или)\s+(?P<right>[\w-]+(?:ть|ти|чь)(?:ся)?)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<left>\b(?:to\s+)?[a-z][\w-]*)\s+"
            r"(?:and|or)\s+(?P<right>[a-z][\w-]*)\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<left>\b[\w-]+(?:er|ir|re|ar))\s+"
            r"(?:et|ou|y|e)\s+(?P<right>[\w-]+(?:er|ir|re|ar))\b",
            flags=re.IGNORECASE,
        ),
    )
    for obligation in obligations:
        split_match = next(
            (pattern.search(obligation) for pattern in predicate_patterns), None
        )
        if split_match is None:
            coordinated.append(obligation)
            continue
        left = split_match.group("left")
        right = split_match.group("right")
        prefix = obligation[: split_match.start("left")]
        suffix = obligation[split_match.end("right") :]
        left_text = f"{prefix}{left}{suffix}".strip()
        right_prefix = prefix
        if left.casefold().startswith("to ") and not right.casefold().startswith("to "):
            right_prefix = f"{prefix}to "
        right_text = f"{right_prefix}{right}{suffix}".strip()
        coordinated.extend(item for item in (left_text, right_text) if item)
    obligations = coordinated

    # Keep a relation question as one self-contained obligation. Splitting
    # "how are X and Y connected" into fragments makes each fragment
    # ungrammatical and lets a broad overview row masquerade as proof for both
    # sides. Post-read labels can keep multiple indispensable rows for the one
    # relation without inventing duplicate obligations.

    # A short follow-up such as "why not the second?" has no subject of its
    # own. Attach it to the preceding premise before the Query IR is frozen.
    # These are grammatical anaphora markers, not material or scenario terms.
    dependent_clause = re.compile(
        r"^(?:and|и|а\s+также|but|но)?\s*"
        r"(?:why|почему|зачем|how|как|что|what)\b.*\b"
        r"(?:first|second|third|other|another|latter|former|"
        r"перв\w*|втор\w*|треть\w*|друг\w*|остальн\w*)\b",
        flags=re.IGNORECASE,
    )
    if len(obligations) > 1 and any(
        dependent_clause.search(item) for item in obligations[1:]
    ):
        merged: list[str] = []
        for item in obligations:
            if merged and dependent_clause.search(item):
                merged[-1] = f"{merged[-1].rstrip(' ,;')}, {item.lstrip(' ,;')}"
            else:
                merged.append(item)
        obligations = merged

    # Resolve clause-local demonstratives against the preceding frozen query
    # clauses. This keeps follow-ups such as "what enables this?" and "is there
    # a contradiction here?" source-neutral but self-contained; candidate text
    # never participates in the resolution.
    anaphora_re = re.compile(
        r"\b(?:это(?:го|му|м)?|этим|здесь|this|that|it|these|those|here|"
        r"cela|ceci|ça|eso|esto|ello|aquí|das|dies|hier)\b",
        flags=re.IGNORECASE,
    )
    resolved_obligations: list[str] = []
    for index, obligation in enumerate(obligations):
        if resolved_obligations and anaphora_re.search(obligation):
            antecedent = "; ".join(obligations[:index])
            resolved_obligations.append(
                f"{obligation} [referent: {antecedent}]"
            )
        else:
            resolved_obligations.append(obligation)
    obligations = resolved_obligations
    if not obligations:
        obligations.append(body)
    result: list[str] = []
    seen: set[str] = set()
    for item in obligations:
        cleaned = " ".join(item.strip(" ,;").split())[:400]
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= 12:
            break
    return tuple(result)


def _planner_query_obligation_specs(
    classified: Any,
) -> tuple[tuple[str, str], ...]:
    """Normalize candidate-independent obligations without losing their type."""

    if not isinstance(classified, list):
        return ()
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in classified:
        raw_origin = (
            str(item.get("origin") or "").strip()
            if isinstance(item, Mapping)
            else ""
        )
        if isinstance(item, Mapping) and raw_origin not in _ANSWER_OBLIGATION_ORIGINS:
            continue
        description = (
            str(item.get("description") or item.get("property") or "")
            if isinstance(item, Mapping)
            else str(item)
            if isinstance(item, str)
            else ""
        )
        normalized = " ".join(description.strip().split())[:400]
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        origin = raw_origin
        seen.add(key)
        result.append((normalized, origin))
        if len(result) >= 12:
            break
    return tuple(result)


def _planner_query_obligations(classified: Any) -> tuple[str, ...]:
    """Return descriptions for callers that do not consume obligation types."""

    return tuple(
        description
        for description, _origin in _planner_query_obligation_specs(classified)
    )


def _finite_comparison_query(query: str) -> bool:
    """Keep a finite alternative comparison in its record-oriented route."""

    lowered = str(query or "").casefold()
    return bool(
        re.search(
            r"\b(?:\u043a\u0430\u043a\u043e\u0439|\u043a\u0430\u043a\u0430\u044f|\u043a\u043e\u0442\u043e\u0440\u044b\u0439|\u0432\u044b\u0431\u0440\u0430\u0442\u044c|\u043f\u043e\u0447\u0435\u043c\u0443\s+\u043d\u0435\s+\u0432\u0442\u043e\u0440\u043e\u0439|"
            r"which|which\s+one|choose\s+between|why\s+not\s+the\s+other|"
            r"lequel|laquelle|choisir\s+entre|pourquoi\s+pas\s+le\s+second)\b",
            lowered,
            flags=re.IGNORECASE,
        )
    )


def _semantic_classifier_delta(
    contract: Mapping[str, Any],
    call: Mapping[str, Any],
    *,
    user_text: str,
) -> dict[str, Any]:
    """Compile the model's semantic hint into a stable, bounded delta.

    The bootstrap model owns the candidate-independent semantic obligations and
    answer shape. Runtime validates their bounds and owns executable retrieval
    policy: source capabilities, scope, cardinality, fidelity and status guards.
    This function deliberately drops optional LLM policy fields before
    materialization.
    """

    result = dict(call or {})
    query = str(user_text or "").strip()
    explicit_kinds = set(_classifier_query_source_kinds(query))
    baseline_kinds = {
        str(source.get("kind") or "")
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
    }
    baseline_by_kind = {
        str(source.get("kind") or ""): dict(source)
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping) and str(source.get("kind") or "")
    }
    model_kinds = {
        str(item).strip().lower()
        for item in result.get("required_sources") or ()
        if str(item).strip().lower() in baseline_kinds
    }
    model_kinds.update(
        str(item.get("kind") or "").strip().lower()
        for item in result.get("source_requirements") or ()
        if isinstance(item, Mapping)
        and str(item.get("kind") or "").strip().lower() in baseline_kinds
    )
    # Explicit query predicates are authoritative. Otherwise retain only the
    # classifier's bounded primary-source intent; never admit a new source kind.
    explicit_primary = explicit_kinds & baseline_kinds
    selected_kinds = (
        explicit_primary
        if explicit_primary
        else explicit_primary | model_kinds
    )
    raw_profile = str(result.get("task_profile") or "").strip()
    profile_is_semantic = raw_profile in {
        "topical_answer",
        "recommendation",
        "workspace_synthesis",
        "comparison",
        "exhaustive_inventory",
    }
    resolved_query_ir_specs = _planner_query_obligation_specs(
        result.get("answer_obligations")
    )
    resolved_answer_operations = tuple(
        description
        for description, origin in resolved_query_ir_specs
        if origin == "synthesis_operation"
    )
    resolved_query_obligation_specs = tuple(
        (description, origin)
        for description, origin in resolved_query_ir_specs
        if origin != "synthesis_operation"
    )
    resolved_query_obligations = tuple(
        description for description, _origin in resolved_query_obligation_specs
    )
    resolved_obligation_origins = dict(resolved_query_obligation_specs)
    parsed_query_obligations = _atomic_query_obligations(query)
    apparent_contradiction = bool(
        _CROSS_RECORD_COMPARISON_RE.search(query)
        and not _finite_comparison_query(query)
    )
    planner_obligations_valid = bool(resolved_query_obligations) and not (
        apparent_contradiction and len(resolved_query_obligations) != 3
    )
    query_obligations = (
        tuple(dict.fromkeys(resolved_query_obligations))[:12]
        if planner_obligations_valid
        else parsed_query_obligations
    )
    fallback_complete = bool(_COMPLETE_INVENTORY_RE.search(query))
    fallback_composition = bool(_COMPOSITION_RE.search(query))
    fallback_cross_record = bool(_CROSS_RECORD_AUDIT_RE.search(query))
    fallback_cross_record_comparison = bool(
        not fallback_complete
        and len(query_obligations) > 1
        and _CROSS_RECORD_COMPARISON_RE.search(query)
    )
    classified_profile = (
        raw_profile
        if profile_is_semantic
        else "exhaustive_inventory"
        if fallback_complete
        else "workspace_synthesis"
        if fallback_composition or fallback_cross_record
        else "topical_answer"
    )
    raw_shape = result.get("answer_shape")
    classified_shape = (
        str(raw_shape.get("kind") or "").strip()
        if isinstance(raw_shape, Mapping)
        else ""
    )
    shape_is_semantic = classified_shape in {
        "freeform",
        "scalar",
        "record",
        "inventory",
    }
    if not shape_is_semantic:
        classified_shape = (
            "inventory" if fallback_complete or fallback_cross_record else "freeform"
        )
    expected_member_count = (
        raw_shape.get("expected_member_count")
        if isinstance(raw_shape, Mapping)
        and type(raw_shape.get("expected_member_count")) is int
        and raw_shape["expected_member_count"] >= 0
        else None
    )
    inventory_unit = (
        str(raw_shape.get("inventory_unit") or "").strip()
        if isinstance(raw_shape, Mapping)
        else ""
    )
    if classified_shape != "inventory" or inventory_unit not in {"record", "value"}:
        inventory_unit = ""
    explicit_inventory = _explicit_inventory_cardinality(query)
    if explicit_inventory is not None and classified_profile != "recommendation":
        # An explicit user cardinality is a structural Query IR predicate. It
        # cannot be downgraded to scalar/record by a provider's semantic hint.
        explicit_count, explicit_unit = explicit_inventory
        classified_shape = "inventory"
        expected_member_count = explicit_count
        inventory_unit = explicit_unit
    raw_mode = str(result.get("selection_mode") or "").strip()
    semantic_modes = {
        "record",
        "composition",
        "cross_record_comparison",
        "member_inventory",
        "cross_record_inventory",
    }
    # The bootstrap classifier is the sole owner of semantic answer shape. Its
    # bounded decision is frozen here; later retrieval calls only label evidence
    # against these obligations and cannot reinterpret record vs composition.
    # Structural query predicates remain deterministic boundary overrides.
    if _finite_comparison_query(query) and classified_shape != "inventory":
        # A bounded choice between named/ordinal alternatives asks for one
        # coherent comparison record. This is an answer-cardinality boundary,
        # not a semantic verdict about which candidate wins.
        classified_mode = "record"
    elif fallback_cross_record_comparison:
        classified_mode = "cross_record_comparison"
    elif fallback_cross_record:
        classified_mode = "cross_record_inventory"
    elif raw_mode in semantic_modes:
        classified_mode = (
            "composition"
            if raw_mode == "cross_record_inventory"
            and not fallback_complete
            else raw_mode
        )
    elif classified_shape == "inventory":
        classified_mode = "member_inventory"
    elif classified_profile in {"workspace_synthesis", "recommendation"}:
        classified_mode = "composition"
    elif classified_profile in {"topical_answer", "comparison"}:
        classified_mode = "record"
    elif fallback_composition:
        classified_mode = "composition"
    else:
        classified_mode = "record"
    if (
        classified_shape == "inventory"
        and inventory_unit == "record"
        and classified_profile in {"topical_answer", "comparison", "exhaustive_inventory"}
        and classified_mode != "cross_record_inventory"
    ):
        # A topical record inventory classifies each finite-corpus object
        # against one positive inclusion predicate. Multiple answer clauses do
        # not turn the final member set into a composition task.
        classified_mode = "member_inventory"
    if classified_shape == "inventory" and inventory_unit == "value" and classified_mode in {
        "member_inventory",
        "cross_record_inventory",
    }:
        classified_mode = (
            "composition"
            if classified_profile in {"workspace_synthesis", "recommendation"}
            and len(query_obligations) > 1
            else "record"
        )
    if (
        classified_mode == "record"
        and (len(query_obligations) > 1 or fallback_composition)
        and not _finite_comparison_query(query)
    ):
        # `record` limits the evidence pack to one object. That is coherent for
        # a finite comparison whose alternatives may be defined together, but
        # it cannot erase independently falsifiable clauses from an otherwise
        # compositional question. Composition still permits one sufficient row;
        # it merely stops the bootstrap route from forbidding a second proof.
        classified_mode = "composition"
    declared_source_kinds = selected_kinds & model_kinds
    if (
        classified_mode == "record"
        and len(declared_source_kinds) > 1
        and len(query_obligations) > 1
        and not _finite_comparison_query(query)
    ):
        # A one-record pack cannot satisfy disjoint corpora which the same
        # frozen planner output declared independently necessary. Resolve this
        # structural contradiction from Query IR fields, without inspecting
        # query wording or candidate content.
        classified_mode = (
            "cross_record_comparison"
            if classified_profile in {"topical_answer", "comparison"}
            else "composition"
        )
    if classified_profile == "recommendation":
        # An open decision is not an inventory of already-existing members.
        # The model owns the semantic profile; runtime owns this coherence
        # invariant so an incompatible shape cannot turn decision context into
        # select-every-member behavior.
        classified_shape = "freeform"
        expected_member_count = None
        if classified_mode in {"member_inventory", "cross_record_inventory"}:
            classified_mode = "composition"
    source_neutral_workspace = (
        result.get("type") == "read"
        and not explicit_primary
        and {"notes", "posts"}.issubset(baseline_kinds)
    )
    relation_needs_both_corpora = (
        classified_mode
        in {"composition", "cross_record_comparison", "cross_record_inventory"}
        and {"notes", "posts"}.issubset(baseline_kinds)
    )
    if (source_neutral_workspace or relation_needs_both_corpora) and result.get("type") == "read":
        # Preserve both corpora for recall. Membership is decided only after
        # full-read labeling, so this does not by itself add material to pack.
        selected_kinds.update(
            kind for kind in ("notes", "posts") if kind in baseline_kinds
        )
    if not profile_is_semantic and classified_mode in {
        "composition",
        "cross_record_comparison",
        "cross_record_inventory",
    }:
        selected_kinds.update(
            kind for kind in ("notes", "posts") if kind in baseline_kinds
        )
    complete = classified_mode in {"member_inventory", "cross_record_inventory"}
    classified_requirements = {
        str(item.get("kind") or "").strip().lower(): item
        for item in result.get("source_requirements") or ()
        if isinstance(item, Mapping)
        and str(item.get("kind") or "").strip().lower() in selected_kinds
    }
    classified_complete_kinds = {
        kind
        for kind, item in classified_requirements.items()
        if str(item.get("coverage") or "") == "complete"
    }
    cross_record_member_kinds = (
        classified_complete_kinds or model_kinds or explicit_primary
    )
    descriptors: list[dict[str, Any]] = []
    for kind in sorted(selected_kinds):
        if kind == "attachments":
            continue
        baseline = baseline_by_kind.get(kind, {})
        classified_source = classified_requirements.get(kind) or {}
        baseline_predicate = str(baseline.get("predicate_kind") or "semantic")
        complete_source = bool(
            classified_mode == "member_inventory"
            or (
                classified_mode == "cross_record_inventory"
                and (
                    not cross_record_member_kinds
                    or kind in cross_record_member_kinds
                )
            )
        )
        descriptor: dict[str, Any] = {
            "kind": kind,
            "query_goal": str(classified_source.get("query_goal") or query)[:1000],
            "coverage": "complete" if complete_source else "relevant",
            "predicate_kind": baseline_predicate,
            "evidence_granularity": (
                "catalog" if baseline_predicate == "structural" else "semantic_card"
            ),
            "claim_modality": (
                str(classified_source.get("claim_modality") or "").strip()
                if str(classified_source.get("claim_modality") or "").strip()
                in {"descriptive", "normative"}
                else "descriptive"
            ),
        }
        if baseline_predicate in {"structural", "mixed"}:
            descriptor["evidence_requirements"] = [
                dict(item)
                for item in baseline.get("evidence_requirements") or ()
                if isinstance(item, Mapping)
            ]
        elif isinstance(classified_source.get("evidence_requirements"), list):
            descriptor["evidence_requirements"] = [
                {
                    "property": str(item.get("property") or "")[:400],
                    "operator": "exists",
                    "scope": "source",
                }
                for item in classified_source["evidence_requirements"][:12]
                if isinstance(item, Mapping)
                and str(item.get("property") or "").strip()
            ]
        if kind == "posts" and (
            classified_profile == "recommendation"
            or classified_mode == "cross_record_inventory"
        ):
            # Open decisions must observe already completed, committed and
            # unfinished work. Cross-record audits likewise classify lifecycle
            # as part of the result; filtering members by the requested outcome
            # before the mapping would make negative/draft matches invisible.
            descriptor["statuses"] = ["draft", "scheduled", "published"]
            descriptor["_runtime_lifecycle_scope"] = "all_member_states"
            if classified_profile == "recommendation":
                baseline_limit = int(
                    (baseline.get("budget") or {}).get("candidate_limit") or 6
                )
                descriptor.update(
                    {
                        "discovery_mode": "catalog_window",
                        "order_dependency": "required",
                        "_runtime_order_dependency": "decision_history",
                        "order_by": "created_at",
                        "order_direction": "desc",
                        "candidate_limit": min(
                            _CATALOG_WINDOW_MAX_CANDIDATES,
                            max(1, baseline_limit),
                        ),
                    }
                )
        elif _has_explicit_post_status_filter(query) and kind == "posts":
            descriptor["statuses"] = list(_canonical_post_statuses(query))
        descriptors.append(descriptor)
    if result.get("type") == "read" and not selected_kinds:
        # Keep an unanchored read answerable with an empty pack instead of letting
        # an optional classifier descriptor invent a source boundary.
        descriptors = []
    # Answer shape constrains the final pack cardinality; it must not rewrite
    # the planner's independently falsifiable evidence premises back into one
    # answer-shaped question. A single record may still prove several premises,
    # but the post-read labeler must verify each premise explicitly.
    semantic_obligations = list(
        query_obligations
        if resolved_query_obligations
        else (query,) if classified_mode == "record" and query else query_obligations
    )
    semantic_obligation_source_kinds: dict[str, tuple[str, ...]] = {}
    semantic_obligation_origins = {
        description: origin
        for description in semantic_obligations
        for origin in [resolved_obligation_origins.get(description, "")]
        if origin
    }
    if classified_mode == "cross_record_inventory":
        # Cross-record membership must be decidable for one opened row at a
        # time. Planner outputs such as "members exist" or "every member is
        # mapped" are aggregate conclusions and make row-local labels
        # logically impossible. The already frozen source coverage supplies
        # the two roles without inspecting query wording: relevant sources
        # define the premise set, complete sources contain candidate members.
        row_local_obligations: list[str] = []
        explicit_premise_present = any(
            str(descriptor.get("coverage") or "") != "complete"
            for descriptor in descriptors
        )
        for descriptor_index, descriptor in enumerate(descriptors):
            requirements = [
                str(item.get("property") or "").strip()
                for item in descriptor.get("evidence_requirements") or ()
                if isinstance(item, Mapping)
                and str(item.get("property") or "").strip()
                not in {"grounded_evidence", "relevant_context"}
            ]
            predicate = "; ".join(requirements) or str(
                descriptor.get("query_goal") or query
            ).strip()
            is_premise = (
                str(descriptor.get("coverage") or "") != "complete"
                if explicit_premise_present
                else len(descriptors) >= 2 and descriptor_index == 0
            )
            role = (
                "premise, plan, index, or queue row that defines the mapping set"
                if is_premise
                else "individual result member whose own content satisfies the "
                "mapping predicate"
            )
            obligation = f"{role}: {predicate}".strip()[:1000]
            obligation_key = obligation.casefold()
            existing_obligation = next(
                (
                    item
                    for item in row_local_obligations
                    if item.casefold() == obligation_key
                ),
                None,
            )
            descriptor_kind = str(descriptor.get("kind") or "")
            if obligation and existing_obligation is not None:
                semantic_obligation_source_kinds[existing_obligation] = tuple(
                    dict.fromkeys(
                        (
                            *semantic_obligation_source_kinds.get(
                                existing_obligation, ()
                            ),
                            descriptor_kind,
                        )
                    )
                )
            elif obligation:
                row_local_obligations.append(obligation)
                semantic_obligation_source_kinds[obligation] = (
                    descriptor_kind,
                )
                semantic_obligation_origins[obligation] = (
                    "mapping_premise" if is_premise else "mapping_member"
                )
        if row_local_obligations:
            semantic_obligations = row_local_obligations[:12]
    if (
        classified_mode == "member_inventory"
        and inventory_unit == "record"
        and semantic_obligations
    ):
        # Unary member classification has one inclusion predicate. The planner
        # protocol places it first; excluded/negative classes are represented
        # by match=false rather than competing obligations.
        semantic_obligations = semantic_obligations[:1]
        semantic_obligation_origins = {
            semantic_obligations[0]: "member_predicate"
        }
    if _finite_comparison_query(query) and classified_mode == "record":
        # A finite comparison is one coherent answer record, but every frozen
        # premise is still a side or criterion of the same alternative set.
        # Canonicalize the semantic type so post-read cannot accept a generic
        # single-option fact as a substitute for that set.
        semantic_obligation_origins = {
            description: "comparison_side" for description in semantic_obligations
        }
    elif classified_profile == "recommendation":
        semantic_obligation_origins = {
            description: (
                "candidate_plan" if origin == "member_predicate" else origin
            )
            for description, origin in semantic_obligation_origins.items()
        }
    # An open recommendation is not a literal fact stored in one row. If the
    # bootstrap model emits only the raw question, freeze a checkable,
    # source-neutral premise instead: workspace themes and lifecycle state that
    # can change the recommendation. This keeps membership semantic and bounded
    # while preventing post-read classification from testing rows against an
    # answer-shaped question that no material can literally entail.
    if (
        classified_profile == "recommendation"
        and len(semantic_obligations) == 1
        and semantic_obligations[0].strip() == query
    ):
        semantic_obligations = [
            (
                "workspace themes, existing topics, and unfinished or published "
                "content that determine the requested recommendation: "
                + query
            )[:1000]
        ]
        semantic_obligation_origins = {
            semantic_obligations[0]: "candidate_plan"
        }
    evidence_kinds = {
        kind
        for kind in (
            explicit_primary
            if source_neutral_workspace
            else explicit_primary or model_kinds
        )
        if kind in selected_kinds and kind != "attachments"
    }
    result.update(
        {
            "search_query": query,
            "required_sources": sorted(evidence_kinds),
            "source_requirements": descriptors,
            "_runtime_source_neutral_discovery": bool(
                source_neutral_workspace or relation_needs_both_corpora
            ),
            "answer_shape": {
                "kind": classified_shape,
                "expected_member_count": (
                    expected_member_count if classified_shape == "inventory" else None
                ),
                "inventory_unit": inventory_unit or None,
            },
            "answer_obligations": [
                {
                    "description": description,
                    **(
                        {"origin": semantic_obligation_origins[description]}
                        if description in semantic_obligation_origins
                        else {}
                    ),
                    **(
                        {
                            "source_kinds": list(
                                semantic_obligation_source_kinds[description]
                            )
                        }
                        if description in semantic_obligation_source_kinds
                        else {}
                    ),
                }
                for description in semantic_obligations
            ],
            "answer_operations": [
                {
                    "operation_id": f"operation:{position}",
                    "description": description,
                    "kind": "synthesis",
                    "input_obligation_ids": [
                        f"answer:{index}"
                        for index in range(len(semantic_obligations))
                    ],
                }
                for position, description in enumerate(resolved_answer_operations)
            ],
            "selection_mode": classified_mode,
            "semantic_contract_source": "bootstrap_classifier",
        }
    )
    result["task_profile"] = classified_profile
    return result


def _classified_discovery_strategy(
    kind: str,
    classified: Mapping[str, Any],
    *,
    predicate_kind: str,
) -> tuple[str, str | None, str | None, int | None]:
    """Validate planner-controlled discovery against resource capabilities."""

    evidence_requirements = [
        item
        for item in classified.get("evidence_requirements") or ()
        if isinstance(item, Mapping)
        and str(item.get("property") or "").strip()
        and str(item.get("operator") or "")
        in {"exists", "count", "filter", "equals", "contains"}
        and str(item.get("scope") or "")
        in {"source", "target", "member", "corpus", "aggregate"}
    ]
    ordered_requirement = bool(
        classified.get("_runtime_order_dependency") == "decision_history"
        or any(
            str(item.get("scope") or "") in {"member", "corpus", "aggregate"}
            or str(item.get("operator") or "") in {"count", "filter"}
            for item in evidence_requirements
        )
    )
    if (
        str(classified.get("discovery_mode") or "") != "catalog_window"
        or str(classified.get("order_dependency") or "") != "required"
        or not ordered_requirement
    ):
        return "semantic_relevance", None, None, None
    order_by = str(classified.get("order_by") or "").strip().lower()
    order_direction = str(classified.get("order_direction") or "").strip().lower()
    statuses = _classified_scope_statuses(kind, classified)
    descriptor = get_resource_descriptor(kind)
    try:
        candidate_limit = int(classified.get("candidate_limit") or 0)
    except (TypeError, ValueError):
        candidate_limit = 0
    if (
        descriptor is None
        or predicate_kind != "semantic"
        or not statuses
        or order_by not in descriptor.catalog_order_fields
        or order_direction not in _CATALOG_WINDOW_DIRECTIONS
        or not 1 <= candidate_limit <= _CATALOG_WINDOW_MAX_CANDIDATES
    ):
        return "semantic_relevance", None, None, None
    return "catalog_window", order_by, order_direction, candidate_limit


def _contract_post_target_ids(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Return canonical post targets already bound by runtime state."""

    targets = (contract.get("target_contract") or {}).get("targets") or ()
    ids = [
        str(target.get("id") or "").strip()
        for target in targets
        if isinstance(target, Mapping)
        and str(target.get("kind") or "") == "post"
        and str(target.get("id") or "").strip()
    ]
    return tuple(dict.fromkeys(ids))
def _fast_path_needs_fidelity_classification(contract: dict[str, Any]) -> bool:
    """Return whether an implicit resolver selection still needs depth routing."""

    resolution = dict((contract.get("target_contract") or {}).get("referent_resolution") or {})
    return any(
        str(reference.get("selection_mode") or "") in {"all", "predicate", "complement"}
        for reference in resolution.get("references") or ()
        if isinstance(reference, dict)
    )


def _prompt_turn_contract(contract: Mapping[str, Any], *, legacy_resolver: bool) -> dict[str, Any]:
    """Keep retrieval/output policy while hiding legacy referent machinery."""
    result = dict(contract or {})
    if not legacy_resolver:
        result.pop("target_contract", None)
        result.pop("target_contract_ref", None)
        result.pop("target", None)
        result.pop("referent_resolution", None)
        result.pop("resolution_events", None)
    return result


def _apply_classifier_source_policy(
    contract: dict[str, Any],
    *,
    required_sources: list[str],
    classifier_requires_evidence: bool,
    classified_source_requirements: list[dict[str, Any]] | None = None,
    query_goal: str = "",
    forced_required_sources: set[str] | None = None,
    source_neutral_discovery: bool = False,
) -> dict[str, Any]:
    """Make semantic classifier output authoritative for factual grounding.

    Optional notes/posts enrichment remains available even when another source is
    required. It is assessed independently and cannot make a run incomplete;
    the planner, rather than the classifier fallback, decides whether an optional
    candidate is useful supporting context.
    """

    listed_required = {
        str(item).strip().lower()
        for item in required_sources
        if str(item).strip().lower() in _CLASSIFIER_SOURCE_KINDS
    }
    classified_by_kind = {
        str(item.get("kind") or "").strip().lower(): dict(item)
        for item in (classified_source_requirements or ())
        if isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() in _CLASSIFIER_SOURCE_KINDS
    }
    typed = int(contract.get("version") or 0) >= 3
    # For typed calls, the detailed descriptors are authoritative. A bare
    # required_sources entry cannot create a semantic evidence obligation with
    # no falsifiable property.
    if typed and source_neutral_discovery:
        # Detailed descriptors may be present for both recall corpora, but only
        # the classifier's explicit evidence intent is required. The second
        # corpus remains discovery-required and is adjudicated post-read.
        required = listed_required | set(forced_required_sources or ())
    else:
        required = (
            set(classified_by_kind) | set(forced_required_sources or ())
            if typed and classified_by_kind
            else listed_required
            | set(classified_by_kind)
            | set(forced_required_sources or ())
        )
    sources = [dict(item) for item in contract.get("source_requirements") or ()]
    preserve_post_target_fidelity = (
        str(contract.get("scope") or "") == "post"
        and str((contract.get("target_contract") or {}).get("target_mode") or "") == "mixed"
    )
    if classifier_requires_evidence and not required and not source_neutral_discovery:
        required.update(
            str(item.get("kind") or "") for item in sources if source_evidence_required(item)
        )
    existing = {str(item.get("kind") or "") for item in sources}
    resolved_query_goal = str(query_goal or "").strip()

    def typed_fidelity(kind: str, legacy_fidelity: str) -> str:
        if not typed:
            return legacy_fidelity
        if kind == "images":
            return "vision"
        if kind == "analytics":
            return "analytics"
        if kind == "channel":
            return "metadata" if legacy_fidelity != "full_text" else "full_text"
        if kind == "attachments" and legacy_fidelity == "catalog":
            return "metadata"
        return legacy_fidelity

    for source in sources:
        kind = str(source.get("kind") or "")
        scope_mode = str((source.get("scope") or {}).get("mode") or "")
        if (
            resolved_query_goal
            and str(source.get("predicate_kind") or "semantic") in {"semantic", "mixed"}
        ):
            source["query_goal"] = resolved_query_goal
        if typed:
            source["evidence_obligation"] = "required" if kind in required else "optional"
            if kind in required:
                source["discovery_obligation"] = "required"
            elif (
                source_neutral_discovery
                and kind in {"notes", "posts"}
                and scope_mode == "corpus"
            ):
                # An unqualified workspace read needs both source registries
                # available to post-read adjudication. This is recall policy,
                # not a request to select one member from each corpus.
                source["discovery_obligation"] = "required"
            else:
                # Evidence can be optional while discovery is still required to
                # expose a finite semantic corpus to the Selector. Preserve that
                # pre-classifier boundary instead of silently downgrading it.
                source.setdefault("discovery_obligation", "optional")
        else:
            source["required"] = kind in required
        classified = classified_by_kind.get(kind) or {}
        classified_statuses = _classified_scope_statuses(kind, classified)
        classified_query_goal = str(classified.get("query_goal") or "").strip()
        if len(classified_query_goal) > 1000:
            classified_query_goal = classified_query_goal[:1000].rstrip()
        coverage = str(classified.get("coverage") or "")
        granularity = str(classified.get("evidence_granularity") or "")
        predicate_kind = str(classified.get("predicate_kind") or "")
        if predicate_kind not in {"structural", "semantic", "mixed"}:
            predicate_kind = str(source.get("predicate_kind") or "semantic")
        classified_requirements = [
            dict(item)
            for item in classified.get("evidence_requirements") or ()
            if isinstance(item, Mapping)
            and str(item.get("property") or "").strip()
            and str(item.get("operator") or "")
            in {"exists", "count", "filter", "equals", "contains"}
            and str(item.get("scope") or "")
            in {"source", "target", "member", "corpus", "aggregate"}
        ]
        if predicate_kind == "structural" and not _catalog_can_prove_requirements(
            kind, classified_requirements
        ):
            predicate_kind = "semantic"
            if granularity in {"", "catalog"}:
                granularity = "semantic_card"
        claim_modality = str(classified.get("claim_modality") or "")
        if claim_modality in {"descriptive", "normative"}:
            source["claim_modality"] = claim_modality
        discovery_mode, order_by, order_direction, window_limit = (
            _classified_discovery_strategy(
                kind,
                classified,
                predicate_kind=predicate_kind,
            )
        )
        if (
            kind == "posts"
            and discovery_mode == "semantic_relevance"
            and str(classified.get("discovery_mode") or "") != "catalog_window"
            and str(classified.get("_runtime_lifecycle_scope") or "")
            != "all_member_states"
            and not _has_explicit_post_status_filter(
                f"{resolved_query_goal} {classified_query_goal}"
            )
        ):
            classified_statuses = ()
        if coverage in {"relevant", "complete"}:
            source["coverage"] = (
                coverage
                if coverage != "complete"
                or (kind in {"posts", "notes"} and scope_mode == "corpus")
                else "relevant"
            )
        else:
            source.setdefault("coverage", "relevant")
        if classified_statuses and scope_mode == "corpus":
            source["scope"] = {
                **dict(source.get("scope") or {}),
                "statuses": list(classified_statuses),
            }
        if (
            granularity in {"catalog", "semantic_card", "full_text"}
            and (scope_mode == "corpus" or not preserve_post_target_fidelity)
        ):
            source["required_fidelity" if typed else "evidence_granularity"] = (
                typed_fidelity(kind, granularity)
            )
        elif not source_evidence_required(source) and kind in {"notes", "posts"}:
            # Optional enrichment is for topical context. Exact claims can still
            # be promoted by the research planner, but a planner failure must not
            # turn every ambient match into an expensive full-object read.
            source["required_fidelity" if typed else "evidence_granularity"] = "semantic_card"
        if typed:
            if classified_query_goal and predicate_kind in {"semantic", "mixed"}:
                source["query_goal"] = classified_query_goal
            source["predicate_kind"] = predicate_kind
            source["discovery_mode"] = discovery_mode
            source["order_dependency"] = (
                "required"
                if discovery_mode == "catalog_window"
                else "irrelevant"
            )
            source["order_by"] = order_by
            source["order_direction"] = order_direction
            if window_limit is not None:
                source["budget"] = {
                    **dict(source.get("budget") or {}),
                    "candidate_limit": window_limit,
                }
            cardinality = dict(source.get("selection_cardinality") or {})
            cardinality["min"] = (
                0
                if not source_evidence_required(source)
                or predicate_kind in {"structural", "mixed"}
                else max(1, int(cardinality.get("min") or 0))
            )
            cardinality["max"] = (
                0
                if predicate_kind == "structural"
                else max(int(cardinality.get("min") or 0), window_limit)
                if window_limit is not None
                else max(
                    int(cardinality.get("min") or 0),
                    int(
                        cardinality.get("max")
                        or (source.get("budget") or {}).get("candidate_limit")
                        or 8
                    ),
                )
            )
            source["selection_cardinality"] = cardinality
            if predicate_kind in {"structural", "mixed"}:
                source["coverage"] = "complete"
            if discovery_mode == "catalog_window":
                source["coverage"] = "relevant"
            if predicate_kind == "structural":
                source["required_fidelity"] = "catalog"
            if classified_requirements:
                source_id = str(source.get("source_id") or f"workspace-{kind}")
                source["evidence_requirements"] = [
                    {
                        "schema": EVIDENCE_REQUIREMENT_SCHEMA,
                        "requirement_id": str(item.get("requirement_id") or f"{source_id}:{kind}.{item['property']}"),
                        "source_id": source_id,
                        "subject": str(item.get("subject") or kind),
                        "property": str(item["property"]),
                        "operator": str(item["operator"]),
                        "scope": str(item["scope"]),
                        "claim_modality": str(
                            item.get("claim_modality") or claim_modality
                        ),
                    }
                    for item in classified_requirements
                ]
            if source_evidence_required(source) and not source.get("evidence_requirements"):
                source_id = str(source.get("source_id") or f"workspace-{kind}")
                source["evidence_requirements"] = [
                    {
                        "schema": EVIDENCE_REQUIREMENT_SCHEMA,
                        "requirement_id": f"{source_id}:grounded_evidence",
                        "source_id": source_id,
                        "subject": kind,
                        "property": "grounded_evidence",
                        "operator": "exists",
                        "scope": "source",
                    }
                ]
    for kind in sorted(required - existing):
        classified_coverage = str(
            classified_by_kind.get(kind, {}).get("coverage") or "relevant"
        )
        if classified_coverage not in {"relevant", "complete"}:
            classified_coverage = "relevant"
        if classified_coverage == "complete" and kind not in {"posts", "notes"}:
            classified_coverage = "relevant"
        classified_granularity = str(
            classified_by_kind.get(kind, {}).get("evidence_granularity") or "full_text"
        )
        if classified_granularity not in {"catalog", "semantic_card", "full_text"}:
            classified_granularity = "full_text"
        classified_predicate = str(
            classified_by_kind.get(kind, {}).get("predicate_kind") or "semantic"
        )
        if classified_predicate not in {"structural", "semantic", "mixed"}:
            classified_predicate = "semantic"
        classified_claim_modality = str(
            classified_by_kind.get(kind, {}).get("claim_modality") or ""
        )
        discovery_mode, order_by, order_direction, window_limit = (
            _classified_discovery_strategy(
                kind,
                classified_by_kind.get(kind, {}),
                predicate_kind=classified_predicate,
            )
        )
        post_target_ids = _contract_post_target_ids(contract)
        target_bound = kind in {"comments", "analytics"} and bool(post_target_ids)
        classified_statuses = _classified_scope_statuses(
            kind, classified_by_kind.get(kind, {})
        )
        if (
            kind == "posts"
            and discovery_mode == "semantic_relevance"
            and str(
                classified_by_kind.get(kind, {}).get("discovery_mode") or ""
            )
            != "catalog_window"
            and str(
                classified_by_kind.get(kind, {}).get(
                    "_runtime_lifecycle_scope"
                )
                or ""
            )
            != "all_member_states"
            and not _has_explicit_post_status_filter(
                f"{resolved_query_goal} "
                f"{classified_by_kind.get(kind, {}).get('query_goal') or ''}"
            )
        ):
            classified_statuses = ()
        added = {
            "source_id": f"workspace-{kind}",
            "kind": kind,
            "role": "source",
            "query_goal": str(
                classified_by_kind.get(kind, {}).get("query_goal")
                or resolved_query_goal
                or f"retrieve {kind} required by the current goal"
            )[:1000],
            "coverage": classified_coverage,
            "scope": {
                "mode": "targets" if target_bound else "corpus",
                "target_ids": list(post_target_ids) if target_bound else [],
                "corpus": None if target_bound else "workspace",
                "owner": "current_user",
                "statuses": list(classified_statuses) if not target_bound else [],
            },
            "freshness": {
                "mode": "latest_available",
                "revision": None,
                "max_age_seconds": None,
                "snapshot_at": None,
            },
            "budget": {
                "search_calls": 1,
                "rewrite_calls": 0,
                "candidate_limit": window_limit or 6,
                "deep_reads": 1,
            },
        }
        if typed:
            source_id = str(added["source_id"])
            added.update(
                {
                    "discovery_obligation": "required",
                    "evidence_obligation": "required",
                    "selection_cardinality": {
                        "min": 0 if classified_predicate in {"structural", "mixed"} else 1,
                        "max": (
                            0
                            if classified_predicate == "structural"
                            else window_limit or 6
                        ),
                    },
                    "coverage": (
                        "relevant"
                        if discovery_mode == "catalog_window"
                        else "complete"
                        if classified_predicate in {"structural", "mixed"}
                        else classified_coverage
                    ),
                    "discovery_mode": discovery_mode,
                    "order_dependency": (
                        "required"
                        if discovery_mode == "catalog_window"
                        else "irrelevant"
                    ),
                    "order_by": order_by,
                    "order_direction": order_direction,
                    "predicate_kind": classified_predicate,
                    **(
                        {"claim_modality": classified_claim_modality}
                        if classified_claim_modality in {"descriptive", "normative"}
                        else {}
                    ),
                    "required_fidelity": (
                        "catalog"
                        if classified_predicate == "structural"
                        else typed_fidelity(kind, classified_granularity)
                    ),
                    "evidence_requirements": [
                        {
                            "schema": EVIDENCE_REQUIREMENT_SCHEMA,
                            "requirement_id": f"{source_id}:grounded_evidence",
                            "source_id": source_id,
                            "subject": kind,
                            "property": "grounded_evidence",
                            "operator": "exists",
                            "scope": "source",
                            "claim_modality": classified_claim_modality,
                        }
                    ],
                }
            )
        else:
            added.update(
                {
                    "required": True,
                    "min_evidence": 1,
                    "evidence_granularity": classified_granularity,
                }
            )
        sources.append(added)
    result = {
        **contract,
        # V1 contracts predate semantic source classification and may still
        # carry requires_workspace=False. A classifier "read" decision is the
        # authoritative signal that the answer needs workspace facts.
        "requires_workspace": bool(
            contract.get("requires_workspace") or classifier_requires_evidence
        ),
        "source_requirements": sources,
        "answerability_without_evidence": not classifier_requires_evidence,
        "evidence_requirements": (
            [
                requirement
                for item in sources
                for requirement in item.get("evidence_requirements") or ()
            ]
            if typed
            else [
                f"{item.get('source_id')}:grounded_evidence"
                for item in sources
                if item.get("required")
            ]
        ),
    }
    budgets = dict(result.get("budgets") or {})
    budgets["search_calls"] = max(
        int(budgets.get("search_calls") or 0),
        sum(int((item.get("budget") or {}).get("search_calls") or 0) for item in sources),
    )
    budgets["deep_reads"] = max(
        int(budgets.get("deep_reads") or 0),
        sum(int((item.get("budget") or {}).get("deep_reads") or 0) for item in sources),
    )
    result["budgets"] = budgets
    return result


def _apply_classifier_answer_shape(
    contract: dict[str, Any], classified: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Admit the reasoner's typed answer shape without language-specific inference."""

    raw = dict(classified or {})
    kind = str(raw.get("kind") or "").strip()
    if kind not in {"freeform", "scalar", "record", "inventory"}:
        return contract
    expected_count: int | None = None
    raw_count = raw.get("expected_member_count")
    if kind == "inventory" and type(raw_count) is int and 1 <= raw_count <= 100:
        expected_count = raw_count
    inventory_unit = str(raw.get("inventory_unit") or "").strip()
    if kind != "inventory" or inventory_unit not in {"record", "value"}:
        inventory_unit = None
    return {
        **contract,
        "answer_shape": {
            "kind": kind,
            "expected_member_count": expected_count,
            "inventory_unit": inventory_unit,
        },
    }


def _apply_classifier_answer_obligations(
    contract: dict[str, Any], classified: Any
) -> dict[str, Any]:
    """Admit bounded source-neutral obligations produced before discovery."""

    if not isinstance(classified, list):
        return contract
    obligations: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_ids_by_kind = {
        str(source.get("kind") or ""): str(source.get("source_id") or "")
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
        and str(source.get("kind") or "")
        and str(source.get("source_id") or "")
    }
    for item in classified:
        description = str(
            item.get("description") or item.get("property") or ""
            if isinstance(item, Mapping)
            else item
        ).strip()
        normalized = " ".join(description.split())[:400]
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        source_kinds = (
            tuple(
                str(kind).strip()
                for kind in item.get("source_kinds") or ()
                if str(kind).strip() in source_ids_by_kind
            )
            if isinstance(item, Mapping)
            else ()
        )
        raw_origin = (
            str(item.get("origin") or "").strip()
            if isinstance(item, Mapping)
            else ""
        )
        if raw_origin == "synthesis_operation":
            continue
        origin = raw_origin if raw_origin in _ANSWER_OBLIGATION_ORIGINS else ""
        obligations.append(
            {
                "description": normalized,
                **({"origin": origin} if origin else {}),
                **(
                    {
                        "source_ids": [
                            source_ids_by_kind[kind] for kind in source_kinds
                        ]
                    }
                    if source_kinds
                    else {}
                ),
            }
        )
        if len(obligations) >= 12:
            break
    if not obligations:
        return contract
    return {
        **contract,
        "answer_obligations": [
            {"obligation_id": f"answer:{position}", **obligation}
            for position, obligation in enumerate(obligations)
        ],
    }


def _apply_classifier_answer_operations(
    contract: dict[str, Any], classified: Any
) -> dict[str, Any]:
    """Freeze answer-level derivations without turning them into evidence slots."""

    if not isinstance(classified, list):
        return contract
    obligation_ids = tuple(
        str(item.get("obligation_id") or "")
        for item in contract.get("answer_obligations") or ()
        if isinstance(item, Mapping) and str(item.get("obligation_id") or "")
    )
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in classified:
        if not isinstance(item, Mapping):
            continue
        description = " ".join(str(item.get("description") or "").split())[:400]
        key = description.casefold()
        if not description or key in seen:
            continue
        raw_inputs = {
            str(value)
            for value in item.get("input_obligation_ids") or ()
            if str(value) in obligation_ids
        }
        seen.add(key)
        operations.append(
            {
                "operation_id": f"operation:{len(operations)}",
                "description": description,
                "kind": "synthesis",
                "input_obligation_ids": [
                    obligation_id
                    for obligation_id in obligation_ids
                    if not raw_inputs or obligation_id in raw_inputs
                ],
            }
        )
        if len(operations) >= 4:
            break
    return {**contract, "answer_operations": operations}


def _apply_inventory_context_policy(contract: dict[str, Any]) -> dict[str, Any]:
    """Expose every required corpus member for semantic inventory classification."""

    cross_record_inventory = (
        str(contract.get("selection_mode") or "") == "cross_record_inventory"
    )
    if (
        int(contract.get("version") or 0) < 3
        or (
            str((contract.get("answer_shape") or {}).get("kind") or "")
            != "inventory"
            and not cross_record_inventory
        )
    ):
        return contract
    changed = False
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        if (
            str(source.get("kind") or "") not in {"notes", "posts"}
            or not source_evidence_required(source)
            or str((source.get("scope") or {}).get("mode") or "") != "corpus"
            or (cross_record_inventory and source.get("coverage") != "complete")
        ):
            sources.append(source)
            continue
        if source.get("coverage") != "complete":
            source["coverage"] = "complete"
            changed = True
        if str(source.get("predicate_kind") or "semantic") in {"semantic", "mixed"}:
            if source.get("required_fidelity") != "semantic_card":
                source["required_fidelity"] = "semantic_card"
                changed = True
            scope = dict(source.get("scope") or {})
            if scope.get("statuses") and not cross_record_inventory:
                source["scope"] = {**scope, "statuses": []}
                changed = True
        sources.append(source)
    return {**contract, "source_requirements": sources} if changed else contract


def _apply_decision_context_policy(contract: dict[str, Any]) -> dict[str, Any]:
    """Separate a bounded observation window from final decision context."""

    if (
        int(contract.get("version") or 0) < 3
        or str(contract.get("task_profile") or "") not in _DECISION_TASK_PROFILES
        or (
            str(contract.get("task_profile") or "") == "workspace_synthesis"
            and str((contract.get("answer_shape") or {}).get("kind") or "") == "inventory"
        )
    ):
        return contract
    changed = False
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        predicate_kind = str(source.get("predicate_kind") or "semantic")
        if predicate_kind in {"semantic", "mixed"}:
            cardinality = dict(source.get("selection_cardinality") or {})
            minimum = 0
            maximum = max(minimum, int(cardinality.get("max") or 0))
            bounded_maximum = (
                min(maximum, _DECISION_POST_SELECTION_MAX)
                if str(source.get("kind") or "") == "posts"
                else maximum
            )
            if (
                int(cardinality.get("min") or 0) != minimum
                or bounded_maximum != maximum
            ):
                source["selection_cardinality"] = {
                    **cardinality,
                    "min": minimum,
                    "max": bounded_maximum,
                }
                changed = True
            if (
                str(source.get("kind") or "") == "posts"
                and source_discovery_required(source)
                and source_evidence_required(source)
            ):
                budget = dict(source.get("budget") or {})
                candidate_limit = max(
                    0,
                    int(
                        budget.get("candidate_limit")
                        or cardinality.get("max")
                        or 0
                    ),
                )
                desired_deep_reads = min(
                    candidate_limit,
                    _DECISION_POST_SELECTION_MAX,
                )
                if int(budget.get("deep_reads") or 0) < desired_deep_reads:
                    source["budget"] = {
                        **budget,
                        "deep_reads": desired_deep_reads,
                    }
                    changed = True
        sources.append(source)
    return {**contract, "source_requirements": sources} if changed else contract


def _recover_explicit_ordered_decision_history(
    contract: dict[str, Any],
    classified_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize decision-state history into a bounded semantic window."""

    if str(contract.get("task_profile") or "") not in _DECISION_TASK_PROFILES:
        return contract
    classified_by_kind = {
        str(item.get("kind") or ""): dict(item)
        for item in classified_sources
        if isinstance(item, Mapping) and str(item.get("kind") or "")
    }
    required_source_count = sum(
        1
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
        and source_discovery_required(source)
        and source_evidence_required(source)
    )
    changed = False
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        classified = classified_by_kind.get(str(source.get("kind") or "")) or {}
        explicit_ordered_history = (
            str(classified.get("discovery_mode") or "") == "semantic_relevance"
            and classified.get("order_by") is not None
            and classified.get("order_direction") is not None
            and classified.get("candidate_limit") is not None
            and str(source.get("predicate_kind") or "") == "semantic"
        )
        typed_decision_history = (
            str(contract.get("task_profile") or "") == "recommendation"
            and required_source_count > 1
            and str(source.get("kind") or "") == "posts"
            and bool(tuple((source.get("scope") or {}).get("statuses") or ()))
        )
        implicit_completed_history = (
            typed_decision_history
            and str(
                classified.get("discovery_mode")
                or source.get("discovery_mode")
                or ""
            )
            == "semantic_relevance"
        )
        existing_completed_history_window = (
            typed_decision_history
            and str(classified.get("discovery_mode") or "") == "catalog_window"
            and str(source.get("discovery_mode") or "") == "catalog_window"
        )
        if (
            (
                explicit_ordered_history
                or implicit_completed_history
                or existing_completed_history_window
            )
            and str((source.get("scope") or {}).get("mode") or "") == "corpus"
            and source_discovery_required(source)
            and source_evidence_required(source)
        ):
            normalized_classified = dict(classified)
            if implicit_completed_history and not explicit_ordered_history:
                budget = dict(source.get("budget") or {})
                cardinality = dict(source.get("selection_cardinality") or {})
                window_limit = int(
                    classified.get("candidate_limit")
                    or budget.get("candidate_limit")
                    or cardinality.get("max")
                    or _DECISION_POST_SELECTION_MAX
                )
                normalized_classified.update(
                    {
                        "discovery_mode": "catalog_window",
                        "order_dependency": "required",
                        "_runtime_order_dependency": "decision_history",
                        "predicate_kind": "semantic",
                        "statuses": list(
                            (source.get("scope") or {}).get("statuses") or ()
                        ),
                        "order_by": "created_at",
                        "order_direction": "desc",
                        "candidate_limit": min(
                            _CATALOG_WINDOW_MAX_CANDIDATES,
                            max(1, window_limit),
                        ),
                    }
                )
            else:
                normalized_classified["discovery_mode"] = "catalog_window"
                normalized_classified["order_dependency"] = "required"
                normalized_classified["_runtime_order_dependency"] = (
                    "decision_history"
                )
            discovery_mode, order_by, order_direction, window_limit = (
                _classified_discovery_strategy(
                    str(source.get("kind") or ""),
                    normalized_classified,
                    predicate_kind="semantic",
                )
            )
            if discovery_mode == "catalog_window" and window_limit is not None:
                budget = dict(source.get("budget") or {})
                cardinality = dict(source.get("selection_cardinality") or {})
                source.update(
                    {
                        "coverage": "relevant",
                        "query_goal": _ORDERED_DECISION_HISTORY_QUERY_GOAL,
                        "predicate_kind": "semantic",
                        "required_fidelity": "semantic_card",
                        "discovery_mode": discovery_mode,
                        "order_dependency": "required",
                        "_runtime_order_dependency": "decision_history",
                        "order_by": order_by,
                        "order_direction": order_direction,
                        "scope": dict(source.get("scope") or {}),
                        "budget": {**budget, "candidate_limit": window_limit},
                        "selection_cardinality": {
                            **cardinality,
                            "min": 0,
                            "max": window_limit,
                        },
                    }
                )
                changed = True
        sources.append(source)
    return {**contract, "source_requirements": sources} if changed else contract


def _reflow_recommendation_membership_caps(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Size semantic source membership after all decision premises are frozen."""

    obligations = [
        dict(item)
        for item in contract.get("answer_obligations") or ()
        if isinstance(item, Mapping)
        and str(item.get("description") or "").strip()
    ]
    obligation_count = len(obligations)
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        if (
            str(source.get("predicate_kind") or "semantic")
            in {"semantic", "mixed"}
            and str(contract.get("selection_mode") or "") == "composition"
        ):
            # The history obligation is appended after the first membership
            # sizing pass. Reflow every semantic source against the completed
            # obligation registry; otherwise a non-history source retains a
            # stale cap and can evict a valid premise before assembly.
            cardinality = dict(source.get("selection_cardinality") or {})
            membership = dict(source.get("membership_cardinality") or {})
            selection_max = max(0, int(cardinality.get("max") or 0))
            if selection_max:
                history_reserve = (
                    1
                    if str(source.get("discovery_mode") or "") == "catalog_window"
                    and str(source.get("order_dependency") or "") == "required"
                    else 0
                )
                # One history obligation may require two bounded observations
                # (for example the latest completed state and its predecessor),
                # while other semantic proofs can come from the same corpus.
                # Reserve the second observation independently of the semantic
                # obligation count so an exact proof cannot evict an anchor.
                membership["max"] = min(
                    selection_max,
                    obligation_count + history_reserve,
                )
                membership["min"] = min(
                    max(0, int(membership.get("min") or 0)),
                    int(membership["max"]),
                )
                source["membership_cardinality"] = membership
        sources.append(source)
    return {
        **contract,
        "answer_obligations": [
            {**item, "obligation_id": f"answer:{position}"}
            for position, item in enumerate(obligations)
        ],
        "source_requirements": sources,
    }


def _ensure_recommendation_candidate_plan_obligation(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """A recorded future plan is always a possible prerequisite of a recommendation."""

    if str(contract.get("task_profile") or "") != "recommendation":
        return contract
    obligations = [
        dict(item)
        for item in contract.get("answer_obligations") or ()
        if isinstance(item, Mapping)
        and str(item.get("description") or "").strip()
    ]
    if any(str(item.get("origin") or "") == "candidate_plan" for item in obligations):
        return _reflow_recommendation_membership_caps(contract)
    obligations = [
        *obligations[:11],
        {
            "description": _RECOMMENDATION_CANDIDATE_PLAN_OBLIGATION,
            "origin": "candidate_plan",
        },
    ]
    return _reflow_recommendation_membership_caps(
        {**contract, "answer_obligations": obligations}
    )


def _ensure_recommendation_history_obligation(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Keep a bounded decision-history source represented in frozen Query IR."""

    if str(contract.get("task_profile") or "") != "recommendation":
        return contract
    history_sources = [
        source
        for source in contract.get("source_requirements") or ()
        if isinstance(source, Mapping)
        and str(source.get("discovery_mode") or "") == "catalog_window"
        and source_discovery_required(source)
        and source_evidence_required(source)
    ]
    if not history_sources:
        return _reflow_recommendation_membership_caps(contract)
    obligations = [
        dict(item)
        for item in contract.get("answer_obligations") or ()
        if isinstance(item, Mapping)
        and str(item.get("description") or "").strip()
    ]
    normalized_history = _ORDERED_DECISION_HISTORY_OBLIGATION.casefold()
    if not any(
        " ".join(str(item.get("description") or "").split()).casefold()
        == normalized_history
        for item in obligations
    ):
        obligations = [
            *obligations[:11],
            {
                "description": _ORDERED_DECISION_HISTORY_OBLIGATION,
                "origin": "ordered_decision_history",
            },
        ]
    return _reflow_recommendation_membership_caps(
        {**contract, "answer_obligations": obligations}
    )


def _materialize_classifier_turn_contract(
    contract: dict[str, Any],
    call: Mapping[str, Any],
    *,
    classified_type: str,
    semantic_only: bool = False,
    user_text: str = "",
) -> dict[str, Any]:
    """Build the typed retrieval contract from one classifier decision."""

    if semantic_only:
        call = _semantic_classifier_delta(contract, call, user_text=user_text)

    raw_required_sources = call.get("required_sources")
    required_sources = (
        [str(item) for item in raw_required_sources]
        if isinstance(raw_required_sources, list)
        else []
    )
    classified_answer_shape = (
        call.get("answer_shape")
        if isinstance(call.get("answer_shape"), Mapping)
        else {}
    )
    forced_required_sources: set[str] = set()
    if (
        str(classified_answer_shape.get("kind") or "") == "inventory"
        and _has_explicit_post_status_filter(
            f"{contract.get('goal') or contract.get('search_query') or ''} "
            f"{call.get('search_query') or ''}"
        )
        and "posts" not in required_sources
    ):
        required_sources.append("posts")
        forced_required_sources.add("posts")
    deterministic_required = any(
        source_evidence_required(item)
        for item in contract.get("source_requirements") or ()
        if isinstance(item, dict)
    )
    explicit_requires_evidence = call.get("requires_evidence")
    if isinstance(explicit_requires_evidence, bool):
        semantic_required = explicit_requires_evidence
    elif int(contract.get("version") or 0) >= 2:
        semantic_required = bool(required_sources)
    else:
        semantic_required = classified_type == "read"
    classified_source_requirements = [
        dict(item)
        for item in (call.get("source_requirements") or ())
        if isinstance(item, dict)
    ]
    source_neutral_discovery = bool(
        call.get("_runtime_source_neutral_discovery")
        or (
            user_text
            and not _classifier_query_source_kinds(user_text)
            and {"notes", "posts"}.issubset(
                {
                    str(item.get("kind") or "")
                    for item in contract.get("source_requirements") or ()
                    if isinstance(item, Mapping)
                }
            )
            and classified_type == "read"
        )
    )
    result = _apply_classifier_source_policy(
        contract,
        required_sources=required_sources,
        classifier_requires_evidence=deterministic_required or semantic_required,
        classified_source_requirements=classified_source_requirements,
        query_goal=str(call.get("search_query") or ""),
        forced_required_sources=forced_required_sources,
        source_neutral_discovery=source_neutral_discovery,
    )
    value_inventory = (
        str(classified_answer_shape.get("kind") or "") == "inventory"
        and str(classified_answer_shape.get("inventory_unit") or "") == "value"
    )
    result["membership_source_scope"] = (
        "source_neutral"
        if source_neutral_discovery or value_inventory
        else "explicit_sources"
    )
    result = _apply_classifier_answer_shape(
        result,
        classified_answer_shape,
    )
    result = _apply_classifier_answer_obligations(
        result,
        call.get("answer_obligations"),
    )
    result = _apply_classifier_answer_operations(
        result,
        call.get("answer_operations"),
    )
    if str(call.get("selection_mode") or "") in {
        "record",
        "member_inventory",
        "composition",
        "cross_record_comparison",
        "cross_record_inventory",
    }:
        result["selection_mode"] = str(call["selection_mode"])
    # A finite comparison still has one final answer record, but its
    # alternatives must be opened before that cardinality is applied. Keep
    # this as a read-only cohort bound; post-read deterministic assembly owns
    # the final one-record membership.
    comparison_query = " ".join(
        part
        for part in (
            str(user_text or "").strip(),
            str(call.get("search_query") or "").strip(),
            str(contract.get("goal") or "").strip(),
        )
        if part
    )
    if (
        str(result.get("selection_mode") or "") == "record"
        and _finite_comparison_query(comparison_query)
    ):
        source_limits = [
            int(item.get("candidate_limit") or (item.get("budget") or {}).get("candidate_limit") or 0)
            for item in result.get("source_requirements") or ()
            if isinstance(item, Mapping)
        ]
        deep_read_limit = int((result.get("budgets") or {}).get("deep_reads") or 0)
        result["read_cohort_max_objects"] = min(
            8,
            max(2, deep_read_limit, *(limit for limit in source_limits if limit > 0)),
        )
    if (
        str(result.get("selection_mode") or "")
        in {"composition", "cross_record_comparison"}
        and str((result.get("answer_shape") or {}).get("kind") or "")
        != "inventory"
    ):
        answer_obligation_count = len(
            [
                item
                for item in result.get("answer_obligations") or ()
                if isinstance(item, Mapping)
                and str(item.get("description") or "").strip()
            ]
        )
        bounded_sources: list[dict[str, Any]] = []
        for source in result.get("source_requirements") or ():
            if not isinstance(source, Mapping):
                continue
            bounded = dict(source)
            independent_requirements = {
                str(item.get("requirement_id") or item.get("property") or "").strip()
                for item in bounded.get("evidence_requirements") or ()
                if isinstance(item, Mapping)
                and str(item.get("requirement_id") or item.get("property") or "").strip()
            }
            cardinality = dict(bounded.get("selection_cardinality") or {})
            if (
                independent_requirements
                and str(bounded.get("predicate_kind") or "semantic")
                in {"semantic", "mixed"}
                and int(cardinality.get("max") or 0) > 0
            ):
                # Source-local requirements do not bound the number of
                # source-neutral answer premises that may come from a corpus.
                # The frozen answer obligations are the deterministic upper
                # bound; post-read still chooses the smallest valid cover.
                membership_max = min(
                    int(cardinality["max"]),
                    answer_obligation_count or len(independent_requirements),
                )
                bounded["membership_cardinality"] = {
                    "min": min(
                        int(cardinality.get("min") or 0), membership_max
                    ),
                    "max": membership_max,
                }
            bounded_sources.append(bounded)
        result["source_requirements"] = bounded_sources
    if str(call.get("semantic_adjudication") or "") == "parallel_v1":
        result["semantic_adjudication"] = "parallel_v1"
    classified_profile = str(call.get("task_profile") or "").strip()
    if (
        classified_profile in _DECISION_TASK_PROFILES
        and str(result.get("task_profile") or "")
        in {"topical_answer", *_DECISION_TASK_PROFILES}
    ):
        result["task_profile"] = classified_profile
    if any(
        source_evidence_required(item)
        and item.get("coverage") == "complete"
        and item.get("predicate_kind") in {"semantic", "mixed"}
        for item in result.get("source_requirements") or ()
        if isinstance(item, dict)
    ) and result.get("task_profile") == "topical_answer":
        result["task_profile"] = "workspace_synthesis"
    result = _normalize_workspace_synthesis_coverage(result)
    if (
        classified_profile == "topical_answer"
        and result.get("task_profile") == "workspace_synthesis"
        and not any(
            source_evidence_required(item)
            and item.get("coverage") == "complete"
            and item.get("predicate_kind") in {"semantic", "mixed"}
            for item in result.get("source_requirements") or ()
            if isinstance(item, Mapping)
        )
    ):
        # The complete->synthesis promotion above is provisional. When typed
        # normalization proves that the classifier requested relevance rather
        # than exhaustive corpus coverage, retain its finite comparison route.
        result["task_profile"] = "topical_answer"
    result = _apply_inventory_context_policy(result)
    if classified_profile in _DECISION_TASK_PROFILES:
        result = _recover_explicit_ordered_decision_history(
            result,
            classified_source_requirements,
        )
        # A classifier may omit the per-source descriptor or return it without
        # a usable discovery mode. Re-run the same typed repair against the
        # materialized contract so validated lifecycle scopes still establish
        # the bounded history boundary.
        result = _recover_explicit_ordered_decision_history(result, ())
        result = _ensure_recommendation_candidate_plan_obligation(result)
        result = _ensure_recommendation_history_obligation(result)
    result = _enforce_materialized_order_dependency(
        result,
        classified_source_requirements,
    )
    return _apply_decision_context_policy(result)


def _enforce_materialized_order_dependency(
    contract: dict[str, Any],
    classified_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reject an ordered window that has no set-wide typed evidence premise."""

    if str(contract.get("task_profile") or "") == "recommendation":
        return contract
    classified_by_kind = {
        str(item.get("kind") or ""): dict(item)
        for item in classified_sources
        if isinstance(item, Mapping) and str(item.get("kind") or "")
    }
    changed = False
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        if str(source.get("discovery_mode") or "") != "catalog_window":
            sources.append(source)
            continue
        requirements = [
            item
            for item in source.get("evidence_requirements") or ()
            if isinstance(item, Mapping)
        ]
        ordered_requirement = any(
            str(item.get("scope") or "") in {"member", "corpus", "aggregate"}
            or str(item.get("operator") or "") in {"count", "filter"}
            for item in requirements
        )
        if ordered_requirement:
            sources.append(source)
            continue
        classified = classified_by_kind.get(str(source.get("kind") or "")) or {}
        original_goal = str(classified.get("query_goal") or "").strip()
        original_fidelity = str(classified.get("evidence_granularity") or "")
        source.update(
            {
                "discovery_mode": "semantic_relevance",
                "order_by": None,
                "order_direction": None,
                **({"query_goal": original_goal} if original_goal else {}),
                **(
                    {"required_fidelity": original_fidelity}
                    if original_fidelity
                    in {"catalog", "semantic_card", "full_text"}
                    else {}
                ),
            }
        )
        changed = True
        sources.append(source)
    return {**contract, "source_requirements": sources} if changed else contract


def _normalize_workspace_synthesis_coverage(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Keep complete semantic coverage for genuinely exhaustive obligations.

    A freeform synthesis can need several relevant records without needing every
    workspace object. Complete semantic coverage is justified only when the
    typed evidence contract addresses members/the corpus/an aggregate, or uses
    a set-wide count/filter operation. Target/source facts remain a relevance
    problem; treating them as complete exhausts bounded reads before selection.
    """

    if (
        int(contract.get("version") or 0) < 3
        or str(contract.get("task_profile") or "") != "workspace_synthesis"
        or str((contract.get("answer_shape") or {}).get("kind") or "")
        == "inventory"
        or str(contract.get("selection_mode") or "")
        == "cross_record_inventory"
    ):
        return contract
    changed = False
    sources: list[dict[str, Any]] = []
    for raw_source in contract.get("source_requirements") or ():
        source = dict(raw_source)
        requirements = [
            item
            for item in source.get("evidence_requirements") or ()
            if isinstance(item, Mapping)
        ]
        exhaustive_obligation = any(
            str(item.get("scope") or "") in {"member", "corpus", "aggregate"}
            or str(item.get("operator") or "") in {"count", "filter"}
            for item in requirements
        )
        if (
            source.get("coverage") == "complete"
            and str(source.get("predicate_kind") or "") in {"semantic", "mixed"}
            and str(source.get("discovery_mode") or "") == "semantic_relevance"
            and not exhaustive_obligation
        ):
            source["coverage"] = "relevant"
            if source.get("predicate_kind") == "mixed":
                source["predicate_kind"] = "semantic"
            changed = True
        sources.append(source)
    return {**contract, "source_requirements": sources} if changed else contract


def _classifier_contract_coherence_errors(
    contract: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return typed contradictions that require semantic classifier repair."""

    if int(contract.get("version") or 0) < 3:
        return ()
    errors: list[str] = []
    decision_profile = str(contract.get("task_profile") or "") in _DECISION_TASK_PROFILES
    for source in contract.get("source_requirements") or ():
        if not isinstance(source, Mapping):
            continue
        source_id = str(source.get("source_id") or source.get("kind") or "unknown")
        if (
            source_evidence_required(source)
            and str(source.get("predicate_kind") or "") in {"semantic", "mixed"}
            and str(source.get("claim_modality") or "")
            not in {"descriptive", "normative"}
        ):
            errors.append("missing_claim_modality:" + source_id)
        if (
            not decision_profile
            or str(source.get("role") or "") != "context"
            or str((source.get("scope") or {}).get("mode") or "") != "corpus"
            or not source_discovery_required(source)
            or not source_evidence_required(source)
            or str(source.get("predicate_kind") or "") != "structural"
            or source_selection_cardinality(source)[1] != 0
        ):
            continue
        errors.append("decision_context_structural_zero_max:" + source_id)
    return tuple(errors)


async def bootstrap_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    contract = dict(state.get("turn_contract") or ctx.turn_contract or {})
    target_contract = dict(contract.get("target_contract") or {})
    return {
        **state,
        "status": "running",
        "step_count": 0,
        "repair_count": state.get("repair_count", 0),
        "turn_contract": contract,
        "target_contract": target_contract,
        "resolution_events": list(target_contract.get("resolution_events") or []),
    }


async def workspace_agent_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.services.ai.rag_json import extract_json_object

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    planner_binding = getattr(ctx, "planner_llm", None)
    if callable(planner_binding):
        planner_spec, planner_model, planner_api_key = planner_binding()
    else:
        planner_spec = getattr(ctx, "planner_spec", None) or getattr(ctx, "reasoner_spec", None)
        planner_model = getattr(ctx, "planner_model", "") or getattr(ctx, "reasoner_model", "")
        planner_api_key = getattr(ctx, "planner_api_key", "") or getattr(ctx, "reasoner_api_key", "")
    deterministic_contract = dict(
        state.get("turn_contract")
        or (config["configurable"] or {}).get("turn_contract")
        or ctx.turn_contract
        or {}
    )
    user_text = str(state.get("user_text") or "")
    user_content = user_text
    budgets = dict(deterministic_contract.get("budgets") or {})
    bootstrap_deadline_ms = int(budgets.get("bootstrap_deadline_ms") or 10_000)
    dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
    runtime_settings = getattr(ctx, "settings", None)
    legacy_resolver = bool(
        getattr(runtime_settings, "agent_referent_resolution_legacy", False)
    )
    semantic_contract_compiler = bool(
        getattr(runtime_settings, "agent_typed_requirements_v1_enabled", False)
        and getattr(runtime_settings, "agent_unified_selector_v1_enabled", False)
    )
    target_mode = (
        str((deterministic_contract.get("target_contract") or {}).get("target_mode") or "")
        if legacy_resolver else ""
    )
    if target_mode == "ambiguous":
        call = {"type": "finish", "search_query": ""}
    elif (
        deterministic_contract.get("execution_mode") == "fast"
        and not _fast_path_needs_fidelity_classification(deterministic_contract)
    ):
        # Exact IDs/open objects are already resolved by code. A classifier call
        # cannot improve the target and only adds latency/referent drift.
        call = {"type": "read", "search_query": deterministic_contract.get("search_query") or ""}
    elif not planner_spec or not planner_model or not planner_api_key:
        call: dict[str, Any] = {"type": "read"}
    else:
        # dialog_context lets the classifier route conversational follow-ups
        # ("покороче", "на английском?") to "finish" instead of a doomed
        # research pass with nothing new to retrieve (agent-runtime-sprints
        # §2.1 — canon requires both planner and answer to see history).
        turn_contract = dict(
            state.get("turn_contract")
            or (config["configurable"] or {}).get("turn_contract")
            or ctx.turn_contract
            or {}
        )
        content_parts: list[str] = []
        if dialog_context.strip():
            content_parts.append(f"Диалог:\n{dialog_context.strip()}")
        if turn_contract:
            target_contract = dict(turn_contract.get("target_contract") or {}) if legacy_resolver else {}
            classifier_contract = {"goal": turn_contract.get("goal")}
            if legacy_resolver:
                classifier_contract.update(
                    {
                        "intent": turn_contract.get("intent"),
                        "output": turn_contract.get("output"),
                        "success_criteria": turn_contract.get("success_criteria") or [],
                        "targets": target_contract.get("targets") or [],
                        "ambiguities": target_contract.get("ambiguities") or [],
                    }
                )
            content_parts.append(
                "Задача и явные цели (не политика retrieval):\n"
                + render_turn_contract(classifier_contract)
            )
        # The classifier must see the post it's being asked to edit — without
        # this it cannot produce a correct edit_post payload and silently
        # falls back to "read"/"finish" (a plain text answer, no proposal).
        if ctx.scope == "post" and ctx.post_data:
            post_id = str(ctx.post_data.get("id") or "")
            post_text = str(ctx.post_data.get("text") or "")
            if post_id and post_text:
                content_parts.append(f"Текущий пост (id={post_id}):\n{post_text}")
        else:
            content_parts.append(
                "Контекст интерфейса: это глобальный чат без открытого поста. "
                "Здесь нельзя выбрать post_proposal. Если пользователь просит изменить "
                "пост, серию или расписание, классифицируй запрос как read: сначала нужно "
                "найти соответствующие заметки и посты workspace и показать результат."
            )
        content_parts.append(f"Текущий запрос:\n{user_text}" if content_parts else user_text)
        user_content = "\n\n".join(content_parts)
        try:
            bootstrap_system = WORKSPACE_SYSTEM
            typed_read = bool(deterministic_contract.get("requires_workspace"))
            bootstrap_transport = _workspace_classifier_transport(
                planner_spec,
                typed_read=typed_read,
            )
            if bootstrap_transport == ChatCompletionCapability.STRICT_JSON_SCHEMA:
                bootstrap_system += (
                    "\n\nДля уже установленного typed read верни только поля строгой "
                    "Query IR schema. Не возвращай source_requirements или executable "
                    "retrieval policy: source scope, coverage, fidelity, statuses and "
                    "budgets компилирует deterministic runtime. Сохрани все правила "
                    "атомизации answer_obligations выше."
                )
            raw = await call_llm_with_deadline(
                ctx,
                phase="bootstrap.classifier",
                phase_timeout_s=bootstrap_deadline_ms / 1000,
                telemetry={
                    "model_role": "reasoner",
                    "retry": False,
                    "semantic_attempt": "query_ir_compilation",
                    "transport_tier": bootstrap_transport.value,
                    "schema_result": "pending",
                },
                messages=[
                    {"role": "system", "content": bootstrap_system},
                    {"role": "user", "content": user_content},
                ],
                spec=planner_spec,
                model=planner_model,
                api_key=planner_api_key,
                temperature=0.0,
                max_tokens=1200,
                output_capability=bootstrap_transport,
                output_schema_name=(
                    "workspace_read_query_ir_v1"
                    if bootstrap_transport
                    == ChatCompletionCapability.STRICT_JSON_SCHEMA
                    else None
                ),
                output_json_schema=(
                    _READ_QUERY_IR_SCHEMA
                    if bootstrap_transport
                    == ChatCompletionCapability.STRICT_JSON_SCHEMA
                    else None
                ),
            )
            call = extract_json_object(raw) or {"type": "read"}
        except PhaseDeadlineExceeded:
            # Classification is degradable; retrieval is not. On a slow
            # provider, preserve the deterministic goal and require evidence
            # from the source kinds already declared by the typed contract.
            fallback_sources = list(
                dict.fromkeys(
                    str(source.get("kind") or "")
                    for source in deterministic_contract.get("source_requirements") or ()
                    if isinstance(source, Mapping)
                    and str(source.get("kind") or "") in _CLASSIFIER_SOURCE_KINDS
                )
            )
            requires_workspace = bool(deterministic_contract.get("requires_workspace"))
            call = {
                "type": "read" if requires_workspace else "finish",
                "requires_evidence": requires_workspace,
                "required_sources": fallback_sources if requires_workspace else [],
                "search_query": str(
                    deterministic_contract.get("search_query")
                    or deterministic_contract.get("goal")
                    or user_text
                ),
                "bootstrap_fallback": "phase_deadline",
            }
    turn_contract = dict(
        state.get("turn_contract")
        or (config["configurable"] or {}).get("turn_contract")
        or ctx.turn_contract
        or {}
    )
    call = _apply_classifier_dependency_gate(call)
    if (
        planner_spec
        and planner_model
        and planner_api_key
        and str((call.get("answer_shape") or {}).get("kind") or "") == "inventory"
    ):
        call = await _resolve_inventory_unit(
            ctx,
            call=call,
            user_text=user_text,
            spec=planner_spec,
            model=planner_model,
            api_key=planner_api_key,
            timeout_s=min(6.0, max(1.0, bootstrap_deadline_ms / 1000)),
        )
    classified_type = str(call.get("type") or "read")
    if classified_type == "reuse_context":
        allowed_refs = {
            str(item.get("ref") or "")
            for item in getattr(ctx, "known_context_refs", ())
            if isinstance(item, Mapping)
        }
        requested_refs = [
            str(item).strip()
            for item in (call.get("context_refs") or ())
            if str(item).strip() in allowed_refs
        ]
        if not requested_refs:
            call = {**call, "type": "read", "context_refs": []}
            classified_type = "read"
        else:
            call = {**call, "type": "reuse_context", "context_refs": list(dict.fromkeys(requested_refs))}
    if classified_type == "post_proposal" and ctx.scope != "post":
        # A global chat has no authoritative mutation target. Preserve the
        # user's requested command only as answer context, then force factual
        # workspace discovery. This is deliberately normalized here rather
        # than in the edge router: downstream policy, tracing and answer
        # generation must all see the same read decision.
        requested_command = str(call.get("command") or "edit_post")
        call = {
            **call,
            "type": "read",
            "requires_evidence": True,
            "required_sources": ["notes", "posts"],
            "global_mutation_fallback": True,
            "requested_command": requested_command,
        }
        classified_type = "read"
    user_text = user_text.strip()
    if (
        classified_type == "read"
        and not dialog_context.strip()
        and user_text.endswith("?")
    ):
        # With no dialog there is no external referent to resolve. Preserve an
        # already grammatical question so the model cannot add hypotheses or
        # alternate predicates while still letting it choose route/sources.
        call = {**call, "search_query": user_text}
    turn_contract = _materialize_classifier_turn_contract(
        turn_contract,
        call,
        classified_type=classified_type,
        semantic_only=semantic_contract_compiler,
        user_text=user_text,
    )
    # Apply the dependency decision to the materialized contract as well. The
    # classifier may have supplied normative source descriptors; without this
    # second boundary pass, baseline source requirements can reintroduce a read
    # route after the earlier gate already decided that workspace evidence is
    # unnecessary.
    if (
        str(call.get("type") or "") == "finish"
        and target_mode != "ambiguous"
        and ctx.scope in {"global", "post"}
    ):
        # Search is unconditional for workspace turns. The classifier may
        # report that general knowledge is sufficient, but it cannot suppress
        # the user's workspace lookup: a more precise tenant-local answer may
        # exist. Keep its answer shape, restore the frozen corpus sources, and
        # let post-read membership return an empty pack when nothing matches.
        baseline_sources = [
            dict(item)
            for item in deterministic_contract.get("source_requirements") or ()
            if isinstance(item, Mapping)
        ]
        baseline_kinds = [
            str(item.get("kind") or "")
            for item in baseline_sources
            if str(item.get("kind") or "")
        ]
        turn_contract = {
            **turn_contract,
            "requires_workspace": True,
            "answerability_without_evidence": True,
            "source_requirements": baseline_sources,
            "required_sources": baseline_kinds,
            "evidence_requirements": list(
                deterministic_contract.get("evidence_requirements") or ()
            ),
            "answer_obligations": list(
                turn_contract.get("answer_obligations") or ()
            )
            or [
                {
                    "obligation_id": "answer:0",
                    "description": str(user_text).strip()[:400],
                    "origin": "frozen_exact_query",
                }
            ],
        }
        call = {
            **call,
            "type": "read",
            "requires_evidence": True,
            "required_sources": baseline_kinds,
            "workspace_search_forced": True,
        }
        classified_type = "read"
    coherence_errors = _classifier_contract_coherence_errors(turn_contract)
    if (
        coherence_errors
        and classified_type == "read"
        and planner_spec
        and planner_model
        and planner_api_key
    ):
        malformed_required_kinds = {
            str(item).strip().lower()
            for item in call.get("required_sources") or ()
            if str(item).strip().lower() in _CLASSIFIER_SOURCE_KINDS
        }
        malformed_required_kinds.update(
            str(item.get("kind") or "").strip().lower()
            for item in call.get("source_requirements") or ()
            if isinstance(item, Mapping)
            and str(item.get("kind") or "").strip().lower() in _CLASSIFIER_SOURCE_KINDS
        )
        repair_content = (
            f"Исходный контекст:\n{user_content}\n\n"
            "Несогласованный tool call:\n"
            + json.dumps(dict(call), ensure_ascii=False, sort_keys=True)
            + "\n\nМатериализованный typed-контракт:\n"
            + json.dumps(
                {
                    "task_profile": turn_contract.get("task_profile"),
                    "source_requirements": turn_contract.get("source_requirements") or [],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n\nОшибки согласованности:\n"
            + json.dumps(coherence_errors, ensure_ascii=False)
        )
        try:
            repair_timeout_ms = min(
                int(budgets.get("soft_deadline_ms") or 30_000),
                max(
                    bootstrap_deadline_ms,
                    _CLASSIFIER_CONTRACT_REPAIR_TIMEOUT_MS,
                ),
            )
            repaired_raw = await call_llm_with_deadline(
                ctx,
                phase="bootstrap.classifier_contract_repair",
                phase_timeout_s=repair_timeout_ms / 1000,
                telemetry={
                    "model_role": "reasoner",
                    "retry": True,
                    "semantic_attempt": "contract_repair",
                    "schema_result": "repair_requested",
                    "validation_error_codes": coherence_errors,
                },
                messages=[
                    {
                        "role": "system",
                        "content": WORKSPACE_SYSTEM + "\n\n" + WORKSPACE_CONTRACT_REPAIR_SYSTEM,
                    },
                    {"role": "user", "content": repair_content},
                ],
                spec=planner_spec,
                model=planner_model,
                api_key=planner_api_key,
                temperature=0.0,
                max_tokens=1200,
            )
            repaired_call = extract_json_object(repaired_raw) or {}
            repaired_required_kinds = {
                str(item).strip().lower()
                for item in repaired_call.get("required_sources") or ()
                if str(item).strip().lower() in _CLASSIFIER_SOURCE_KINDS
            }
            repaired_required_kinds.update(
                str(item.get("kind") or "").strip().lower()
                for item in repaired_call.get("source_requirements") or ()
                if isinstance(item, Mapping)
                and str(item.get("kind") or "").strip().lower() in _CLASSIFIER_SOURCE_KINDS
            )
            if (
                str(repaired_call.get("type") or "") == "read"
                and repaired_required_kinds == malformed_required_kinds
            ):
                if not dialog_context.strip() and user_text.endswith("?"):
                    repaired_call = {**repaired_call, "search_query": user_text}
                repaired_contract = _materialize_classifier_turn_contract(
                    deterministic_contract,
                    repaired_call,
                    classified_type="read",
                    semantic_only=semantic_contract_compiler,
                    user_text=user_text,
                )
                repaired_errors = _classifier_contract_coherence_errors(repaired_contract)
                if not repaired_errors:
                    call = {**repaired_call, "bootstrap_contract_repaired": True}
                    turn_contract = repaired_contract
                    coherence_errors = ()
        except PhaseDeadlineExceeded:
            call = {
                **call,
                "bootstrap_contract_repair_fallback": "phase_deadline",
            }
    if coherence_errors:
        call = {
            **call,
            "bootstrap_contract_coherence_errors": list(coherence_errors),
        }
    has_required_sources = any(
        isinstance(item, dict) and source_evidence_required(item)
        for item in turn_contract.get("source_requirements") or ()
    )
    if has_required_sources and target_mode != "ambiguous" and classified_type == "finish":
        call = {**call, "type": "read"}
        classified_type = "read"
    if turn_contract.get("intent") in {"compare_with_feed_posts", "inspect_note"}:
        if str(call.get("type") or "") != "read" and ctx.scope != "post":
            call = {**call, "type": "read"}
    call_type = str(call.get("type") or "read")
    if call_type not in {"read", "finish", "reuse_context", "post_proposal", "media_proposal"}:
        call = {"type": "read"}
        call_type = "read"
    # Resolved search query for the seed prefetch (anaphora expanded). Fall back
    # to raw user_text when the classifier omitted or emptied it.
    classifier_query = str(call.get("search_query") or "").strip()
    contract_query = str(turn_contract.get("search_query") or "").strip()
    search_query = (
        contract_query or classifier_query or str(state.get("user_text") or "")
        if target_mode in {"exact", "set"} or str(turn_contract.get("corpus") or "") == "exact_note"
        else classifier_query or contract_query or str(state.get("user_text") or "")
    )
    if call_type == "reuse_context":
        search_query = ""
    return {
        **state,
        "current_tool": call_type,
        "tool_call": call,
        "search_query": search_query,
        "turn_contract": turn_contract,
        "known_context_refs": list(call.get("context_refs") or ())
        if call_type == "reuse_context" else [],
        # Workspace search is mandatory. Empty evidence and ambiguity are
        # handled after the recall pass, never by bypassing it.
        "direct_finish": False,
    }


def route_workspace_call(
    state: AgentGraphState,
) -> Literal["seed", "answer"]:
    """Every workspace turn enters the mandatory recall pass."""

    return "seed"


def route_after_research(
    state: AgentGraphState,
) -> Literal["answer", "resolve_schedule_time", "build_action_proposal", "build_media_proposal"]:
    """Dispatch the already-researched turn to its requested terminal path."""

    call = state.get("tool_call") or {}
    call_type = str(call.get("type") or "read")
    scope = str(state.get("scope") or "global")
    if call_type == "post_proposal":
        # Defense in depth for old checkpoints or malformed classifier output:
        # a global run can read and answer about candidate posts, never mutate
        # an object that was not opened as the current post.
        if scope != "post":
            return "answer"
        if str(call.get("command") or "") == "schedule_post":
            return "resolve_schedule_time"
        return "build_action_proposal"
    if call_type == "media_proposal":
        return "build_media_proposal"
    return "answer"


def _research_was_attempted(state: AgentGraphState) -> bool:
    """Return whether a terminal node received a real research handoff."""

    return bool(
        state.get("evidence_pack_schema")
        or state.get("finish_retrieval")
        or state.get("search_ledger")
        or state.get("research_transcript")
    )


REFUSAL_TEXT = (
    "Не нашёл в workspace данных, чтобы ответить на это фактически. "
    "Уточните запрос или добавьте материалы, на которые можно опереться."
)

_GROUNDED_ANSWER_BASE = (
    "Выполни текущий запрос пользователя с учётом его формулировки и диалога. "
    "EvidencePack — дополнительный контекст и единственный источник фактов именно "
    "о workspace, а не готовый ответ и не замена задачи пользователя. Используй "
    "только относящиеся к запросу материалы и не превращай ответ в отчёт о поиске "
    "или пересказ EvidencePack. Не выдумывай отсутствующие workspace-факты; каждый "
    "такой factual claim должен ссылаться только на id из EvidencePack. Общие "
    "объяснения и рассуждения могут опираться на сам запрос, диалог и общие знания. "
    "Контракт результата авторитетен: не меняй target/corpus/output."
)
_ENRICHED_ANSWER_BASE = (
    "Сначала полноценно ответь на вопрос пользователя по его формулировке и диалогу. "
    "EvidencePack — дополнительный контекст: используй только относящиеся к вопросу "
    "материалы и не превращай ответ в отчёт о поиске. Факты именно о workspace не "
    "выдумывай и связывай только с id из EvidencePack; общие рассуждения и советы "
    "могут опираться на сам вопрос и общие знания."
)
_ANSWER_COUNTING_RULE = (
    "При подсчете применяй критерий вопроса к каждому объекту, а не используй "
    "общий размер списка. Учитывай все объекты EvidencePack. Не сужай ответ до "
    "подмножества из прошлых реплик."
)
_ANSWER_ID_RULE = (
    "Не показывай пользователю tech_id, note:, UUID и другие технические id; "
    "называй объекты по заголовку или содержанию."
)
_ANSWER_RECOMMENDATION_RULE = (
    "Не советуй создать или сделать то, что EvidencePack показывает уже "
    "существующим или выполненным; предложи доработать существующий объект."
)


def _render_verified_pack(pack: dict[str, Any]) -> str:
    blocks: list[str] = []
    for raw in pack.get("items") or []:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("citation_path") or raw.get("id") or "")
        content = str(raw.get("content") or "").strip()
        if not path or not content:
            continue
        fidelity = str(raw.get("fidelity") or "full_text")
        scope = str(raw.get("allowed_claim_scope") or "content")
        object_kind = str(raw.get("object_kind") or "unknown")
        evidence_role = str(raw.get("evidence_role") or "supporting")
        source_requirement_id = str(raw.get("source_requirement_id") or "")
        blocks.append(
            f"[object_kind={object_kind}; evidence_role={evidence_role}; "
            f"source_requirement_id={source_requirement_id or 'unscoped'}; "
            f"fidelity={fidelity}; allowed_claim_scope={scope}]\n"
            +
            wrap_untrusted_block(
                identifier=path,
                title=str(raw.get("title") or path),
                body=content,
            )
        )
    unresolved = [str(item) for item in (pack.get("unresolved") or []) if str(item).strip()]
    if unresolved:
        blocks.append("Отсутствующие данные: " + "; ".join(unresolved))
    return "\n\n---\n\n".join(blocks)


def _channel_voice_block(ctx: RuntimeContext) -> str:
    """Channel voice/tone/rules for the system prompt of generating nodes.

    Ambient behavior, not a retrievable fact — fed directly rather than
    through RAG, same as build_summary_bundle(post=None) in the legacy
    /ai/reply/ primer. Without this the agent writes with no channel voice at
    all (unlike /ai/reply/, which always had it).
    """
    from app.services.ai.bundle import build_summary_bundle

    if not ctx.channel_profile:
        return ""
    text = build_summary_bundle(ctx.channel_profile, telegram=ctx.telegram_profile, post=None)
    return text.strip()


async def answer_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    from app.services.ai.rag_json import extract_json_object

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
    turn_contract = dict(
        state.get("turn_contract")
        or (config["configurable"] or {}).get("turn_contract")
        or ctx.turn_contract
        or {}
    )
    phase6_enabled = bool(getattr(ctx.settings, "agent_answer_phase6_enabled", True))
    output_schema = resolve_output_schema(turn_contract)
    target_contract = dict(turn_contract.get("target_contract") or {})
    legacy_resolver = bool(getattr(ctx.settings, "agent_referent_resolution_legacy", False))
    if legacy_resolver and target_contract.get("target_mode") == "ambiguous":
        ambiguity = next(iter(target_contract.get("ambiguities") or ()), {})
        question = str(
            ambiguity.get("question")
            or ((target_contract.get("referent_resolution") or {}).get("ambiguity") or {}).get("question")
            or "Уточните, какой именно объект нужно использовать."
        )
        return {
            **state,
            "answer_text": question,
            "claims": [],
            "used_context_refs": [],
            "output_schema": output_schema,
            "output_validation": {
                "ok": True,
                "issues": [],
                "factual": False,
                "model": "deterministic_clarification",
            },
            "answer_repair_count": 0,
            "stopped_reason": "referent_ambiguity",
        }
    selector_failed = bool((state.get("material_plan") or {}).get("selector_failure")) or any(
        isinstance(item, dict) and item.get("kind") == "selector_failed"
        for item in state.get("evidence_gaps") or ()
    )
    if selector_failed:
        return {
            **state,
            "answer_text": (
                "Не удалось надежно оценить контекст рабочего пространства. "
                "Повторите запрос; вывод по доступным материалам не сформирован."
            ),
            "claims": [],
            "used_context_refs": [],
            "output_schema": output_schema,
            "output_validation": {
                "ok": True,
                "issues": [],
                "factual": True,
                "model": "deterministic_selector_failure",
            },
            "answer_repair_count": 0,
            "stopped_reason": "selector_failed",
        }
    evidence_pack = dict(state.get("evidence_pack") or {}) if phase6_enabled else {}
    evidence_ids = list(evidence_pack.get("evidence_ids") or state.get("evidence_ids") or [])
    semantic_card_ids = {
        str(item.get("id") or "")
        for item in evidence_pack.get("items") or ()
        if isinstance(item, dict) and item.get("fidelity") == "semantic_card"
    }
    supplied_context_refs = supplied_object_refs(evidence_pack)
    claim_evidence_aliases = evidence_id_aliases(evidence_pack)
    evidence_fidelity = {
        str(item.get("id") or ""): str(item.get("fidelity") or "full_text")
        for item in evidence_pack.get("items") or ()
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    evidence_roles = {
        str(item.get("id") or ""): str(item.get("evidence_role") or "supporting")
        for item in evidence_pack.get("items") or ()
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    allow_optional_only_claims = not any(
        isinstance(source, dict)
        and source_evidence_required(source)
        and source.get("coverage") == "complete"
        for source in turn_contract.get("source_requirements") or ()
    )
    rag_context = (
        _render_verified_pack(evidence_pack).strip()
        if evidence_pack
        else str(state.get("rag_context") or "").strip()
    )
    evidence_records = dict(state.get("evidence_records") or {})
    style_profile = build_style_profile(
        {
            eid: evidence_records[eid]
            for eid in evidence_ids
            if eid in evidence_records and eid not in semantic_card_ids
        }
    )
    came_through_research = (
        str((state.get("tool_call") or {}).get("type") or "") == "read"
        or bool(state.get("search_ledger"))
        or bool(state.get("finish_retrieval_attempted"))
    )
    has_grounded_evidence = bool(evidence_ids and rag_context)
    research_expected = came_through_research or bool(
        turn_contract.get("requires_workspace")
        and not turn_contract.get("answerability_without_evidence", False)
    )
    factual = is_factual_profile(turn_contract, researched=research_expected)

    prompt_parts: list[str] = []
    if turn_contract:
        prompt_parts.append(
            "Контракт результата (авторитетен; выполни corpus, output и "
            "success_criteria буквально):\n"
            + render_turn_contract(_prompt_turn_contract(turn_contract, legacy_resolver=legacy_resolver))
        )
    if style_profile:
        prompt_parts.append(
            "Измеренный профиль референсных постов:\n"
            + render_turn_contract(style_profile)
        )
    if dialog_context.strip():
        prompt_parts.append(f"Диалог:\n{dialog_context.strip()}")
    # Post-scope: the current post is a deictic reference ("этот пост") that
    # research/RAG cannot resolve — there is nothing to search for by meaning.
    # Without this the "finish" path (workspace_agent_node classified the turn
    # as conversational, e.g. "Как тебе этот пост?") never sees the post body
    # at all, even once ctx.post_data resolves correctly (chat d395d1ef).
    if not came_through_research and ctx.scope == "post" and ctx.post_data:
        post_id = str(ctx.post_data.get("id") or "")
        post_text = str(ctx.post_data.get("text") or "")
        if post_id and post_text:
            prompt_parts.append(f"Текущий пост (tech_id={post_id}):\n{post_text}")
    prompt_parts.append(f"Вопрос:\n{state.get('user_text', '')}")
    if (state.get("tool_call") or {}).get("global_mutation_fallback"):
        prompt_parts.append(
            "Глобальный чат: пользователь просит изменить объект workspace, но открытого "
            "поста в этом контексте нет. Используй найденные материалы, назови подходящие "
            "серии/посты и объясни, что саму правку можно продолжить из чата конкретного "
            "поста. Поиск уже выполнен в этом ходе: не обещай найти что-то позже и не "
            "описывай будущий вызов инструмента."
        )
    if came_through_research and not has_grounded_evidence:
        searched_sources = list(
            dict.fromkeys(
                str(item.get("source_requirement_id") or "unscoped")
                for item in (state.get("search_ledger") or [])
                if str(item.get("tool") or "")
                in {"SearchNodes", "SearchObjectChunks", "ListPosts", "ListGlobalNotes"}
            )
        )
        prompt_parts.append(
            "Результат workspace discovery (служебные данные, не готовый ответ):\n"
            + render_turn_contract(
                {
                    "status": "no_relevant_workspace_evidence",
                    "searched_sources": searched_sources,
                    "unresolved": list(evidence_pack.get("unresolved") or state.get("unresolved") or []),
                    "instruction": (
                        "Ответь на сообщение по его смыслу и диалогу. Не выдумывай факты "
                        "workspace. Упомяни отсутствие данных только если пользователь "
                        "действительно просил найти, проверить или сообщить такой факт."
                    ),
                }
            )
        )
    if came_through_research and has_grounded_evidence:
        # Grounded path: cite only the retrieved evidence, same contract as before.
        evidence_titles = [str(t) for t in (state.get("evidence_titles") or []) if str(t).strip()]
        # Spell out the object count explicitly rather than relying on the
        # model to count blocks itself — an earlier dialog frame ("заметки
        # про систему") can otherwise make it silently answer about only the
        # subset it recognizes from that frame and drop the rest, even though
        # research already gathered evidence for all of them (chat 63dfb9e4:
        # research opened 4 notes, but the answer only discussed the 2 named
        # in the prior turn and ignored evidence for the other 2).
        if len(evidence_titles) > 1:
            prompt_parts.append(
                f"Evidence охватывает {len(evidence_titles)} объектов: "
                + "; ".join(evidence_titles)
            )
        # Explicit image-attachment inventory (chat 9f3d5fdf / 8caf07f4).
        # Original check scanned rag_context text for "image/" — wrong: vision
        # captions are plain prose ("На изображении рекламный баннер..."), they
        # never contain "image/". Guard fired even when attachments were in
        # evidence, causing answer to claim "НЕТ изображений" (chat 8caf07f4).
        # Correct signal: structural — does any evidence record path contain
        # "/attachment/"? That path is written by _attachment_cite_path and is
        # present iff a real image attachment was hydrated into the pack.
        has_image_attachment = any("/attachment/" in str(rid) for rid in evidence_ids)
        if not has_image_attachment:
            prompt_parts.append(
                "Инвентарь изображений: в собранном evidence НЕТ вложений-"
                "изображений (ни у одной заметки/поста нет прикреплённой картинки). "
                "Не утверждай, что изображение существует, и не описывай его "
                "содержимое: текст, описывающий схему/картинку, — это НЕ "
                "приложенное изображение. Если пользователь предполагает, что "
                "картинки есть, а их в evidence нет — прямо скажи, что в "
                "найденном их нет."
            )
        prompt_parts.append(
            f"EvidencePack schema={str(evidence_pack.get('schema') or EVIDENCE_PACK_SCHEMA)}; "
            f"objects={len(evidence_ids)}; ids={evidence_ids}\n{rag_context}"
        )
        prompt_parts.append(
            "Evidence boundary: object_kind and evidence_role are structural metadata, "
            "not prose. Only evidence_role=required_target objects belong to the user's "
            "requested target/corpus enumeration. evidence_role=supporting_optional may "
            "clarify or enrich a required object, but must never be counted, numbered, "
            "or presented as a member of that target/corpus. Preserve object_kind exactly: "
            "a note is not a post even when its text discusses posts."
        )
        if semantic_card_ids:
            prompt_parts.append(
                "Fidelity rule: semantic_card подтверждает только общую тему или назначение "
                "материала. Не извлекай из semantic_card точные факты, числа, даты, цитаты, "
                "статусы, детали аргументации, медиа, аналитику или комментарии. Такие "
                "утверждения допустимы только по full_text."
            )
        prompt_parts.append(
            'Верни JSON {"answer":"...","claims":[{"text":"...","evidence_ids":[...],'
            '"claim_scope":"topic_only|content|exact"}],"used_context_refs":[...]}. '
            "В claims[].evidence_ids используй только точные IDs из списка EvidencePack ids; "
            "короткие object refs вида post:ID и note:ID туда не помещай. "
            "used_context_refs может содержать только реально использованные объекты из: "
            + str(sorted(supplied_context_refs))
        )
        channel_block = _channel_voice_block(ctx)
        system_text = (
            (f"{channel_block}\n\n" if channel_block else "")
            + (_GROUNDED_ANSWER_BASE if factual else _ENRICHED_ANSWER_BASE) + "\n"
            # Counting/filtering guard: a listing block (перечень заметок/постов)
            # gives the TOTAL number of items, not the number matching the
            # question. For «сколько X про Y» / «какие из них Y» не бери общее
            # число из перечня — оцени содержимое каждого элемента по критерию
            # вопроса и посчитай только подходящие. Если тела для оценки нет —
            # скажи, что содержимое не прочитано, а не выдавай общий счёт за ответ.
            + _ANSWER_COUNTING_RULE + "\n"
            # Scope guard: если в user-контенте указано «Evidence охватывает N
            # объектов» — учти ВСЕ N при подсчёте/выводе, а не только те, что
            # упоминались в «Диалог» ранее. Диалог задаёт тему обсуждения, но
            # не список объектов для ответа — evidence может быть шире того,
            # что обсуждалось.
            "\n"
            # Id-hygiene guard (чат 74b0ef7d): технические id (tech_id=…, note:…,
            # UUID) — внутренние ключи, пользователю не нужны и не должны попадать
            # в ответ. Ссылайся на посты/заметки по заголовку или содержанию. И не
            # путай авторскую нумерацию внутри текста заметки («Пост 2») с
            # системным tech_id: число в id не означает позицию в серии.
            + _ANSWER_ID_RULE + "\n"
            # Recommendation-consistency invariant (chat d8ec8cc6 is one
            # instance): a recommendation must not contradict the state the
            # evidence already shows — don't advise creating/doing what evidence
            # says already exists or is already done. d8ec8cc6 recommended
            # writing a post that was already in drafts AND cited in the same
            # answer; that's the retrieved-but-ignored variant, distinct from
            # never-retrieved (chat 38e115df, fixed at the planner). Stated as
            # the general rule, not the single case, with the case as example.
            + _ANSWER_RECOMMENDATION_RULE + "\n"
            "Не рекомендуй несуществующие действия. В частности, заметку нельзя "
            "и не нужно «связывать с постами и файлами»: после сохранения она уже "
            "доступна AI в workspace.\n"
            "Контракт результата в user-сообщении авторитетен: не подменяй target, "
            "не добавляй evidence из другого corpus и соблюдай требования output.\n"
            + UNTRUSTED_SYSTEM_NOTE
        )
    else:
        # Conversational "finish" path (agent-runtime-sprints §2.1): a
        # follow-up like "покороче" or "на английском?" needs the prior turn
        # from dialog_context, not new evidence — there is none to fetch.
        prompt_parts.append(
            'Верни JSON {"answer":"...","claims":[],"used_context_refs":[]}.'
        )
        channel_block = _channel_voice_block(ctx)
        system_text = (
            (f"{channel_block}\n\n" if channel_block else "")
            + "Отвечай на запрос, используя его формулировку, диалог выше и текущий пост "
            "(если он передан) как контекст — например, если это правка твоего "
            "предыдущего ответа или вопрос про сам пост. Не выдумывай факты о "
            "workspace, которых нет в этом контексте. Если research был выполнен, "
            "но не дал пригодных данных, всё равно дай полезный ответ из общих знаний. "
            "Упоминай отсутствие конкретных данных только когда пользователь явно "
            "просил найти или проверить их. Не предлагай функций вне "
            "supported_capabilities из контракта результата."
        )
    prompt = "\n\n".join(prompt_parts)

    answer_spec, answer_model, answer_api_key = (
        ctx.answer_llm()
        if phase6_enabled
        else (ctx.reasoner_spec, ctx.reasoner_model, ctx.reasoner_api_key)
    )
    if not answer_spec or not answer_model or not answer_api_key:
        answer = rag_context or "Для ответа не требуется дополнительный контекст."
        return {
            **state,
            "answer_text": answer,
            "claims": [],
            "output_schema": output_schema,
            "output_validation": {"ok": True, "issues": [], "model": "deterministic"},
        }

    # Stream the answer tokens as they arrive so the chat renders the reply
    # progressively (real chunked streaming), instead of dropping the whole
    # text at once when the run finishes. We forward ONLY the decoded "answer"
    # field mid-stream (never raw JSON syntax); the authoritative parse of both
    # answer and claims still happens once at the end from the full raw string,
    # so the grounding contract (claims ⊆ evidence) is unchanged.
    #
    # get_stream_writer() is a no-op when the "custom" stream mode isn't
    # subscribed, but it raises when called with no runnable context at all
    # (answer_node invoked directly in unit tests, not via graph.astream). Fall
    # back to a no-op writer there so the streaming path stays test-friendly.
    try:
        writer = get_stream_writer()
    except RuntimeError:
        writer = lambda _chunk: None  # noqa: E731 — trivial no-op sink
    raw_parts: list[str] = []
    last_emitted = ""
    output_contract = dict(turn_contract.get("output") or {})
    requested_chars = int(output_contract.get("min_chars") or 0)
    max_answer_tokens = min(6000, max(2400, requested_chars * 3 + 600))
    async for token in stream_llm_with_deadline(
        ctx,
        phase="answer.generate",
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
        spec=answer_spec,
        model=answer_model,
        api_key=answer_api_key,
        temperature=0.1,
        max_tokens=max_answer_tokens,
    ):
        raw_parts.append(token)
        partial = extract_partial_answer("".join(raw_parts))
        # Throttle: only emit when the visible text actually grew by a few
        # chars, so we don't write a DB event per token (the executor commits
        # each custom event for the live SSE reader).
        if partial is not None and len(partial) - len(last_emitted) >= 48:
            last_emitted = partial
            writer({"answer_partial": partial})

    raw = "".join(raw_parts)
    final_partial = extract_partial_answer(raw)
    if final_partial is not None and final_partial != last_emitted:
        writer({"answer_partial": final_partial})
    parsed = extract_json_object(raw) or {}
    validation = validate_answer_output(
        parsed,
        evidence_ids=set(evidence_ids),
        factual=factual,
        schema=output_schema,
        supplied_context_refs=supplied_context_refs,
        evidence_id_aliases=claim_evidence_aliases,
        evidence_fidelity=evidence_fidelity,
        evidence_roles=evidence_roles,
        allow_optional_only_claims=allow_optional_only_claims,
    )
    answer_text = str(parsed.get("answer") or raw).strip()
    claims = list(validation.claims)
    repair_count = 0
    if any(
        issue.endswith("optional_only_outside_required_corpus")
        for issue in validation.issues
    ):
        repair_count = 1
        required_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_roles.get(evidence_id) == "required_target"
        ]
        optional_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_roles.get(evidence_id) == "supporting_optional"
        ]
        scope_repair_raw = await call_llm_with_deadline(
            ctx,
            phase="answer.scope_repair",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Исправь соответствие ответа target/corpus. Верни только JSON "
                        "той же schema. Объекты supporting_optional можно использовать "
                        "только как фон для required_target; не перечисляй и не считай "
                        "их как элементы целевого корпуса. Не меняй тип объекта: заметка "
                        "не является постом."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Schema: {output_schema}. Required target evidence: {required_ids}. "
                        f"Supporting optional evidence: {optional_ids}.\n"
                        f"Контракт:\n{render_turn_contract(turn_contract)}\n\n"
                        f"Предыдущий output:\n{raw}"
                    ),
                },
            ],
            spec=answer_spec,
            model=answer_model,
            api_key=answer_api_key,
            temperature=0.0,
            max_tokens=max_answer_tokens,
        )
        scope_repaired = extract_json_object(scope_repair_raw) or {}
        scope_validation = validate_answer_output(
            scope_repaired,
            evidence_ids=set(evidence_ids),
            factual=factual,
            schema=output_schema,
            supplied_context_refs=supplied_context_refs,
            evidence_id_aliases=claim_evidence_aliases,
            evidence_fidelity=evidence_fidelity,
            evidence_roles=evidence_roles,
            allow_optional_only_claims=allow_optional_only_claims,
        )
        if scope_validation.ok:
            parsed = scope_repaired
            validation = scope_validation
            answer_text = str(scope_repaired.get("answer") or "").strip()
            claims = list(scope_validation.claims)
    if not validation.ok and not factual:
        recovered_answer = str(
            parsed.get("answer") or extract_complete_answer(raw) or ""
        ).strip()
        if recovered_answer:
            recovered = {"answer": recovered_answer, "claims": []}
            recovered_validation = validate_answer_output(
                recovered,
                evidence_ids=set(evidence_ids),
                factual=False,
                schema=output_schema,
                supplied_context_refs=supplied_context_refs,
                evidence_id_aliases=claim_evidence_aliases,
                evidence_fidelity=evidence_fidelity,
                evidence_roles=evidence_roles,
                allow_optional_only_claims=allow_optional_only_claims,
            )
            if recovered_validation.ok:
                parsed = recovered
                validation = recovered_validation
                answer_text = recovered_answer
                claims = []
    if (
        not validation.ok
        and factual
        and evidence_ids
        and "answer" in validation.issues
    ):
        # Some providers finish the complete `answer` string but hit the token
        # limit while serializing the claims array. Preserve that useful answer
        # and bind it to the already verified pack instead of replacing it with
        # an empty-evidence refusal. Do not salvage a partial answer string: it
        # may end mid-sentence and would hide a real generation failure.
        recovered_answer = str(extract_complete_answer(raw) or "").strip()
        if recovered_answer:
            recovered = {
                "answer": recovered_answer,
                "claims": [
                    {"text": recovered_answer, "evidence_ids": list(evidence_ids)}
                ],
            }
            recovered_validation = validate_answer_output(
                recovered,
                evidence_ids=set(evidence_ids),
                factual=True,
                schema=output_schema,
                supplied_context_refs=supplied_context_refs,
                evidence_id_aliases=claim_evidence_aliases,
                evidence_fidelity=evidence_fidelity,
                evidence_roles=evidence_roles,
                allow_optional_only_claims=allow_optional_only_claims,
            )
            if recovered_validation.ok:
                parsed = recovered
                validation = recovered_validation
                answer_text = recovered_answer
                claims = list(validation.claims)
    if not validation.ok:
        repair_count = max(1, repair_count)
        repair_prompt = (
            f"Schema: {output_schema}. Исправь только JSON-формат и citations. "
            "Текст answer сохрани дословно, не добавляй факты и не меняй EvidencePack. "
            f"Ошибки: {list(validation.issues)}. Допустимые evidence_ids: {evidence_ids}.\n"
            f"Предыдущий raw output:\n{raw}"
        )
        repaired_raw = await call_llm_with_deadline(
            ctx,
            phase="answer.format_repair",
            messages=[
                {"role": "system", "content": "Верни только JSON указанной schema."},
                {"role": "user", "content": repair_prompt},
            ],
            spec=answer_spec,
            model=answer_model,
            api_key=answer_api_key,
            temperature=0.0,
            max_tokens=max_answer_tokens,
        )
        repaired = extract_json_object(repaired_raw) or {}
        repaired_validation = validate_answer_output(
            repaired,
            evidence_ids=set(evidence_ids),
            factual=factual,
            schema=output_schema,
            supplied_context_refs=supplied_context_refs,
            evidence_id_aliases=claim_evidence_aliases,
            evidence_fidelity=evidence_fidelity,
            evidence_roles=evidence_roles,
            allow_optional_only_claims=allow_optional_only_claims,
        )
        repaired_text = str(repaired.get("answer") or "").strip()
        original_answer = str(
            parsed.get("answer") or extract_partial_answer(raw) or raw
        ).strip()
        preserves_answer = bool(original_answer) and repaired_text == original_answer
        if repaired_validation.ok and preserves_answer:
            parsed = repaired
            validation = repaired_validation
            answer_text = repaired_text
            claims = list(validation.claims)
    quality_issues = validate_result_contract(
        answer_text,
        turn_contract,
        style_profile=style_profile,
    )
    if not validation.ok and factual:
        answer_text = REFUSAL_TEXT
        claims = []
    used_context_refs = list(validation.used_context_refs) if validation.ok else []
    return {
        **state,
        "answer_text": answer_text,
        "claims": claims,
        "used_context_refs": used_context_refs,
        "result_contract_issues": quality_issues,
        "output_schema": output_schema,
        "output_validation": {
            "ok": validation.ok,
            "issues": list(validation.issues),
            "factual": factual,
            "model": answer_model,
        },
        "answer_repair_count": repair_count,
    }


_EDIT_POST_SYSTEM = (
    "Ты редактируешь текст поста для Telegram. Тебе дан текущий текст поста в "
    "виде Telegram HTML и инструкция пользователя, а также, если есть, недавний "
    "диалог. Верни ТОЛЬКО итоговый текст поста целиком в виде Telegram HTML — "
    "с применённой правкой, сохранив всё остальное без изменений (переносы "
    "строк передавай как <br>).\n\n"
    "Инструкция может ссылаться на предыдущий ход анафорой («сделай ЕЁ через "
    "пробел», «добавь ТО ЖЕ в конец»). Используй недавний диалог, чтобы понять, "
    "к чему относится ссылка — например, если пользователь до этого просил "
    "добавить цифру, а потом просит «сделать её через пробел», это значит "
    "добавить ту же цифру, но через пробел, даже если предыдущая правка была "
    "отклонена. Если из диалога неясно, к чему относится ссылка, следуй "
    "инструкции буквально, не выдумывая контекст.\n\n"
    "Разрешённые теги: <strong>, <em>, <u>, <s>, <code>, <a href=\"...\">, "
    "<span class=\"tg-spoiler\">, <tg-emoji emoji-id=\"...\">, <br>. Никаких "
    "других тегов, атрибутов, markdown-разметки или ```-блоков.\n\n"
    "Если в тексте встречаются <tg-emoji emoji-id=\"...\">...</tg-emoji> — это "
    "кастомные эмодзи пользователя из его наборов Telegram. Копируй такие теги "
    "ДОСЛОВНО, включая emoji-id и содержимое, если не удаляешь именно этот "
    "фрагмент текста. Не придумывай новые emoji-id и не добавляй новые "
    "<tg-emoji> — их нет в твоём распоряжении.\n\n"
    "Форматирование (жирный, курсив и т.п.) применяй по своему усмотрению там, "
    "где это уместно и улучшает читаемость, даже если пользователь не просил "
    "об этом явно — но не переусердствуй и не меняй стиль поста без причины. "
    "Не добавляй пояснений — только сам текст поста в виде HTML."
)


async def _generate_edited_post_html(
    ctx: RuntimeContext,
    *,
    current_html: str,
    instruction: str,
    dialog_context: str = "",
    pending_artifact: ArtifactHandle | None = None,
    last_proposed_post_html: str | None = None,
    workspace_context: str = "",
) -> str | None:
    """Generate the full edited post as Telegram HTML in a dedicated LLM call.

    Split out of the router (workspace_agent_node): that node is a lightweight
    classifier capped at max_tokens=600, which physically cannot re-emit a
    ~1200-char Cyrillic post, so it "cheated" by echoing the prompt's
    placeholder (`<полный новый текст поста>`) verbatim into patch.text — the
    proposal then carried garbage that would have overwritten the post body on
    approval (chat 25e2cac3). Here the budget is sized to the actual post.

    Fed with (and returning) Telegram HTML rather than plain text so inline
    formatting and existing <tg-emoji> custom emoji survive an AI edit instead
    of being silently flattened to plain text (chat 49a569c8 follow-up).

    dialog_context carries the recent turns as display text only — it does NOT
    include what a prior edit_post turn actually proposed (linearize_for_llm
    drops the `proposal` payload). So an anaphoric instruction ("сделай ЕЁ
    через пробел") had nothing concrete to resolve against and the referenced
    change silently vanished (chat 2b9447dd). last_proposed_post_html carries
    that prior proposed body separately.

    A rejected proposal in this UI means "this exact wording isn't right yet",
    not "forget it, go back to the saved post" — the "Отклонить" button starts
    another refinement round, it doesn't reset the thread. So when the new
    instruction is a follow-up edit on an unapplied proposal (chat 2b9447dd
    turn 3: "Добавь после неё точку" referring to the "3"/"4" from two
    still-rejected edits), the edit must be layered ON TOP OF
    last_proposed_post_html, not on current_html — current_html has no digit
    at all, so "after it" has nothing to anchor to and the model silently
    returns the post unchanged (observed regression: three chained anaphoric
    edits, only the first one actually landed). current_html is used instead
    only when there is no pending proposal to continue from.
    """
    from app.services.ai.rag_json import _strip_code_fences

    if not ctx.reasoner_spec or not ctx.reasoner_model or not ctx.reasoner_api_key:
        return None
    pending_html = (
        str(pending_artifact.content or "").strip()
        if pending_artifact and pending_artifact.kind == "edit_post_proposal"
        else str(last_proposed_post_html or "").strip()
    )
    edit_base = current_html
    proposal_block = ""
    if pending_html and pending_html != current_html.strip():
        edit_base = pending_html
        artifact_label = pending_artifact.handle if pending_artifact else "artifact:legacy-pending-edit"
        proposal_block = (
            "Пользователь уже несколько сообщений подряд правит один и тот же "
            "черновик — предыдущие варианты были отклонены не потому что не по "
            "теме, а потому что формулировка ещё не финальная. Текст поста, "
            "сохранённый в системе, ниже (для справки, на случай если это "
            "первое сообщение в цепочке правок):\n"
            f"{current_html}\n\n"
            "Предыдущий предложенный вариант отличается от сохранённого текста. "
            "Считай эту разницу авторитетным объектом местоимений «его/её/это» "
            f"в новой инструкции. Handle этого объекта: {artifact_label}.\n\n"
        )
    # Budget the completion to comfortably exceed the source text: Cyrillic runs
    # ~1 token/char, HTML tags add overhead on top, and an edit can only grow
    # the text modestly, so 3x chars plus headroom avoids mid-text truncation.
    max_tokens = min(6000, max(800, len(edit_base) * 3 + 400))
    context_block = f"Недавний диалог:\n{dialog_context}\n\n" if dialog_context.strip() else ""
    evidence_block = (
        "Проверенные материалы workspace, собранные перед правкой. Используй их "
        "только если инструкция явно на них опирается; не выдумывай дополнительные факты:\n"
        f"{workspace_context}\n\n"
        if workspace_context.strip()
        else ""
    )
    prompt = (
        f"{context_block}{evidence_block}{proposal_block}Текст поста, который нужно отредактировать "
        f"(Telegram HTML):\n{edit_base}\n\n"
        f"Инструкция:\n{instruction}"
    )
    channel_block = _channel_voice_block(ctx)
    edit_system = f"{_EDIT_POST_SYSTEM}\n\n{channel_block}" if channel_block else _EDIT_POST_SYSTEM
    raw = await call_llm_with_deadline(
        ctx,
        phase="action.edit_post",
        messages=[
            {"role": "system", "content": edit_system},
            {"role": "user", "content": prompt},
        ],
        spec=ctx.reasoner_spec,
        model=ctx.reasoner_model,
        api_key=ctx.reasoner_api_key,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    # Post bodies are multi-line (newlines, emoji, quotes). Asking for JSON
    # {"text":"..."} was fragile — models emit literal newlines inside the
    # string and json.loads rejects it, so generation "failed" on every real
    # post (chat 479a2210, 1178-char multi-line post). Take the raw completion
    # as the new body instead; only strip a stray ```-fence the model may wrap
    # around it. No JSON round-trip means no escaping to get wrong.
    return _strip_code_fences(str(raw or "")).strip() or None


async def resolve_schedule_time_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Pin schedule_post's target time down before a proposal is created.

    On success, fills tool_call.payload.scheduled_at (UTC ISO) so
    build_action_proposal_node's payload carries a value _schedule_post can
    parse. On failure (ambiguous/missing time), skips proposal creation
    entirely and answers with a clarifying question instead — the user needs
    to reply with a concrete time, not stare at a proposal card that will
    400 on approval.
    """
    from app.services.agent.scheduling.time_resolver import resolve_schedule_time

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
    resolution = await resolve_schedule_time(
        ctx,
        instruction=str(state.get("user_text") or ""),
        dialog_context=dialog_context,
    )
    if not resolution.resolved:
        return {
            **state,
            "answer_text": resolution.clarifying_question or "Уточните дату и время публикации.",
            "claims": [],
            "stopped_reason": "schedule_time_unresolved",
        }
    call = dict(state.get("tool_call") or {})
    call["payload"] = {**dict(call.get("payload") or {}), "scheduled_at": resolution.scheduled_at_utc}
    return {**state, "tool_call": call}


def route_schedule_time_resolution(
    state: AgentGraphState,
) -> Literal["build_action_proposal", "complete"]:
    return "complete" if state.get("stopped_reason") == "schedule_time_unresolved" else "build_action_proposal"


async def build_action_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.session import async_session_factory

    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    if not _research_was_attempted(state):
        return {
            **state,
            "errors": [*(state.get("errors") or []), "proposal_research_missing"],
            "answer_text": "Не удалось проверить workspace перед предложением действия.",
        }
    if not ctx.settings.agent_actions_enabled:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "agent_actions_disabled"],
            "answer_text": "Действия агента отключены feature flag.",
        }
    call = state.get("tool_call") or {}
    command = str(call.get("command") or "")
    payload = dict(call.get("payload") or {})

    # edit_post text is generated here, not by the router. The router only
    # classifies; the authoritative post_id comes from ctx.post_data (never the
    # model, which used to echo "<id из блока>"), and the full new text is
    # produced by a properly-budgeted LLM call.
    if command == "edit_post" and ctx.scope == "post" and ctx.post_data:
        from app.services.telegram.text_formatting import stored_fields_from_platform_html

        post_id = str(ctx.post_data.get("id") or "")
        current_text = str(ctx.post_data.get("text") or "")
        # Feed the model the existing textHtml (falling back to plain text for
        # posts without formatting) so it can see and preserve inline styling
        # and any <tg-emoji> custom emoji already in the post.
        current_html = str(ctx.post_data.get("textHtml") or current_text)
        if not post_id or not current_text:
            return {
                **state,
                "errors": [*(state.get("errors") or []), "edit_post_missing_context"],
                "answer_text": "Не удалось определить пост для редактирования.",
            }
        new_html = await _generate_edited_post_html(
            ctx,
            current_html=current_html,
            instruction=str(state.get("user_text") or ""),
            dialog_context=ctx.dialog_context,
            pending_artifact=ctx.pending_artifact,
            last_proposed_post_html=ctx.last_proposed_post_html,
            workspace_context=(
                _render_verified_pack(dict(state.get("evidence_pack") or {})).strip()
                or str(state.get("rag_context") or "").strip()
            ),
        )
        if not new_html:
            return {
                **state,
                "errors": [*(state.get("errors") or []), "edit_post_generation_failed"],
                "answer_text": "Не удалось сгенерировать изменённый текст поста.",
            }
        # Derive text from the HTML the model returned rather than trusting it
        # separately — the two must never disagree, since the post renders
        # textHtml over text (TelegramFormattedText); a mismatch showed stale
        # wording (chat 49a569c8). stored_fields_from_platform_html re-validates
        # via the same normalize_platform_text_html path platform-authored posts
        # go through, and falls back to plain text if the model's HTML is
        # broken or has no real formatting.
        new_text, new_text_html = stored_fields_from_platform_html(new_html)
        patch: dict[str, Any] = {"text": new_text or new_html, "textHtml": new_text_html}
        payload = {"post_id": post_id, "patch": patch}
    elif (
        command in {"publish_post", "schedule_post", "cancel_schedule", "delete_post", "restore_post"}
        and ctx.scope == "post"
        and ctx.post_data
        and not str(payload.get("post_id") or "").strip()
    ):
        # Same failure shape as edit_post above, minus the text generation:
        # the router is a 600-token classifier with no reliable memory of the
        # post id it was shown, so it can emit payload={} for a bare "Опубликуй
        # этот пост" — the proposal then reaches the user with an empty
        # payload and the confirmation card renders "Пост пустой" (there is
        # nothing to look up post_id from). ctx.post_data is the same
        # authoritative source edit_post already trusts over the model.
        payload = {**payload, "post_id": str(ctx.post_data.get("id") or "")}
    async with async_session_factory() as session:
        run = await session.get(AgentRun, uuid.UUID(state["run_id"]))
        if run is None:
            raise RuntimeError("agent_run_not_found")
        proposal = await create_proposal(
            session,
            run=run,
            user_id=uuid.UUID(state["user_id"]),
            command=command,
            payload=payload,
            resource_version=str(call.get("resource_version") or "") or None,
            warnings=[str(item) for item in call.get("warnings") or []],
        )
        await session.commit()
    pending = {
        "type": "action_proposal",
        "proposal": {
            "id": str(proposal.id),
            "command": proposal.command,
            "payload_hash": proposal.payload_hash,
            "payload": proposal.payload,
            "warnings": proposal.warnings,
            "resource_version": proposal.resource_version,
        },
    }
    return {
        **state,
        "proposal_ids": [*(state.get("proposal_ids") or []), str(proposal.id)],
        "interrupt": pending,
    }


async def build_media_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    ctx: RuntimeContext = config["configurable"]["runtime_context"]
    if not _research_was_attempted(state):
        return {
            **state,
            "errors": [*(state.get("errors") or []), "media_research_missing"],
            "answer_text": "Не удалось проверить workspace перед предложением медиа.",
        }
    if not ctx.settings.agent_media_enabled:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "agent_media_disabled"],
            "answer_text": "Генерация медиа отключена feature flag.",
        }
    call = state.get("tool_call") or {}
    kind = str(call.get("kind") or "image")
    model = resolve_profile_media_model(ctx.ai_profile, kind=kind)  # type: ignore[arg-type]
    if model is None:
        return {
            **state,
            "errors": [*(state.get("errors") or []), f"no_active_{kind}_model"],
            "answer_text": f"В профиле не выбрана активная {kind}-модель.",
        }
    capability = lookup_capability(
        str(model.get("provider") or ""),
        str(model.get("model") or ""),
    )
    if capability is None or capability.kind != kind:
        return {
            **state,
            "errors": [*(state.get("errors") or []), "unsupported_media_model"],
            "answer_text": "Выбранная media-модель пока не поддерживается runtime.",
        }
    pending = {
        "type": "media_cost",
        "proposal": {
            "kind": kind,
            "provider": model.get("provider"),
            "model": model.get("model"),
            "model_id": model.get("id"),
            "prompt": str(call.get("prompt") or ""),
            "options": dict(call.get("options") or {}),
            "cost_ceiling": call.get("cost_ceiling"),
            "workspace_context": (
                _render_verified_pack(dict(state.get("evidence_pack") or {})).strip()
                or str(state.get("rag_context") or "").strip()
            ),
        },
    }
    return {**state, "interrupt": pending}


def _action_result_text(decision: dict[str, Any]) -> str:
    """Report the real outcome of an approved action, not a hardcoded string.

    The resume payload carries `applied` — the execute_approved_proposal result
    (e.g. {"post_id": .., "status": "published"}). Reflecting it means a failed
    or unexpected execution no longer reads as a flat "выполнено"
    (agent-runtime-remaining.md Спринт 5)."""
    if decision.get("decision") != "approve":
        return "Предложенное действие отклонено."
    applied = decision.get("applied")
    if not isinstance(applied, dict) or not applied:
        # Approved but no execution result surfaced — be honest, don't claim done.
        return "Действие подтверждено (результат исполнения недоступен)."
    status = str(applied.get("status") or "").strip()
    post_id = str(applied.get("post_id") or "").strip()
    tail = f" (пост {post_id}, статус: {status})" if status else ""
    return f"Действие подтверждено и выполнено{tail}."


async def action_hitl_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt")
    if pending and pending.get("type") == "action_proposal":
        decision = interrupt(pending)
        return {
            **state,
            "interrupt": None,
            "status": "running",
            "answer_text": _action_result_text(decision),
        }
    return state


async def media_hitl_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt")
    if pending and pending.get("type") in {"media_cost", "media_attach"}:
        decision = interrupt(pending)
        return {
            **state,
            "interrupt": None,
            "status": "running",
            "media_decision": {
                **decision,
                "proposal": dict(pending.get("proposal") or {}),
            },
        }
    return state


def route_media_decision(state: AgentGraphState) -> Literal["submit_media", "complete"]:
    decision = state.get("media_decision") or {}
    return "submit_media" if decision.get("decision") == "approve" else "complete"


async def submit_media_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.session import async_session_factory

    proposal = dict((state.get("interrupt") or {}).get("proposal") or {})
    # On resume the interrupt payload was cleared; retain the original proposal
    # in the resume value when provided by the API.
    decision = state.get("media_decision") or {}
    proposal = dict(decision.get("proposal") or proposal)
    async with async_session_factory() as session:
        job = await create_media_job(
            session,
            user_id=uuid.UUID(state["user_id"]),
            run_id=uuid.UUID(state["run_id"]),
            job_type=str(proposal.get("kind") or "image"),
            provider=str(proposal.get("provider") or ""),
            model=str(proposal.get("model") or ""),
            brief={
                "prompt": str(proposal.get("prompt") or ""),
                "options": dict(proposal.get("options") or {}),
                "model_id": proposal.get("model_id"),
                "workspace_context": str(proposal.get("workspace_context") or ""),
            },
            reserved_cost=proposal.get("cost_ceiling"),
        )
        await enqueue_media_job(session, job)
        await session.commit()
    return {
        **state,
        "job_ids": [*(state.get("job_ids") or []), str(job.id)],
        "interrupt": {"type": "awaiting_job", "job_id": str(job.id)},
    }


async def media_wait_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    pending = state.get("interrupt") or {}
    result = interrupt(pending)
    return {
        **state,
        "interrupt": None,
        "media_result": result,
    }


async def build_media_attach_proposal_node(
    state: AgentGraphState,
    config: RunnableConfig,
) -> dict[str, Any]:
    from app.db.models import MediaAsset
    from app.db.session import async_session_factory
    from app.services.agent.media.storage import MediaStorage
    from app.core.config import get_settings

    result = state.get("media_result") or {}
    post_id = str(state.get("post_id") or "")
    asset_id = str(result.get("asset_id") or "")
    if not post_id or not asset_id:
        return state
    async with async_session_factory() as session:
        run = await session.get(AgentRun, uuid.UUID(state["run_id"]))
        asset = await session.get(MediaAsset, uuid.UUID(asset_id))
        if run is None or asset is None or asset.user_id != uuid.UUID(state["user_id"]):
            raise RuntimeError("media_attach_target_not_found")
        payload = {
            "post_id": post_id,
            "asset_id": asset_id,
            "mime_type": asset.mime_type,
            "name": "generated",
            "preview_url": MediaStorage(get_settings()).signed_preview_url(asset.object_key),
        }
        proposal = await create_proposal(
            session,
            run=run,
            user_id=uuid.UUID(state["user_id"]),
            command="attach_media",
            payload=payload,
            warnings=["Медиа будет прикреплено к посту только после подтверждения."],
        )
        await session.commit()
    pending = {
        "type": "action_proposal",
        "proposal": {
            "id": str(proposal.id),
            "command": proposal.command,
            "payload_hash": proposal.payload_hash,
            "payload": proposal.payload,
            "warnings": proposal.warnings,
        },
    }
    return {
        **state,
        "proposal_ids": [*(state.get("proposal_ids") or []), str(proposal.id)],
        "interrupt": pending,
    }


async def complete_node(state: AgentGraphState, config: RunnableConfig) -> dict[str, Any]:
    return {**state, "status": "completed"}


def build_workspace_graph() -> StateGraph:
    graph = StateGraph(AgentGraphState)
    graph.add_node("bootstrap", bootstrap_node)
    graph.add_node("workspace_agent", workspace_agent_node)
    # Research nodes are first-class in the single graph (agent-runtime-sprints §1.0), not a
    # nested subgraph. One checkpointer, one state, no content="" repackaging.
    graph.add_node("seed", research_seed_node)
    graph.add_node("planner", research_planner_node)
    graph.add_node("tool", research_tool_node)
    graph.add_node("verify", research_verify_node)
    graph.add_node("pack", research_pack_node)
    graph.add_node("answer", answer_node)
    graph.add_node("resolve_schedule_time", resolve_schedule_time_node)
    graph.add_node("build_action_proposal", build_action_proposal_node)
    graph.add_node("build_media_proposal", build_media_proposal_node)
    graph.add_node("action_hitl", action_hitl_node)
    graph.add_node("media_hitl", media_hitl_node)
    graph.add_node("submit_media", submit_media_node)
    graph.add_node("media_wait", media_wait_node)
    graph.add_node("build_media_attach_proposal", build_media_attach_proposal_node)
    graph.add_node("complete", complete_node)
    graph.set_entry_point("bootstrap")
    graph.add_edge("bootstrap", "workspace_agent")
    graph.add_conditional_edges(
        "workspace_agent",
        route_workspace_call,
        {"seed": "seed", "answer": "answer"},
    )
    # read → research loop (seed → planner ⇄ tool → verify → pack) → answer
    graph.add_conditional_edges("seed", route_research_seed)
    graph.add_conditional_edges("planner", route_research_plan)
    graph.add_conditional_edges("tool", route_research_after_tool)
    graph.add_conditional_edges("verify", route_research_verify)
    graph.add_conditional_edges("pack", route_after_research)
    graph.add_edge("answer", "complete")
    graph.add_conditional_edges("resolve_schedule_time", route_schedule_time_resolution)
    graph.add_edge("build_action_proposal", "action_hitl")
    graph.add_edge("build_media_proposal", "media_hitl")
    graph.add_edge("action_hitl", "complete")
    graph.add_conditional_edges("media_hitl", route_media_decision)
    graph.add_edge("submit_media", "media_wait")
    graph.add_edge("media_wait", "build_media_attach_proposal")
    graph.add_edge("build_media_attach_proposal", "action_hitl")
    graph.add_edge("complete", END)
    return graph


def get_compiled_workspace_graph():
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        return build_workspace_graph().compile(checkpointer=get_checkpointer())
    saver = get_checkpointer()
    cached = _compiled_graphs.get(loop_key)
    if cached is None or cached[0] is not saver:
        compiled = build_workspace_graph().compile(checkpointer=saver)
        _compiled_graphs[loop_key] = (saver, compiled)
        return compiled
    return cached[1]


async def run_workspace_graph(
    *,
    run_id: uuid.UUID,
    user_text: str,
    runtime_context: RuntimeContext,
    configurable: dict[str, Any] | None = None,
) -> AgentGraphState:
    await ensure_checkpointer_ready()
    graph = get_compiled_workspace_graph()
    rollout_flags = runtime_rollout_flags(
        runtime_context.settings,
        contract_version=int(runtime_context.turn_contract.get("version") or 0),
    )
    initial: AgentGraphState = {
        "run_id": str(run_id),
        "assistant_message_id": str(run_id),
        "user_id": str(runtime_context.user_id),
        "user_text": user_text,
        "scope": runtime_context.scope,
        "post_id": str((runtime_context.post_data or {}).get("id") or "") or None,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "used_context_refs": [],
        "message_context_manifest": {},
        "repair_count": 0,
        "max_steps": runtime_context.settings.rag_agent_max_steps,
        "current_post_notes": [],
        "search_ledger": [],
        "finish_retrieval_attempted": False,
        "validator_events": [],
        "phase5_enabled": bool(
            runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 2
        ),
        "adaptive_evidence_depth_enabled": bool(
            (
                getattr(runtime_context.settings, "agent_adaptive_evidence_depth_v1_enabled", False)
                or (
                    rollout_flags["unified_selector"]
                    and int(runtime_context.turn_contract.get("version") or 0) >= 3
                )
            )
            and runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 2
        ),
        "unified_selector_enabled": bool(
            rollout_flags["unified_selector"]
            and runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 3
        ),
        "verified_pack_boundary_enabled": bool(
            rollout_flags["verified_pack_boundary"]
            and runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 3
        ),
        "planner_policy_enabled": bool(
            rollout_flags["planner_policy"]
            and runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 3
        ),
        "recall_verifier_enabled": bool(
            rollout_flags["unified_selector"]
            and runtime_context.settings.agent_planner_phase5_enabled
            and int(runtime_context.turn_contract.get("version") or 0) >= 3
            and getattr(
                runtime_context.settings,
                "agent_recall_verifier_v1_enabled",
                False,
            )
        ),
        "recall_verifier_shadow": bool(
            getattr(runtime_context.settings, "agent_recall_verifier_v1_shadow", True)
        ),
        "plan_decisions": [],
        "planner_input_signatures": [],
        "planner_noop_count": 0,
        "material_plan": empty_material_plan(),
        "candidate_envelopes": [],
        "planner_calls_used": 0,
        "search_calls_used": 0,
        "deep_reads_used": 0,
        "tool_calls_used": 0,
        "planner_invalid_count": 0,
        "sufficiency": {},
        "evidence_gaps": [],
        "soft_deadline_reached": False,
        "deadline_exhausted": False,
    }
    cfg = {
        "configurable": {
            "thread_id": str(run_id),
            "runtime_context": runtime_context,
            **(configurable or {}),
        }
    }
    final_state: AgentGraphState = initial
    async for chunk in graph.astream(initial, cfg, stream_mode="values"):
        if isinstance(chunk, dict):
            final_state = chunk
    return final_state
