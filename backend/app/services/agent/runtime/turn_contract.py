"""Deterministic per-turn goal and referent contract.

The LLM still decides how to phrase an answer, but it must not decide which
object words such as "this note" or "their posts" refer to from scratch in
every node.  This module extracts the stable parts once and threads them
through classifier, research and answer generation.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from app.services.ai.chat_history import linearize_for_llm

_POST_IDEA_RE = re.compile(
    r"\bпост(?:ом|а|у|е)?\s*(\d+)\s*[—-]\s*[«\"]?([^»\"\n,.]+(?:[,:][^»\"\n]+)?)",
    re.IGNORECASE,
)
_POST_REFERENT_RE = re.compile(r"\b(эт\w*|этому|этого|этот|он|его)\s+пост|\bэтому\s*$", re.I)
_NOTE_REFERENT_RE = re.compile(
    r"\b(эт\w*\s+заметк\w*|эту\s+заметк\w*|про\s+заметк\w*|"
    r"создал\w*\s+заметк\w*|добавил\w*\s+(?:ее|её)|прочитай\w*\s+(?:ее|её)|"
    r"посмотри\w*\s+на\s+(?:эту|нее|неё)|что\s+там|пример\w*\s+.*\s+там)\b",
    re.I,
)

SUPPORTED_CAPABILITIES = (
    "read posts, notes, attachments, comments and post analytics",
    "create, edit, schedule, publish, delete and restore posts via approval",
    "generate and attach media via approval",
)


def _dialog_pairs(history: list[Mapping[str, Any]] | None) -> list[tuple[str, str]]:
    # Preserve a leading assistant artifact as well: imported/branched histories
    # can legitimately start at a generated draft even though the conversational
    # prompt later filters roles for alternation.
    return linearize_for_llm(history or [])


def _last_text(pairs: list[tuple[str, str]], role: str) -> str:
    for item_role, text in reversed(pairs):
        if item_role == role and text.strip():
            return text.strip()
    return ""


def _working_post_artifact(
    pairs: list[tuple[str, str]],
    *,
    prefer_longest: bool = False,
) -> str:
    """Return the latest full draft-like assistant artifact, without truncation."""
    candidates: list[str] = []
    for role, text in reversed(pairs):
        if role != "assistant":
            continue
        stripped = text.strip()
        if len(stripped) >= 500 and stripped.count("\n\n") >= 2:
            if not prefer_longest:
                return stripped[:12000]
            candidates.append(stripped[:12000])
    return max(candidates, key=len, default="")


def _ledger_artifact(
    dialog_ledger: tuple[Any, ...],
    *,
    post_draft_only: bool = False,
    prefer_longest: bool = False,
) -> str:
    """Return the latest full assistant artifact kept outside clipped history."""
    candidates: list[str] = []
    for turn in reversed(dialog_ledger):
        for entity in reversed(tuple(getattr(turn, "entities", ()) or ())):
            entity_type = str(getattr(entity, "entity_type", "") or "")
            if post_draft_only and entity_type != "post_draft":
                continue
            content = str(getattr(entity, "content", "") or "").strip()
            if content:
                if not prefer_longest:
                    return content[:12000]
                candidates.append(content[:12000])
    return max(candidates, key=len, default="")


def _post_idea_label(text: str) -> str:
    match = _POST_IDEA_RE.search(text or "")
    if not match:
        return ""
    title = " ".join(match.group(2).strip(" «»\"").split())
    return f"Пост {match.group(1)} — {title}" if title else f"Пост {match.group(1)}"


def _clean_note_title(value: Any) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    # BlockNote imports can repeat the document heading several times.  A
    # repeated title is one title, not five separate semantic signals.
    return lines[0]


def _recent_note_target(
    *,
    user_text: str,
    pairs: list[tuple[str, str]],
    recent_note: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not recent_note:
        return None
    recent_users = "\n".join(text for role, text in pairs[-8:] if role == "user")
    creation_context = f"{recent_users}\n{user_text}"
    has_creation_context = bool(
        re.search(r"\b(создал|добавил)\w*\s+(?:эту\s+)?заметк", creation_context, re.I)
    )
    title = _clean_note_title(recent_note.get("title"))
    title_tokens = {
        token[:6]
        for token in re.findall(r"[\w-]+", title.lower())
        if len(token) >= 5
    }
    context_tokens = {
        token[:6]
        for token in re.findall(r"[\w-]+", f"{recent_users}\n{user_text}".lower())
        if len(token) >= 5
    }
    has_named_note_context = bool(
        title_tokens
        and len(title_tokens & context_tokens) >= min(2, len(title_tokens))
    )
    if not (
        _NOTE_REFERENT_RE.search(user_text)
        and (has_creation_context or has_named_note_context)
    ):
        return None
    note_id = str(recent_note.get("id") or "").strip()
    if not note_id:
        return None
    return {
        "kind": "recent_note",
        "id": note_id,
        "title": title or note_id,
        "created_at": str(recent_note.get("created_at") or ""),
        "authoritative": True,
    }


def _ledger_note_target(
    *,
    user_text: str,
    dialog_ledger: tuple[Any, ...],
) -> dict[str, Any] | None:
    if not _NOTE_REFERENT_RE.search(user_text or ""):
        return None
    for turn in reversed(dialog_ledger):
        for entity in reversed(tuple(getattr(turn, "entities", ()) or ())):
            if str(getattr(entity, "entity_type", "")) != "note":
                continue
            note_id = str(getattr(entity, "note_id", "") or "").strip()
            if not note_id:
                continue
            return {
                "kind": "ledger_note",
                "id": note_id,
                "title": str(getattr(entity, "title", "") or note_id),
                "authoritative": True,
            }
    return None


def build_turn_contract(
    *,
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    scope: str,
    recent_note: Mapping[str, Any] | None = None,
    dialog_ledger: tuple[Any, ...] = (),
) -> dict[str, Any]:
    current = (user_text or "").strip()
    lowered = current.lower()
    pairs = _dialog_pairs(history)
    history_assistant = _last_text(pairs, "assistant")
    ledger_assistant = _ledger_artifact(dialog_ledger)
    last_assistant = ledger_assistant or history_assistant
    prefer_longest_artifact = any(
        marker in lowered
        for marker in ("размер уменьш", "слишком корот", "слишком маленьк")
    )
    working_artifact = (
        _working_post_artifact(pairs, prefer_longest=prefer_longest_artifact)
        or _ledger_artifact(
            dialog_ledger,
            post_draft_only=True,
            prefer_longest=prefer_longest_artifact,
        )
    )

    compare_posts = "пересека" in lowered and "пост" in lowered
    style_request = any(
        marker in lowered
        for marker in (
            "в их стиле",
            "в стиле моих пост",
            "именно в стиле",
            "как мои обычные",
            "как мои полные",
            "их верст",
            "их вёрст",
        )
    )
    feed_corpus = bool(
        compare_posts
        or style_request
        or ("пост" in lowered and any(m in lowered for m in ("имеющ", "из лент", "в лент", "которые у меня уже")))
    )
    write_post = bool(
        any(marker in lowered for marker in ("напиши текст", "напиши пост", "текст этого пост"))
        or ("напиши" in lowered and ("пост" in lowered or working_artifact))
    )
    inspect_note = "замет" in lowered and any(
        marker in lowered for marker in ("прочитай", "посмотри", "что написано", "что дальше", "добавил", "создал")
    )

    if style_request or write_post:
        intent = "write_post"
    elif compare_posts:
        intent = "compare_with_feed_posts"
    elif inspect_note:
        intent = "inspect_note"
    elif scope == "post" and any(marker in lowered for marker in ("добав", "убер", "удал", "сделай", "измени")):
        intent = "edit_post"
    else:
        intent = "answer"

    target = _recent_note_target(
        user_text=current,
        pairs=pairs,
        recent_note=recent_note,
    )
    if target is None:
        target = _ledger_note_target(
            user_text=current,
            dialog_ledger=dialog_ledger,
        )
    if target is None and last_assistant and (
        _POST_REFERENT_RE.search(lowered) or "этого поста" in lowered or "этому посту" in lowered
    ):
        referent_content = working_artifact if write_post and working_artifact else last_assistant
        target = {
            "kind": "dialog_artifact",
            "role": "assistant",
            "label": _post_idea_label(referent_content) or "предмет предыдущего ответа ассистента",
            "content": referent_content[:12000],
            "authoritative": True,
        }

    output: dict[str, Any] = {"kind": "answer"}
    if intent == "write_post":
        output = {
            "kind": "post_draft",
            "match_reference_style": style_request,
            "match_sentence_length": style_request,
            "preserve_paragraph_layout": style_request or "абзац" in lowered,
            "require_section_headings": "заголов" in lowered or style_request,
            "min_paragraphs": 5 if style_request or "абзац" in lowered else 2,
            "min_section_headings": 2 if "заголов" in lowered or style_request else 0,
        }
        if working_artifact:
            output["min_chars"] = max(400, int(len(working_artifact) * 0.9))
            output["working_artifact"] = working_artifact

    corpus = "feed_posts" if feed_corpus else "workspace"
    if target and target.get("kind") in {"recent_note", "ledger_note"}:
        corpus = "exact_note"

    requires_workspace = bool(
        feed_corpus
        or target
        or inspect_note
        or any(marker in lowered for marker in ("пост", "замет", "канал", "метрик", "изображ"))
    )
    if corpus in {"feed_posts", "exact_note"}:
        max_steps = 4
    elif target:
        max_steps = 6
    else:
        # Broad inventory questions may legitimately need the configured ten
        # steps. The no-progress guard, not a smaller blanket cap, stops loops.
        max_steps = 10

    success_criteria = ["answer the current user request, not a neighboring semantic topic"]
    if corpus == "feed_posts":
        success_criteria.append("use actual feed posts as evidence; planning notes are out of scope")
    if target:
        success_criteria.append("use only the authoritative referent as the target object")
    if output.get("kind") == "post_draft":
        success_criteria.append("satisfy the requested length, headings and paragraph layout")

    search_query = current
    if target and target.get("kind") == "dialog_artifact":
        search_query = f"{current}. Целевой материал: {target.get('label')}. {target.get('content', '')[:800]}"
    elif target and target.get("kind") in {"recent_note", "ledger_note"}:
        search_query = f"Открыть конкретную заметку {target.get('title')} ({target.get('id')})"

    return {
        "version": 1,
        "intent": intent,
        "scope": scope,
        "corpus": corpus,
        "target": target,
        "output": output,
        "requires_workspace": requires_workspace,
        "required_evidence_kinds": ["post_text"] if corpus == "feed_posts" else [],
        "search_query": search_query,
        "max_steps": max_steps,
        "success_criteria": success_criteria,
        "supported_capabilities": list(SUPPORTED_CAPABILITIES),
        "prohibited_recommendations": [
            "link a note to posts or files",
            "claim a workspace mutation exists when it is not in supported_capabilities",
        ],
    }


def render_turn_contract(contract: Mapping[str, Any] | None) -> str:
    if not contract:
        return "(контракт хода отсутствует)"
    return json.dumps(dict(contract), ensure_ascii=False, sort_keys=True)
