"""Deterministic grounding / trajectory graders (agent-runtime-sprints Фаза 0).

These lock in the anti-hallucination invariants enforced by §1.1–1.5 so that a
future refactor cannot silently reintroduce fabricated citations or answers on
an empty pack. Graders are pure functions over a final run state; each scenario
below is a golden fixture of that state.
"""

from __future__ import annotations

from app.services.agent.runtime.graders import (
    grade_claims_subset_evidence,
    grade_empty_pack_no_claim,
    grade_run,
    grade_trajectory_includes,
)


# --------------------------------------------------------------------------- #
# Golden fixtures — final run states
# --------------------------------------------------------------------------- #


def _grounded_run() -> dict:
    """Healthy run: answer claims cite evidence that exists."""
    return {
        "rag_context": "[id: /post/3/] Пост про запуск.",
        "evidence_ids": ["/post/3/"],
        "evidence_records": {"/post/3/": {"content": "Пост про запуск."}},
        "answer_text": "Пост 3 про запуск.",
        "claims": [{"text": "Пост 3 про запуск.", "evidence_ids": ["/post/3/"]}],
        "research_transcript": ["OpenPost(/post/3/): ok", "FinishRetrieval(ready)"],
        "stopped_reason": "ready",
    }


def _empty_pack_refusal_run() -> dict:
    """agent-runtime-sprints §1.1: no evidence → honest refusal, no claims."""
    return {
        "rag_context": "",
        "evidence_ids": [],
        "evidence_records": {},
        "answer_text": "Не нашёл в workspace данных, чтобы ответить фактически.",
        "claims": [],
        "stopped_reason": "empty_evidence_refusal",
        "research_transcript": ["SearchNodes: 0 hits", "FinishRetrieval(partial)"],
    }


def _fabricated_citation_run() -> dict:
    """Regression trap: answer cites an evidence_id the run never collected."""
    return {
        "rag_context": "[id: /post/3/] Пост про запуск.",
        "evidence_ids": ["/post/3/"],
        "evidence_records": {"/post/3/": {"content": "Пост про запуск."}},
        "answer_text": "Пост 7 про акцию.",
        "claims": [{"text": "Пост 7 про акцию.", "evidence_ids": ["/post/7/"]}],
    }


def _empty_pack_hallucinated_run() -> dict:
    """Regression trap: empty pack but the model still asserted a fact."""
    return {
        "rag_context": "",
        "evidence_ids": [],
        "evidence_records": {},
        "answer_text": "У поста 3 охват 5000.",
        "claims": [{"text": "У поста 3 охват 5000.", "evidence_ids": []}],
        "stopped_reason": "ready",
    }


# --------------------------------------------------------------------------- #
# claims ⊆ evidence
# --------------------------------------------------------------------------- #


def test_grounded_run_passes_all_graders() -> None:
    report = grade_run(_grounded_run(), must_call=["OpenPost"])
    assert report.ok, report.failures


def test_fabricated_citation_fails_subset_grader() -> None:
    result = grade_claims_subset_evidence(_fabricated_citation_run())
    assert result.passed is False
    assert "/post/7/" in result.reason


# --------------------------------------------------------------------------- #
# empty pack ⇒ no factual claim
# --------------------------------------------------------------------------- #


def test_empty_pack_refusal_passes() -> None:
    result = grade_empty_pack_no_claim(_empty_pack_refusal_run())
    assert result.passed is True


def test_empty_pack_hallucination_fails() -> None:
    result = grade_empty_pack_no_claim(_empty_pack_hallucinated_run())
    assert result.passed is False


def test_empty_pack_grader_not_applicable_when_pack_present() -> None:
    # A grounded run has a non-empty pack; the empty-pack grader is a no-op pass.
    result = grade_empty_pack_no_claim(_grounded_run())
    assert result.passed is True
    assert "not applicable" in result.reason


# --------------------------------------------------------------------------- #
# trajectory must-call
# --------------------------------------------------------------------------- #


def test_trajectory_superset_detects_missing_tool() -> None:
    # notes-content question that never reached OpenNote must fail.
    result = grade_trajectory_includes(_grounded_run(), must_call=["OpenNote"])
    assert result.passed is False
    assert "OpenNote" in result.reason


def test_trajectory_superset_passes_when_present() -> None:
    result = grade_trajectory_includes(_grounded_run(), must_call=["OpenPost"])
    assert result.passed is True
