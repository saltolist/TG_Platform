"""Linearize branched chat history for LLM context (mirror frontend chatPaths.ts)."""

from __future__ import annotations

from typing import Any, Mapping


def clamp_active_branch_index(message: Mapping[str, Any]) -> int:
    if message.get("role") != "user":
        return 0
    branches = message.get("userBranches")
    if not isinstance(branches, list) or not branches:
        return 0
    raw = message.get("activeUserBranch")
    try:
        index = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        index = 0
    return max(0, min(index, len(branches) - 1))


def display_user_text(message: Mapping[str, Any]) -> str:
    if message.get("role") != "user":
        return ""
    branches = message.get("userBranches")
    if isinstance(branches, list) and branches:
        branch = branches[clamp_active_branch_index(message)]
        if isinstance(branch, Mapping):
            return str(branch.get("text") or "")
        return ""
    return str(message.get("text") or "")


def display_ai_text(message: Mapping[str, Any]) -> str:
    if message.get("role") != "ai":
        return ""
    variants = message.get("variants")
    if isinstance(variants, list) and variants:
        selected = message.get("selectedVariant")
        try:
            index = int(selected) if selected is not None else 0
        except (TypeError, ValueError):
            index = 0
        index = max(0, min(index, len(variants) - 1))
        variant = variants[index]
        if isinstance(variant, Mapping):
            return str(variant.get("text") or "")
        return ""
    return str(message.get("text") or "")


def map_message_at_path(
    history: list[Mapping[str, Any]],
    path: list[int],
    updater: Any,
) -> list[dict[str, Any]]:
    """Return history with one message replaced (mirrors frontend mapMessageAtPath)."""
    if not path:
        return [dict(item) if isinstance(item, Mapping) else item for item in history]

    head, *rest = path

    def map_list(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, message in enumerate(items):
            if index != head:
                result.append(dict(message) if isinstance(message, Mapping) else message)
                continue
            current = dict(message) if isinstance(message, Mapping) else message
            if not rest:
                result.append(dict(updater(current)))
                continue
            if current.get("role") != "user":
                result.append(current)
                continue
            branches = current.get("userBranches")
            if not isinstance(branches, list) or not branches:
                result.append(current)
                continue
            branch_index = clamp_active_branch_index(current)
            branch = dict(branches[branch_index]) if isinstance(branches[branch_index], Mapping) else {}
            continuation = branch.get("continuation")
            if isinstance(continuation, list):
                branch["continuation"] = map_list(continuation)
            new_branches = [dict(item) if isinstance(item, Mapping) else item for item in branches]
            new_branches[branch_index] = branch
            current["userBranches"] = new_branches
            result.append(current)
        return result

    return map_list(list(history))


def flatten_visible_with_paths(
    history: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return visible messages in UI order (active branches only)."""
    out: list[dict[str, Any]] = []

    def walk(items: list[Mapping[str, Any]], prefix: list[int]) -> None:
        for index, message in enumerate(items):
            path = [*prefix, index]
            out.append({"message": message, "path": path})
            if message.get("role") == "user":
                branches = message.get("userBranches")
                if isinstance(branches, list) and branches:
                    branch = branches[clamp_active_branch_index(message)]
                    if isinstance(branch, Mapping):
                        continuation = branch.get("continuation")
                        if isinstance(continuation, list):
                            walk(continuation, path)
                    break

    walk(history, [])
    return out


def message_to_llm_role_content(message: Mapping[str, Any]) -> tuple[str, str] | None:
    role = message.get("role")
    if role == "user":
        text = display_user_text(message).strip()
        return ("user", text) if text else None
    if role == "ai":
        text = display_ai_text(message).strip()
        return ("assistant", text) if text else None
    return None


def linearize_for_llm(history: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in flatten_visible_with_paths(history):
        message = item["message"]
        if not isinstance(message, Mapping):
            continue
        pair = message_to_llm_role_content(message)
        if pair is not None:
            pairs.append(pair)

    while pairs and pairs[-1][0] == "assistant" and not pairs[-1][1].strip():
        pairs.pop()

    return pairs


def filter_alternating_roles(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop leading assistants and broken role alternation."""
    filtered: list[tuple[str, str]] = []
    for role, content in pairs:
        if not filtered:
            if role == "assistant":
                continue
            filtered.append((role, content))
            continue
        if filtered[-1][0] == role:
            continue
        filtered.append((role, content))
    return filtered


def count_user_turns(pairs: list[tuple[str, str]]) -> int:
    return sum(1 for role, _ in pairs if role == "user")


def active_thread_key(history: list[Mapping[str, Any]]) -> str:
    """Signature of active branches — mirrors frontend visibleHistoryRevision()."""
    parts: list[str] = []

    def walk(items: list[Mapping[str, Any]], prefix: str) -> None:
        for index, message in enumerate(items):
            path = f"{prefix}{index}"
            if message.get("role") == "user":
                branches = message.get("userBranches")
                if isinstance(branches, list) and branches:
                    branch_index = clamp_active_branch_index(message)
                    parts.append(f"{path}@{branch_index}")
                    branch = branches[branch_index]
                    if isinstance(branch, Mapping):
                        continuation = branch.get("continuation")
                        if isinstance(continuation, list):
                            walk(continuation, f"{path}.")
                    break

    walk(history, "")
    return ",".join(parts)
