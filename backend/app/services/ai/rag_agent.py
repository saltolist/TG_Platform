"""L2 agentic RAG planner loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.ai.note_citations import NoteCite
from app.services.ai.providers import ProviderSpec
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_tools import (
    AgentState,
    ToolOutcome,
    tool_get_post_analytics,
    tool_hydrate_attachment,
    tool_list_note_attachments,
    tool_list_post_comments,
    tool_list_post_notes,
    tool_open_note,
    tool_open_post,
    tool_search_nodes,
)

logger = logging.getLogger(__name__)

_AGENT_SYSTEM = (
    "Ты planner для agentic RAG. Выбирай один инструмент за шаг и верни только JSON: "
    '{"tool": "<имя>", "args": {...}}. '
    "Доступные инструменты:\n"
    '- SearchNodes: {"query": "...", "node_types": ["post_text","note_chunk",...], "k": 4}\n'
    '- OpenPost: {"post_id": "..."}\n'
    '- ListPostNotes: {"post_id": "..."}\n'
    '- OpenNote: {"note_id": "...", "post_id": "..."?}\n'
    '- ListNoteAttachments: {"note_id": "...", "post_id": "..."?}\n'
    '- HydrateAttachment: {"ref": "attachment:<id>|file:<id>", "mode": "text"|"vision", '
    '"note_id": "..."?, "post_id": "..."?}\n'
    '- ListPostComments: {"post_id": "..."}\n'
    '- GetPostAnalytics: {"post_id": "...", "period": "7d|30d|90d|24h|all"}\n'
    '- Stop: {"reason": "sufficient"}\n'
    "SearchNodes возвращает кандидатов без содержимого — для текста вызывай OpenPost/OpenNote. "
    "HydrateAttachment mode=vision используй только если вопрос про содержимое изображения — "
    "не для обычных текстовых вопросов. "
    "ListPostComments используй, если вопрос про реакцию аудитории или комментарии. "
    "Когда контекста достаточно — Stop."
)

_KNOWN_TOOLS = frozenset(
    {
        "SearchNodes",
        "OpenPost",
        "ListPostNotes",
        "OpenNote",
        "ListNoteAttachments",
        "HydrateAttachment",
        "ListPostComments",
        "GetPostAnalytics",
        "Stop",
    }
)


@dataclass(frozen=True)
class PlannerAction:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    rag_context: str
    cites: list[NoteCite]
    stopped_reason: str


def parse_planner_action(raw: str) -> PlannerAction | None:
    payload = extract_json_object(raw or "")
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if not tool:
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    return PlannerAction(tool=tool, args=args)


def build_agent_messages(
    user_text: str,
    transcript: list[str],
    hints: list[str],
) -> list[dict[str, str]]:
    lines = [f"Вопрос пользователя:\n{user_text.strip()}"]
    if hints:
        lines.append("Подсказки эскалации (информационно):")
        lines.extend(f"- {hint}" for hint in hints)
    if transcript:
        lines.append("Ход выполнения:")
        lines.extend(transcript)
    lines.append("Следующий инструмент (JSON):")
    return [
        {"role": "system", "content": _AGENT_SYSTEM},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def render_agent_context(blocks: list[tuple[NoteCite, str]]) -> tuple[str, list[NoteCite]]:
    if not blocks:
        return "", []

    lines: list[str] = ["---", "**Контекст из базы знаний:**"]
    cites: list[NoteCite] = []
    for index, (cite, plain) in enumerate(blocks, start=1):
        cites.append(cite)
        label = f"**{cite.title}**"
        lines.append(
            f"\n[{index}] cite-path: {cite.path} cite-title: {cite.title}\n{label}\n{plain}"
        )
    if len(lines) <= 2:
        return "", []
    lines.append("---")
    return "\n".join(lines), cites


async def _dispatch_tool(state: AgentState, action: PlannerAction) -> ToolOutcome:
    tool = action.tool
    args = action.args
    try:
        if tool == "SearchNodes":
            return await tool_search_nodes(
                state,
                query=str(args.get("query") or ""),
                node_types=args.get("node_types") if isinstance(args.get("node_types"), list) else None,
                k=int(args["k"]) if isinstance(args.get("k"), (int, float)) else None,
            )
        if tool == "OpenPost":
            return await tool_open_post(state, post_id=str(args.get("post_id") or ""))
        if tool == "ListPostNotes":
            return tool_list_post_notes(state, post_id=str(args.get("post_id") or ""))
        if tool == "OpenNote":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            return await tool_open_note(
                state,
                note_id=str(args.get("note_id") or ""),
                post_id=post_id or None,
            )
        if tool == "ListNoteAttachments":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            return await tool_list_note_attachments(
                state,
                note_id=str(args.get("note_id") or ""),
                post_id=post_id or None,
            )
        if tool == "HydrateAttachment":
            post_id_raw = args.get("post_id")
            post_id = str(post_id_raw).strip() if post_id_raw else None
            note_id_raw = args.get("note_id")
            note_id = str(note_id_raw).strip() if note_id_raw else None
            return await tool_hydrate_attachment(
                state,
                ref=str(args.get("ref") or ""),
                mode=str(args.get("mode") or "text"),
                note_id=note_id or None,
                post_id=post_id or None,
            )
        if tool == "ListPostComments":
            return tool_list_post_comments(state, post_id=str(args.get("post_id") or ""))
        if tool == "GetPostAnalytics":
            return await tool_get_post_analytics(
                state,
                post_id=str(args.get("post_id") or ""),
                period=str(args.get("period") or "30d"),
            )
        return ToolOutcome(summary=f"Неизвестный инструмент: {tool}", error="unknown_tool")
    except Exception as exc:
        logger.warning("RAG tool %s failed: %s", tool, exc)
        return ToolOutcome(summary=f"Инструмент {tool} завершился с ошибкой.", error=str(exc))


async def run_agentic_loop(
    *,
    state: AgentState,
    user_text: str,
    seed_ref: str | None,
    hints: list[str],
    spec: ProviderSpec,
    model: str,
    api_key: str,
    max_steps: int,
) -> AgentResult:
    from app.services.ai.llm import complete_chat_completion

    transcript: list[str] = []
    steps_used = 0

    if seed_ref and seed_ref.startswith("note:"):
        note_id = seed_ref[len("note:") :].strip()
        post_id = str((state.base_post_data or {}).get("id") or "").strip() or None
        outcome = await tool_open_note(state, note_id=note_id, post_id=post_id)
        transcript.append(f"[seed] OpenNote note_id={note_id}: {outcome.summary}")
        if outcome.error:
            logger.warning("RAG L2 seed OpenNote failed: %s", outcome.error)

    stopped_reason = "budget_exhausted"
    while steps_used < max_steps:
        messages = build_agent_messages(user_text, transcript, hints)
        try:
            raw = await complete_chat_completion(
                spec=spec,
                model=model,
                api_key=api_key,
                messages=messages,
            )
        except Exception as exc:
            logger.warning("RAG L2 planner call failed: %s", exc)
            stopped_reason = "call_failed"
            break

        action = parse_planner_action(raw)
        if action is None:
            logger.warning("RAG L2 planner parse failed: %r", (raw or "")[:200])
            stopped_reason = "parse_failed"
            break

        if action.tool not in _KNOWN_TOOLS:
            logger.warning("RAG L2 unknown tool: %s", action.tool)
            stopped_reason = "unknown_tool"
            break

        if action.tool == "Stop":
            stopped_reason = str(action.args.get("reason") or "sufficient")
            break

        outcome = await _dispatch_tool(state, action)
        transcript.append(f"{action.tool}({action.args}): {outcome.summary}")
        if outcome.error:
            logger.warning("RAG L2 tool %s error: %s", action.tool, outcome.error)
        steps_used += 1

    rag_context, cites = render_agent_context(state.context_blocks)
    return AgentResult(rag_context=rag_context, cites=cites, stopped_reason=stopped_reason)
