"""Per-active-thread rolling summary and bundle profile state."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from app.services.ai.bundle_profile import (
    _valid_generations,
    branch_fingerprint_from_profile,
    empty_bundle_profile,
    prepare_bundle_profile_for_assemble,
    recompute_bundle_profile_stub,
)
from app.services.ai.chat_history import active_thread_key, count_user_turns, filter_alternating_roles, linearize_for_llm
from app.services.ai.rolling_summary import reconcile_rolling_summary_fields

THREAD_CONTEXT_KEY = "thread_context"
ACTIVE_THREAD_KEY = "active_thread_key"
GLOBAL_FINGERPRINT_KEY = "global_fingerprint_at_last_refresh"
PARENT_GENERATIONS_KEY = "parent_generations_snapshot"


def empty_thread_state(*, global_fingerprint: str | None = None) -> dict[str, Any]:
    return {
        "rolling_summary": "",
        "rolling_summary_idx": 0,
        "rolling_summary_profile": empty_bundle_profile(),
        GLOBAL_FINGERPRINT_KEY: global_fingerprint,
    }


def thread_state_from_flat(meta: Mapping[str, Any]) -> dict[str, Any]:
    profile = meta.get("rolling_summary_profile")
    try:
        summary_idx = int(meta.get("rolling_summary_idx") or 0)
    except (TypeError, ValueError):
        summary_idx = 0
    return {
        "rolling_summary": str(meta.get("rolling_summary") or "").strip(),
        "rolling_summary_idx": max(0, summary_idx),
        "rolling_summary_profile": (
            copy.deepcopy(dict(profile))
            if isinstance(profile, Mapping)
            else empty_bundle_profile()
        ),
        GLOBAL_FINGERPRINT_KEY: meta.get(GLOBAL_FINGERPRINT_KEY),
    }


def load_thread_context(meta: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(meta, Mapping):
        return {}
    raw = meta.get(THREAD_CONTEXT_KEY)
    if not isinstance(raw, Mapping):
        return {}
    threads: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, Mapping):
            threads[key] = dict(value)
    return threads


def find_ancestor_thread_key(thread_key: str, threads: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Best ancestor thread for fork seeding (e.g. 8@1 → 8@0)."""
    if thread_key in threads:
        return thread_key

    parts = thread_key.split(",")
    if parts and "@" in parts[-1]:
        fork_path, _branch = parts[-1].rsplit("@", 1)
        parts[-1] = f"{fork_path}@0"
        sibling_zero = ",".join(parts)
        if sibling_zero in threads:
            return sibling_zero

    best: str | None = None
    for key in threads:
        if thread_key == key or thread_key.startswith(f"{key},"):
            if best is None or len(key) > len(best):
                best = key
    return best


def seed_thread_state_from_parent(
    parent_state: Mapping[str, Any],
    *,
    user_turn_count: int,
    global_fingerprint: str,
) -> dict[str, Any]:
    """Fork: inherit bundle timeline up to the fork turn, not future global channel state."""
    profile = recompute_bundle_profile_stub(
        parent_state.get("rolling_summary_profile"),
        user_turn_count=user_turn_count,
    )
    branch_fingerprint = branch_fingerprint_from_profile(profile)
    parent_generations = _valid_generations(parent_state.get("rolling_summary_profile"))
    return {
        "rolling_summary": "",
        "rolling_summary_idx": 0,
        "rolling_summary_profile": profile,
        GLOBAL_FINGERPRINT_KEY: branch_fingerprint or global_fingerprint,
        PARENT_GENERATIONS_KEY: [dict(item) for item in parent_generations],
    }


def resolve_thread_state(
    chat_meta: Mapping[str, Any] | None,
    history: list[Mapping[str, Any]] | None,
    *,
    global_fingerprint: str | None = None,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    """Return mutable state for the active thread, its key, and the full thread map."""
    base_meta = dict(chat_meta) if isinstance(chat_meta, Mapping) else {}
    thread_key = active_thread_key(list(history or []))
    threads = load_thread_context(base_meta)
    raw_pairs = linearize_for_llm(list(history or []))
    valid_pairs = filter_alternating_roles(raw_pairs)
    user_turn_count = count_user_turns(valid_pairs)

    if thread_key not in threads:
        has_legacy_flat = bool(
            base_meta.get("rolling_summary") or base_meta.get("rolling_summary_profile")
        )
        flat_state = thread_state_from_flat(base_meta) if has_legacy_flat else None

        prev_key = base_meta.get(ACTIVE_THREAD_KEY)
        if not isinstance(prev_key, str):
            prev_key = None

        parent_state: Mapping[str, Any] | None = None
        if prev_key:
            parent_state = threads.get(prev_key)
        if parent_state is None:
            ancestor = find_ancestor_thread_key(thread_key, threads)
            if ancestor:
                parent_state = threads.get(ancestor)
        if parent_state is None and flat_state is not None:
            if not threads and (prev_key is None or prev_key == thread_key):
                threads[thread_key] = flat_state
            else:
                fingerprint = global_fingerprint or flat_state.get(GLOBAL_FINGERPRINT_KEY) or ""
                threads[thread_key] = seed_thread_state_from_parent(
                    flat_state,
                    user_turn_count=user_turn_count,
                    global_fingerprint=str(fingerprint),
                )
        elif parent_state is not None:
            fingerprint = global_fingerprint or parent_state.get(GLOBAL_FINGERPRINT_KEY) or ""
            threads[thread_key] = seed_thread_state_from_parent(
                parent_state,
                user_turn_count=user_turn_count,
                global_fingerprint=str(fingerprint),
            )
        else:
            threads[thread_key] = empty_thread_state(global_fingerprint=global_fingerprint)

    state = dict(threads[thread_key])
    if state.get(GLOBAL_FINGERPRINT_KEY) is None:
        generations = (state.get("rolling_summary_profile") or {}).get("generations") or []
        if generations:
            state[GLOBAL_FINGERPRINT_KEY] = str(generations[-1].get("fingerprint") or "")
        elif global_fingerprint is not None:
            state[GLOBAL_FINGERPRINT_KEY] = global_fingerprint
        threads[thread_key] = state

    profile = prepare_bundle_profile_for_assemble(
        state.get("rolling_summary_profile"),
        user_turn_count=user_turn_count,
        global_fingerprint_at_last_refresh=state.get(GLOBAL_FINGERPRINT_KEY),
        parent_generations=state.get(PARENT_GENERATIONS_KEY),
    )
    state["rolling_summary_profile"] = profile
    state = reconcile_rolling_summary_fields(state, valid_pairs)
    threads[thread_key] = state
    return state, thread_key, threads


def flatten_thread_meta(
    thread_state: Mapping[str, Any],
    *,
    thread_key: str,
    threads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist per-thread store and mirror active thread into flat chat meta fields."""
    return {
        ACTIVE_THREAD_KEY: thread_key,
        THREAD_CONTEXT_KEY: {key: dict(value) for key, value in threads.items()},
        "rolling_summary": str(thread_state.get("rolling_summary") or "").strip(),
        "rolling_summary_idx": int(thread_state.get("rolling_summary_idx") or 0),
        "rolling_summary_profile": dict(
            thread_state.get("rolling_summary_profile") or empty_bundle_profile()
        ),
        GLOBAL_FINGERPRINT_KEY: thread_state.get(GLOBAL_FINGERPRINT_KEY),
    }
