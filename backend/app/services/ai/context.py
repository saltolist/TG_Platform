"""Assemble LLM message list for AI replies (Phase 2, step 3.3)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.bundle import build_summary_bundle, bundle_fingerprint
from app.services.ai.chat_history import (
    count_user_turns,
    filter_alternating_roles,
    linearize_for_llm,
)
from app.services.ai.context_config import (
    PRIMER_ACK,
    PROMPT_WINDOW,
    SUMMARY_BUNDLE_CATCHUP_MESSAGES,
)

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


def resolve_stub_bundle_text(
    *,
    profile_meta: Mapping[str, Any] | None,
    current_bundle: str,
    current_fingerprint: str,
    user_turn_count: int,
) -> str:
    """Pick bundle generation for primer (catch-up versioning)."""
    meta = profile_meta if isinstance(profile_meta, Mapping) else {}
    generations = meta.get("generations")
    if not isinstance(generations, list) or not generations:
        return current_bundle

    valid_generations = [item for item in generations if isinstance(item, Mapping)]
    if not valid_generations:
        return current_bundle

    stub_id = meta.get("stub_generation_id")
    stub: Mapping[str, Any] | None = None
    if isinstance(stub_id, str):
        stub = next((item for item in valid_generations if item.get("id") == stub_id), None)
    if stub is None:
        stub = valid_generations[0]

    matured = stub
    for generation in sorted(
        valid_generations,
        key=lambda item: int(item.get("anchor_user_turn") or 0),
    ):
        anchor = int(generation.get("anchor_user_turn") or 0)
        if anchor + SUMMARY_BUNDLE_CATCHUP_MESSAGES <= user_turn_count:
            matured = generation

    text = str(matured.get("text") or "").strip()
    if text:
        return text

    if current_fingerprint == str(stub.get("fingerprint") or ""):
        return current_bundle

    return str(stub.get("text") or current_bundle)


def take_prompt_window(pairs: list[tuple[str, str]], *, window_size: int = PROMPT_WINDOW) -> list[tuple[str, str]]:
    if window_size <= 0:
        return []
    return pairs[-window_size:]


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
    fingerprint = bundle_fingerprint(channel_profile, post=post)

    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)
    user_turn_count = count_user_turns(valid_pairs)

    trimmed_user_text = user_text.strip()
    if trimmed_user_text:
        if not valid_pairs or valid_pairs[-1][0] != "user":
            valid_pairs.append(("user", trimmed_user_text))
        elif valid_pairs[-1][1] != trimmed_user_text:
            valid_pairs.append(("user", trimmed_user_text))

    window_pairs = take_prompt_window(valid_pairs)

    rolling_summary = ""
    if isinstance(chat_meta, Mapping):
        rolling_summary = str(chat_meta.get("rolling_summary") or "").strip()

    profile_meta = (
        chat_meta.get("rolling_summary_profile")
        if isinstance(chat_meta, Mapping)
        else None
    )
    bundle_for_primer = resolve_stub_bundle_text(
        profile_meta=profile_meta if isinstance(profile_meta, Mapping) else None,
        current_bundle=current_bundle,
        current_fingerprint=fingerprint,
        user_turn_count=user_turn_count,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_primer_user_content(bundle_for_primer, rolling_summary)},
        {"role": "assistant", "content": PRIMER_ACK},
    ]

    for role, content in window_pairs:
        messages.append({"role": role, "content": content})

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
