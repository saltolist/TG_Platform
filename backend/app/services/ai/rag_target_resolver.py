"""LLM target-post resolution for global named-post queries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.ai.providers import ProviderSpec
from app.services.ai.rag import _post_title_from_text
from app.services.ai.rag_json import extract_json_object
from app.services.ai.rag_retrieval_brief import RetrievalBrief
from app.services.ai.rag_retrieval_plan import format_l1_hits_for_plan

logger = logging.getLogger(__name__)

_CONFIDENT = frozenset({"high", "medium"})


@dataclass(frozen=True)
class TargetPostResolution:
    post_id: str | None
    rationale: str
    confidence: str

    @property
    def is_confident(self) -> bool:
        return self.confidence in _CONFIDENT and bool(self.post_id)


def format_catalog_for_planner(posts: list[Mapping[str, Any]]) -> str:
    if not posts:
        return "(каталог постов ещё не загружен — начни план с ListPosts)"
    lines = ["Каталог постов пользователя (ListPosts):"]
    for item in posts:
        post_id = str(item.get("id") or "").strip()
        if not post_id:
            continue
        text_value = str(item.get("text") or "").strip()
        title = _post_title_from_text(text_value) if text_value else f"Пост {post_id}"
        preview = text_value[:120] + ("…" if len(text_value) > 120 else "")
        notes_count = int(item.get("notes_count") or len(item.get("notes") or []))
        status = str(item.get("status") or "draft")
        lines.append(
            f"- post_id={post_id} status={status} title={title!r} "
            f"notes={notes_count} preview={preview!r}"
        )
    return "\n".join(lines)


def format_resolution_for_planner(resolution: TargetPostResolution | None) -> str:
    if resolution is None:
        return "(target post ещё не определён)"
    if not resolution.post_id:
        return (
            f"Target resolution: post_id=null confidence={resolution.confidence!r}\n"
            f"Rationale: {resolution.rationale}\n"
            "Сначала ListPosts/SearchNodes(post_text), затем OpenPost с id из каталога."
        )
    return (
        f"Target resolution: post_id={resolution.post_id!r} "
        f"confidence={resolution.confidence!r}\n"
        f"Rationale: {resolution.rationale}\n"
        "План обязан работать с этим post_id; L1 note_chunk id — не замена target post."
    )


def _build_resolver_messages(
    *,
    user_text: str,
    dialog_context: str,
    brief: RetrievalBrief,
    catalog_posts: list[Mapping[str, Any]],
    l1_results: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    user_block = "\n\n".join(
        part
        for part in [
            f"Вопрос пользователя:\n{user_text.strip()}",
            f"Контекст диалога:\n{dialog_context.strip()}" if dialog_context.strip() else "",
            f"Задача retrieval: {brief.task}",
            f"Evidence needed: {list(brief.evidence_needed)}",
            format_catalog_for_planner(catalog_posts),
            format_l1_hits_for_plan(l1_results),
            (
                "Определи, о каком посте спрашивает пользователь (semantic referent).\n"
                "Верни только JSON:\n"
                '{"post_id": "<id из каталога>|null", '
                '"rationale": "почему этот пост", '
                '"confidence": "high"|"medium"|"low"|"none"}\n'
                "Правила:\n"
                "- Сопоставляй referent из вопроса с title/preview поста в каталоге.\n"
                "- Не выбирай пост только потому, что у него больше заметок или PNG.\n"
                "- post_id из L1 note_chunk — кандидат на media, не автоматический target.\n"
                "- Если referent неоднозначен или поста нет в каталоге — post_id=null, confidence=none."
            ),
        ]
        if part
    )
    return [
        {
            "role": "system",
            "content": (
                "Ты resolver target post для agentic RAG. "
                "Твоя задача — понять, о каком посте пользователь, по смыслу вопроса и каталогу."
            ),
        },
        {"role": "user", "content": user_block},
    ]


def parse_target_resolution(raw: str, *, catalog_posts: list[Mapping[str, Any]]) -> TargetPostResolution:
    payload = extract_json_object(raw or "")
    if not payload:
        return TargetPostResolution(
            post_id=None,
            rationale="parse_failed",
            confidence="none",
        )

    post_id = str(payload.get("post_id") or "").strip() or None
    rationale = str(payload.get("rationale") or "").strip() or "—"
    confidence = str(payload.get("confidence") or "none").strip().lower()
    if confidence not in {"high", "medium", "low", "none"}:
        confidence = "none"

    if post_id:
        catalog_ids = {str(item.get("id") or "").strip() for item in catalog_posts}
        if post_id not in catalog_ids:
            return TargetPostResolution(
                post_id=None,
                rationale=f"unknown post_id {post_id!r} not in catalog",
                confidence="none",
            )

    if post_id and confidence == "none":
        confidence = "medium"

    if not post_id:
        confidence = "none"

    return TargetPostResolution(
        post_id=post_id,
        rationale=rationale,
        confidence=confidence,
    )


async def resolve_target_post(
    *,
    user_text: str,
    dialog_context: str,
    brief: RetrievalBrief,
    catalog_posts: list[Mapping[str, Any]],
    l1_results: list[Mapping[str, Any]],
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> TargetPostResolution:
    if not brief.named_post_query or not catalog_posts:
        return TargetPostResolution(
            post_id=None,
            rationale="no_named_post_or_empty_catalog",
            confidence="none",
        )

    from app.services.ai.llm import complete_chat_completion

    messages = _build_resolver_messages(
        user_text=user_text,
        dialog_context=dialog_context,
        brief=brief,
        catalog_posts=catalog_posts,
        l1_results=l1_results,
    )
    try:
        raw = await complete_chat_completion(
            spec=spec,
            model=model,
            api_key=api_key,
            messages=messages,
        )
    except Exception as exc:
        logger.warning("RAG L2 target resolver failed: %s", exc)
        return TargetPostResolution(
            post_id=None,
            rationale=f"resolver_error: {exc}",
            confidence="none",
        )

    return parse_target_resolution(raw or "", catalog_posts=catalog_posts)


def format_resolver_trace_lines(
    *,
    resolution: TargetPostResolution,
    raw: str = "",
) -> list[str]:
    lines = [
        f"post_id={resolution.post_id!r}",
        f"confidence={resolution.confidence!r}",
        f"rationale={resolution.rationale!r}",
    ]
    if raw.strip():
        preview = raw.strip()
        if len(preview) > 600:
            preview = preview[:599] + "…"
        lines.append(f"raw: {preview}")
    return lines
