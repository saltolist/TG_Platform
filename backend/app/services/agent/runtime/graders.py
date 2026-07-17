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

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


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


def _is_refusal(state: Mapping[str, Any]) -> bool:
    """The runtime's empty-pack answer guard emits a stable refusal marker."""
    return bool(
        (state.get("stopped_reason") or "") == "empty_evidence_refusal"
    ) or not str(state.get("answer_text") or "").strip()


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
    """Empty pack ⇒ no factual claim. If the run collected no evidence
    (empty rag_context and no evidence_ids), the answer must be a refusal
    rather than fabricated text (DoD #1, answer guard §1.1)."""
    rag = str(state.get("rag_context") or "").strip()
    ids = state.get("evidence_ids") or []
    if rag or ids:
        return GraderResult(
            name="empty_pack_no_claim",
            passed=True,
            reason="pack non-empty — grader not applicable",
        )
    if _has_factual_claim(state) or not _is_refusal(state):
        return GraderResult(
            name="empty_pack_no_claim",
            passed=False,
            reason="empty pack but answer made a factual claim / did not refuse",
        )
    return GraderResult(
        name="empty_pack_no_claim",
        passed=True,
        reason="empty pack → refusal",
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
    ]
    if must_call:
        results.append(grade_trajectory_includes(state, must_call=must_call))
    return GraderReport(results=results)
