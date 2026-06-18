"""Summary bundle versioning and floating generations (ai-context-assembly.md)."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from app.services.ai.context_config import SUMMARY_BUNDLE_CATCHUP_MESSAGES

PRIMER_ACK_FLOATING = "Понял, учту."


def empty_bundle_profile() -> dict[str, Any]:
    return {"stub_generation_id": None, "generations": []}


def _valid_generations(profile_meta: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(profile_meta, Mapping):
        return []
    raw = profile_meta.get("generations")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def resolve_matured_generation(
    generations: list[Mapping[str, Any]],
    *,
    stub_generation_id: str | None,
    user_turn_count: int,
) -> Mapping[str, Any] | None:
    if not generations:
        return None

    stub: Mapping[str, Any] | None = None
    if isinstance(stub_generation_id, str):
        stub = next((item for item in generations if item.get("id") == stub_generation_id), None)
    if stub is None:
        stub = generations[0]

    matured = stub
    for generation in sorted(
        generations,
        key=lambda item: int(item.get("anchor_user_turn") or 0),
    ):
        anchor = int(generation.get("anchor_user_turn") or 0)
        if anchor + SUMMARY_BUNDLE_CATCHUP_MESSAGES <= user_turn_count:
            matured = generation

    return matured


def ensure_bundle_profile(
    profile_meta: Mapping[str, Any] | None,
    *,
    current_bundle: str,
    current_fingerprint: str,
    user_turn_count: int,
) -> dict[str, Any]:
    """Track bundle generations; mature stub after N user-turns."""
    generations = _valid_generations(profile_meta)
    stub_id = (
        str(profile_meta.get("stub_generation_id"))
        if isinstance(profile_meta, Mapping) and profile_meta.get("stub_generation_id")
        else None
    )

    latest_fingerprint = str(generations[-1].get("fingerprint") or "") if generations else ""
    if not generations or latest_fingerprint != current_fingerprint:
        generations.append(
            {
                "id": uuid.uuid4().hex[:12],
                "fingerprint": current_fingerprint,
                "text": current_bundle,
                "anchor_user_turn": user_turn_count,
            }
        )

    if not stub_id:
        stub_id = str(generations[0].get("id") or "")

    matured = resolve_matured_generation(
        generations,
        stub_generation_id=stub_id,
        user_turn_count=user_turn_count,
    )
    if matured is not None:
        stub_id = str(matured.get("id") or stub_id)

    return {
        "stub_generation_id": stub_id,
        "generations": generations,
    }


def bundle_text_for_primer(
    profile_meta: Mapping[str, Any],
    *,
    current_bundle: str,
    user_turn_count: int,
) -> str:
    generations = _valid_generations(profile_meta)
    if not generations:
        return current_bundle

    stub_id = str(profile_meta.get("stub_generation_id") or "")
    matured = resolve_matured_generation(
        generations,
        stub_generation_id=stub_id or None,
        user_turn_count=user_turn_count,
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
        if anchor + SUMMARY_BUNDLE_CATCHUP_MESSAGES <= user_turn_count:
            continue

        text = str(generation.get("text") or "").strip()
        if text:
            injections[anchor] = text

    return injections
