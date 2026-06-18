"""Summary bundle versioning and floating generations (ai-context-assembly.md)."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES


def empty_bundle_profile() -> dict[str, Any]:
    return {"stub_generation_id": None, "generations": []}


def _valid_generations(profile_meta: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(profile_meta, Mapping):
        return []
    raw = profile_meta.get("generations")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def prune_generations_for_turn(
    generations: list[Mapping[str, Any]],
    user_turn_count: int,
) -> list[dict[str, Any]]:
    """Drop bundle generations that belong to turns after the active branch fork point."""
    return [
        dict(item)
        for item in generations
        if int(item.get("anchor_user_turn") or 0) <= user_turn_count
    ]


def branch_fingerprint_from_profile(profile_meta: Mapping[str, Any] | None) -> str | None:
    """Last bundle fingerprint the branch timeline has actually reached."""
    generations = _valid_generations(profile_meta)
    if not generations:
        return None
    fingerprint = str(generations[-1].get("fingerprint") or "").strip()
    return fingerprint or None


def generation_seen_on_branch(
    profile_meta: Mapping[str, Any] | None,
    fingerprint: str,
    *,
    up_to_turn: int,
) -> bool:
    """Whether a bundle generation with ``fingerprint`` was already introduced on this branch."""
    for generation in _valid_generations(profile_meta):
        if str(generation.get("fingerprint") or "") != fingerprint:
            continue
        if int(generation.get("anchor_user_turn") or 0) <= up_to_turn:
            return True
    return False


def should_introduce_pruned_bundle_now(
    parent_generations: list[Mapping[str, Any]],
    current_fingerprint: str,
    user_turn_count: int,
) -> bool:
    """True when a forked branch missed a parent channel change within catchup range."""
    for generation in parent_generations:
        if str(generation.get("fingerprint") or "") != current_fingerprint:
            continue
        anchor = int(generation.get("anchor_user_turn") or 0)
        if anchor > user_turn_count and (
            user_turn_count + SUMMARY_BUNDLE_CATCHUP_MESSAGES >= anchor
        ):
            return True
    return False


def ensure_unseen_channel_bundle_floating(
    floating: dict[int, str],
    *,
    profile_meta: Mapping[str, Any] | None,
    primer_stub_id: str,
    current_bundle: str,
    current_fingerprint: str,
    user_turn_count: int,
    window_user_turns: set[int],
    parent_generations: list[Mapping[str, Any]] | None = None,
) -> dict[int, str]:
    """Attach current channel bundle to the send turn if this branch has not seen it yet."""
    if user_turn_count not in window_user_turns or user_turn_count in floating:
        return floating

    gen_map = {
        str(item.get("id") or ""): item
        for item in _valid_generations(profile_meta)
        if item.get("id")
    }
    primer = gen_map.get(primer_stub_id)
    primer_fp = str(primer.get("fingerprint") or "") if primer else ""
    if not current_fingerprint or current_fingerprint == primer_fp:
        return floating
    if generation_seen_on_branch(profile_meta, current_fingerprint, up_to_turn=user_turn_count):
        return floating

    parent = list(parent_generations or [])
    if parent and not should_introduce_pruned_bundle_now(
        parent,
        current_fingerprint,
        user_turn_count,
    ):
        return floating

    text = current_bundle.strip()
    if not text:
        return floating

    result = dict(floating)
    result[user_turn_count] = text
    return result


def recompute_bundle_profile_stub(
    profile_meta: Mapping[str, Any] | None,
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> dict[str, Any]:
    """Prune future generations and resolve the primer stub for the current turn."""
    generations = prune_generations_for_turn(_valid_generations(profile_meta), user_turn_count)
    head = resolve_matured_generation(
        generations,
        stub_generation_id=None,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    stub_id = str(head.get("id") or "") if head is not None else None

    return {
        "stub_generation_id": stub_id,
        "generations": generations,
    }


def prepare_bundle_profile_for_assemble(
    profile_meta: Mapping[str, Any] | None,
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
    current_bundle: str | None = None,
    current_fingerprint: str | None = None,
    global_fingerprint_at_last_refresh: str | None = None,
    parent_generations: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bundle profile for prompt assembly — may preview a pending channel change on this thread."""
    profile = recompute_bundle_profile_stub(
        profile_meta,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    if not current_fingerprint or not current_bundle:
        return profile

    generations = list(profile.get("generations") or [])
    latest_fingerprint = str(generations[-1].get("fingerprint") or "") if generations else ""
    if latest_fingerprint == current_fingerprint:
        return profile

    show_pending = False
    if global_fingerprint_at_last_refresh is None:
        show_pending = True
    elif current_fingerprint != global_fingerprint_at_last_refresh:
        show_pending = True

    if not show_pending:
        return profile

    if parent_generations and not should_introduce_pruned_bundle_now(
        list(parent_generations),
        current_fingerprint,
        user_turn_count,
    ):
        return profile

    generations.append(
        {
            "id": uuid.uuid4().hex[:12],
            "fingerprint": current_fingerprint,
            "text": current_bundle,
            "anchor_user_turn": user_turn_count,
        }
    )
    return recompute_bundle_profile_stub(
        {**profile, "generations": generations},
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )


def advance_bundle_profile(
    profile_meta: Mapping[str, Any] | None,
    *,
    current_bundle: str,
    current_fingerprint: str,
    global_fingerprint_at_last_refresh: str | None,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> tuple[dict[str, Any], str]:
    """Update bundle profile after a reply; record channel changes only on this thread."""
    profile = recompute_bundle_profile_stub(
        profile_meta,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    generations = list(profile.get("generations") or [])
    last_seen = global_fingerprint_at_last_refresh

    if not generations:
        generations.append(
            {
                "id": uuid.uuid4().hex[:12],
                "fingerprint": current_fingerprint,
                "text": current_bundle,
                "anchor_user_turn": user_turn_count,
            }
        )
        last_seen = current_fingerprint
    elif last_seen is None:
        latest_fingerprint = str(generations[-1].get("fingerprint") or "")
        if latest_fingerprint != current_fingerprint:
            generations.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "fingerprint": current_fingerprint,
                    "text": current_bundle,
                    "anchor_user_turn": user_turn_count,
                }
            )
    elif current_fingerprint != last_seen:
        latest_fingerprint = str(generations[-1].get("fingerprint") or "")
        if latest_fingerprint != current_fingerprint:
            generations.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "fingerprint": current_fingerprint,
                    "text": current_bundle,
                    "anchor_user_turn": user_turn_count,
                }
            )
        last_seen = current_fingerprint

    profile = recompute_bundle_profile_stub(
        {**profile, "generations": generations},
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    if last_seen is None and generations:
        last_seen = current_fingerprint
    assert last_seen is not None or not generations
    return profile, last_seen or current_fingerprint


def generation_is_matured(
    generation: Mapping[str, Any],
    *,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> bool:
    """A generation is mature after N user-turns, or once its anchor left the prompt window."""
    anchor = int(generation.get("anchor_user_turn") or 0)
    if anchor + SUMMARY_BUNDLE_CATCHUP_MESSAGES <= user_turn_count:
        return True
    if (
        window_user_turns is not None
        and anchor > 0
        and anchor not in window_user_turns
        and user_turn_count > anchor
    ):
        return True
    return False


def resolve_matured_generation(
    generations: list[Mapping[str, Any]],
    *,
    stub_generation_id: str | None,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> Mapping[str, Any] | None:
    """Primer head = latest matured generation, or the first (baseline) stub if none matured yet."""
    del stub_generation_id  # head is derived from maturity, not persisted stub id
    if not generations:
        return None

    sorted_generations = sorted(
        generations,
        key=lambda item: int(item.get("anchor_user_turn") or 0),
    )
    matured = [
        generation
        for generation in sorted_generations
        if generation_is_matured(
            generation,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        )
    ]
    if matured:
        return matured[-1]
    return sorted_generations[0]


def ensure_bundle_profile(
    profile_meta: Mapping[str, Any] | None,
    *,
    current_bundle: str,
    current_fingerprint: str,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
    global_fingerprint_at_last_refresh: str | None = None,
) -> dict[str, Any]:
    """Track bundle generations; mature stub after N user-turns."""
    profile, _ = advance_bundle_profile(
        profile_meta,
        current_bundle=current_bundle,
        current_fingerprint=current_fingerprint,
        global_fingerprint_at_last_refresh=global_fingerprint_at_last_refresh,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    return profile


def bundle_text_for_primer(
    profile_meta: Mapping[str, Any],
    *,
    current_bundle: str,
    user_turn_count: int,
    window_user_turns: set[int] | None = None,
) -> str:
    generations = _valid_generations(profile_meta)
    if not generations:
        return current_bundle

    stub_id = str(profile_meta.get("stub_generation_id") or "")
    matured = resolve_matured_generation(
        generations,
        stub_generation_id=stub_id or None,
        user_turn_count=user_turn_count,
        window_user_turns=window_user_turns,
    )
    if matured is None:
        return current_bundle

    text = str(matured.get("text") or "").strip()
    return text or current_bundle


def get_floating_bundle_injections(
    profile_meta: Mapping[str, Any],
    *,
    primer_stub_id: str,
    user_turn_count: int,
    window_user_turns: set[int],
) -> dict[int, str]:
    """Generations that float in the dialog window before they mature into primer."""
    injections: dict[int, str] = {}
    for generation in _valid_generations(profile_meta):
        generation_id = str(generation.get("id") or "")
        if not generation_id or generation_id == primer_stub_id:
            continue

        anchor = int(generation.get("anchor_user_turn") or 0)
        if anchor not in window_user_turns:
            continue
        if generation_is_matured(
            generation,
            user_turn_count=user_turn_count,
            window_user_turns=window_user_turns,
        ):
            continue

        text = str(generation.get("text") or "").strip()
        if text:
            injections[anchor] = text

    return injections
