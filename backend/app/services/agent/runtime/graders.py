"""Deterministic groundedness / trajectory graders (agent-runtime-sprints Фаза 0).

These are pure functions over a run's final ``AgentGraphState`` (or any dict of
the same shape). They encode the anti-hallucination invariants enforced by the
runtime so that regressions are caught mechanically — no LLM judge, no wording
assertions. The same functions power unit tests now and can grade production
traces later (Фаза 6/7).

Each grader returns a ``GraderResult`` with a boolean ``passed`` and a short
human-readable ``reason``; ``ok`` on a batch is the AND of all results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.agent.runtime.result_quality import (
    build_style_profile,
    validate_result_contract,
)


@dataclass(frozen=True)
class GraderResult:
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class GraderReport:
    results: list[GraderResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[GraderResult]:
        return [r for r in self.results if not r.passed]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _evidence_keys(state: Mapping[str, Any]) -> set[str]:
    """All evidence IDs the run legitimately has (records ∪ packed ids)."""
    records = state.get("evidence_records") or {}
    ids = state.get("evidence_ids") or []
    return {str(k) for k in records} | {str(i) for i in ids}


def _claim_cited_ids(state: Mapping[str, Any]) -> list[str]:
    cited: list[str] = []
    for claim in state.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for eid in claim.get("evidence_ids") or []:
            cited.append(str(eid))
    return cited


def _has_factual_claim(state: Mapping[str, Any]) -> bool:
    """A factual claim = a claim carrying at least one evidence_id, or any
    non-empty claim text on a run that produced no evidence."""
    for claim in state.get("claims") or []:
        if isinstance(claim, dict) and (claim.get("evidence_ids") or str(claim.get("text") or "").strip()):
            return True
    return False


# --------------------------------------------------------------------------- #
# Graders
# --------------------------------------------------------------------------- #


def grade_claims_subset_evidence(state: Mapping[str, Any]) -> GraderResult:
    """Every evidence_id cited by an answer claim must exist in the run's
    evidence. Catches fabricated citations (agent-runtime-sprints §1.2/DoD #1)."""
    keys = _evidence_keys(state)
    cited = _claim_cited_ids(state)
    dangling = [c for c in cited if c not in keys]
    if dangling:
        return GraderResult(
            name="claims_subset_evidence",
            passed=False,
            reason=f"claims cite non-existent evidence: {dangling}",
        )
    return GraderResult(
        name="claims_subset_evidence",
        passed=True,
        reason=f"{len(cited)} cited ids all present",
    )


def grade_empty_pack_no_claim(state: Mapping[str, Any]) -> GraderResult:
    """Empty pack ⇒ no workspace-factual claim.

    The final model may still answer from the user's message, dialog and
    general knowledge. An empty retrieval result is context, not a terminal
    refusal; only evidence-backed claim objects are forbidden without evidence.
    """
    rag = str(state.get("rag_context") or "").strip()
    ids = state.get("evidence_ids") or []
    if rag or ids:
        return GraderResult(
            name="empty_pack_no_claim",
            passed=True,
            reason="pack non-empty — grader not applicable",
        )
    if _has_factual_claim(state):
        return GraderResult(
            name="empty_pack_no_claim",
            passed=False,
            reason="empty pack but answer emitted a workspace-factual claim",
        )
    return GraderResult(
        name="empty_pack_no_claim",
        passed=True,
        reason="empty pack → no workspace-factual claims",
    )


_IMAGE_AFFIRM_MARKERS = (
    "изображени",
    "картинк",
    "фотограф",
    "иллюстрац",
    "на ней изображ",
    "на картинке",
    "на изображении",
)
_IMAGE_NEGATION_MARKERS = ("нет изображени", "нет картинок", "не приложен", "отсутству")


def grade_image_claim_backed(state: Mapping[str, Any]) -> GraderResult:
    """No affirming an image the evidence doesn't carry (chat 9f3d5fdf/8caf07f4).

    Image existence is structural: a hydrated attachment produces an evidence
    record with a citation path containing '/attachment/'. The old approach
    scanned rag_context text for "image/" — wrong: vision captions are plain
    prose and never contain "image/", so the grader falsely reported "no image"
    even for valid vision evidence (chat 8caf07f4). Record paths are the
    authoritative signal.
    """
    evidence_records = state.get("evidence_records") or {}
    has_attachment = any("/attachment/" in str(rid) for rid in evidence_records)
    if not has_attachment:
        # Fallback for runs that don't populate evidence_records (unit tests,
        # legacy paths): keep the old rag_context text check.
        rag = str(state.get("rag_context") or "").lower()
        has_attachment = "image/" in rag
    if has_attachment:
        return GraderResult(
            name="image_claim_backed",
            passed=True,
            reason="pack carries image attachment(s) — grader not applicable",
        )
    answer = str(state.get("answer_text") or "").lower()
    if any(neg in answer for neg in _IMAGE_NEGATION_MARKERS):
        return GraderResult(
            name="image_claim_backed",
            passed=True,
            reason="answer denies images, does not affirm",
        )
    if any(marker in answer for marker in _IMAGE_AFFIRM_MARKERS):
        return GraderResult(
            name="image_claim_backed",
            passed=False,
            reason="answer affirms an image but pack has no image attachment",
        )
    return GraderResult(
        name="image_claim_backed",
        passed=True,
        reason="answer makes no image affirmation",
    )


def grade_exact_claims_not_card_only(state: Mapping[str, Any]) -> GraderResult:
    """Consume fidelity-aware semantic grader labels when a run provides them."""

    semantic_result = state.get("fidelity_grader") or {}
    if isinstance(semantic_result, Mapping) and semantic_result.get("exact_claim_on_card"):
        return GraderResult(
            name="exact_claims_not_card_only",
            passed=False,
            reason="semantic grader found an exact/content claim backed only by semantic_card",
        )
    card_ids = {
        str(item.get("id") or "")
        for item in (state.get("evidence_pack") or {}).get("items") or ()
        if isinstance(item, Mapping) and item.get("fidelity") == "semantic_card"
    }
    violations: list[str] = []
    for claim in state.get("claims") or ():
        if not isinstance(claim, Mapping):
            continue
        scope = str(claim.get("claim_scope") or "")
        cited = {str(item) for item in claim.get("evidence_ids") or ()}
        if scope in {"exact", "content", "quote", "analytics"} and cited and cited <= card_ids:
            violations.append(str(claim.get("text") or "")[:80])
    return GraderResult(
        name="exact_claims_not_card_only",
        passed=not violations,
        reason=(
            f"card-only exact claims: {violations}"
            if violations
            else "no semantically labelled exact claim relies only on cards"
        ),
    )


def grade_context_refs_subset_supplied(state: Mapping[str, Any]) -> GraderResult:
    """User-facing refs must come from verified context or authoritative targets."""
    from app.services.agent.runtime.message_context import supplied_object_refs

    manifest = state.get("message_context_manifest") or {}
    refs = {
        str(item.get("ref") or "")
        for item in manifest.get("context_refs") or ()
        if isinstance(item, Mapping)
    }
    supplied = supplied_object_refs(state.get("evidence_pack") or {})
    target_contract = state.get("target_contract") or (state.get("turn_contract") or {}).get("target_contract") or {}
    supplied.update(
        f"{item.get('kind')}:{item.get('id')}"
        for item in target_contract.get("targets") or ()
        if isinstance(item, Mapping) and item.get("kind") in {"post", "note"} and item.get("id")
    )
    dangling = sorted(refs - supplied)
    return GraderResult(
        name="context_refs_subset_supplied",
        passed=not dangling,
        reason=f"unsupported context refs: {dangling}" if dangling else "all context refs were supplied",
    )


def grade_referent_targets_bounded(state: Mapping[str, Any]) -> GraderResult:
    contract = state.get("target_contract") or (state.get("turn_contract") or {}).get("target_contract") or {}
    resolution = contract.get("referent_resolution") or {}
    resolved = {
        str(item)
        for reference in resolution.get("references") or ()
        if isinstance(reference, Mapping)
        for item in reference.get("target_ids") or ()
    }
    targets = {
        f"{item.get('kind')}:{item.get('id')}"
        for item in contract.get("targets") or ()
        if isinstance(item, Mapping) and item.get("kind") and item.get("id")
    }
    invented = sorted(resolved - targets)
    return GraderResult(
        name="referent_targets_bounded",
        passed=not invented,
        reason=f"resolution introduced targets outside contract: {invented}" if invented else "resolved targets are contract-bound",
    )


def grade_complete_catalog_coverage(state: Mapping[str, Any]) -> GraderResult:
    contract = state.get("turn_contract") or {}
    coverage = state.get("coverage_targets_by_source") or {}
    sufficiency = state.get("sufficiency") or {}
    missing: list[str] = []
    for source in contract.get("source_requirements") or ():
        if not isinstance(source, Mapping) or not source.get("required") or source.get("coverage") != "complete":
            continue
        source_id = str(source.get("source_id") or "")
        if source_id not in coverage:
            missing.append(f"{source_id}:catalog")
    if sufficiency.get("status") == "ready":
        missing.extend(
            str(item) for item in sufficiency.get("open_requirements") or ()
            if str(item).startswith("coverage:")
        )
    return GraderResult(
        name="complete_catalog_coverage",
        passed=not missing,
        reason=f"incomplete authoritative catalogs: {missing}" if missing else "complete sources are catalog-bound",
    )


def grade_trajectory_includes(
    state: Mapping[str, Any],
    *,
    must_call: Sequence[str],
) -> GraderResult:
    """Trajectory superset check: the research transcript must show every tool
    in ``must_call`` (LangSmith trajectory `superset`). Used e.g. to assert a
    notes-content question actually reached OpenNote (DoD #3)."""
    transcript = " \n".join(str(line) for line in (state.get("research_transcript") or []))
    missing = [tool for tool in must_call if tool not in transcript]
    if missing:
        return GraderResult(
            name="trajectory_includes",
            passed=False,
            reason=f"trajectory missing required tools: {missing}",
        )
    return GraderResult(
        name="trajectory_includes",
        passed=True,
        reason=f"all required tools called: {list(must_call)}",
    )


def grade_result_contract(state: Mapping[str, Any]) -> GraderResult:
    """Target corpus and requested output shape must survive to the answer."""
    contract = dict(state.get("turn_contract") or {})
    if not contract:
        return GraderResult(
            name="result_contract",
            passed=True,
            reason="no turn contract — grader not applicable",
        )
    evidence_ids = [str(item) for item in (state.get("evidence_ids") or [])]
    records = dict(state.get("evidence_records") or {})
    corpus = str(contract.get("corpus") or "workspace")
    if corpus == "feed_posts":
        out_of_scope = [eid for eid in evidence_ids if "/note/" in eid or eid.startswith("/global/")]
        has_post = any(
            str((records.get(eid) or {}).get("kind") or "") == "post_text"
            for eid in evidence_ids
        )
        if out_of_scope or not has_post:
            return GraderResult(
                name="result_contract",
                passed=False,
                reason=f"feed_posts corpus violation: out_of_scope={out_of_scope} has_post={has_post}",
            )
    if corpus == "exact_note":
        note_id = str((contract.get("target") or {}).get("id") or "")
        wrong = [eid for eid in evidence_ids if note_id and f"/{note_id}/" not in eid]
        if wrong or not any(note_id and f"/{note_id}/" in eid for eid in evidence_ids):
            return GraderResult(
                name="result_contract",
                passed=False,
                reason=f"exact_note corpus violation: target={note_id!r} wrong={wrong}",
            )
    style_profile = build_style_profile(records)
    issues = validate_result_contract(
        str(state.get("answer_text") or ""),
        contract,
        style_profile=style_profile,
    )
    if issues:
        return GraderResult(
            name="result_contract",
            passed=False,
            reason=f"output contract violations: {issues}",
        )
    return GraderResult(
        name="result_contract",
        passed=True,
        reason="target corpus and output requirements satisfied",
    )


def grade_run(
    state: Mapping[str, Any],
    *,
    must_call: Sequence[str] | None = None,
) -> GraderReport:
    """Run the always-on deterministic graders over a final run state.

    ``must_call`` is optional per-scenario trajectory expectation.
    """
    results = [
        grade_claims_subset_evidence(state),
        grade_empty_pack_no_claim(state),
        grade_image_claim_backed(state),
        grade_exact_claims_not_card_only(state),
        grade_context_refs_subset_supplied(state),
        grade_referent_targets_bounded(state),
        grade_complete_catalog_coverage(state),
        grade_result_contract(state),
    ]
    if must_call:
        results.append(grade_trajectory_includes(state, must_call=must_call))
    return GraderReport(results=results)


# --------------------------------------------------------------------------- #
# Durable trace graders (Workspace Agent performance plan, phase 0)
# --------------------------------------------------------------------------- #


def _trace_event_fields(event: Any) -> tuple[str, Mapping[str, Any]]:
    if isinstance(event, Mapping):
        event_type = str(event.get("event_type") or event.get("type") or "")
        payload = event.get("payload")
    else:
        event_type = str(getattr(event, "event_type", "") or "")
        payload = getattr(event, "payload", None)
    return event_type, payload if isinstance(payload, Mapping) else {}


def _planner_tool_calls(events: Sequence[Any]) -> list[tuple[str, Mapping[str, Any]]]:
    calls: list[tuple[str, Mapping[str, Any]]] = []
    for event in events:
        event_type, payload = _trace_event_fields(event)
        if event_type != "planner_step":
            continue
        tool = str(payload.get("tool") or "")
        args = payload.get("args")
        calls.append((tool, args if isinstance(args, Mapping) else {}))
    return calls


def grade_no_duplicate_tool_calls(events: Sequence[Any]) -> GraderResult:
    """The same non-terminal tool with the same args may not run twice."""
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    for tool, args in _planner_tool_calls(events):
        if not tool or tool == "FinishRetrieval":
            continue
        key = (tool, json.dumps(dict(args), ensure_ascii=True, sort_keys=True, default=str))
        if key in seen:
            duplicates.append(f"{tool}({key[1]})")
        seen.add(key)
    if duplicates:
        return GraderResult(
            name="no_duplicate_tool_calls",
            passed=False,
            reason=f"duplicate calls: {duplicates}",
        )
    return GraderResult(
        name="no_duplicate_tool_calls",
        passed=True,
        reason="no duplicate non-terminal tool calls",
    )


def grade_valid_finish_evidence_ids(events: Sequence[Any]) -> GraderResult:
    """FinishRetrieval may cite only IDs observed in prior tool results."""
    observed: set[str] = set()
    invalid: list[str] = []
    finish_calls = 0
    for event in events:
        event_type, payload = _trace_event_fields(event)
        if event_type == "tool_result":
            record_ids = payload.get("record_ids")
            if isinstance(record_ids, Sequence) and not isinstance(record_ids, str):
                observed.update(str(item) for item in record_ids)
            continue
        if event_type != "planner_step" or str(payload.get("tool") or "") != "FinishRetrieval":
            continue
        finish_calls += 1
        args = payload.get("args")
        evidence_ids = args.get("evidence_ids") if isinstance(args, Mapping) else []
        if isinstance(evidence_ids, Sequence) and not isinstance(evidence_ids, str):
            invalid.extend(str(item) for item in evidence_ids if str(item) not in observed)
        elif evidence_ids:
            invalid.append("<non-list evidence_ids>")
    if invalid:
        return GraderResult(
            name="valid_finish_evidence_ids",
            passed=False,
            reason=f"FinishRetrieval cites unobserved evidence: {invalid}",
        )
    return GraderResult(
        name="valid_finish_evidence_ids",
        passed=True,
        reason=f"all evidence IDs valid across {finish_calls} finish call(s)",
    )


def grade_no_finish_loops(events: Sequence[Any]) -> GraderResult:
    finishes = sum(
        1
        for tool, _args in _planner_tool_calls(events)
        if tool == "FinishRetrieval"
    )
    if finishes > 1:
        return GraderResult(
            name="no_finish_loops",
            passed=False,
            reason=f"FinishRetrieval repeated {finishes} times",
        )
    return GraderResult(
        name="no_finish_loops",
        passed=True,
        reason=f"FinishRetrieval calls={finishes}",
    )


def grade_output_event_schema(events: Sequence[Any]) -> GraderResult:
    """Validate the final, non-partial answer event without judging wording."""
    terminal_status = ""
    final_answer: Mapping[str, Any] | None = None
    for event in events:
        event_type, payload = _trace_event_fields(event)
        if event_type == "answer" and not payload.get("partial"):
            final_answer = payload
        if event_type in {"run_completed", "run_failed", "run_interrupted", "run_cancelled"}:
            terminal_status = str(payload.get("status") or event_type.removeprefix("run_"))
    if not terminal_status:
        return GraderResult(
            name="output_event_schema",
            passed=True,
            reason="non-terminal trace has no required answer yet",
        )
    if terminal_status in {"failed", "interrupted", "cancelled"}:
        return GraderResult(
            name="output_event_schema",
            passed=True,
            reason=f"terminal status {terminal_status} has no required answer",
        )
    if final_answer is None:
        return GraderResult(
            name="output_event_schema",
            passed=False,
            reason="completed trace has no final answer event",
        )
    text = final_answer.get("text")
    claims = final_answer.get("claims")
    evidence_ids = final_answer.get("evidence_ids")
    issues: list[str] = []
    if not isinstance(text, str):
        issues.append("text must be a string")
    if not isinstance(claims, list):
        issues.append("claims must be a list")
    else:
        for index, claim in enumerate(claims):
            if not isinstance(claim, Mapping):
                issues.append(f"claims[{index}] must be an object")
                continue
            if not isinstance(claim.get("text"), str):
                issues.append(f"claims[{index}].text must be a string")
            cited = claim.get("evidence_ids")
            if not isinstance(cited, list) or not all(isinstance(item, str) for item in cited):
                issues.append(f"claims[{index}].evidence_ids must be string[]")
    if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
        issues.append("evidence_ids must be string[]")
    if issues:
        return GraderResult(
            name="output_event_schema",
            passed=False,
            reason="; ".join(issues),
        )
    return GraderResult(
        name="output_event_schema",
        passed=True,
        reason="final answer event matches the phase-0 schema",
    )


def grade_trace(events: Sequence[Any]) -> GraderReport:
    """Run deterministic trajectory/output checks over a durable trace."""
    return GraderReport(
        results=[
            grade_no_duplicate_tool_calls(events),
            grade_valid_finish_evidence_ids(events),
            grade_no_finish_loops(events),
            grade_output_event_schema(events),
        ]
    )


def grade_unified_phase0_snapshot(scenario: Mapping[str, Any]) -> GraderReport:
    """Grade only frozen observable safety facts, never model prose."""

    snapshots = scenario.get("snapshots") or {}
    final_pack = snapshots.get("final_pack") or {}
    checkpoint = snapshots.get("checkpoint") or {}
    expected = scenario.get("expected") or {}
    actual_refs = sorted(str(item) for item in final_pack.get("evidence_refs") or ())
    expected_refs = sorted(str(item) for item in expected.get("final_evidence_refs") or ())
    evidence = GraderResult(
        name="frozen_final_evidence",
        passed=actual_refs == expected_refs,
        reason=f"expected={expected_refs}, actual={actual_refs}",
    )
    status = str(scenario.get("status") or "unknown")
    checkpoint_ok = (
        status not in {"interrupted", "cancelled"}
        or str(checkpoint.get("status") or "") == status
    )
    checkpoint_result = GraderResult(
        name="terminal_checkpoint_status",
        passed=checkpoint_ok,
        reason=f"scenario={status}, checkpoint={checkpoint.get('status')}",
    )
    return GraderReport(results=[evidence, checkpoint_result])
