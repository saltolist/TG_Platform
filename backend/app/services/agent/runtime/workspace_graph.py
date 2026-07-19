"""Compiled WorkspaceAgent graph with durable checkpointing."""

from __future__ import annotations

import logging
import asyncio
import uuid
from typing import Any, Literal

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
from app.services.agent.research.trust import UNTRUSTED_SYSTEM_NOTE, wrap_untrusted_block
from app.services.agent.runtime.answer_stream import extract_complete_answer, extract_partial_answer
from app.services.agent.runtime.budget import call_llm_with_deadline, stream_llm_with_deadline
from app.services.agent.runtime.checkpoint import ensure_checkpointer_ready, get_checkpointer
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.result_quality import (
    build_style_profile,
    validate_result_contract,
)
from app.services.agent.runtime.output_contract import (
    is_factual_profile,
    resolve_output_schema,
    validate_answer_output,
)
from app.services.agent.runtime.state import AgentGraphState
from app.services.agent.runtime.turn_contract import render_turn_contract

logger = logging.getLogger(__name__)
_compiled_graphs: dict[int, tuple[object, Any]] = {}

WORKSPACE_SYSTEM = """Ты единственный WorkspaceAgent платформы.
Верни один JSON tool call:
- {"type":"read","requires_evidence":true,"required_sources":["notes|posts|analytics|comments|attachments|images"]} — ответ невозможен без фактов workspace;
- {"type":"finish","requires_evidence":false,"required_sources":[]} — на сообщение можно полноценно ответить по его тексту, диалогу и общим знаниям;
- {"type":"post_proposal","command":"create_post|edit_post|schedule_post|publish_post|cancel_schedule|delete_post|restore_post","payload":{...}};
- {"type":"media_proposal","kind":"image|video","prompt":"...","options":{},"cost_ceiling":number}.
Не выполняй мутации напрямую. Выбирай только тип вызова, без keyword routing.
Не предлагай функций, которых нет в перечисленных tools. В частности, в платформе
нет действия «связать заметку с постами или файлами»; заметки и файлы уже являются
частью workspace и доступны AI после сохранения.
Обычные answer-turns в любом случае выполняют отдельный ограниченный поиск по заметкам и постам для обогащения ответа. Поэтому НЕ выбирай "read" и НЕ добавляй required_sources только ради полезного контекста. Выбирай "read" лишь когда факты именно из workspace необходимы для выполнения запроса: пользователь просит найти, перечислить, посчитать, проверить или описать свои объекты/метрики. Совет, оценка или общий вопрос, на который можно ответить без утверждений о содержимом workspace, — "finish"; найденные материалы всё равно будут доступны как необязательное обогащение.
Если передан блок "Диалог" — используй его, чтобы понять контекст запроса. Короткая правка твоего предыдущего ответа без новых фактических вопросов (перефразируй, покороче, на другом языке, другим тоном) — это "finish", даже если предыдущий ответ был по фактам workspace: факты уже собраны и лежат в диалоге, повторный поиск не нужен.
Если передан блок "Текущий пост" и пользователь просит изменить его текст (убрать/добавить/переформулировать что-то в посте) — верни ровно {"type":"post_proposal","command":"edit_post","payload":{}}. Полный текст поста и его id проставляются отдельным детерминированным шагом — тебе НЕ нужно возвращать ни текст, ни id здесь, только классифицировать запрос как edit_post.

Дополнительно ВСЕГДА добавляй в JSON поле "search_query" — самодостаточную формулировку того, что пользователь ищет, пригодную для семантического поиска по заметкам и постам. Раскрой анафоры и подразумеваемое из блока "Диалог": "а сколько там с картинками?" → "сколько заметок с изображениями"; "покороче" (правка ответа) → повтори тему прошлого ответа своими словами. Если запрос и так самодостаточный — повтори его суть без изменений. Не оставляй "search_query" пустым для "read"-запросов."""

_CLASSIFIER_SOURCE_KINDS = frozenset(
    {"notes", "posts", "analytics", "comments", "attachments", "images"}
)


def _apply_classifier_source_policy(
    contract: dict[str, Any],
    *,
    required_sources: list[str],
    classifier_requires_evidence: bool,
) -> dict[str, Any]:
    """Make semantic classifier output authoritative for factual grounding.

    Notes/posts stay present as optional enrichment on every corpus turn. The
    classifier may promote relevant kinds to required without rebuilding the
    target contract or relying on language-specific marker lists.
    """

    required = {
        str(item).strip().lower()
        for item in required_sources
        if str(item).strip().lower() in _CLASSIFIER_SOURCE_KINDS
    }
    sources = [dict(item) for item in contract.get("source_requirements") or ()]
    if classifier_requires_evidence and not required:
        required.update(
            str(item.get("kind") or "") for item in sources if item.get("required")
        )
    existing = {str(item.get("kind") or "") for item in sources}
    for source in sources:
        source["required"] = str(source.get("kind") or "") in required
    for kind in sorted(required - existing):
        sources.append(
            {
                "source_id": f"workspace-{kind}",
                "kind": kind,
                "role": "source",
                "required": True,
                "query_goal": f"retrieve {kind} required by the current goal",
                "min_evidence": 1,
                "evidence_granularity": "full_text",
                "scope": {
                    "mode": "corpus",
                    "target_ids": [],
                    "corpus": "workspace",
                    "owner": "current_user",
                    "statuses": [],
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
                    "candidate_limit": 6,
                    "deep_reads": 1,
                },
            }
        )
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
        "evidence_requirements": [
            f"{item.get('source_id')}:grounded_evidence"
            for item in sources
            if item.get("required")
        ],
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
    target_mode = str((deterministic_contract.get("target_contract") or {}).get("target_mode") or "")
    if target_mode == "ambiguous":
        call = {"type": "finish", "search_query": ""}
    elif deterministic_contract.get("execution_mode") == "fast":
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
        dialog_context = str((config["configurable"] or {}).get("dialog_context") or "")
        turn_contract = dict(
            state.get("turn_contract")
            or (config["configurable"] or {}).get("turn_contract")
            or ctx.turn_contract
            or {}
        )
        user_text = str(state.get("user_text") or "")
        content_parts: list[str] = []
        if dialog_context.strip():
            content_parts.append(f"Диалог:\n{dialog_context.strip()}")
        if turn_contract:
            target_contract = dict(turn_contract.get("target_contract") or {})
            classifier_contract = {
                "goal": turn_contract.get("goal"),
                "intent": turn_contract.get("intent"),
                "output": turn_contract.get("output"),
                "success_criteria": turn_contract.get("success_criteria") or [],
                "targets": target_contract.get("targets") or [],
                "ambiguities": target_contract.get("ambiguities") or [],
            }
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
        content_parts.append(f"Текущий запрос:\n{user_text}" if content_parts else user_text)
        user_content = "\n\n".join(content_parts)
        raw = await call_llm_with_deadline(
            ctx,
            phase="bootstrap.classifier",
            messages=[
                {"role": "system", "content": WORKSPACE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            spec=planner_spec,
            model=planner_model,
            api_key=planner_api_key,
            temperature=0.0,
            max_tokens=600,
        )
        call = extract_json_object(raw) or {"type": "read"}
    turn_contract = dict(
        state.get("turn_contract")
        or (config["configurable"] or {}).get("turn_contract")
        or ctx.turn_contract
        or {}
    )
    classified_type = str(call.get("type") or "read")
    raw_required_sources = call.get("required_sources")
    required_sources = (
        [str(item) for item in raw_required_sources]
        if isinstance(raw_required_sources, list)
        else []
    )
    deterministic_required = any(
        bool(item.get("required"))
        for item in turn_contract.get("source_requirements") or ()
        if isinstance(item, dict)
    )
    explicit_requires_evidence = call.get("requires_evidence")
    if isinstance(explicit_requires_evidence, bool):
        semantic_required = explicit_requires_evidence
    elif int(turn_contract.get("version") or 0) >= 2:
        # V2 always performs discovery, so `read` is not itself proof that an
        # answer must be refused on an empty pack. Structured source promotion
        # is the backwards-compatible factual signal when the new boolean is
        # omitted by a model.
        semantic_required = bool(required_sources)
    else:
        semantic_required = classified_type == "read"
    classifier_requires_evidence = deterministic_required or semantic_required
    turn_contract = _apply_classifier_source_policy(
        turn_contract,
        required_sources=required_sources,
        classifier_requires_evidence=classifier_requires_evidence,
    )
    if (
        turn_contract.get("requires_workspace")
        and target_mode != "ambiguous"
        and classified_type == "finish"
    ):
        call = {**call, "type": "read"}
    if turn_contract.get("intent") in {"write_post", "compare_with_feed_posts", "inspect_note"}:
        if str(call.get("type") or "") != "read" and ctx.scope != "post":
            call = {**call, "type": "read"}
    call_type = str(call.get("type") or "read")
    if call_type not in {"read", "finish", "post_proposal", "media_proposal"}:
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
    return {
        **state,
        "current_tool": call_type,
        "tool_call": call,
        "search_query": search_query,
        "turn_contract": turn_contract,
    }


def route_workspace_call(
    state: AgentGraphState,
) -> Literal["seed", "answer", "resolve_schedule_time", "build_action_proposal", "build_media_proposal"]:
    # "read" enters the research loop directly at its first node (seed). The
    # research nodes (seed/planner/tool/verify/pack) are first-class members of
    # this single graph — no nested subgraph, no separate checkpointer, and no
    # lossy repackaging of evidence_records (agent-runtime-sprints §1.0).
    call = state.get("tool_call") or {}
    call_type = str(call.get("type") or "read")
    scope = str(state.get("scope") or "global")

    # Post-mutation proposals require a post context. In global scope the agent
    # has no post to mutate, so treat any post_proposal as a plain "finish" and
    # route straight to the answer node — no proposal card is ever created.
    if call_type == "post_proposal" and scope != "post":
        return "answer"

    if call_type == "post_proposal" and str(call.get("command") or "") == "schedule_post":
        # schedule_post needs an actual instant before a proposal is worth
        # creating — the classifier never computes one (it's a 600-token
        # router, not a date parser), so route through a dedicated resolver
        # first (chat 4a3ed2f5: every schedule_post proposal used to reach
        # the user with no scheduled_at and fail approval with a silent 400).
        return "resolve_schedule_time"
    return {
        "read": "seed",
        "finish": "answer",
        "post_proposal": "build_action_proposal",
        "media_proposal": "build_media_proposal",
    }.get(call_type, "seed")  # type: ignore[return-value]


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
        blocks.append(
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
    evidence_pack = dict(state.get("evidence_pack") or {}) if phase6_enabled else {}
    evidence_ids = list(evidence_pack.get("evidence_ids") or state.get("evidence_ids") or [])
    rag_context = (
        _render_verified_pack(evidence_pack).strip()
        if evidence_pack
        else str(state.get("rag_context") or "").strip()
    )
    evidence_records = dict(state.get("evidence_records") or {})
    style_profile = build_style_profile(
        {eid: evidence_records[eid] for eid in evidence_ids if eid in evidence_records}
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
            "Контракт результата (авторитетен; выполни target, corpus, output и "
            "success_criteria буквально):\n"
            + render_turn_contract(turn_contract)
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
            'Верни JSON {"answer":"...","claims":[{"text":"...","evidence_ids":[...]}]}.'
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
        prompt_parts.append('Верни JSON {"answer":"...","claims":[]}.')
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
    )
    answer_text = str(parsed.get("answer") or raw).strip()
    claims = list(validation.claims)
    repair_count = 0
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
            )
            if recovered_validation.ok:
                parsed = recovered
                validation = recovered_validation
                answer_text = recovered_answer
                claims = list(validation.claims)
    if not validation.ok:
        repair_count = 1
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
    return {
        **state,
        "answer_text": answer_text,
        "claims": claims,
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


def _deterministic_followup_edit(
    *,
    current_html: str,
    instruction: str,
    last_proposed_post_html: str | None,
) -> str | None:
    """Apply unambiguous punctuation follow-ups without another interpretation.

    If the previous proposal changed only the final punctuation, "put it after
    the period" has one stable referent: that introduced punctuation mark.
    """
    lowered = (instruction or "").lower()
    if "после точки" not in lowered or not last_proposed_post_html:
        return None
    current = current_html.rstrip()
    previous = last_proposed_post_html.rstrip()
    if not current.endswith(".") or len(previous) < 2:
        return None
    introduced = previous[-1]
    if introduced not in "?!":
        return None
    if previous[:-1] != current[:-1]:
        return None
    return current + introduced


async def _generate_edited_post_html(
    ctx: RuntimeContext,
    *,
    current_html: str,
    instruction: str,
    dialog_context: str = "",
    last_proposed_post_html: str | None = None,
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
    deterministic = _deterministic_followup_edit(
        current_html=current_html,
        instruction=instruction,
        last_proposed_post_html=last_proposed_post_html,
    )
    if deterministic is not None:
        return deterministic
    edit_base = current_html
    proposal_block = ""
    if last_proposed_post_html and last_proposed_post_html.strip() != current_html.strip():
        edit_base = last_proposed_post_html.strip()
        proposal_block = (
            "Пользователь уже несколько сообщений подряд правит один и тот же "
            "черновик — предыдущие варианты были отклонены не потому что не по "
            "теме, а потому что формулировка ещё не финальная. Текст поста, "
            "сохранённый в системе, ниже (для справки, на случай если это "
            "первое сообщение в цепочке правок):\n"
            f"{current_html}\n\n"
            "Предыдущий предложенный вариант отличается от сохранённого текста. "
            "Считай эту разницу авторитетным объектом местоимений «его/её/это» "
            "в новой инструкции.\n\n"
        )
    # Budget the completion to comfortably exceed the source text: Cyrillic runs
    # ~1 token/char, HTML tags add overhead on top, and an edit can only grow
    # the text modestly, so 3x chars plus headroom avoids mid-text truncation.
    max_tokens = min(6000, max(800, len(edit_base) * 3 + 400))
    context_block = f"Недавний диалог:\n{dialog_context}\n\n" if dialog_context.strip() else ""
    prompt = (
        f"{context_block}{proposal_block}Текст поста, который нужно отредактировать "
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
            last_proposed_post_html=ctx.last_proposed_post_html,
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
    graph.add_conditional_edges("workspace_agent", route_workspace_call)
    # read → research loop (seed → planner ⇄ tool → verify → pack) → answer
    graph.add_conditional_edges("seed", route_research_seed)
    graph.add_conditional_edges("planner", route_research_plan)
    graph.add_conditional_edges("tool", route_research_after_tool)
    graph.add_conditional_edges("verify", route_research_verify)
    graph.add_edge("pack", "answer")
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
    initial: AgentGraphState = {
        "run_id": str(run_id),
        "user_id": str(runtime_context.user_id),
        "user_text": user_text,
        "scope": runtime_context.scope,
        "post_id": str((runtime_context.post_data or {}).get("id") or "") or None,
        "status": "running",
        "evidence_records": {},
        "evidence_ids": [],
        "repair_count": 0,
        "max_steps": runtime_context.settings.rag_agent_max_steps,
        "search_ledger": [],
        "finish_retrieval_attempted": False,
        "validator_events": [],
        "phase5_enabled": bool(
            runtime_context.settings.agent_planner_phase5_enabled
            and runtime_context.turn_contract.get("version") == 2
        ),
        "planner_calls_used": 0,
        "search_calls_used": 0,
        "deep_reads_used": 0,
        "tool_calls_used": 0,
        "planner_invalid_count": 0,
        "sufficiency": {},
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
