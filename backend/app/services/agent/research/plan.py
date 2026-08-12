"""Persistent research plan: the planner's open-obligations ledger.

The planner is otherwise a myopic reactor — each step is an independent LLM
call whose `reasoning`/`gap` never reach the next step (only `tool → summary`
does). A stated intent ("надо проверить global notes") therefore evaporates
between steps, and the model finishes having silently abandoned it.

This module makes the plan first-class, persistent state with one invariant:
**a plan item never leaves the plan silently.** It leaves only via an explicit
`done` (with a citing evidence_id) or `dropped` (with a reason). If the model
omits a previously-open item from its new plan, `merge_plan` re-inserts it as
`open` and records a repair hint — the code refuses to forget. FinishRetrieval
is then gated (see `open_items`) until nothing is `open`.
"""

from __future__ import annotations

from typing import Any, Mapping

VALID_STATUS = frozenset({"open", "done", "dropped"})
TERMINAL_STATUS = frozenset({"done", "dropped"})


def _slug(text: str) -> str:
    """Deterministic id from item text (no Date.now/random — resume-safe).

    Stable across re-emission so merge can match an incoming item to its prior
    entry even when the model omits the id. Collisions across genuinely distinct
    items are acceptable: they'd merge into one plan line, never crash.
    """
    cleaned = " ".join(str(text or "").split()).lower()
    return cleaned[:80] or "item"


def _item_key(item: Mapping[str, Any]) -> str:
    """Identity for matching prev↔incoming: model id if given, else text slug."""
    raw_id = str(item.get("id") or "").strip()
    return raw_id or _slug(str(item.get("text") or ""))


def parse_plan(payload: Any) -> list[dict[str, Any]] | None:
    """Extract a plan list from the raw planner JSON `plan` field.

    Returns None when the key is absent/malformed (the planner said nothing
    about the plan this step) so the caller can carry the previous plan
    unchanged. Returns [] only when the model explicitly sent an empty list.
    """
    if payload is None:
        return None
    if not isinstance(payload, list):
        return None
    items: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        status = str(entry.get("status") or "open").strip().lower()
        if status not in VALID_STATUS:
            status = "open"
        item: dict[str, Any] = {
            "id": str(entry.get("id") or "").strip() or _slug(text),
            "text": text,
            "status": status,
        }
        reason = str(entry.get("reason") or "").strip()
        if reason:
            item["reason"] = reason
        evidence_id = str(entry.get("evidence_id") or "").strip()
        if evidence_id:
            item["evidence_id"] = evidence_id
        items.append(item)
    return items


def merge_plan(
    prev: list[dict[str, Any]],
    incoming: list[dict[str, Any]] | None,
    *,
    evidence_ids: frozenset[str],
    evidence_handle_map: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge the planner's new plan onto the persisted one, enforcing invariants.

    Returns (merged_plan, repair_hints). The hints are fed back to the planner
    so a rejected transition is visible next step. Rules:
    - Absent `incoming` (None) → carry `prev` unchanged, no hints.
    - Any `prev` item that was `open` but is missing from `incoming` is
      re-inserted as `open` (the no-silent-drop invariant) with a hint.
    - `done` requires an `evidence_id` present in the collected records; else the
      transition is refused (kept `open`) with a hint — lying about done is cheap
      to attempt but does not stick.
    - `dropped` requires a non-empty `reason`; else refused (kept `open`).
    - A `prev` item already terminal (done/dropped) stays terminal; it cannot be
      silently reopened and re-closed to dodge a citation.
    """
    prev_by_key = {_item_key(it): it for it in prev}
    hints: list[str] = []
    if incoming is None:
        return [dict(it) for it in prev], hints

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _emit(key: str, item: dict[str, Any]) -> None:
        if key not in merged:
            order.append(key)
        merged[key] = item

    for item in incoming:
        key = _item_key(item)
        prior = prev_by_key.get(key)
        # An already-terminal item is frozen: keep the prior terminal record so a
        # done/dropped can't be reopened to shed its citation, then re-closed.
        if prior and prior.get("status") in TERMINAL_STATUS:
            _emit(key, dict(prior))
            continue
        resolved = _resolve_transition(
            item,
            evidence_ids=evidence_ids,
            evidence_handle_map=evidence_handle_map or {},
            hints=hints,
        )
        _emit(key, resolved)

    # No-silent-drop: any previously-open item the model omitted comes back open.
    for key, prior in prev_by_key.items():
        if key in merged:
            continue
        if prior.get("status") in TERMINAL_STATUS:
            _emit(key, dict(prior))
            continue
        _emit(key, {**prior, "status": "open"})
        hints.append(
            f"unclosed_plan_item: «{prior.get('text')}» — закрой явно "
            f"(done с evidence_id или dropped с reason), не выбрасывай молча"
        )

    return [merged[key] for key in order], hints


def _resolve_transition(
    item: dict[str, Any],
    *,
    evidence_ids: frozenset[str],
    evidence_handle_map: Mapping[str, str],
    hints: list[str],
) -> dict[str, Any]:
    """Validate one incoming item's status; downgrade to `open` if unjustified."""
    status = item.get("status")
    if status == "done":
        evidence_id = str(item.get("evidence_id") or "").strip()
        # Exact match (normal case).
        if evidence_id in evidence_ids:
            return item
        canonical = evidence_handle_map.get(evidence_id)
        if canonical in evidence_ids:
            return {**item, "evidence_id": canonical}
        hints.append(
            f"plan_done_needs_evidence: «{item.get('text')}» помечен done без "
            f"валидного evidence_id из собранного context — оставлен open"
        )
        return {"id": item["id"], "text": item["text"], "status": "open"}
    if status == "dropped":
        if not str(item.get("reason") or "").strip():
            hints.append(
                f"plan_drop_needs_reason: «{item.get('text')}» помечен dropped без "
                f"причины — оставлен open"
            )
            return {"id": item["id"], "text": item["text"], "status": "open"}
        return item
    return item


def open_items(plan: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Items still blocking finish."""
    return [it for it in (plan or []) if it.get("status") == "open"]


def render_plan_for_planner(plan: list[dict[str, Any]] | None) -> str:
    """Render the plan for the next planner step's prompt.

    Open items are what the planner must still act on or explicitly close;
    terminal items are shown briefly so the model doesn't re-add them.
    """
    items = plan or []
    if not items:
        return ""
    mark = {"open": "☐", "done": "✓", "dropped": "✗"}
    lines = ["План (открытые пункты блокируют FinishRetrieval):"]
    for it in items:
        glyph = mark.get(str(it.get("status")), "☐")
        suffix = ""
        if it.get("status") == "done" and it.get("evidence_id"):
            suffix = f" [{it['evidence_id']}]"
        elif it.get("status") == "dropped" and it.get("reason"):
            suffix = f" ({it['reason']})"
        lines.append(f"  {glyph} [{it.get('id')}] {it.get('text')}{suffix}")
    return "\n".join(lines)
