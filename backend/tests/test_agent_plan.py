"""Persistent-plan invariants: parse, merge (no-silent-drop), and finish-gate."""

from __future__ import annotations

import pytest

from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.plan import (
    merge_plan,
    open_items,
    parse_plan,
    render_plan_for_planner,
)

NO_EVIDENCE: frozenset[str] = frozenset()


def _plan(*items: dict) -> list[dict]:
    return [dict(it) for it in items]


def test_parse_plan_absent_returns_none() -> None:
    # No `plan` key → carry previous plan unchanged (distinct from an empty list).
    assert parse_plan(None) is None
    assert parse_plan("not a list") is None


def test_parse_plan_normalizes_status_and_id() -> None:
    parsed = parse_plan([{"text": "проверить global notes"}, {"text": "x", "status": "WAT"}])
    assert parsed is not None
    assert parsed[0]["status"] == "open"
    assert parsed[0]["id"]  # slug assigned when model omits id
    assert parsed[1]["status"] == "open"  # unknown status falls back to open


def test_merge_none_incoming_carries_prev_unchanged() -> None:
    prev = _plan({"id": "1", "text": "a", "status": "open"})
    merged, hints = merge_plan(prev, None, evidence_ids=NO_EVIDENCE)
    assert merged == prev
    assert hints == []


def test_merge_reinserts_silently_dropped_open_item() -> None:
    # The core invariant: model omits an open item → code re-inserts it as open
    # and nags. A stated intent cannot evaporate between steps.
    prev = _plan(
        {"id": "1", "text": "прочитать посты", "status": "open"},
        {"id": "2", "text": "проверить global notes", "status": "open"},
    )
    incoming = _plan({"id": "1", "text": "прочитать посты", "status": "open"})
    merged, hints = merge_plan(prev, incoming, evidence_ids=NO_EVIDENCE)
    ids = {it["id"]: it["status"] for it in merged}
    assert ids == {"1": "open", "2": "open"}  # item 2 survived
    assert any("unclosed_plan_item" in h for h in hints)


def test_merge_done_requires_valid_evidence_id() -> None:
    prev = _plan({"id": "1", "text": "прочитать посты", "status": "open"})
    # done citing an id that isn't in records → refused, kept open.
    incoming = _plan({"id": "1", "text": "прочитать посты", "status": "done", "evidence_id": "/ghost/"})
    merged, hints = merge_plan(prev, incoming, evidence_ids=NO_EVIDENCE)
    assert merged[0]["status"] == "open"
    assert any("plan_done_needs_evidence" in h for h in hints)
    # done with a real evidence id → accepted.
    merged2, hints2 = merge_plan(
        prev, incoming, evidence_ids=frozenset({"/ghost/"})
    )
    assert merged2[0]["status"] == "done"
    assert hints2 == []


def test_merge_drop_requires_reason() -> None:
    prev = _plan({"id": "1", "text": "проверить global notes", "status": "open"})
    incoming = _plan({"id": "1", "text": "проверить global notes", "status": "dropped"})
    merged, hints = merge_plan(prev, incoming, evidence_ids=NO_EVIDENCE)
    assert merged[0]["status"] == "open"
    assert any("plan_drop_needs_reason" in h for h in hints)
    # With a reason → accepted.
    incoming2 = _plan(
        {"id": "1", "text": "проверить global notes", "status": "dropped", "reason": "пусто"}
    )
    merged2, _ = merge_plan(prev, incoming2, evidence_ids=NO_EVIDENCE)
    assert merged2[0]["status"] == "dropped"


def test_merge_terminal_item_frozen_cannot_reopen() -> None:
    # A done item cannot be reopened to shed its citation and re-closed.
    prev = _plan({"id": "1", "text": "a", "status": "done", "evidence_id": "/e/"})
    incoming = _plan({"id": "1", "text": "a", "status": "open"})
    merged, _ = merge_plan(prev, incoming, evidence_ids=NO_EVIDENCE)
    assert merged[0]["status"] == "done"
    assert merged[0]["evidence_id"] == "/e/"


def test_open_items_and_render() -> None:
    plan = _plan(
        {"id": "1", "text": "a", "status": "done", "evidence_id": "/e/"},
        {"id": "2", "text": "b", "status": "open"},
    )
    assert [it["id"] for it in open_items(plan)] == ["2"]
    rendered = render_plan_for_planner(plan)
    assert "✓" in rendered and "☐" in rendered and "[2]" in rendered


def _rec() -> EvidenceRecord:
    return EvidenceRecord(
        id="/posts/",
        kind="search_hit",
        source_ref="/posts/",
        content="Посты пользователя: ...",
        citation_path="/posts/",
        citation_title="Посты",
    )


@pytest.mark.asyncio
async def test_verify_gate_blocks_finish_with_open_items() -> None:
    """Explicit FinishRetrieval while a plan item is open → bounced back to the
    planner with a hint, before evidence verification even runs."""
    from app.services.agent.research.graph import research_verify_node

    state = {
        "evidence_records": {"/posts/": _rec().to_dict()},
        "tool_action": {
            "tool": "FinishRetrieval",
            "args": {"status": "ready", "evidence_ids": ["/posts/"]},
        },
        "plan": _plan(
            {"id": "1", "text": "прочитать посты", "status": "done", "evidence_id": "/posts/"},
            {"id": "2", "text": "проверить global notes", "status": "open"},
        ),
        "step_count": 3,
        "max_steps": 10,
        "repair_count": 0,
        "plan_repair_count": 0,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is False
    assert result["plan_repair_count"] == 1
    assert any("unfinished_plan_items" in h for h in result["research_hints"])


@pytest.mark.asyncio
async def test_verify_gate_allows_finish_when_all_items_closed() -> None:
    from app.services.agent.research.graph import research_verify_node

    state = {
        "evidence_records": {"/posts/": _rec().to_dict()},
        "tool_action": {
            "tool": "FinishRetrieval",
            "args": {"status": "ready", "evidence_ids": ["/posts/"]},
        },
        "plan": _plan(
            {"id": "1", "text": "прочитать посты", "status": "done", "evidence_id": "/posts/"},
            {"id": "2", "text": "проверить global notes", "status": "dropped", "reason": "пусто"},
        ),
        "step_count": 3,
        "max_steps": 10,
        "repair_count": 0,
        "plan_repair_count": 0,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is True


@pytest.mark.asyncio
async def test_verify_gate_does_not_block_when_budget_exhausted() -> None:
    """The gate must yield to the step budget — a starved run still terminates."""
    from app.services.agent.research.graph import research_verify_node

    state = {
        "evidence_records": {"/posts/": _rec().to_dict()},
        "tool_action": {
            "tool": "FinishRetrieval",
            "args": {"status": "ready", "evidence_ids": ["/posts/"]},
        },
        "plan": _plan({"id": "2", "text": "проверить global notes", "status": "open"}),
        "step_count": 10,
        "max_steps": 10,
        "repair_count": 0,
        "plan_repair_count": 0,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is True


@pytest.mark.asyncio
async def test_verify_gate_yields_after_repair_cap() -> None:
    from app.services.agent.research.graph import MAX_PLAN_REPAIRS, research_verify_node

    state = {
        "evidence_records": {"/posts/": _rec().to_dict()},
        "tool_action": {
            "tool": "FinishRetrieval",
            "args": {"status": "ready", "evidence_ids": ["/posts/"]},
        },
        "plan": _plan({"id": "2", "text": "проверить global notes", "status": "open"}),
        "step_count": 3,
        "max_steps": 10,
        "repair_count": 0,
        "plan_repair_count": MAX_PLAN_REPAIRS,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is True
