"""Structured retrieval planning for L2 agentic RAG (plan-and-execute)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services.ai.providers import ProviderSpec
from app.services.ai.rag import NODE_POST_TEXT
from app.services.ai.rag_escalation import TierAResult
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_sufficiency import TierBResult

logger = logging.getLogger(__name__)

DISCOVERY_TOOLS = frozenset({"ListPosts", "SearchNodes"})
MAX_PLAN_REPLANS = 2

_TOOLS_BLOCK = (
    "Доступные инструменты:\n"
    '- ListPosts: {"status": "all"|"published"|"draft"|"scheduled"} — каталог постов '
    "(в global chat, если id поста неизвестен)\n"
    '- SearchNodes: {"query": "...", "node_types": ["post_text","note_chunk",...], "k": 4}\n'
    '- OpenPost: {"post_id": "..."}\n'
    '- ListPostNotes: {"post_id": "..."}\n'
    '- OpenNote: {"note_id": "...", "post_id": "..."?}\n'
    '- ListNoteAttachments: {"note_id": "...", "post_id": "..."?}\n'
    '- HydrateAttachment: {"ref": "attachment:<id>|file:<id>", "mode": "text"|"vision", '
    '"note_id": "..."?, "post_id": "..."?}\n'
    '- ListPostComments: {"post_id": "..."}\n'
    '- GetPostAnalytics: {"post_id": "...", "period": "7d|30d|90d|24h|all"}\n'
)

_PLAN_SYSTEM_PREFIX = (
    "Ты составляешь план retrieval для agentic RAG: какие инструменты вызвать, "
    "чтобы собрать контекст для ответа на вопрос пользователя. "
    "Верни только JSON без пояснений:\n"
    '{"goal": "краткая цель", "steps": ['
    '{"tool": "<имя>", "args": {...}, "purpose": "зачем этот шаг"}, ...]}\n'
    f"{_TOOLS_BLOCK}"
    "Правила:\n"
)

_PLAN_SYSTEM_SUFFIX = (
    "- SearchNodes даёт только кандидатов — для текста вызывай OpenPost/OpenNote.\n"
    "- Если post_id/note_id ещё неизвестны из L1 или подсказок — начни с ListPosts "
    "и/или SearchNodes; после discovery executor автоматически пересоставит план.\n"
    "- Не указывай выдуманные id и плейсхолдеры — только реальные id из известного контекста.\n"
    "- Учитывай подсказки эскалации и результаты L1.\n"
    "- HydrateAttachment mode=vision — только для вопросов про содержимое изображения."
)


def _plan_system_prompt(max_steps: int) -> str:
    """Build planner system prompt without str.format (JSON braces are literal)."""
    return (
        f"{_PLAN_SYSTEM_PREFIX}"
        f"- 1–{max_steps} шагов; не включай Stop — завершение проверит executor.\n"
        f"{_PLAN_SYSTEM_SUFFIX}"
    )


def _replan_system_prompt(max_steps: int) -> str:
    return (
        "Ты продолжаешь план retrieval для agentic RAG после уже выполненных шагов. "
        "Верни только JSON без пояснений:\n"
        '{"goal": "краткая цель", "steps": ['
        '{"tool": "<имя>", "args": {...}, "purpose": "зачем этот шаг"}, ...]}\n'
        f"{_TOOLS_BLOCK}"
        "Правила:\n"
        f"- 1–{max_steps} шагов; не включай Stop — завершение проверит executor.\n"
        "- Используй только post_id/note_id/ref из блока «Ход выполнения» — не выдумывай.\n"
        "- Не повторяй уже успешно выполненные шаги, если их результат достаточен.\n"
        "- Если вопрос про пост(ы), а пост ещё не открыт — приоритет OpenPost над OpenNote.\n"
        "- SearchNodes даёт только кандидатов — для текста вызывай OpenPost/OpenNote.\n"
        "- HydrateAttachment mode=vision — только для вопросов про содержимое изображения."
    )

_KNOWN_PLAN_TOOLS = frozenset(
    {
        "ListPosts",
        "SearchNodes",
        "OpenPost",
        "ListPostNotes",
        "OpenNote",
        "ListNoteAttachments",
        "HydrateAttachment",
        "ListPostComments",
        "GetPostAnalytics",
    }
)

POST_QUERY_MARKERS = (
    "пост",
    "посты",
    "черновик",
    "черновики",
    "опублик",
    "серия пост",
    "приветственн",
    "запланир",
    "отложен",
    "дайджест",
    "публикац",
    "draft",
    "publish",
)

_MULTI_STEP_MARKERS = (
    " и ",
    " а также ",
    " сравни",
    " разниц",
    " оба ",
    " обе ",
    " нескольк",
)


@dataclass(frozen=True)
class L2PlanContext:
    planning_mode: str = "auto"
    l1_results: list[Mapping[str, Any]] = field(default_factory=list)
    tier_a: TierAResult | None = None
    tier_b: TierBResult | None = None


@dataclass(frozen=True)
class RetrievalPlanStep:
    tool: str
    args: dict[str, Any]
    purpose: str


@dataclass(frozen=True)
class RetrievalPlan:
    goal: str
    steps: list[RetrievalPlanStep]


@dataclass(frozen=True)
class StructuredPlanDecision:
    use_plan: bool
    reason: str


def _query_has_markers(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def format_l1_hits_for_plan(results: list[Mapping[str, Any]], *, limit: int = 5) -> str:
    if not results:
        return "(L1 не нашёл релевантных узлов)"
    lines = ["Результаты L1 (top hits):"]
    for item in results[:limit]:
        node_type = str(item.get("node_type") or "?")
        note_id = str(item.get("note_id") or "")
        post_id = str(item.get("post_id") or "")
        similarity = float(item.get("similarity") or 0.0)
        chunk = str(item.get("chunk_text") or "").strip()
        preview = chunk[:100] + ("…" if len(chunk) > 100 else "")
        id_part = f"note_id={note_id}" if note_id else ""
        if post_id:
            id_part = f"{id_part} post_id={post_id}".strip()
        lines.append(
            f"- {node_type} {id_part} similarity={similarity:.2f} preview={preview!r}"
        )
    return "\n".join(lines)


def decide_structured_plan(
    *,
    planning_mode: str,
    user_text: str,
    scope: str,
    hints: list[str],
    tier_a: TierAResult | None,
    tier_b: TierBResult | None,
    l1_results: list[Mapping[str, Any]],
) -> StructuredPlanDecision:
    mode = (planning_mode or "auto").strip().lower()
    if mode == "off":
        return StructuredPlanDecision(use_plan=False, reason="planning_mode=off")
    if mode == "always":
        return StructuredPlanDecision(use_plan=True, reason="planning_mode=always")

    reasons: list[str] = []

    if tier_a and tier_a.fast_path == "miss":
        reasons.append("l1_miss")

    if tier_a and tier_a.fast_path in {"cross_post", "post_note"}:
        reasons.append(f"fast_path={tier_a.fast_path}")

    if len(hints) >= 2:
        reasons.append("multiple_hints")

    if tier_b and len(tier_b.open_next) >= 2:
        reasons.append("tier_b_multi_open_next")

    if scope == "global" and _query_has_markers(user_text, POST_QUERY_MARKERS):
        reasons.append("post_related_query")

    if _query_has_markers(user_text, _MULTI_STEP_MARKERS):
        reasons.append("multi_part_query")

    l1_has_post_text = any(
        str(item.get("node_type") or "") == NODE_POST_TEXT for item in l1_results
    )
    if (
        scope == "global"
        and _query_has_markers(user_text, POST_QUERY_MARKERS)
        and not l1_has_post_text
    ):
        reasons.append("post_query_without_post_text_hit")

    if not reasons:
        return StructuredPlanDecision(use_plan=False, reason="simple_l2_reactive")

    return StructuredPlanDecision(use_plan=True, reason=",".join(reasons))


def parse_retrieval_plan(raw: str, *, max_steps: int) -> RetrievalPlan | None:
    payload = extract_json_object(raw or "")
    if not payload:
        return None

    goal = str(payload.get("goal") or "").strip()
    steps_raw = payload.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        return None

    steps: list[RetrievalPlanStep] = []
    for item in steps_raw[:max_steps]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        if tool not in _KNOWN_PLAN_TOOLS:
            continue
        args = item.get("args")
        if not isinstance(args, dict):
            args = {}
        purpose = str(item.get("purpose") or "").strip()
        steps.append(RetrievalPlanStep(tool=tool, args=args, purpose=purpose))

    if not steps:
        return None
    return RetrievalPlan(goal=goal or "retrieval", steps=steps)


def build_plan_messages(
    *,
    user_text: str,
    l1_summary: str,
    hints: list[str],
    scope: str,
    max_steps: int,
    tier_a: TierAResult | None = None,
    tier_b: TierBResult | None = None,
) -> list[dict[str, str]]:
    lines = [
        f"Вопрос пользователя:\n{user_text.strip()}",
        f"Чат: scope={scope}",
        l1_summary,
    ]
    if hints:
        lines.append("Подсказки эскалации:")
        lines.extend(f"- {hint}" for hint in hints)
    if tier_a is not None:
        lines.append(
            "Ярус A: "
            f"fast_path={tier_a.fast_path or '—'} "
            f"escalate_target={tier_a.escalate_target or '—'} "
            f"escalate_post_id={tier_a.escalate_post_id or '—'}"
        )
    if tier_b is not None:
        lines.append(
            f"Ярус B: sufficient={tier_b.sufficient} open_next={tier_b.open_next or []}"
        )
    lines.append("Составь план retrieval (JSON):")
    system = _plan_system_prompt(max_steps)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def build_replan_messages(
    *,
    user_text: str,
    transcript: list[str],
    hints: list[str],
    scope: str,
    max_steps: int,
    trigger: str,
) -> list[dict[str, str]]:
    lines = [
        f"Вопрос пользователя:\n{user_text.strip()}",
        f"Чат: scope={scope}",
        f"Причина replan: {trigger}",
        "Ход выполнения:",
    ]
    if transcript:
        lines.extend(transcript)
    else:
        lines.append("(пусто)")
    if hints:
        lines.append("Подсказки эскалации:")
        lines.extend(f"- {hint}" for hint in hints)
    lines.append("Составь план продолжения retrieval (JSON):")
    return [
        {"role": "system", "content": _replan_system_prompt(max_steps)},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def format_plan_trace_lines(plan: RetrievalPlan) -> list[str]:
    lines = [f"goal={plan.goal!r}", f"steps={len(plan.steps)}"]
    for index, step in enumerate(plan.steps, start=1):
        purpose = f" purpose={step.purpose!r}" if step.purpose else ""
        lines.append(f"  {index}. {step.tool}({step.args!r}){purpose}")
    return lines


def _preview_plan_raw(raw: str, limit: int = 1200) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def format_plan_compose_trace_lines(
    *,
    raw: str,
    plan: RetrievalPlan | None,
    decision_reason: str,
    phase: str = "initial",
) -> list[str]:
    lines = [f"phase={phase}", f"trigger={decision_reason}", f"raw: {_preview_plan_raw(raw)}"]
    if plan is not None:
        lines.extend(format_plan_trace_lines(plan))
    else:
        lines.append("parse_failed=true")
    return lines


async def compose_retrieval_plan(
    *,
    user_text: str,
    l1_results: list[Mapping[str, Any]],
    hints: list[str],
    scope: str,
    spec: ProviderSpec,
    model: str,
    api_key: str,
    max_steps: int,
    tier_a: TierAResult | None = None,
    tier_b: TierBResult | None = None,
    transcript: list[str] | None = None,
    replan_trigger: str | None = None,
) -> tuple[RetrievalPlan | None, str]:
    from app.services.ai.llm import complete_chat_completion

    if transcript is not None:
        messages = build_replan_messages(
            user_text=user_text,
            transcript=transcript,
            hints=hints,
            scope=scope,
            max_steps=max_steps,
            trigger=replan_trigger or "continue",
        )
    else:
        messages = build_plan_messages(
            user_text=user_text,
            l1_summary=format_l1_hits_for_plan(l1_results),
            hints=hints,
            scope=scope,
            max_steps=max_steps,
            tier_a=tier_a,
            tier_b=tier_b,
        )
    try:
        raw = await complete_chat_completion(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        )
    except Exception as exc:
        logger.warning("RAG L2 plan compose failed: %s", exc)
        return None, ""

    plan = parse_retrieval_plan(raw or "", max_steps=max_steps)
    if plan is None:
        logger.warning("RAG L2 plan parse failed: %r", (raw or "")[:240])
    return plan, raw or ""
