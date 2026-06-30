"""Web search reasoner: builds an optimal standalone search query for path C.

Uses conversation history + current user text to formulate a self-contained
query, resolving anaphora/references. Falls back to raw user text on error.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.services.ai.chat_history import filter_alternating_roles, linearize_for_llm
from app.services.ai.providers import ProviderSpec
from app.core.config import Settings, get_settings
from app.db.models import User
from app.services.ai.keys import resolve_model_api_key
from app.services.ai.providers import get_provider_spec

_log = logging.getLogger(__name__)

WEB_REASONER_SYSTEM = (
    "Ты формулируешь поисковый запрос для веб-поиска на основе последнего сообщения пользователя "
    "и контекста диалога. "
    "Разреши местоимения и отсылки («это», «он», «второй пункт», «подробнее») по контексту диалога. "
    "Верни только текст запроса — без кавычек, скобок и пояснений. "
    "Если запрос уже самодостаточен — верни его без изменений."
)

_META_MARKERS = (
    "поисковый запрос",
    "сформулиру",
    "верну запрос",
    "контекст диалога",
)

_QUERY_MAX_CHARS = 1500


def _is_invalid_web_query_response(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered or len(lowered) < 3:
        return True
    marker_hits = sum(1 for m in _META_MARKERS if m in lowered)
    if marker_hits >= 2:
        return True
    return marker_hits >= 1 and len(lowered) < 50


def build_web_search_query_from_history(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    max_turns: int = 3,
    max_chars: int = _QUERY_MAX_CHARS,
) -> str:
    """Concatenate recent turns into a history-expanded query.

    The current user message is always included first; then we add recent
    user/assistant turns (up to max_turns) to give context for anaphora.
    """
    pairs = filter_alternating_roles(linearize_for_llm(history or []))
    current = user_text.strip()

    # Exclude the last pair if it duplicates the current user message
    if pairs and pairs[-1][0] == "user" and pairs[-1][1].strip() == current:
        pairs = pairs[:-1]

    recent = pairs[-max_turns * 2 :] if pairs else []

    parts = [current]
    for role, text in recent:
        prefix = "Пользователь" if role == "user" else "Ассистент"
        parts.append(f"{prefix}: {text.strip()}")

    combined = "\n".join(parts)
    return combined[:max_chars] if len(combined) > max_chars else combined


def build_web_rewrite_messages(
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    max_turns: int = 3,
) -> list[dict[str, str]]:
    """Build LLM messages for the web reasoner (query rewrite)."""
    pairs = filter_alternating_roles(linearize_for_llm(history or []))
    current = user_text.strip()

    if pairs and pairs[-1][0] == "user" and pairs[-1][1].strip() == current:
        pairs = pairs[:-1]

    recent = pairs[-max_turns * 2 :] if pairs else []
    dialog_lines = [
        f"{'Пользователь' if r == 'user' else 'Ассистент'}: {t.strip()}"
        for r, t in recent
    ]
    context_block = "\n".join(dialog_lines)

    user_content = (
        f"Контекст диалога:\n{context_block}\n\nПоследнее сообщение: {current}"
        if context_block
        else current
    )
    return [
        {"role": "system", "content": WEB_REASONER_SYSTEM},
        {"role": "user", "content": user_content},
    ]


async def rewrite_web_query_llm(
    *,
    user_text: str,
    history: list[Mapping[str, Any]] | None,
    spec: ProviderSpec,
    model: str,
    api_key: str,
) -> str:
    """Call LLM to produce an optimal web search query. Falls back to user_text."""
    from app.services.ai.llm import stream_chat_completion_tokens

    messages = build_web_rewrite_messages(user_text, history)
    try:
        tokens: list[str] = []
        async for chunk in stream_chat_completion_tokens(
            spec=spec, model=model, api_key=api_key, messages=messages
        ):
            tokens.append(chunk)
        result = "".join(tokens).strip()
        if _is_invalid_web_query_response(result):
            _log.debug("Web reasoner returned meta-reply, falling back to user_text")
            return user_text.strip()
        return result
    except Exception as exc:
        _log.warning("Web reasoner LLM call failed, using raw user text: %s", exc)
        return user_text.strip()


def pick_active_web_reasoner_model(ai_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    models = ai_profile.get("webReasonerModels") or []
    for m in models:
        if m.get("active") and m.get("provider") and m.get("model"):
            return dict(m)
    return None


def resolve_web_reasoner_llm(
    user: User,
    ai_profile: Mapping[str, Any],
    settings: Settings | None = None,
) -> tuple[ProviderSpec, str, str] | None:
    """Resolve the web reasoner LLM.

    Falls back to the orchestrator model if no dedicated web reasoner is configured.
    """
    from app.services.ai.orchestrator import resolve_orchestrator_llm

    model = pick_active_web_reasoner_model(ai_profile)
    if model is not None:
        resolution = resolve_model_api_key(model, user, settings or get_settings())
        if resolution.has_key and resolution.api_key:
            provider_name = str(model.get("provider") or "").strip()
            model_id = str(model.get("model") or "").strip()
            spec = get_provider_spec(provider_name)
            if spec is not None and model_id:
                return spec, model_id, resolution.api_key

    return resolve_orchestrator_llm(user, ai_profile, settings)
