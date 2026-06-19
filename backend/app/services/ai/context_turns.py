"""User-turn annotation for prompt windows."""

from __future__ import annotations

from app.services.ai.context_config import PROMPT_WINDOW


def annotate_user_turns(
    pairs: list[tuple[str, str]],
) -> list[tuple[int | None, str, str]]:
    user_turn = 0
    annotated: list[tuple[int | None, str, str]] = []
    for role, content in pairs:
        if role == "user":
            user_turn += 1
            annotated.append((user_turn, role, content))
        else:
            annotated.append((None, role, content))
    return annotated


def compute_window_user_turns(
    pairs: list[tuple[str, str]],
    *,
    window_size: int = PROMPT_WINDOW,
) -> set[int]:
    if window_size <= 0 or not pairs:
        return set()
    window_len = min(window_size, len(pairs))
    window_annotated = annotate_user_turns(pairs)[-window_len:]
    return {
        user_turn
        for user_turn, role, _ in window_annotated
        if role == "user" and user_turn is not None
    }
