"""Inspect one formal live canary decision without emitting source or user content."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models import AgentEvent, AgentRun
from app.db.session import async_session_factory


DEFAULT_MANIFEST = (
    BACKEND_ROOT / "tests/fixtures/agent_unified_phase6/v6/formal_canary_manifest.json"
)
POSITION_ERRORS = {
    "wrong_cardinality",
    "unknown_position",
    "duplicate_position",
    "missing_position",
    "out_of_range_position",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def _materialized_candidate_refs(
    items: list[Mapping[str, Any]], candidates: list[Mapping[str, Any]]
) -> set[str]:
    refs: set[str] = set()
    ref_by_path = {
        str(candidate.get("citation_path") or ""): str(candidate.get("ref") or "")
        for candidate in candidates
        if candidate.get("citation_path") and candidate.get("ref")
    }
    for item in items:
        provenance = item.get("provenance") or {}
        selection = provenance.get("selection") or {}
        source_ref = str(item.get("source_ref") or provenance.get("source_ref") or "")
        if source_ref in ref_by_path:
            refs.add(ref_by_path[source_ref])
        for parent in (selection.get("parent"), provenance.get("parent")):
            if isinstance(parent, Mapping) and parent.get("ref"):
                refs.add(str(parent["ref"]))
    return refs


async def inspect(sequence: int, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario = manifest["scenarios"][sequence - 1]
    async with async_session_factory() as session:
        runs = (
            await session.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(200))
        ).scalars().all()
        run = next(
            item
            for item in runs
            if _digest((item.snapshot or {}).get("user_text")) == scenario["query_digest"]
        )
        events = (
            await session.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id)
                .order_by(AgentEvent.sequence)
            )
        ).scalars().all()

    trace = next(
        item.payload for item in reversed(events) if item.event_type == "unified_rollout_trace"
    )
    selector = trace.get("selector") or {}
    assessments = selector.get("assessments") or []
    selected = {
        str(item.get("ref") or "")
        for item in assessments
        if item.get("relevance") != "irrelevant"
    }
    expected = set(scenario.get("expected_refs") or [])
    supporting = set(scenario.get("allowed_supporting_refs") or [])
    critical = set(scenario.get("critical_refs") or [])
    frozen_irrelevant = set(scenario.get("irrelevant_refs") or [])
    final_items = (trace.get("final_pack") or {}).get("items") or []
    candidates = (run.snapshot or {}).get("candidate_envelopes") or []
    materialized = _materialized_candidate_refs(final_items, candidates)
    provider = selector.get("provider_observability") or []
    validation_errors = [
        str(code)
        for event in events
        if event.event_type == "planner_step"
        for code in event.payload.get("validation_error_codes") or []
    ]
    owner_verified = all(
        (item.get("provenance") or {}).get("owner_verified") is True for item in final_items
    )
    status_verified = all(
        (item.get("provenance") or {}).get("status_verified") is True for item in final_items
    )
    checks = {
        "completed": (
            run.status == "completed"
            and (trace.get("lifecycle") or {}).get("status") == "completed"
        ),
        "critical_recall": critical <= selected,
        "no_unexpected_selection": not (selected - expected - supporting),
        "no_frozen_irrelevant": not (selected & frozen_irrelevant),
        "critical_materialized": critical <= materialized,
        "first_attempt_valid": (
            selector.get("attempts") == 1
            and len(provider) == 1
            and all(
                item.get("schema_result") == "valid" and not item.get("retry")
                for item in provider
            )
        ),
        "no_validation_errors": not validation_errors,
        "no_position_errors": not (set(validation_errors) & POSITION_ERRORS),
        "cards_llm_v9_fresh": all(
            item.get("card_origin") == "llm"
            and item.get("selector_summary_version") == 9
            and item.get("selector_summary_fresh") is True
            for item in candidates
        ),
        "provenance_verified": owner_verified and status_verified,
    }
    observability = provider[0] if provider else {}
    return {
        "sequence": sequence,
        "scenario_id": scenario["scenario_id"],
        "run_digest": _digest(run.id)[:16],
        "created_at": run.created_at.isoformat(),
        "candidate_count": len(candidates),
        "selected_refs": sorted(selected),
        "materialized_candidate_refs": sorted(materialized),
        "unexpected_refs": sorted(selected - expected - supporting),
        "missed_critical_refs": sorted(critical - selected),
        "selected_irrelevant_refs": sorted(selected & frozen_irrelevant),
        "selector_attempts": selector.get("attempts"),
        "schema_result": observability.get("schema_result"),
        "provider_total_tokens": observability.get("total_tokens"),
        "provider_duration_ms": observability.get("duration_ms"),
        "validation_error_codes": validation_errors,
        "checks": checks,
        "pass": all(checks.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence", type=int, required=True, choices=range(1, 21))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = asyncio.run(inspect(args.sequence, args.manifest))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
