"""Shared typed contracts for Workspace Agent tools.

The graph still accepts the legacy tool names during rollout, but all tool
outcomes pass through this module.  Keeping error codes and response modes in a
small, dependency-free contract makes a failed tool actionable to both the
planner and operational tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

ResponseMode = Literal["compact", "detailed"]


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class ToolBatchRequest:
    """Canonical task-oriented batch request used by consolidated tools."""

    tool: str
    items: tuple[dict[str, Any], ...] = ()
    mode: ResponseMode = "compact"
    idempotency_key: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ToolBatchRequest":
        raw_items = (
            payload.get("items")
            or payload.get("actions")
            or payload.get("objects")
            or payload.get("ids")
            or payload.get("refs")
            or payload.get("intents")
            or payload.get("attachments")
            or ()
        )
        items = tuple(
            dict(item) if isinstance(item, Mapping) else {"ref": str(item)}
            for item in raw_items
            if isinstance(item, (Mapping, str))
        )
        mode = str(payload.get("response_mode") or payload.get("mode") or "compact")
        if mode not in {"compact", "detailed"}:
            mode = "compact"
        return cls(
            tool=str(payload.get("tool") or ""),
            items=items,
            mode=mode,  # type: ignore[arg-type]
            idempotency_key=str(payload.get("idempotency_key") or "") or None,
        )


_ERRORS: dict[str, ToolError] = {
    "already_opened": ToolError("already_opened", "Object is already open", next_action="use_cached_evidence"),
    "not_found": ToolError("not_found", "Object was not found", next_action="resolve_objects"),
    "forbidden": ToolError("forbidden", "Object is outside the authorized scope", next_action="finish_partial"),
    "stale_revision": ToolError("stale_revision", "Object revision is stale", next_action="search_objects"),
    "empty_scope": ToolError("empty_scope", "No objects matched the requested scope", next_action="search_objects"),
    "empty_query": ToolError("empty_query", "Search query is empty", next_action="search_objects"),
    "post_not_open": ToolError("precondition_failed", "Open the post before reading its children", next_action="OpenObjects"),
    "note_not_found": ToolError("not_found", "Note was not found", next_action="resolve_objects"),
    "unknown_tool": ToolError("unsupported_tool", "Tool is not available in this execution mode"),
    "proposal_required": ToolError("proposal_required", "Mutation requires approval", next_action="route_mutation"),
    "missing_post_id": ToolError("invalid_arguments", "post_id is required", next_action="ResolveObjects"),
    "missing_note_id": ToolError("invalid_arguments", "note_id is required", next_action="ResolveObjects"),
    "missing_ref": ToolError("invalid_arguments", "attachment ref is required", next_action="ResolveObjects"),
    "file_not_found": ToolError("not_found", "Attachment was not found", next_action="ResolveObjects"),
    "invalid_ref": ToolError("invalid_arguments", "Attachment ref is invalid", next_action="ResolveObjects"),
    "invalid_mode": ToolError("invalid_arguments", "Response mode is invalid", next_action="finish_partial"),
    "vision_budget_exhausted": ToolError("budget_exhausted", "Vision budget is exhausted", next_action="finish_partial"),
    "fetch_failed": ToolError("provider_unavailable", "Attachment fetch failed", retryable=True, next_action="retry_once"),
    "no_text": ToolError("empty_result", "Attachment contains no extractable text", next_action="finish_partial"),
}


def typed_tool_error(code: str | None, message: str = "") -> ToolError | None:
    """Map legacy string errors to a stable planner-facing error contract."""

    if not code:
        return None
    raw_code = str(code)
    base = _ERRORS.get(raw_code)
    if base is None and ":" in raw_code:
        base = _ERRORS.get(raw_code.split(":", 1)[0])
    if base is None:
        stable_code = raw_code
        if len(stable_code) > 64 or any(char.isspace() for char in stable_code):
            stable_code = "tool_failed"
        return ToolError(
            code=stable_code,
            message=message or str(code),
            retryable=False,
            next_action="finish_partial",
        )
    return ToolError(
        code=base.code,
        message=message or base.message,
        retryable=base.retryable,
        next_action=base.next_action,
    )


CONSOLIDATED_TOOLS = frozenset(
    {
        "ResolveObjects",
        "SearchObjects",
        "OpenObjects",
        "SearchObjectChunks",
        "HydrateAttachments",
        "ReadAnalytics",
        "ProposeAction",
    }
)


__all__ = [
    "CONSOLIDATED_TOOLS",
    "ResponseMode",
    "ToolBatchRequest",
    "ToolError",
    "typed_tool_error",
]
