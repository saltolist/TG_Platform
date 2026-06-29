"""Types for context stamp mechanics (v2 labels + JSON stamps)."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class SummaryVersions(TypedDict):
    channel: int
    post: int


class StampAddress(TypedDict):
    msg: int
    msgVersion: int
    branch: int


class StampSummary(TypedDict):
    head: SummaryVersions
    attach: SummaryVersions


class CatalogSnapshot(TypedDict):
    channel: int
    post: int


class ContextStamp(TypedDict):
    scope: Literal["global", "post"]
    address: StampAddress
    summary: StampSummary
    catalog: CatalogSnapshot


class PendingItem(TypedDict):
    version: int
    sinceMsg: int


class LayerPending(TypedDict):
    channel: list[PendingItem]
    post: list[PendingItem]


class BranchStampState(TypedDict):
    head: SummaryVersions
    pending: LayerPending
    rolling_summary: str
    rolling_summary_idx: int


class StampContextRoot(TypedDict, total=False):
    branches: dict[str, BranchStampState]
    next_branch_id: int
    branch_registry: dict[str, int]


STAMP_CONTEXT_KEY = "stamp_context"
STAMP_MECHANICS_FLAG = "context_stamp_mechanics"
ACTIVE_BRANCH_KEY = "active_branch"


def empty_summary_versions(*, post_default: int = 0) -> SummaryVersions:
    return {"channel": 0, "post": post_default}


def empty_pending() -> LayerPending:
    return {"channel": [], "post": []}


def empty_branch_state(*, post_head: int = 0) -> BranchStampState:
    return {
        "head": empty_summary_versions(post_default=post_head),
        "pending": empty_pending(),
        "rolling_summary": "",
        "rolling_summary_idx": 0,
    }


def empty_stamp_context(*, post_head: int = 0) -> StampContextRoot:
    return {
        "branches": {"1": empty_branch_state(post_head=post_head)},
        "next_branch_id": 2,
        "branch_registry": {},
    }


def normalize_summary_versions(raw: Any, *, scope: str) -> SummaryVersions:
    data = raw if isinstance(raw, dict) else {}
    channel = max(0, int(data.get("channel") or 0))
    post = max(0, int(data.get("post") or 0))
    if scope == "global":
        post = 0
    return {"channel": channel, "post": post}


def branch_state_key(branch_id: int) -> str:
    return str(max(1, int(branch_id)))
