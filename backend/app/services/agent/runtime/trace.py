"""Human-readable trace of a WorkspaceAgent run, rendered from durable events.

Unlike the legacy AI_CONTEXT_LOG path (a process-local ContextVar buffer that
never survived the Celery worker boundary), this renders the "why did the agent
decide this" timeline straight from the `agent_events` rows persisted in the DB
(agent-runtime-remaining.md Спринт 5). Durable, cross-process, available after
the fact. Pure function over (event_type, payload) — no I/O, trivially tested.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_BANNER = "═" * 72
_SECTION = "─" * 72


def _preview(text: Any, limit: int = 200) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def _fmt_planner_step(p: Mapping[str, Any]) -> list[str]:
    tool = p.get("tool") or p.get("decision_code") or "?"
    args = p.get("args")
    head = f"planner step {p.get('step', '?')} → {tool}"
    if isinstance(args, Mapping) and args:
        head += f" args={dict(args)}"
    lines = [head]
    if p.get("decision_code"):
        lines.append(f"    decision: {_preview(p['decision_code'])}")
    actions = p.get("actions")
    if isinstance(actions, Sequence) and not isinstance(actions, str) and len(actions) > 1:
        lines.append(
            "    batch: "
            + ", ".join(
                str(item.get("tool") or "?") for item in actions if isinstance(item, Mapping)
            )
        )
    if p.get("reasoning"):
        lines.append(f"    reasoning: {_preview(p['reasoning'])}")
    if p.get("gap"):
        lines.append(f"    gap: {_preview(p['gap'])}")
    plan = p.get("plan")
    if isinstance(plan, Sequence) and not isinstance(plan, str) and plan:
        glyph = {"open": "☐", "done": "✓", "dropped": "✗"}
        rendered = " ".join(
            f"{glyph.get(str(it.get('status')), '☐')}{it.get('id')}"
            for it in plan
            if isinstance(it, Mapping)
        )
        lines.append(f"    plan: {rendered}")
    if p.get("repair_hint"):
        lines.append(f"    repair_hint: {_preview(p['repair_hint'])}")
    return lines


def _fmt_workspace_step(p: Mapping[str, Any]) -> list[str]:
    return [f"workspace → {p.get('tool') or '?'}"]


def _fmt_tool_result(p: Mapping[str, Any]) -> list[str]:
    head = f"tool  {p.get('tool') or '?'} → {_preview(p.get('summary'), 160)}"
    lines = [head]
    if p.get("error"):
        lines.append(f"    error: {_preview(p['error'])}")
    record_ids = p.get("record_ids")
    if isinstance(record_ids, Sequence) and not isinstance(record_ids, str) and record_ids:
        lines.append(f"    evidence+= {list(record_ids)}")
    return lines


def _fmt_answer(p: Mapping[str, Any]) -> list[str]:
    claims = p.get("claims")
    evidence = p.get("evidence_ids")
    n_claims = len(claims) if isinstance(claims, Sequence) and not isinstance(claims, str) else 0
    ev = list(evidence) if isinstance(evidence, Sequence) and not isinstance(evidence, str) else []
    return [
        f"answer: {_preview(p.get('text'), 240)}",
        f"    claims={n_claims}  evidence={ev}",
    ]


def _fmt_generic(event_type: str, p: Mapping[str, Any]) -> list[str]:
    reason = p.get("stopped_reason") or p.get("status") or p.get("error")
    return [f"{event_type}" + (f"  ({_preview(reason, 80)})" if reason else "")]


def _event_fields(evt: Any) -> tuple[int, str, Mapping[str, Any]]:
    """Accept both ORM AgentEvent objects and plain dicts."""
    if isinstance(evt, Mapping):
        seq = int(evt.get("sequence") or 0)
        etype = str(evt.get("event_type") or "?")
        payload = evt.get("payload")
    else:
        seq = int(getattr(evt, "sequence", 0) or 0)
        etype = str(getattr(evt, "event_type", "?"))
        payload = getattr(evt, "payload", None)
    return seq, etype, payload if isinstance(payload, Mapping) else {}


# event_type → formatter. Lifecycle noise (graph_state per value-tick) is
# folded into the header/terminal, not rendered per-line.
_FORMATTERS = {
    "workspace_step": _fmt_workspace_step,
    "planner_step": _fmt_planner_step,
    "tool_result": _fmt_tool_result,
    "answer": _fmt_answer,
}
_TERMINAL = {"run_completed", "run_interrupted", "run_failed", "interrupt"}
# Rendered only in the header, never as a body line.
_SKIP = {"graph_state", "graph_started", "graph_resumed"}


def render_run_trace(events: Sequence[Any], *, run_id: str | None = None) -> str:
    """Render the durable event chain into a readable decision timeline.

    events: AgentEvent rows (or dicts) in sequence order. Returns "" for an
    empty chain so callers can cheaply skip logging."""
    if not events:
        return ""

    user_text = ""
    header_status = ""
    terminal_lines: list[str] = []
    body: list[str] = []
    step_no = 0

    for evt in events:
        seq, etype, payload = _event_fields(evt)
        if etype == "graph_started":
            user_text = str(payload.get("user_text") or "")
            continue
        if etype in _SKIP:
            if payload.get("status"):
                header_status = str(payload.get("status"))
            continue
        if etype in _TERMINAL:
            terminal_lines.extend(f"    {line}" for line in _fmt_generic(etype, payload))
            if payload.get("status"):
                header_status = str(payload.get("status"))
            continue
        formatter = _FORMATTERS.get(etype)
        rendered = formatter(payload) if formatter else _fmt_generic(etype, payload)
        step_no += 1
        body.append(f"[{step_no}] {rendered[0]}")
        body.extend(rendered[1:])

    head = f"AGENT RUN {run_id or '?'}"
    if header_status:
        head += f"  status={header_status}"
    out = [_BANNER, head]
    if user_text:
        out.append(f"user: {_preview(user_text, 240)}")
    out.append(_SECTION)
    out.extend(body or ["(no decision events)"])
    if terminal_lines:
        out.append(_SECTION)
        out.append("terminal:")
        out.extend(terminal_lines)
    out.append(_BANNER)
    return "\n".join(out)
