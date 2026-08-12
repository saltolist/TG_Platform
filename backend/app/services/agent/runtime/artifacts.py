"""Typed runtime handles for user-visible and evidence artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Mapping


ArtifactKind = Literal["edit_post_proposal", "evidence"]


@dataclass(frozen=True)
class ArtifactHandle:
    handle: str
    kind: ArtifactKind
    canonical_ref: str
    content: str | None = None
    revision: int | None = None
    provenance: Literal["history_proposal", "runtime_evidence"] = "runtime_evidence"


def proposal_artifact_from_history(history: list[Mapping[str, Any]]) -> ArtifactHandle | None:
    """Resolve the latest structured edit proposal on the active dialog branch."""

    from app.services.ai.chat_history import flatten_visible_with_paths

    for item in reversed(flatten_visible_with_paths(history)):
        message = item["message"]
        if not isinstance(message, Mapping) or message.get("role") != "ai":
            continue
        proposal = message.get("proposal")
        if not isinstance(proposal, Mapping) or proposal.get("command") != "edit_post":
            continue
        for container_key in ("payload", "preview"):
            container = proposal.get(container_key)
            if not isinstance(container, Mapping):
                continue
            patch = container.get("patch")
            if not isinstance(patch, Mapping):
                continue
            html = patch.get("textHtml") or patch.get("text")
            if not isinstance(html, str) or not html.strip():
                continue
            content = html.strip()
            proposal_id = str(proposal.get("id") or "").strip()
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            canonical_ref = f"proposal:{proposal_id}" if proposal_id else f"proposal:sha256:{digest}"
            return ArtifactHandle(
                handle="artifact:pending-edit",
                kind="edit_post_proposal",
                canonical_ref=canonical_ref,
                content=content,
                provenance="history_proposal",
            )
        return None
    return None


def evidence_handles(evidence_ids: frozenset[str]) -> dict[str, str]:
    """Create deterministic run-local handles for canonical evidence records."""

    return {
        f"evidence:{index}": evidence_id
        for index, evidence_id in enumerate(sorted(evidence_ids), start=1)
    }


__all__ = ["ArtifactHandle", "evidence_handles", "proposal_artifact_from_history"]
