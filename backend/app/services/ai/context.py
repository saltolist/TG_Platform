"""Assemble LLM message list for AI replies (Phase 2, step 3.3)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint
from app.services.ai.bundle_profile import (
    advance_bundle_profile,
    bundle_text_for_primer,
    ensure_unseen_channel_bundle_floating,
    get_floating_bundle_injections,
    prepare_bundle_profile_for_assemble,
)
from app.services.ai.chat_history import (
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW
from app.services.ai.context_turns import compute_window_user_turns
from app.services.ai.context_primer import (
    DEFAULT_SYSTEM_PROMPT,
    build_dialog_messages,
    build_primer_user_content,
    take_prompt_window,
)
from app.services.ai.message_bundle import (
    resolve_bundle_from_messages,
    resolve_bundle_from_profile_snapshot,
)
from app.services.ai.context_labels import assemble_reply_messages_from_labels
from app.services.ai.summary_catalog import (
    ensure_initial_global_version,
    ensure_post_local_catalog_current,
)
from app.services.ai.thread_context import resolve_thread_state

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
) -> list[dict[str, str]]:
    """Build OpenAI-compatible messages: system → primer → dialog window."""
    system_prompt = str(ai_profile.get("systemPrompt") or "").strip() or DEFAULT_SYSTEM_PROMPT

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

    label_messages = assemble_reply_messages_from_labels(
        ai_profile=ai_profile,
        user_text=user_text,
        scope=scope,
        history=history,
        chat_meta=chat_meta,
        catalog=catalog,
        post_id=post_id if scope == "post" else None,
        log_labels=log_labels,
    )
    if label_messages is not None:
        return label_messages

    current_bundle = build_summary_bundle(
        channel_profile,
        telegram=telegram_profile,
        post=post,
    )
    fingerprint = bundle_fingerprint(channel_profile, telegram=telegram_profile, post=post)

    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)

    trimmed_user_text = user_text.strip()
    if trimmed_user_text:
        if not valid_pairs or valid_pairs[-1][0] != "user":
            valid_pairs.append(("user", trimmed_user_text))
        elif valid_pairs[-1][1] != trimmed_user_text:
            valid_pairs.append(("user", trimmed_user_text))

    user_turn_count = count_user_turns(valid_pairs)
    window_pairs = take_prompt_window(valid_pairs)
    window_user_turns = compute_window_user_turns(valid_pairs)

    rolling_summary = ""
    bundle_profile: dict[str, Any] = {}
    if isinstance(chat_meta, Mapping):
        thread_state, _, _ = resolve_thread_state(
            chat_meta,
            list(history or []),
            global_fingerprint=fingerprint,
        )
        rolling_summary = str(thread_state.get("rolling_summary") or "").strip()
        bundle_profile = prepare_bundle_profile_for_assemble(
            thread_state.get("rolling_summary_profile"),
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
            current_bundle=current_bundle,
            current_fingerprint=fingerprint,
            global_fingerprint_at_last_refresh=thread_state.get("global_fingerprint_at_last_refresh"),
            parent_generations=thread_state.get("parent_generations_snapshot"),
        )
    else:
        bundle_profile = prepare_bundle_profile_for_assemble(
            None,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        )

    primer_stub_id = str(bundle_profile.get("stub_generation_id") or "")
    bundle_for_primer = bundle_text_for_primer(
        bundle_profile,
        current_bundle=current_bundle,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    floating_bundles = get_floating_bundle_injections(
        bundle_profile,
        primer_stub_id=primer_stub_id,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )

    message_bundle = resolve_bundle_from_messages(
        list(history or []),
        bundle_profile,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        fallback_primer=bundle_for_primer,
        fallback_stub_id=primer_stub_id,
        fallback_floating=floating_bundles,
    )
    if message_bundle is None:
        message_bundle = resolve_bundle_from_profile_snapshot(
            bundle_profile,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
            fallback_primer=bundle_for_primer,
            fallback_stub_id=primer_stub_id,
            fallback_floating=floating_bundles,
        )
    if message_bundle is not None:
        bundle_for_primer, primer_stub_id, floating_bundles = message_bundle

    floating_bundles = ensure_unseen_channel_bundle_floating(
        floating_bundles,
        profile_meta=bundle_profile,
        primer_stub_id=primer_stub_id,
        current_bundle=current_bundle,
        current_fingerprint=fingerprint,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
        parent_generations=(
            thread_state.get("parent_generations_snapshot")
            if isinstance(chat_meta, Mapping)
            else None
        ),
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_primer_user_content(bundle_for_primer, rolling_summary)},
        {"role": "assistant", "content": PRIMER_ACK},
    ]
    messages.extend(
        build_dialog_messages(
            window_pairs,
            valid_pairs=valid_pairs,
            floating_bundles=floating_bundles,
        )
    )

    return messages


def build_reply_messages(
    ai_profile: Mapping[str, Any],
    user_text: str,
    scope: str = "global",
    **kwargs: Any,
) -> list[dict[str, str]]:
    """Backward-compatible entry point (minimal context when kwargs omitted)."""
    return assemble_reply_messages(
        ai_profile=ai_profile,
        user_text=user_text,
        scope=scope,
        history=kwargs.get("history"),
        channel_profile=kwargs.get("channel_profile"),
        telegram_profile=kwargs.get("telegram_profile"),
        post_data=kwargs.get("post_data"),
        chat_meta=kwargs.get("chat_meta"),
        summary_catalog=kwargs.get("summary_catalog"),
    )
