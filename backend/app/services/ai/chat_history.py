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

    def map_at(items: list[Mapping[str, Any]], subpath: list[int]) -> list[dict[str, Any]]:
        if not subpath:
            return [dict(item) if isinstance(item, Mapping) else item for item in items]

        sub_head, *sub_rest = subpath
        result: list[dict[str, Any]] = []
        for index, message in enumerate(items):
            if index != sub_head:
                result.append(dict(message) if isinstance(message, Mapping) else message)
                continue
            current = dict(message) if isinstance(message, Mapping) else message
            if not sub_rest:
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
                branch["continuation"] = map_at(continuation, sub_rest)
            new_branches = [dict(item) if isinstance(item, Mapping) else item for item in branches]
            new_branches[branch_index] = branch
            current["userBranches"] = new_branches
            result.append(current)
        return result

    return map_at(list(history), path)


def _strip_branch_stamps(branch: Mapping[str, Any]) -> dict[str, Any]:
    stripped = dict(branch)
    stripped.pop("contextLabel", None)
    stripped.pop("context_label", None)
    stripped.pop("bundleContext", None)
    stripped.pop("bundle_context", None)
    stripped.pop("contextStamp", None)
    stripped.pop("context_stamp", None)
    continuation = stripped.get("continuation")
    if isinstance(continuation, list):
        stripped["continuation"] = [
            _strip_message_stamps(item) if isinstance(item, Mapping) else item
            for item in continuation
        ]
    return stripped


def _strip_message_stamps(message: Mapping[str, Any]) -> dict[str, Any]:
    """Remove client-authored stamps; only the server may set contextLabel."""
    if message.get("role") != "user":
        return dict(message)
    stripped = dict(message)
    stripped.pop("contextLabel", None)
    stripped.pop("context_label", None)
    stripped.pop("bundleContext", None)
    stripped.pop("bundle_context", None)
    stripped.pop("contextStamp", None)
    stripped.pop("context_stamp", None)
    branches = stripped.get("userBranches")
    if isinstance(branches, list):
        stripped["userBranches"] = [
            _strip_branch_stamps(branch) if isinstance(branch, Mapping) else branch
            for branch in branches
        ]
    return stripped


def normalize_branched_history(history: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Fold linear siblings after a branched user node into branch 0 continuation.

    Mirrors frontend ``normalizeBranchedHistory`` so PATCH merge aligns tree shape.
    """

    def normalize_list(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        index = 0
        while index < len(items):
            message = items[index]
            if not isinstance(message, Mapping):
                out.append(message)  # type: ignore[arg-type]
                index += 1
                continue
            current = dict(message)
            if current.get("role") == "user":
                branches = current.get("userBranches")
                if isinstance(branches, list) and branches:
                    orphans = [
                        dict(item) if isinstance(item, Mapping) else item
                        for item in items[index + 1 :]
                    ]
                    new_branches: list[dict[str, Any]] = []
                    for branch_index, branch in enumerate(branches):
                        if not isinstance(branch, Mapping):
                            new_branches.append(
                                dict(branch) if isinstance(branch, Mapping) else branch
                            )
                            continue
                        branch_copy = dict(branch)
                        continuation = branch_copy.get("continuation")
                        cont_list = list(continuation) if isinstance(continuation, list) else []
                        if branch_index == 0:
                            branch_copy["continuation"] = normalize_list(cont_list + orphans)
                        else:
                            branch_copy["continuation"] = normalize_list(cont_list)
                        new_branches.append(branch_copy)
                    current["userBranches"] = new_branches
                    out.append(current)
                    return out
            out.append(current)
            index += 1
        return out

    if not isinstance(history, list) or not history:
        return []
    return normalize_list(list(history))


def _merge_user_message_stamps(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(incoming)
    if existing is None or existing.get("role") != "user" or incoming.get("role") != "user":
        return merged
    if existing.get("contextLabel"):
        merged["contextLabel"] = existing["contextLabel"]
    if existing.get("contextStamp"):
        merged["contextStamp"] = existing["contextStamp"]
    if existing.get("bundleContext"):
        merged["bundleContext"] = existing["bundleContext"]

    incoming_branches = incoming.get("userBranches")
    if not isinstance(incoming_branches, list):
        return merged

    existing_branches = existing.get("userBranches")
    merged_branches: list[dict[str, Any]] = []
    for index, branch in enumerate(incoming_branches):
        if not isinstance(branch, Mapping):
            merged_branches.append(dict(branch) if isinstance(branch, Mapping) else branch)
            continue
        branch_copy = dict(branch)
        existing_branch = (
            existing_branches[index]
            if isinstance(existing_branches, list) and index < len(existing_branches)
            else None
        )
        if isinstance(existing_branch, Mapping):
            if existing_branch.get("contextLabel"):
                branch_copy["contextLabel"] = existing_branch["contextLabel"]
            if existing_branch.get("contextStamp"):
                branch_copy["contextStamp"] = existing_branch["contextStamp"]
            if existing_branch.get("bundleContext"):
                branch_copy["bundleContext"] = existing_branch["bundleContext"]
        incoming_cont = branch.get("continuation")
        if isinstance(incoming_cont, list):
            existing_cont = (
                existing_branch.get("continuation")
                if isinstance(existing_branch, Mapping)
                else None
            )
            branch_copy["continuation"] = merge_history_stamps(
                existing_cont if isinstance(existing_cont, list) else [],
                incoming_cont,
            )
        merged_branches.append(branch_copy)
    merged["userBranches"] = merged_branches
    if isinstance(incoming_branches, list) and len(incoming_branches) > 1:
        if merged_branches and isinstance(merged_branches[0], Mapping):
            branch0 = dict(merged_branches[0])
            changed = False
            if merged.get("contextLabel") and not branch0.get("contextLabel"):
                branch0["contextLabel"] = merged["contextLabel"]
                changed = True
            if merged.get("contextStamp") and not branch0.get("contextStamp"):
                branch0["contextStamp"] = merged["contextStamp"]
                changed = True
            if changed:
                merged_branches[0] = branch0
                merged["userBranches"] = merged_branches
        merged.pop("contextLabel", None)
        merged.pop("contextStamp", None)
        merged.pop("context_stamp", None)
    return merged


def _align_existing_history_for_merge(
    existing: list[Mapping[str, Any]],
    incoming: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Fold existing linear tails into branch continuations when incoming has branches.

    After a client-side fork the DB may still store a flat history while PATCH sends
    a branched tree. Index-based stamp merge would drop stamps on messages that moved
    into branch continuations without this alignment step.
    """

    def align_level(
        ex_items: list[Mapping[str, Any]],
        inc_items: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        aligned: list[Any] = [
            dict(item) if isinstance(item, Mapping) else item for item in ex_items
        ]
        index = 0
        while index < len(inc_items):
            if index >= len(aligned):
                break
            inc = inc_items[index]
            ex = aligned[index]
            if not isinstance(inc, Mapping):
                index += 1
                continue
            if inc.get("role") != "user":
                index += 1
                continue
            inc_branches = inc.get("userBranches")
            if not isinstance(inc_branches, list) or not inc_branches:
                index += 1
                continue

            ex_branches = ex.get("userBranches") if isinstance(ex, Mapping) else None
            if isinstance(ex_branches, list) and ex_branches:
                ex_copy = dict(ex) if isinstance(ex, Mapping) else {}
                merged_branches: list[dict[str, Any]] = []
                for branch_index, inc_branch in enumerate(inc_branches):
                    if not isinstance(inc_branch, Mapping):
                        if branch_index < len(ex_branches):
                            merged_branches.append(
                                dict(ex_branches[branch_index])
                                if isinstance(ex_branches[branch_index], Mapping)
                                else ex_branches[branch_index]
                            )
                        continue
                    ex_branch = (
                        ex_branches[branch_index]
                        if branch_index < len(ex_branches)
                        else {}
                    )
                    branch_copy = dict(ex_branch) if isinstance(ex_branch, Mapping) else {}
                    inc_cont = inc_branch.get("continuation")
                    if isinstance(inc_cont, list):
                        ex_cont = branch_copy.get("continuation")
                        branch_copy["continuation"] = align_level(
                            list(ex_cont) if isinstance(ex_cont, list) else [],
                            inc_cont,
                        )
                    merged_branches.append(branch_copy)
                ex_copy["userBranches"] = merged_branches
                aligned[index] = ex_copy
                index += 1
                continue

            if not isinstance(ex, Mapping) or ex.get("role") != "user":
                index += 1
                continue

            tail = aligned[index + 1 :]
            aligned = aligned[: index + 1]
            ex_copy = dict(ex)
            parent_label = ex_copy.pop("contextLabel", None)
            parent_bundle = ex_copy.pop("bundleContext", None)
            ex_copy.pop("text", None)
            new_branches: list[dict[str, Any]] = []
            for branch_index, inc_branch in enumerate(inc_branches):
                if not isinstance(inc_branch, Mapping):
                    new_branches.append({})
                    continue
                branch_copy: dict[str, Any] = {
                    key: value for key, value in inc_branch.items() if key != "continuation"
                }
                inc_cont = inc_branch.get("continuation")
                if branch_index == 0:
                    branch_copy["text"] = str(ex.get("text") or inc_branch.get("text") or "")
                    if parent_label:
                        branch_copy["contextLabel"] = parent_label
                    if parent_bundle:
                        branch_copy["bundleContext"] = parent_bundle
                    branch_copy["continuation"] = align_level(
                        list(tail),
                        inc_cont if isinstance(inc_cont, list) else [],
                    )
                elif isinstance(inc_cont, list):
                    branch_copy["continuation"] = align_level([], inc_cont)
                new_branches.append(branch_copy)
            ex_copy["userBranches"] = new_branches
            aligned[index] = ex_copy
            return aligned
        return aligned

    return align_level(list(existing), list(incoming))


def merge_history_stamps(
    existing: list[Mapping[str, Any]] | None,
    incoming: list[Mapping[str, Any]],
    *,
    strip_incoming: bool = False,
) -> list[dict[str, Any]]:
    """Keep immutable per-message stamps when client PATCH omits or overwrites them."""
    if strip_incoming:
        incoming = [
            _strip_message_stamps(item) if isinstance(item, Mapping) else item
            for item in incoming
        ]
    existing_norm = normalize_branched_history(existing)
    incoming_norm = normalize_branched_history(incoming)
    if not existing_norm:
        return incoming_norm

    existing_aligned = _align_existing_history_for_merge(existing_norm, incoming_norm)

    merged: list[dict[str, Any]] = []
    for index, incoming_message in enumerate(incoming_norm):
        if not isinstance(incoming_message, Mapping):
            merged.append(incoming_message)
            continue
        existing_message = (
            existing_aligned[index] if index < len(existing_aligned) else None
        )
        if isinstance(existing_message, Mapping):
            merged.append(_merge_user_message_stamps(existing_message, incoming_message))
        else:
            merged.append(dict(incoming_message))
    return merged


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
