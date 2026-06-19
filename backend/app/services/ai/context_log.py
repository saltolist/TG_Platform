"""Terminal logging of LLM context (full prompt + reply, including branches)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Mapping

from app.services.ai.chat_history import (
    clamp_active_branch_index,
    filter_alternating_roles,
    flatten_visible_with_paths,
    linearize_for_llm,
)

logger = logging.getLogger("tg.ai.context")

_BANNER = "═" * 72
_SECTION = "─" * 72
_filter_lock = threading.Lock()
_chat_filter = ""


def init_chat_filter(initial: str) -> None:
    global _chat_filter
    with _filter_lock:
        _chat_filter = initial.strip()


def get_chat_filter() -> str:
    with _filter_lock:
        return _chat_filter


def set_chat_filter(value: str) -> None:
    global _chat_filter
    with _filter_lock:
        _chat_filter = value.strip()


def _chat_label(*, scope: str, chat_id: str | None, post_id: str | None, post_chat_id: str | None) -> str:
    if scope == "post":
        return f"post={post_id or '?'} chat={post_chat_id or '?'}"
    return f"chat={chat_id or '?'}"


def _format_ai_message(path: str, message: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    variants = message.get("variants")
    if isinstance(variants, list) and variants:
        try:
            selected = int(message.get("selectedVariant") or 0)
        except (TypeError, ValueError):
            selected = 0
        selected = max(0, min(selected, len(variants) - 1))
        lines.append(f"[{path}] ai — {len(variants)} variant(s), selected={selected}")
        for index, variant in enumerate(variants):
            if not isinstance(variant, Mapping):
                continue
            tag = " *SELECTED*" if index == selected else ""
            caption = str(variant.get("llmCaption") or variant.get("label") or "").strip()
            model_hint = f" ({caption})" if caption else ""
            text = str(variant.get("text") or "").strip()
            lines.append(f"  ├─ variant {index}{tag}{model_hint}")
            lines.append(f"  │  {text}")
        return lines

    text = str(message.get("text") or "").strip()
    if message.get("streaming"):
        text = text or "(streaming…)"
    lines.append(f"[{path}] ai: {text}")
    return lines


def _format_user_branches(path: str, message: Mapping[str, Any]) -> list[str]:
    branches = message.get("userBranches")
    label_suffix = ""
    raw_label = message.get("contextLabel") or message.get("context_label")
    if isinstance(raw_label, str) and raw_label.strip():
        label_suffix = f"  [{raw_label.strip()}]"

    if not isinstance(branches, list) or not branches:
        text = str(message.get("text") or "").strip()
        return [f"[{path}] user{label_suffix}: {text}"]

    active = clamp_active_branch_index(message)
    lines = [f"[{path}] user — {len(branches)} branch(es), active={active}{label_suffix}"]
    for index, branch in enumerate(branches):
        if not isinstance(branch, Mapping):
            continue
        tag = " *ACTIVE*" if index == active else ""
        text = str(branch.get("text") or "").strip()
        lines.append(f"  ├─ branch {index}{tag}")
        lines.append(f"  │  text: {text}")
        continuation = branch.get("continuation")
        if isinstance(continuation, list) and continuation:
            nested = format_history_tree(continuation, prefix=f"{path}.{index}/")
            for nested_line in nested.splitlines():
                lines.append(f"  │  {nested_line}")
    return lines


def format_history_tree(
    history: list[Mapping[str, Any]] | None,
    *,
    prefix: str = "",
) -> str:
    """Render full chat tree with all user branches and ai variants."""
    if not history:
        return "(empty history)"

    lines: list[str] = []
    for index, message in enumerate(history):
        if not isinstance(message, Mapping):
            continue
        path = f"{prefix}{index}" if prefix else str(index)
        role = message.get("role")
        if role == "user":
            lines.extend(_format_user_branches(path, message))
            if message.get("userBranches"):
                break
            continue
        if role == "ai":
            lines.extend(_format_ai_message(path, message))
            continue
        lines.append(f"[{path}] {role}: {message}")

    return "\n".join(lines) if lines else "(empty history)"


def format_active_thread(history: list[Mapping[str, Any]] | None) -> str:
    """Linear active branch — the thread that goes into the LLM window."""
    pairs = filter_alternating_roles(linearize_for_llm(list(history or [])))
    if not pairs:
        return "(empty active thread)"
    lines: list[str] = []
    for role, content in pairs:
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _llm_message_label(index: int, role: str, content: str) -> str:
    if role == "system":
        return "system"
    if role == "assistant" and index == 2 and content.startswith("Понял"):
        return "assistant/primer-ack"
    if role == "user" and content.startswith("SUMMARY_BUNDLE:"):
        if index <= 2:
            return "user/primer"
        return "user/floating-bundle"
    return role


def format_llm_messages(
    messages: list[dict[str, str]],
    *,
    message_labels: Mapping[int, str] | None = None,
) -> str:
    lines: list[str] = []
    for index, message in enumerate(messages):
        role = message.get("role", "?")
        content = message.get("content", "")
        label = None
        if message_labels is not None:
            label = message_labels.get(index)
        if not label:
            label = _llm_message_label(index, role, content)
        lines.append(f"── [{index}] {label} {_SECTION[: max(0, 40 - len(label))]}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def should_log_llm_context(
    *,
    enabled: bool,
    chat_filter: str,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
) -> bool:
    """Log only when AI_CONTEXT_LOG=1 and AI_CONTEXT_LOG_CHAT matches this request."""
    if not enabled:
        return False
    filt = chat_filter.strip()
    if not filt:
        return False

    if filt.startswith("post:"):
        parts = filt.split(":", 2)
        if len(parts) != 3:
            return False
        _, want_post_id, want_chat_id = parts
        return (
            scope == "post"
            and str(post_id or "") == want_post_id
            and str(post_chat_id or "") == want_chat_id
        )

    if scope == "global":
        return str(chat_id or "") == filt
    if scope == "post":
        return str(post_chat_id or "") == filt
    return False


def log_llm_request(
    *,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
    provider: str,
    model: str,
    history: list[Mapping[str, Any]] | None,
    messages: list[dict[str, str]],
    message_labels: Mapping[int, str] | None = None,
) -> None:
    label = _chat_label(scope=scope, chat_id=chat_id, post_id=post_id, post_chat_id=post_chat_id)
    active_paths = [
        ".".join(str(part) for part in item["path"])
        for item in flatten_visible_with_paths(list(history or []))
    ]
    body = "\n".join(
        [
            _BANNER,
            f"AI REQUEST  scope={scope}  {label}  model={provider}/{model}",
            _SECTION,
            "Chat tree (all branches & variants):",
            format_history_tree(history),
            _SECTION,
            f"Active thread (linear, paths: {', '.join(active_paths) or '—'}):",
            format_active_thread(history),
            _SECTION,
            f"Messages to LLM ({len(messages)}):",
            format_llm_messages(messages, message_labels=message_labels),
            _BANNER,
        ]
    )
    logger.info("\n%s", body)


def log_llm_response(
    *,
    scope: str,
    chat_id: str | None,
    post_id: str | None,
    post_chat_id: str | None,
    provider: str,
    model: str,
    assistant_text: str,
) -> None:
    label = _chat_label(scope=scope, chat_id=chat_id, post_id=post_id, post_chat_id=post_chat_id)
    reply = assistant_text.strip() or "(empty)"
    body = "\n".join(
        [
            _BANNER,
            f"AI RESPONSE  scope={scope}  {label}  model={provider}/{model}",
            _SECTION,
            "Assistant reply:",
            reply,
            _BANNER,
        ]
    )
    logger.info("\n%s", body)
