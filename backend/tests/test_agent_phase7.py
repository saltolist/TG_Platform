"""Phase-7 consolidated tools, resume observability and replay contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_tool_contract_normalizes_batch_mode_and_typed_errors() -> None:
    from app.services.agent.runtime.tool_contracts import ToolBatchRequest, typed_tool_error

    request = ToolBatchRequest.from_mapping({"tool": "OpenObjects", "ids": ["note:n1"], "mode": "bad"})
    assert request.tool == "OpenObjects"
    assert request.items == ({"ref": "note:n1"},)
    assert request.mode == "compact"
    error = typed_tool_error("post_not_open", "open first")
    assert error is not None
    assert error.code == "precondition_failed"
    assert error.next_action == "OpenObjects"


@pytest.mark.asyncio
async def test_open_objects_batch_returns_typed_per_item_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.agent.research.graph import ToolAction, _execute_tool
    from app.services.ai.rag_tools import ToolOutcome

    async def fake_execute(_state, action):
        if action.args.get("post_id") == "missing":
            return ToolOutcome(summary="missing", error="not_found")
        return ToolOutcome(summary="opened", hits=({"ref": "post:ok"},), result_count=1)

    monkeypatch.setattr("app.services.agent.research.graph._execute_tool_impl", fake_execute)
    outcome = await _execute_tool(
        object(),
        ToolAction(tool="OpenObjects", args={"ids": ["post:ok", "post:missing"], "response_mode": "detailed"}),
    )
    assert outcome.response_mode == "detailed"
    assert outcome.result_count == 1
    assert outcome.items[1]["error"]["code"] == "not_found"
    assert outcome.items[1]["error"]["next_action"] == "resolve_objects"


def test_trace_replay_comparison_preserves_evidence_and_reports_latency() -> None:
    from app.services.agent.runtime.replay import compare_traces, render_comparison_report

    old = [
        {"event_type": "planner_step", "payload": {}},
        {"event_type": "tool_result", "payload": {"tool": "OpenNote", "record_ids": ["note:n1"]}},
        {"event_type": "run_metrics", "payload": {"duration_ms": 1200, "phase_timings_ms": {"discovery": 900}}},
        {"event_type": "run_completed", "payload": {"status": "completed"}},
    ]
    new = [
        {"event_type": "tool_result", "payload": {"tool": "OpenObjects", "record_ids": ["note:n1"], "cache_hit": False}},
        {"event_type": "run_metrics", "payload": {"duration_ms": 700, "phase_timings_ms": {"deep_read": 500}, "execution_mode": "fast", "worker_warm": True}},
        {"event_type": "run_completed", "payload": {"status": "completed"}},
    ]
    comparison = compare_traces(old, new)
    assert comparison["delta"]["quality_preserved"] is True
    assert comparison["delta"]["duration_reduction"] > 0
    assert "quality_preserved=True" in render_comparison_report(comparison)


def test_hitl_resume_continuity_restores_targets_and_evidence() -> None:
    from app.services.agent.runtime.executor import _restore_resume_continuity

    before = {
        "turn_contract": {"revision": 4},
        "target_contract": {"targets": [{"id": "note-1"}]},
        "evidence_ids": ["note:note-1@rev:4"],
        "evidence_records": {"note:note-1@rev:4": {"content": "source"}},
    }
    restored = _restore_resume_continuity(before, {"status": "completed", "answer_text": "done"})
    assert restored["turn_contract"] == before["turn_contract"]
    assert restored["target_contract"] == before["target_contract"]
    assert restored["evidence_ids"] == before["evidence_ids"]


def test_run_metrics_and_trace_split_mode_warm_state_and_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.services.agent.runtime.executor import _llm_metrics_payload
    from app.services.agent.runtime.trace import render_run_trace

    monkeypatch.setattr(
        "app.tasks.async_runtime.runtime_status",
        lambda: {
            "ready": True,
            "status": "ready",
            "worker_init_ms": 24.0,
            "checkpointer_init_ms": 3.0,
            "graph_compile_ms": 2.0,
        },
    )
    ctx = SimpleNamespace(
        llm_metrics=[],
        turn_contract={"execution_mode": "compact"},
        phase_timings={"queue_wait": 12.0, "bootstrap": 8.0, "deep_read": 40.0, "answer": 20.0},
    )
    payload = _llm_metrics_payload(ctx, duration_ms=80.0)
    assert payload["schema"] == "workspace.run-metrics/v1"
    assert payload["execution_mode"] == "compact"
    assert payload["worker_warm"] is True
    assert payload["time_to_final_ms"] == 92.0
    assert payload["checkpointer_init_ms"] == 3.0
    assert payload["graph_compile_ms"] == 2.0
    body = render_run_trace([{"sequence": 1, "event_type": "run_metrics", "payload": payload}])
    assert "mode=compact worker=warm" in body
    assert "deep_read=40.0ms" in body


def test_phase7_fixture_report_passes() -> None:
    from scripts.agent_phase7_trace_report import build_report, check_report

    fixture = Path(__file__).parent / "fixtures/agent_phase7/v1/scenarios.json"
    report = build_report(fixture)
    assert report["quality_floor"] == 1.0
    assert report["tool_call_p50_reduction"] > 0.2
    assert check_report(report, fixture) == []
