"""Assemble LLM message list for AI replies (Phase 2, step 3.3)."""

from __future__ import annotations

from typing import Any, Mapping

from app.core.config import get_settings
from app.services.ai.context_labels import assemble_reply_messages_from_labels
from app.services.ai.summary_catalog import (
    ensure_initial_global_version,
    ensure_post_local_catalog_current,
)


def append_user_text_to_pairs(
    valid_pairs: list[tuple[str, str]],
    user_text: str,
) -> list[tuple[str, str]]:
    """Append a user turn to valid_pairs if not already the last entry with same text."""
    trimmed = user_text.strip()
    if not trimmed:
        return valid_pairs
    if not valid_pairs or valid_pairs[-1][0] != "user":
        valid_pairs.append(("user", trimmed))
    elif valid_pairs[-1][1] != trimmed:
        valid_pairs.append(("user", trimmed))
    return valid_pairs


def assemble_reply_messages(
    *,
    ai_profile: Mapping[str, Any],
    user_text: str,
    scope: str = "global",
    history: list[Mapping[str, Any]] | None = None,
    channel_profile: Mapping[str, Any] | None = None,
    telegram_profile: Mapping[str, Any] | None = None,
    post_data: Mapping[str, Any] | None = None,
    chat_meta: Mapping[str, Any] | None = None,
    summary_catalog: Mapping[str, Any] | None = None,
    log_labels: dict[int, str] | None = None,
    log_stamps: dict[int, dict[str, Any]] | None = None,
    rag_context: str | None = None,
) -> list[dict[str, str]]:
    """Build OpenAI-compatible messages: system → primer → dialog window [→ RAG]."""
    post = post_data if scope == "post" else None
    post_id = str(post.get("id") or "") if isinstance(post, Mapping) and post.get("id") else None

    catalog = ensure_initial_global_version(
        summary_catalog,
        channel=channel_profile,
        telegram=telegram_profile,
    )
    if scope == "post" and post_id:
        catalog, _ = ensure_post_local_catalog_current(
            catalog,
            post_id=post_id,
            channel=channel_profile,
            telegram=telegram_profile,
            post=post,
        )

    messages = None
    if get_settings().ai_context_stamps:
        from app.services.ai.context_stamp_assembly import assemble_reply_messages_from_stamps

        messages = assemble_reply_messages_from_stamps(
            ai_profile=ai_profile,
            user_text=user_text,
            scope=scope,
            history=history,
            chat_meta=chat_meta,
            catalog=catalog,
            post_id=post_id if scope == "post" else None,
            log_labels=log_labels,
            log_stamps=log_stamps,
        )
    else:
        messages = assemble_reply_messages_from_labels(
            ai_profile=ai_profile,
            user_text=user_text,
            scope=scope,
            history=history,
            chat_meta=chat_meta,
            catalog=catalog,
            post_id=post_id if scope == "post" else None,
            log_labels=log_labels,
        )

    if rag_context:
        # Append RAG context to the last user message
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                messages[i] = {
                    "role": "user",
                    "content": messages[i]["content"] + "\n\n" + rag_context,
                }
                break

    return messages

