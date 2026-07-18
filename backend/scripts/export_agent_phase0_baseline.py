"""Export a read-only, anonymized Workspace Agent phase-0 trace fixture.

The exporter never stores raw user, answer, reasoning, summary, query, chat ID
or run ID values. The one chat explicitly named by the phase plan is retained
as a provenance label; its content remains redacted like every other trace.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.models import AgentEvent, AgentRun
from app.db.session import async_session_factory
from app.services.agent.runtime.baseline import SCHEMA_VERSION
from app.services.agent.runtime.graders import grade_trace

PROBLEM_CHAT_ID = "b9a1ff2d-4fae-47f3-9217-b0b9423c60be"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "tests/fixtures/agent_baseline/v1/scenarios.json"
TEXT_KEYS = {
    "user_text",
    "text",
    "reason",
    "reasoning",
    "observations",
    "gap",
    "summary",
    "repair_hint",
    "query",
    "search_query",
    "prompt",
    "answer_requires",
    "signature",
    "error",
}
SAFE_STRING_KEYS = {
    "tool",
    "status",
    "type",
    "stopped_reason",
    "phase",
    "token_method",
    "provider",
    "model",
}


def _fingerprint(value: Any) -> dict[str, Any]:
    text = str(value or "")
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "chars": len(text),
    }


def _opaque(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


class RefTokenizer:
    def __init__(self) -> None:
        self._refs: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def token(self, value: Any, *, hint: str = "object") -> str:
        raw = str(value)
        if raw in self._refs:
            return self._refs[raw]
        kind = hint.removesuffix("_id").removesuffix("_ids") or "object"
        if raw.startswith("/note/") or hint == "note_id":
            kind = "note"
        elif raw.startswith("/post/") or hint == "post_id":
            kind = "post"
        elif "/attachment/" in raw or hint in {"file_id", "attachment_id"}:
            kind = "attachment"
        elif raw.startswith("/"):
            kind = "evidence"
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"{kind}:{self._counts[kind]}"
        self._refs[raw] = token
        return token


def _sanitize(value: Any, *, key: str, refs: RefTokenizer) -> Any:
    if key in TEXT_KEYS:
        return _fingerprint(value)
    if (
        key in {"evidence_ids", "record_ids", "new_record_ids"}
        and isinstance(value, Sequence)
        and not isinstance(value, str)
    ):
        return [refs.token(item, hint="evidence_id") for item in value]
    if key.endswith("_id") and value not in {None, ""}:
        return refs.token(value, hint=key)
    if isinstance(value, Mapping):
        return {str(child_key): _sanitize(child, key=str(child_key), refs=refs) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize(child, key=key, refs=refs) for child in value]
    if isinstance(value, str) and key not in SAFE_STRING_KEYS:
        return _fingerprint(value)
    return value


def _terminal_event_type(status: str) -> str:
    if status == "failed":
        return "run_failed"
    if status == "interrupted":
        return "run_interrupted"
    if status == "cancelled":
        return "run_cancelled"
    return "run_completed"


def _sanitize_events(run: AgentRun, events: Sequence[AgentEvent]) -> list[dict[str, Any]]:
    refs = RefTokenizer()
    trace: list[dict[str, Any]] = []
    first_partial_at: int | None = None
    final_answer: AgentEvent | None = None
    allowed = {
        "run_started",
        "graph_started",
        "workspace_step",
        "planner_step",
        "tool_result",
        "interrupt",
        "run_metrics",
    }
    for event in events:
        at_ms = max(0, round((event.created_at - run.created_at).total_seconds() * 1000))
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if event.event_type == "answer":
            if payload.get("partial"):
                first_partial_at = at_ms if first_partial_at is None else first_partial_at
            else:
                final_answer = event
            continue
        if event.event_type not in allowed and not event.event_type.startswith("run_"):
            continue
        safe_payload = _sanitize(payload, key="payload", refs=refs)
        if event.event_type.startswith("run_"):
            safe_payload = {
                key: value
                for key, value in safe_payload.items()
                if key in {"status", "stopped_reason", "error"}
            }
        trace.append({"at_ms": at_ms, "event_type": event.event_type, "payload": safe_payload})

    if first_partial_at is not None:
        trace.append({"at_ms": first_partial_at, "event_type": "answer_started", "payload": {}})
    if final_answer is not None:
        payload = final_answer.payload if isinstance(final_answer.payload, Mapping) else {}
        safe = {
            "text": json.dumps(_fingerprint(payload.get("text")), sort_keys=True),
            "claims": [],
            "evidence_ids": _sanitize(payload.get("evidence_ids") or [], key="evidence_ids", refs=refs),
        }
        for claim in payload.get("claims") or []:
            if not isinstance(claim, Mapping):
                safe["claims"].append("<invalid-claim>")
                continue
            safe["claims"].append(
                {
                    "text": json.dumps(_fingerprint(claim.get("text")), sort_keys=True),
                    "evidence_ids": _sanitize(claim.get("evidence_ids") or [], key="evidence_ids", refs=refs),
                }
            )
        at_ms = max(0, round((final_answer.created_at - run.created_at).total_seconds() * 1000))
        trace.append({"at_ms": at_ms, "event_type": "answer", "payload": safe})

    terminal_type = _terminal_event_type(run.status)
    if not any(item["event_type"] == terminal_type for item in trace) and run.status != "running":
        terminal_at = run.completed_at or run.updated_at
        trace.append(
            {
                "at_ms": max(0, round((terminal_at - run.created_at).total_seconds() * 1000)),
                "event_type": terminal_type,
                "payload": {"status": run.status},
            }
        )
    trace.sort(key=lambda item: (item["at_ms"], item["event_type"] == "answer"))
    return trace


def _phase_metrics(run: AgentRun, trace: Sequence[Mapping[str, Any]]) -> dict[str, int | None]:
    def first(event_type: str) -> int | None:
        return next((int(item["at_ms"]) for item in trace if item["event_type"] == event_type), None)

    graph_started = first("graph_started")
    workspace = first("workspace_step")
    answer = first("answer_started")
    if answer is None:
        answer = first("answer")
    terminal_types = {"run_completed", "run_failed", "run_interrupted", "run_cancelled"}
    terminal_values = [
        int(item["at_ms"])
        for item in trace
        if str(item["event_type"]) in terminal_types
    ]
    terminal = max(terminal_values) if terminal_values else None
    research_end = answer if answer is not None else terminal
    return {
        "startup": graph_started if graph_started is not None else None,
        "bootstrap": (
            max(0, workspace - graph_started)
            if graph_started is not None and workspace is not None
            else None
        ),
        "research": max(0, research_end - workspace) if workspace is not None and research_end is not None else None,
        "answer": max(0, terminal - answer) if answer is not None and terminal is not None else None,
    }


def _select_evenly(runs: Sequence[AgentRun], count: int) -> list[AgentRun]:
    if count <= 0 or not runs:
        return []
    if len(runs) <= count:
        return list(runs)
    indexes = {round(index * (len(runs) - 1) / (count - 1)) for index in range(count)} if count > 1 else {0}
    return [runs[index] for index in sorted(indexes)]


def _select_runs(runs: Sequence[AgentRun]) -> list[tuple[AgentRun, str]]:
    ordered = sorted(runs, key=lambda run: run.created_at)
    problem = [run for run in ordered if run.chat_id == PROBLEM_CHAT_ID]
    selected: list[tuple[AgentRun, str]] = [
        (run, f"problem_chat_turn_{index + 1}")
        for index, run in enumerate(problem)
    ]
    selected_ids = {run.id for run, _ in selected}

    targets = {"failed": 7, "interrupted": 7, "cancelled": 3, "running": 2}
    for status, count in targets.items():
        candidates = [run for run in ordered if run.status == status and run.id not in selected_ids]
        for run in _select_evenly(candidates, count):
            selected.append((run, f"status_{status}"))
            selected_ids.add(run.id)

    completed = [
        run
        for run in ordered
        if run.status == "completed" and run.id not in selected_ids and run.completed_at is not None
    ]
    completed.sort(key=lambda run: (run.completed_at - run.created_at).total_seconds())
    for run in _select_evenly(completed, max(0, 32 - len(selected))):
        selected.append((run, "completed_latency_quantile"))
    if len(selected) != 32:
        raise RuntimeError(f"expected 32 selected runs, got {len(selected)}")
    return selected


def _scenario(run: AgentRun, events: Sequence[AgentEvent], *, reason: str, index: int) -> dict[str, Any]:
    trace = _sanitize_events(run, events)
    metrics_event = next(
        (item["payload"] for item in reversed(trace) if item["event_type"] == "run_metrics"),
        None,
    )
    report = grade_trace(trace)
    failures = [result.name for result in report.failures]
    if run.chat_id == PROBLEM_CHAT_ID and reason == "problem_chat_turn_1":
        failures.extend(["cross_loop_retry", "embedding_cold_start"])
    if run.status == "running":
        failures.append("non_terminal_run")
    if not isinstance(metrics_event, Mapping):
        failures.append("token_telemetry_missing")

    final_evidence: list[str] = []
    for item in trace:
        if item["event_type"] == "answer":
            final_evidence = list(item["payload"].get("evidence_ids") or [])
    planner_calls = sum(item["event_type"] == "planner_step" for item in trace)
    tool_calls = sum(item["event_type"] == "tool_result" for item in trace)
    has_answer = any(item["event_type"] == "answer" for item in trace)
    duration_ms = round(((run.completed_at or run.updated_at) - run.created_at).total_seconds() * 1000)
    turn_number = problem_turn = None
    if run.chat_id == PROBLEM_CHAT_ID and reason.startswith("problem_chat_turn_"):
        problem_turn = int(reason.rsplit("_", 1)[1])
        turn_number = problem_turn
    scenario_id = (
        f"b9a1ff2d-turn-{problem_turn}"
        if problem_turn is not None
        else f"prod-{index:02d}-{_opaque('trace', run.id).split(':')[1]}"
    )
    return {
        "id": scenario_id,
        "split": "golden" if index <= 24 else "held_out",
        "provenance": {
            "kind": "anonymized_production_trace",
            "source_chat_ref": (
                PROBLEM_CHAT_ID
                if run.chat_id == PROBLEM_CHAT_ID
                else _opaque("chat", run.chat_id or "none")
            ),
            "source_run_ref": _opaque("run", run.id),
            "sample_reason": reason,
            "turn": turn_number,
        },
        "temperature": "cold" if problem_turn == 1 else "warm" if problem_turn in {2, 3} else "unknown",
        "known_failures": sorted(set(failures)),
        "trace": trace,
        "expected": {
            "terminal_status": run.status,
            "target_refs": final_evidence if problem_turn is not None else [],
            "target_annotation": (
                "production_review"
                if problem_turn in {1, 3}
                else "not_applicable"
                if problem_turn == 2
                else "not_annotated"
            ),
            "current_grader_results": {result.name: result.passed for result in report.results},
            "regression_expectations": {
                failure: {"current": True, "desired": False}
                for failure in sorted(set(failures))
            },
            "quality_floor": {
                "valid_finish_evidence_ids": True,
                "output_event_schema": True,
            },
        },
        "metrics": {
            "duration_ms": duration_ms,
            "planner_calls": planner_calls,
            "tool_calls": tool_calls,
            "llm_calls_inferred": (
                int(metrics_event.get("llm_calls") or 0)
                if isinstance(metrics_event, Mapping)
                else int(any(item["event_type"] == "workspace_step" for item in trace))
                + planner_calls
                + int(has_answer)
            ),
            "tokens": {
                "prompt": int(metrics_event.get("prompt_tokens") or 0) if isinstance(metrics_event, Mapping) else None,
                "completion": (
                    int(metrics_event.get("completion_tokens") or 0)
                    if isinstance(metrics_event, Mapping)
                    else None
                ),
                "total": int(metrics_event.get("total_tokens") or 0) if isinstance(metrics_event, Mapping) else None,
                "availability": "estimated" if isinstance(metrics_event, Mapping) else "not_recorded_by_agent_runtime",
            },
            "phase_ms": _phase_metrics(run, trace),
            "tool_trajectory": [
                str(item["payload"].get("tool") or "")
                for item in trace
                if item["event_type"] == "planner_step"
            ],
        },
    }


async def export(output: Path) -> None:
    async with async_session_factory() as session:
        runs = list((await session.scalars(select(AgentRun))).all())
        selected = _select_runs(runs)
        scenarios: list[dict[str, Any]] = []
        for index, (run, reason) in enumerate(selected, start=1):
            events = list(
                (
                    await session.scalars(
                        select(AgentEvent)
                        .where(AgentEvent.run_id == run.id)
                        .order_by(AgentEvent.sequence.asc())
                    )
                ).all()
            )
            scenarios.append(_scenario(run, events, reason=reason, index=index))

    captured_at = max(run.updated_at for run, _reason in selected).astimezone(timezone.utc)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at.isoformat(),
        "source": {
            "kind": "local_production_like_database",
            "selection": "3 requested chat turns + 29 status/latency-stratified runs",
            "content_policy": "raw text and non-requested identifiers removed",
        },
        "quality_floor": {
            "description": "Formal invariants that later phases may not regress",
            "required_graders": ["valid_finish_evidence_ids", "output_event_schema"],
            "known_regressions": ["no_duplicate_tool_calls", "no_finish_loops"],
            "minimum_pass_counts": {
                "no_duplicate_tool_calls": 30,
                "valid_finish_evidence_ids": 31,
                "no_finish_loops": 27,
                "output_event_schema": 32,
            },
            "minimum_annotated_target_accuracy": 1.0,
        },
        "scenarios": scenarios,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(scenarios)} anonymized scenarios to {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    asyncio.run(export(args.output))


if __name__ == "__main__":
    main()
