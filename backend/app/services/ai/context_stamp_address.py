"""Resolve msg-ver-branch address and branch registry for stamp mechanics."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.chat_history import clamp_active_branch_index
from app.services.ai.context_stamp_label import read_context_stamp
from app.services.ai.context_stamp_types import (
    STAMP_CONTEXT_KEY,
    StampAddress,
    StampContextRoot,
    branch_state_key,
    empty_stamp_context,
)


def _path_key(path: list[int]) -> str:
    return ".".join(str(part) for part in path)


def _registry_key(path: list[int], branch_index: int) -> str:
    return f"{_path_key(path)}@{branch_index}"


def _bump_next_branch_id(stamp_context: StampContextRoot, assigned_branch_id: int) -> None:
    next_id = max(2, int(stamp_context.get("next_branch_id") or 2))
    stamp_context["next_branch_id"] = max(next_id, int(assigned_branch_id) + 1)


def _resolve_fork_branch_id(
    message: Mapping[str, Any],
    *,
    node_path: list[int],
    bi: int,
    current_branch: int,
    registry: dict[str, int],
    stamp_context: StampContextRoot,
) -> int:
    """Resolve global branch id for fork slot ``bi`` (new id only for unstamped edit)."""
    reg_key = _registry_key(node_path, bi)
    branches = message.get("userBranches")
    branch_index = bi if isinstance(branches, list) and len(branches) > 1 else None
    stamp = read_context_stamp(message, branch_index=branch_index)
    if stamp is not None:
        stamped_branch = max(1, int(stamp.get("address", {}).get("branch") or 0))
        if stamped_branch > 0:
            registry[reg_key] = stamped_branch
            _bump_next_branch_id(stamp_context, stamped_branch)
            return stamped_branch

    if reg_key in registry:
        return registry[reg_key]

    if bi == 0:
        registry[reg_key] = current_branch
        return current_branch

    next_id = int(stamp_context.get("next_branch_id") or 2)
    registry[reg_key] = next_id
    stamp_context["next_branch_id"] = next_id + 1
    return next_id


def load_stamp_context(chat_meta: Mapping[str, Any] | None, *, post_head: int = 0) -> StampContextRoot:
    if not chat_meta:
        return empty_stamp_context(post_head=post_head)
    raw = chat_meta.get(STAMP_CONTEXT_KEY)
    if not isinstance(raw, dict):
        return empty_stamp_context(post_head=post_head)
    branches = raw.get("branches")
    if not isinstance(branches, dict) or not branches:
        return empty_stamp_context(post_head=post_head)
    return {
        "branches": dict(branches),
        "next_branch_id": max(2, int(raw.get("next_branch_id") or 2)),
        "branch_registry": dict(raw.get("branch_registry") or {}),
    }


def resolve_active_branch_id(
    history: list[Mapping[str, Any]] | None,
    stamp_context: StampContextRoot,
) -> int:
    """Walk active path and resolve global branch id (1-based)."""
    branch_id = 1
    registry: dict[str, int] = dict(stamp_context.get("branch_registry") or {})

    def walk(items: list[Mapping[str, Any]], path: list[int], current_branch: int) -> int:
        nonlocal registry
        result_branch = current_branch
        for index, message in enumerate(items):
            if not isinstance(message, Mapping):
                continue
            node_path = [*path, index]
            if message.get("role") != "user":
                continue
            branches = message.get("userBranches")
            if isinstance(branches, list) and branches:
                bi = clamp_active_branch_index(message)
                result_branch = _resolve_fork_branch_id(
                    message,
                    node_path=node_path,
                    bi=bi,
                    current_branch=current_branch,
                    registry=registry,
                    stamp_context=stamp_context,
                )
                branch = branches[bi]
                if isinstance(branch, Mapping):
                    continuation = branch.get("continuation")
                    if isinstance(continuation, list):
                        result_branch = walk(continuation, node_path, result_branch)
                break
        stamp_context["branch_registry"] = registry
        return result_branch

    return walk(list(history or []), [], branch_id)


def resolve_address_for_path(
    history: list[Mapping[str, Any]] | None,
    path: list[int],
    *,
    stamp_context: StampContextRoot,
) -> StampAddress | None:
    """Address for the user message at ``path`` on the active tree."""
    if not path:
        return None
    msg = 0
    branch_id = 1
    registry: dict[str, int] = dict(stamp_context.get("branch_registry") or {})
    target = list(path)
    found: StampAddress | None = None

    def walk(items: list[Mapping[str, Any]], node_path: list[int], current_branch: int) -> bool:
        nonlocal msg, branch_id, found
        for index, message in enumerate(items):
            if not isinstance(message, Mapping):
                continue
            full_path = [*node_path, index]
            if message.get("role") != "user":
                continue
            msg += 1
            branches = message.get("userBranches")
            bi = 0
            branched = isinstance(branches, list) and len(branches) > 1
            if branches:
                bi = clamp_active_branch_index(message)
                branch_id = _resolve_fork_branch_id(
                    message,
                    node_path=full_path,
                    bi=bi,
                    current_branch=current_branch,
                    registry=registry,
                    stamp_context=stamp_context,
                )
            else:
                branch_id = current_branch
            msg_version = bi + 1 if branched and full_path == target else 1
            if full_path == target:
                found = {
                    "msg": msg,
                    "msgVersion": msg_version,
                    "branch": branch_id,
                }
                return True
            if branches:
                branch = branches[bi]
                if isinstance(branch, Mapping):
                    continuation = branch.get("continuation")
                    if isinstance(continuation, list):
                        if walk(continuation, full_path, branch_id):
                            return True
                return False
        return False

    walk(list(history or []), [], 1)
    stamp_context["branch_registry"] = registry
    return found


def resolve_current_address(
    history: list[Mapping[str, Any]] | None,
    *,
    stamp_context: StampContextRoot,
) -> tuple[StampAddress | None, list[int] | None]:
    """Address and path for the last user turn on the active branch."""
    entries: list[tuple[list[int], Mapping[str, Any]]] = []

    def walk(items: list[Mapping[str, Any]], node_path: list[int]) -> None:
        for index, message in enumerate(items):
            if not isinstance(message, Mapping):
                continue
            full_path = [*node_path, index]
            if message.get("role") == "user":
                entries.append((full_path, message))
                branches = message.get("userBranches")
                if isinstance(branches, list) and branches:
                    bi = clamp_active_branch_index(message)
                    branch = branches[bi]
                    if isinstance(branch, Mapping):
                        continuation = branch.get("continuation")
                        if isinstance(continuation, list):
                            walk(continuation, full_path)
                    break

    walk(list(history or []), [])
    if not entries:
        return None, None
    path, _ = entries[-1]
    address = resolve_address_for_path(history, path, stamp_context=stamp_context)
    return address, path


def resolve_fork_parent_branch_id(
    stamp_context: StampContextRoot,
    *,
    fork_path: list[int],
    fork_branch_id: int,
) -> int:
    """Branch id for branch_index 0 at the fork node (line we edit from)."""
    registry = dict(stamp_context.get("branch_registry") or {})
    parent_key = _registry_key(fork_path, 0)
    if parent_key in registry:
        return max(1, int(registry[parent_key]))
    return max(1, int(fork_branch_id) - 1)


def ensure_branch_state(stamp_context: StampContextRoot, branch_id: int, *, post_head: int = 0) -> None:
    from app.services.ai.context_stamp_types import empty_branch_state

    key = branch_state_key(branch_id)
    branches = stamp_context.setdefault("branches", {})
    if key not in branches:
        branches[key] = empty_branch_state(post_head=post_head)
