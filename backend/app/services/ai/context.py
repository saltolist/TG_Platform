"""Assemble LLM message list for AI replies (Phase 2, step 3.3)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint
from app.services.ai.bundle_profile import (
    bundle_text_for_primer,
    ensure_bundle_profile,
    get_floating_bundle_injections,
)
from app.services.ai.chat_history import (
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_config import PRIMER_ACK, PROMPT_WINDOW
from app.services.ai.context_meta import annotate_user_turns, compute_window_user_turns

DEFAULT_SYSTEM_PROMPT = (
    "Ты AI-ассистент TG Platform. Помогай автору Telegram-канала с текстами, "
    "идеями и анализом. Отвечай на языке пользователя, кратко и по делу."
)

PRIMER_USER_TAG = "SUMMARY_BUNDLE"
CONTEXT_SUMMARY_TAG = "CONTEXT_SUMMARY"


def build_primer_user_content(bundle_text: str, rolling_summary: str = "") -> str:
    parts = [f"{PRIMER_USER_TAG}:", bundle_text.strip()]
    summary = rolling_summary.strip()
    if summary:
        parts.extend(["", f"{CONTEXT_SUMMARY_TAG}:", summary])
    return "\n".join(parts)


def attach_floating_bundle_to_user_message(bundle_text: str, user_text: str) -> str:
    """Append channel update bundle to the user turn it belongs to (no extra ack pair)."""
    bundle_block = f"{PRIMER_USER_TAG}:\n{bundle_text.strip()}"
    text = user_text.strip()
    if not text:
        return bundle_block
    return f"{bundle_block}\n\n{text}"


def take_prompt_window(pairs: list[tuple[str, str]], *, window_size: int = PROMPT_WINDOW) -> list[tuple[str, str]]:
    if window_size <= 0:
        return []
    return pairs[-window_size:]


def build_dialog_messages(
    window_pairs: list[tuple[str, str]],
    *,
    valid_pairs: list[tuple[str, str]],
    floating_bundles: dict[int, str],
) -> list[dict[str, str]]:
    annotated = annotate_user_turns(valid_pairs)
    window_len = len(window_pairs)
    window_annotated = annotated[-window_len:] if window_len else []

    messages: list[dict[str, str]] = []
    for user_turn, role, content in window_annotated:
        if role == "user" and user_turn is not None and user_turn in floating_bundles:
            content = attach_floating_bundle_to_user_message(floating_bundles[user_turn], content)
        messages.append({"role": role, "content": content})
    return messages


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
) -> list[dict[str, str]]:
    """Build OpenAI-compatible messages: system → primer → dialog window."""
    system_prompt = str(ai_profile.get("systemPrompt") or "").strip() or DEFAULT_SYSTEM_PROMPT

    post = post_data if scope == "post" else None
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
        rolling_summary = str(chat_meta.get("rolling_summary") or "").strip()
        bundle_profile = ensure_bundle_profile(
            chat_meta.get("rolling_summary_profile"),
            current_bundle=current_bundle,
            current_fingerprint=fingerprint,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        )
    else:
        bundle_profile = ensure_bundle_profile(
            None,
            current_bundle=current_bundle,
            current_fingerprint=fingerprint,
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
    )
