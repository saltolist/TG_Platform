"""Per-user-message bundle context (head + floating generation ids)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.bundle_profile import (
    _valid_generations,
    generation_is_matured,
    recompute_bundle_profile_stub,
)
from app.services.ai.chat_history import (
    clamp_active_branch_index,
    flatten_visible_with_paths,
    map_message_at_path,
)


def read_message_bundle_context(message: Mapping[str, Any]) -> dict[str, str] | None:
    raw = message.get("bundleContext")
    if raw is None:
        raw = message.get("bundle_context")
    if not isinstance(raw, Mapping):
        return None
    head = raw.get("headGenerationId") or raw.get("head_generation_id")
    if not isinstance(head, str) or not head.strip():
        return None
    ctx: dict[str, str] = {"headGenerationId": head.strip()}
    floating = raw.get("floatingGenerationId") or raw.get("floating_generation_id")
    if isinstance(floating, str) and floating.strip():
        ctx["floatingGenerationId"] = floating.strip()
    return ctx


def generations_by_id(profile_meta: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or ""): dict(item)
        for item in _valid_generations(profile_meta)
        if item.get("id")
    }


def user_messages_on_path(
    history: list[Mapping[str, Any]],
) -> list[tuple[int, Mapping[str, Any], list[int]]]:
    entries: list[tuple[int, Mapping[str, Any], list[int]]] = []
    turn = 0
    for item in flatten_visible_with_paths(history):
        message = item["message"]
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        turn += 1
        path = item.get("path")
        if isinstance(path, list):
            entries.append((turn, message, [int(part) for part in path]))
    return entries


def last_user_message_path(history: list[Mapping[str, Any]] | None) -> list[int] | None:
    entries = user_messages_on_path(list(history or []))
    if not entries:
        return None
    return entries[-1][2]


def compute_bundle_context_stamp(
    profile_meta: Mapping[str, Any],
    *,
    user_turn_count: int,
    window_user_turns: set[int],
) -> dict[str, str]:
    """Snapshot bundle ids for the user turn that just received a reply."""
    view = recompute_bundle_profile_stub(
        profile_meta,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    head_id = str(view.get("stub_generation_id") or "")
    floating_id: str | None = None
    for generation in view.get("generations") or []:
        generation_id = str(generation.get("id") or "")
        if not generation_id or generation_id == head_id:
            continue
        anchor = int(generation.get("anchor_user_turn") or 0)
        if anchor != user_turn_count:
            continue
        if generation_is_matured(
            generation,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        ):
            continue
        floating_id = generation_id
        break

    stamp: dict[str, str] = {"headGenerationId": head_id}
    if floating_id:
        stamp["floatingGenerationId"] = floating_id
    return stamp


def resolve_fork_primer_override(
    entries: list[tuple[int, Mapping[str, Any], list[int]]],
    profile_meta: Mapping[str, Any] | None,
    *,
    profile_head_id: str,
    user_turn_count: int,
) -> tuple[str, str] | None:
    """When profile head belongs to a longer branch, use stamp from the active fork point."""
    gen_map = generations_by_id(profile_meta)
    profile_head = gen_map.get(profile_head_id)
    if not profile_head:
        return None

    profile_head_anchor = int(profile_head.get("anchor_user_turn") or 0)

    for turn, message, _path in reversed(entries):
        if turn >= user_turn_count:
            continue
        branches = message.get("userBranches")
        if not isinstance(branches, list) or len(branches) < 2:
            continue
        if clamp_active_branch_index(message) == 0:
            continue

        ctx = read_message_bundle_context(message)
        if ctx is None:
            continue

        stamp_head_id = ctx.get("headGenerationId") or ""
        if not stamp_head_id or stamp_head_id == profile_head_id or stamp_head_id not in gen_map:
            continue

        if profile_head_anchor <= turn:
            continue

        stamp_head = gen_map[stamp_head_id]
        primer = str(stamp_head.get("text") or "").strip()
        if primer:
            return primer, stamp_head_id

    return None


def resolve_bundle_from_messages(
    history: list[Mapping[str, Any]] | None,
    profile_meta: Mapping[str, Any] | None,
    *,
    user_turn_count: int,
    window_user_turns: set[int],
    fallback_primer: str,
    fallback_stub_id: str,
    fallback_floating: dict[int, str],
) -> tuple[str, str, dict[int, str]] | None:
    """Apply per-message floating bundles; fork override for primer when profile is too new."""
    entries = user_messages_on_path(list(history or []))
    if not entries:
        return None

    gen_map = generations_by_id(profile_meta)
    if not gen_map:
        return None

    stamped = [entry for entry in entries if read_message_bundle_context(entry[1])]
    if not stamped:
        return None

    floating = dict(fallback_floating)

    for turn, message, _path in entries:
        ctx = read_message_bundle_context(message)
        if ctx is None:
            continue
        floating_id = ctx.get("floatingGenerationId")
        if not floating_id or turn not in window_user_turns or floating_id not in gen_map:
            continue
        if floating_id == fallback_stub_id:
            continue
        generation = gen_map[floating_id]
        if generation_is_matured(
            generation,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        ):
            continue
        text = str(generation.get("text") or "").strip()
        if text:
            floating[turn] = text

    primer = fallback_primer
    head_id = fallback_stub_id

    fork_override = resolve_fork_primer_override(
        entries,
        profile_meta,
        profile_head_id=head_id,
        user_turn_count=user_turn_count,
    )
    if fork_override is not None:
        primer, head_id = fork_override

    if user_turn_count not in floating:
        for generation_id, generation in gen_map.items():
            if generation_id == head_id:
                continue
            anchor = int(generation.get("anchor_user_turn") or 0)
            if anchor != user_turn_count or anchor not in window_user_turns:
                continue
            if generation_is_matured(
                generation,
                user_turn_count=user_turn_count,
                window_user_turns=window_user_turns,
            ):
                continue
            text = str(generation.get("text") or "").strip()
            if text:
                floating[user_turn_count] = text
                break

    return primer, head_id, floating


def apply_bundle_context_stamp_to_history(
    history: list[Mapping[str, Any]] | None,
    stamp: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    """Persist bundleContext on the user message at ``stamp.path``."""
    if not history or not isinstance(stamp, Mapping):
        return None
    raw_path = stamp.get("path")
    head_id = stamp.get("headGenerationId") or stamp.get("head_generation_id")
    if not isinstance(raw_path, list) or not isinstance(head_id, str) or not head_id.strip():
        return None

    path = [int(part) for part in raw_path]
    bundle_context: dict[str, str] = {"headGenerationId": head_id.strip()}
    floating_id = stamp.get("floatingGenerationId") or stamp.get("floating_generation_id")
    if isinstance(floating_id, str) and floating_id.strip():
        bundle_context["floatingGenerationId"] = floating_id.strip()

    def attach(message: Mapping[str, Any]) -> dict[str, Any]:
        updated = dict(message)
        if updated.get("role") == "user":
            updated["bundleContext"] = bundle_context
        return updated

    return map_message_at_path(list(history), path, attach)


def resolve_bundle_from_profile_snapshot(
    profile_meta: Mapping[str, Any] | None,
    *,
    user_turn_count: int,
    window_user_turns: set[int],
    fallback_primer: str,
    fallback_stub_id: str,
    fallback_floating: dict[int, str],
) -> tuple[str, str, dict[int, str]] | None:
    """Derive primer/floating from bundle profile when messages lack bundleContext."""
    gen_map = generations_by_id(profile_meta)
    if not gen_map:
        return None

    stamp = compute_bundle_context_stamp(
        profile_meta or {},
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    head_id = stamp.get("headGenerationId") or ""
    if not head_id or head_id not in gen_map:
        return None

    primer = str(gen_map[head_id].get("text") or "").strip() or fallback_primer
    floating = dict(fallback_floating)
    floating_id = stamp.get("floatingGenerationId")
    if (
        isinstance(floating_id, str)
        and floating_id in gen_map
        and user_turn_count in window_user_turns
    ):
        text = str(gen_map[floating_id].get("text") or "").strip()
        if text:
            floating[user_turn_count] = text

    return primer, head_id, floating
