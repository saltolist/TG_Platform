"""Universal entity binding policy for L2 agentic RAG."""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.services.ai.rag import NODE_NOTE_CHUNK, NODE_POST_TEXT
from app.services.ai.rag_retrieval_brief import RetrievalBrief
from app.services.ai.rag_retrieval_plan import POST_QUERY_MARKERS

_PLACEHOLDER_MARKERS = (
    "PLACEHOLDER",
    "TODO",
    "TBD",
    "UNKNOWN",
    "FROM_SEARCH",
    "FROM_OPEN",
    "FROM_LIST",
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_NUMERIC_ID_RE = re.compile(r"^\d+$")

_CONFIDENT_RESOLUTION = frozenset({"high", "medium"})


def is_invalid_plan_id(value: str) -> bool:
    """True when planner invented a placeholder instead of a real id."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return True
    if "<" in cleaned and ">" in cleaned:
        return True
    upper = cleaned.upper()
    if any(marker in upper for marker in _PLACEHOLDER_MARKERS):
        return True
    if cleaned.startswith(("attachment:", "file:", "note:", "post:", "media:")):
        suffix = cleaned.split(":", 1)[1].strip()
        return is_invalid_plan_id(suffix)
    if _UUID_RE.match(cleaned) or _NUMERIC_ID_RE.match(cleaned):
        return False
    if re.fullmatch(r"[\w-]+", cleaned) and len(cleaned) >= 2:
        return False
    return True


def collect_invalid_plan_ids(plan_steps: list[Any]) -> list[str]:
    invalid: list[str] = []
    for step in plan_steps:
        tool = getattr(step, "tool", "")
        args = getattr(step, "args", {}) or {}
        if not isinstance(args, dict):
            continue
        for key in ("post_id", "note_id"):
            raw = args.get(key)
            if raw is None:
                continue
            value = str(raw).strip()
            if value and is_invalid_plan_id(value):
                invalid.append(f"{tool}.{key}={value!r}")
        if tool == "HydrateAttachment":
            ref = str(args.get("ref") or "").strip()
            if ref and not ref.startswith(("attachment:", "file:")) and is_invalid_plan_id(ref):
                invalid.append(f"HydrateAttachment.ref={ref!r}")
    return invalid


def l1_note_only_post_id(
    l1_results: list[Mapping[str, Any]],
    post_id: str,
) -> bool:
    pid = str(post_id or "").strip()
    if not pid:
        return False
    has_post_text = any(
        str(item.get("node_type") or "") == NODE_POST_TEXT
        and str(item.get("post_id") or "").strip() == pid
        for item in l1_results
    )
    if has_post_text:
        return False
    return any(
        str(item.get("node_type") or "") == NODE_NOTE_CHUNK
        and str(item.get("post_id") or "").strip() == pid
        for item in l1_results
    )


def can_bind_target_post(
    *,
    brief: RetrievalBrief | None,
    scope: str,
    post_id: str,
    post_data: Mapping[str, Any] | None,
    discovery_completed: bool,
    seed_post_id: str | None,
    tier_a_post_id: str | None,
    l1_results: list[Mapping[str, Any]] | None = None,
    target_resolution_post_id: str | None = None,
    target_resolution_confidence: str | None = None,
) -> tuple[bool, str]:
    pid = str(post_id or "").strip()
    if not pid:
        return False, "empty_post_id"

    if scope == "post":
        return True, "post_scope"
    if seed_post_id and pid == seed_post_id:
        return True, "seed_post"
    if tier_a_post_id and pid == tier_a_post_id:
        return True, "tier_a_escalate"

    resolution_id = str(target_resolution_post_id or "").strip()
    resolution_conf = str(target_resolution_confidence or "").strip().lower()
    if resolution_id and resolution_conf in _CONFIDENT_RESOLUTION:
        if pid == resolution_id:
            return True, "target_resolution"
        return False, "target_resolution_mismatch"

    if not brief or not brief.named_post_query:
        if discovery_completed:
            return True, "discovery_completed"
        return False, "discovery_required"

    if not discovery_completed:
        return False, "discovery_required"

    if l1_results and l1_note_only_post_id(l1_results, pid):
        return False, "l1_note_referent_mismatch"

    return True, "discovery_referent_ok"


def plan_has_off_target_discovery(plan_steps: list[Any]) -> bool:
    """Named-post query should not rely on note_chunk-only discovery."""
    if not plan_steps:
        return False
    first = plan_steps[0]
    if getattr(first, "tool", "") != "SearchNodes":
        return False
    args = getattr(first, "args", {}) or {}
    if not isinstance(args, dict):
        return False
    node_types = args.get("node_types")
    if not isinstance(node_types, list) or not node_types:
        return False
    normalized = {str(item).strip() for item in node_types if str(item).strip()}
    if not normalized or normalized == {"note_chunk"}:
        return not any(getattr(step, "tool", "") == "ListPosts" for step in plan_steps)
    if "post_text" in normalized:
        return False
    return "note_chunk" in normalized and not any(
        getattr(step, "tool", "") == "ListPosts" for step in plan_steps
    )


_POST_SCOPED_BINDING_TOOLS = frozenset(
    {
        "OpenPost",
        "ListPostNotes",
        "OpenNote",
        "ListNoteAttachments",
        "HydrateAttachment",
    }
)

_NOTE_MEDIA_TOOLS = frozenset({"OpenNote", "ListNoteAttachments", "HydrateAttachment"})


def should_block_post_scoped_tool(
    *,
    tool: str,
    post_id: str | None,
    brief: RetrievalBrief | None,
    scope: str,
    resolved_target_post_id: str | None,
    l1_results: list[Mapping[str, Any]] | None = None,
    opened_posts: Mapping[str, Mapping[str, Any]] | None = None,
    target_resolution_post_id: str | None = None,
    target_resolution_confidence: str | None = None,
) -> tuple[bool, str, str]:
    """Return (blocked, summary, error_code) for global named-post binding policy."""
    del opened_posts  # binding uses resolver / resolved_target_post_id only
    if tool not in _POST_SCOPED_BINDING_TOOLS:
        return False, "", ""
    if scope != "global" or brief is None or not brief.named_post_query:
        return False, "", ""

    pid = str(post_id or "").strip()
    l1_results = l1_results or []

    resolution_id = str(target_resolution_post_id or "").strip()
    resolution_conf = str(target_resolution_confidence or "").strip().lower()
    if (
        resolution_id
        and resolution_conf in _CONFIDENT_RESOLUTION
        and tool == "OpenPost"
        and pid
        and pid != resolution_id
    ):
        summary = (
            f"OpenPost({pid}): blocked — target resolution post_id={resolution_id} "
            f"(confidence={resolution_conf})"
        )
        return True, summary, "binding_blocked"

    if resolved_target_post_id and pid and pid != resolved_target_post_id:
        summary = (
            f"{tool}({pid}): blocked — target bound to {resolved_target_post_id} "
            "(cross_post=deny)"
        )
        return True, summary, "binding_blocked"

    if tool == "OpenPost" and pid:
        if (
            not resolved_target_post_id
            and l1_note_only_post_id(l1_results, pid)
        ):
            summary = (
                f"OpenPost({pid}): blocked — L1 note candidate before target binding"
            )
            return True, summary, "binding_blocked"
        return False, "", ""

    if not resolved_target_post_id and tool in _NOTE_MEDIA_TOOLS | {"ListPostNotes"}:
        summary = f"{tool}: blocked — target post not bound yet"
        return True, summary, "binding_blocked"

    if (
        not resolved_target_post_id
        and pid
        and tool in _NOTE_MEDIA_TOOLS
        and l1_note_only_post_id(l1_results, pid)
    ):
        summary = (
            f"{tool}: blocked — note/media from L1 candidate post {pid} "
            "before target binding"
        )
        return True, summary, "binding_blocked"

    return False, "", ""


def format_target_evidence_gap(state: Any) -> str | None:
    """Human-readable gap line for answer model when target post lacks attachments."""
    gap = getattr(state, "target_evidence_gap", None)
    target_id = getattr(state, "resolved_target_post_id", None)
    if not gap or not target_id:
        return None

    opened = getattr(state, "opened_posts", {}) or {}
    post_data = opened.get(str(target_id), {})
    from app.services.ai.rag import _post_title_from_text

    text_value = str(post_data.get("text") or "").strip()
    title = _post_title_from_text(text_value) if text_value else str(target_id)

    if gap == "no_notes_on_target":
        return (
            f"У поста «{title}» (post_id={target_id}) нет заметок и вложений. "
            "Изображения для сравнения на этом посте недоступны. "
            "Не используй media/заметки других постов без явного разрешения пользователя."
        )
    if gap == "no_image_attachments_on_target":
        return (
            f"У поста «{title}» (post_id={target_id}) нет image-вложений в заметках. "
            "Сравнение изображений по этому посту невозможно."
        )
    return None
