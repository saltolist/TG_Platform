"""Format and apply context stamp labels (from contextStamp JSON)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.services.ai.chat_history import clamp_active_branch_index, map_message_at_path
from app.services.ai.context_stamp_types import (
    CatalogSnapshot,
    ContextStamp,
    StampAddress,
    StampSummary,
    SummaryVersions,
)

_LEGACY_MSG_VER_BRANCH_RE = re.compile(
    r"^(?P<msg>\d+)-(?P<ver>\d+)-(?P<branch>\d+)$"
)
_POST_STAMP_LABEL_RE = re.compile(
    r"^(?P<gh>\d+)\.(?P<lh>\d+)-(?P<ga>\d+)\.(?P<la>\d+)-(?P<turn>.+)$"
)
_GLOBAL_STAMP_LABEL_RE = re.compile(
    r"^(?P<gh>\d+)-(?P<ga>\d+)-(?P<turn>.+)$"
)


def _format_turn_segment(*, msg: int, branch: int) -> str:
    if msg <= 0:
        return "0"
    return f"{int(branch)}.{int(msg)}"


def _parse_turn_segment(turn: str) -> tuple[int, int] | None:
    text = str(turn or "").strip()
    if text == "0":
        return 0, 1
    if "." in text:
        branch_part, msg_part = text.split(".", 1)
        if branch_part.isdigit() and msg_part.isdigit():
            return int(msg_part), int(branch_part)
        return None
    if text.isdigit():
        return int(text), 1
    return None


def format_stamp_primer_label(head: SummaryVersions, *, scope: str) -> str:
    """Primer log label: head bundle only, turn ``0``."""
    gh = max(0, int(head.get("channel") or 0))
    if scope == "post":
        lh = max(1, int(head.get("post") or 0))
        return f"{gh}.{lh}-0.0-0"
    return f"{gh}-0-0"


def format_stamp_label(stamp: ContextStamp | Mapping[str, Any]) -> str:
    """Build ``contextLabel`` from full ``contextStamp`` JSON."""
    if not isinstance(stamp, Mapping):
        raise TypeError("format_stamp_label expects a contextStamp mapping")
    summary = stamp.get("summary")
    address = stamp.get("address")
    if not isinstance(summary, dict) or not isinstance(address, dict):
        raise TypeError("contextStamp must include summary and address")
    scope = stamp.get("scope")
    if scope not in ("global", "post"):
        head_raw = summary.get("head")
        head = head_raw if isinstance(head_raw, dict) else {}
        attach_raw = summary.get("attach")
        attach = attach_raw if isinstance(attach_raw, dict) else {}
        scope = (
            "post"
            if int(head.get("post") or 0) > 0 or int(attach.get("post") or 0) > 0
            else "global"
        )

    head_raw = summary.get("head")
    attach_raw = summary.get("attach")
    head = head_raw if isinstance(head_raw, dict) else {}
    attach = attach_raw if isinstance(attach_raw, dict) else {}

    gh = max(0, int(head.get("channel") or 0))
    ga = max(0, int(attach.get("channel") or 0))
    msg = max(0, int(address.get("msg") or 0))
    branch = max(1, int(address.get("branch") or 1))
    turn = _format_turn_segment(msg=msg, branch=branch)

    if scope == "post":
        lh = max(1, int(head.get("post") or 0))
        la = max(0, int(attach.get("post") or 0))
        if ga <= 0 and la <= 0:
            ga, la = 0, 0
        return f"{gh}.{lh}-{ga}.{la}-{turn}"

    if ga <= 0:
        ga = 0
    return f"{gh}-0-{ga}-{turn}"


def parse_stamp_label(raw: str) -> StampAddress | None:
    """Parse ``contextLabel`` turn address (msg + branch); msgVersion only in JSON."""
    text = str(raw or "").strip()
    if not text:
        return None

    legacy = _LEGACY_MSG_VER_BRANCH_RE.match(text)
    if legacy is not None:
        return {
            "msg": int(legacy.group("msg")),
            "msgVersion": int(legacy.group("ver")),
            "branch": int(legacy.group("branch")),
        }

    match = _POST_STAMP_LABEL_RE.match(text)
    if match is not None:
        turn = _parse_turn_segment(match.group("turn"))
        if turn is None:
            return None
        msg, branch = turn
        return {"msg": msg, "msgVersion": 1, "branch": branch}

    match = _GLOBAL_STAMP_LABEL_RE.match(text)
    if match is not None:
        turn = _parse_turn_segment(match.group("turn"))
        if turn is None:
            return None
        msg, branch = turn
        return {"msg": msg, "msgVersion": 1, "branch": branch}

    return None


def is_stamp_label(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    if _LEGACY_MSG_VER_BRANCH_RE.match(text):
        return True
    if _POST_STAMP_LABEL_RE.match(text):
        return True
    return _GLOBAL_STAMP_LABEL_RE.match(text) is not None


def build_context_stamp(
    *,
    scope: str,
    address: StampAddress,
    head: SummaryVersions,
    attach: SummaryVersions,
    catalog_channel: int,
    catalog_post: int,
) -> ContextStamp:
    if scope == "global":
        head = {**head, "post": 0}
        attach = {**attach, "post": 0}
    summary: StampSummary = {"head": dict(head), "attach": dict(attach)}
    catalog: CatalogSnapshot = {
        "channel": max(0, int(catalog_channel)),
        "post": max(0, int(catalog_post)),
    }
    return {
        "scope": "post" if scope == "post" else "global",
        "address": dict(address),
        "summary": summary,
        "catalog": catalog,
    }


def read_context_stamp(
    message: Mapping[str, Any],
    *,
    branch_index: int | None = None,
) -> ContextStamp | None:
    """Read ``contextStamp`` from user message or branch node."""
    branches = message.get("userBranches")
    if isinstance(branches, list) and len(branches) > 1:
        bi = branch_index if branch_index is not None else clamp_active_branch_index(message)
        if 0 <= bi < len(branches):
            branch = branches[bi]
            if isinstance(branch, Mapping):
                parsed = _parse_context_stamp_raw(
                    branch.get("contextStamp") or branch.get("context_stamp")
                )
                if parsed is not None:
                    return parsed
        if bi == 0:
            parsed = _parse_context_stamp_raw(
                message.get("contextStamp") or message.get("context_stamp")
            )
            if parsed is not None:
                return parsed
        return None

    return _parse_context_stamp_raw(message.get("contextStamp") or message.get("context_stamp"))


def _parse_context_stamp_raw(raw: Any) -> ContextStamp | None:
    if not isinstance(raw, dict):
        return None
    address = raw.get("address")
    summary = raw.get("summary")
    if not isinstance(address, dict) or not isinstance(summary, dict):
        return None
    head = summary.get("head")
    attach = summary.get("attach")
    if not isinstance(head, dict) or not isinstance(attach, dict):
        return None
    scope = raw.get("scope")
    if scope not in ("global", "post"):
        scope = "post" if int(head.get("post") or 0) > 0 or int(attach.get("post") or 0) > 0 else "global"
    catalog = raw.get("catalog")
    catalog_channel = int(catalog.get("channel") or 0) if isinstance(catalog, dict) else 0
    catalog_post = int(catalog.get("post") or 0) if isinstance(catalog, dict) else 0
    return {
        "scope": scope,
        "address": {
            "msg": int(address.get("msg") or 0),
            "msgVersion": int(address.get("msgVersion") or 1),
            "branch": int(address.get("branch") or 1),
        },
        "summary": {
            "head": {
                "channel": max(0, int(head.get("channel") or 0)),
                "post": max(0, int(head.get("post") or 0)),
            },
            "attach": {
                "channel": max(0, int(attach.get("channel") or 0)),
                "post": max(0, int(attach.get("post") or 0)),
            },
        },
        "catalog": {"channel": catalog_channel, "post": catalog_post},
    }


def _should_keep_existing_stamp(message: Mapping[str, Any], *, branch_index: int | None = None) -> bool:
    """Once a user-turn has contextStamp or contextLabel, it is never rewritten."""
    if read_context_stamp(message, branch_index=branch_index) is not None:
        return True
    if branch_index is not None:
        branches = message.get("userBranches")
        if isinstance(branches, list) and 0 <= branch_index < len(branches):
            branch = branches[branch_index]
            raw = branch.get("contextLabel") or branch.get("context_label") if isinstance(branch, Mapping) else None
        else:
            raw = None
    else:
        raw = message.get("contextLabel") or message.get("context_label")
    return isinstance(raw, str) and bool(raw.strip())


def _stamp_on_user_message(message: Mapping[str, Any], stamp: ContextStamp) -> dict[str, Any]:
    label = format_stamp_label(stamp)
    updated = dict(message)
    branches = updated.get("userBranches")
    if isinstance(branches, list) and len(branches) > 1:
        bi = clamp_active_branch_index(updated)
        if _should_keep_existing_stamp(updated, branch_index=bi):
            return updated
        new_branches: list[Any] = []
        for index, branch in enumerate(branches):
            if index != bi:
                new_branches.append(dict(branch) if isinstance(branch, Mapping) else branch)
                continue
            branch_copy = dict(branch) if isinstance(branch, Mapping) else {}
            branch_copy["contextLabel"] = label
            branch_copy["contextStamp"] = dict(stamp)
            new_branches.append(branch_copy)
        if updated.get("contextLabel") or updated.get("contextStamp"):
            parent_label = updated.get("contextLabel")
            parent_stamp = updated.get("contextStamp")
            if new_branches and isinstance(new_branches[0], Mapping):
                branch0 = dict(new_branches[0])
                if parent_label and not branch0.get("contextLabel"):
                    branch0["contextLabel"] = parent_label
                if parent_stamp and not branch0.get("contextStamp"):
                    branch0["contextStamp"] = parent_stamp
                new_branches[0] = branch0
            updated.pop("contextLabel", None)
            updated.pop("context_label", None)
            updated.pop("contextStamp", None)
            updated.pop("context_stamp", None)
        updated["userBranches"] = new_branches
        return updated

    if _should_keep_existing_stamp(updated):
        return updated
    updated["contextLabel"] = label
    updated["contextStamp"] = dict(stamp)
    return updated


def stamp_context_stamp_on_path(
    history: list[Mapping[str, Any]],
    path: list[int],
    stamp: ContextStamp,
) -> list[dict[str, Any]] | None:
    """Write ``contextLabel`` + ``contextStamp`` on user message at ``path``."""

    def attach(message: Mapping[str, Any]) -> dict[str, Any]:
        if message.get("role") != "user":
            return dict(message)
        return _stamp_on_user_message(message, stamp)

    return map_message_at_path(list(history), path, attach)


def stamped_label_from_message(message: Mapping[str, Any], *, branch_index: int | None = None) -> str | None:
    stamp = read_context_stamp(message, branch_index=branch_index)
    if stamp is not None:
        return format_stamp_label(stamp)
    raw = message.get("contextLabel") or message.get("context_label")
    if isinstance(raw, str) and is_stamp_label(raw):
        return raw.strip()
    return None
