"""Enumerate context stamps on the active branch (msg → stamp)."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import clamp_active_branch_index
from app.services.ai.context_label import enumerate_active_user_turns
from app.services.ai.context_stamp_label import read_context_stamp
from app.services.ai.context_stamp_types import ContextStamp


def iter_all_stamps_in_history(
    history: list[Mapping[str, Any]] | None,
) -> list[ContextStamp]:
    """Every ``contextStamp`` in the chat tree (all branches, not only active path)."""
    collected: list[ContextStamp] = []

    def walk(items: list[Mapping[str, Any]]) -> None:
        for message in items:
            if not isinstance(message, Mapping) or message.get("role") != "user":
                continue
            branches = message.get("userBranches")
            if isinstance(branches, list) and branches:
                for bi, branch in enumerate(branches):
                    if not isinstance(branch, Mapping):
                        continue
                    stamp = read_context_stamp(message, branch_index=bi)
                    if stamp is not None:
                        collected.append(stamp)
                    continuation = branch.get("continuation")
                    if isinstance(continuation, list):
                        walk(continuation)
            else:
                stamp = read_context_stamp(message)
                if stamp is not None:
                    collected.append(stamp)

    walk(list(history or []))
    return collected


def catalog_layer_versions_seen_in_chat(
    history: list[Mapping[str, Any]] | None,
    layer: str,
) -> set[int]:
    """Catalog versions already present anywhere in chat (head or attach stamps)."""
    seen: set[int] = set()
    for stamp in iter_all_stamps_in_history(history):
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            continue
        for part in ("head", "attach"):
            block = summary.get(part)
            if not isinstance(block, dict):
                continue
            version = max(0, int(block.get(layer) or 0))
            if version > 0:
                seen.add(version)
    return seen


def attach_version_seen_in_chat(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: str,
    version: int,
) -> bool:
    if version <= 0:
        return False
    return version in catalog_layer_versions_seen_in_chat(history, layer)


def stamps_by_msg_on_active_path(
    history: list[Mapping[str, Any]] | None,
) -> dict[int, ContextStamp]:
    """Map sequential user-turn number → stamped ``contextStamp`` on active path."""
    result: dict[int, ContextStamp] = {}
    msg = 0

    def walk(items: list[Mapping[str, Any]]) -> None:
        nonlocal msg
        for message in items:
            if not isinstance(message, Mapping):
                continue
            if message.get("role") != "user":
                continue
            msg += 1
            branches = message.get("userBranches")
            if isinstance(branches, list) and branches:
                bi = clamp_active_branch_index(message)
                stamp = read_context_stamp(message, branch_index=bi)
                if stamp is not None:
                    result[msg] = stamp
                branch = branches[bi]
                if isinstance(branch, Mapping):
                    continuation = branch.get("continuation")
                    if isinstance(continuation, list):
                        walk(continuation)
                break
            stamp = read_context_stamp(message)
            if stamp is not None:
                result[msg] = stamp

    walk(list(history or []))
    return result


def stamped_layer_attach_by_msg(
    history: list[Mapping[str, Any]] | None,
    layer: str,
) -> dict[int, int]:
    """Map user-turn number → stamped attach version for a summary layer."""
    result: dict[int, int] = {}
    for msg, stamp in stamps_by_msg_on_active_path(history).items():
        summary = stamp.get("summary")
        if not isinstance(summary, dict):
            continue
        attach = summary.get("attach")
        if not isinstance(attach, dict):
            continue
        result[int(msg)] = max(0, int(attach.get(layer) or 0))
    return result


def attach_already_stamped_on_earlier_msg(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: str,
    version: int,
    current_msg: int,
) -> bool:
    """True when an earlier user-turn already stamped this attach version."""
    if version <= 0:
        return False
    for msg, attached in stamped_layer_attach_by_msg(history, layer).items():
        if msg < current_msg and attached == version:
            return True
    return False


def pending_queue_from_stamp_attaches(
    history: list[Mapping[str, Any]] | None,
    *,
    layer: str,
    head: int,
    up_to_msg: int | None = None,
) -> list[dict[str, int]]:
    """Rebuild pending queue from stamped attach versions on the active path."""
    by_version: dict[int, int] = {}
    for msg, attached in stamped_layer_attach_by_msg(history, layer).items():
        if up_to_msg is not None and msg > up_to_msg:
            continue
        if attached <= head:
            continue
        if attached not in by_version or msg < by_version[attached]:
            by_version[attached] = msg
    return sorted(
        [{"version": version, "sinceMsg": since_msg} for version, since_msg in by_version.items()],
        key=lambda item: (item["sinceMsg"], item["version"]),
    )


def merge_pending_queues(
    *queues: list[dict[str, int]],
    head: int,
) -> list[dict[str, int]]:
    by_version: dict[int, int] = {}
    for queue in queues:
        for item in queue:
            version = int(item["version"])
            since_msg = int(item["sinceMsg"])
            if version <= head:
                continue
            if version not in by_version or since_msg < by_version[version]:
                by_version[version] = since_msg
    return sorted(
        [{"version": version, "sinceMsg": since_msg} for version, since_msg in by_version.items()],
        key=lambda item: (item["sinceMsg"], item["version"]),
    )
