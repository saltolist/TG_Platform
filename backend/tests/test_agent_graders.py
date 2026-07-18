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
    grade_image_claim_backed,
    grade_result_contract,
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


# --------------------------------------------------------------------------- #
# image claim must be backed by an image attachment in the pack (chat 9f3d5fdf)
# --------------------------------------------------------------------------- #


def _confabulated_image_run() -> dict:
    """Regression trap: answer affirms an image, but pack has no image attachment.

    The note's prose describes a schema; the model reported it as an attached
    picture, "confirming" the user's presupposition that images exist.
    """
    return {
        "rag_context": "[id: /note/global/n1/] Заметка про каскадный поиск: уровни 0,1,2.",
        "evidence_ids": ["/note/global/n1/"],
        "answer_text": "Да, в заметке есть изображение — схема каскадного поиска.",
        "claims": [{"text": "В заметке есть изображение схемы.", "evidence_ids": ["/note/global/n1/"]}],
    }


def test_confabulated_image_fails_grader() -> None:
    result = grade_image_claim_backed(_confabulated_image_run())
    assert result.passed is False
    assert "no image attachment" in result.reason


def test_image_claim_passes_when_pack_has_image() -> None:
    state = dict(_confabulated_image_run())
    state["rag_context"] += "\nВложения заметки:\n- схема (тип: image/png)"
    result = grade_image_claim_backed(state)
    assert result.passed is True


def test_image_claim_passes_via_attachment_record_path() -> None:
    # evidence_records with /attachment/ path → grader passes without "image/" in
    # rag_context (chat 8caf07f4: vision captions are plain prose, never contain
    # "image/", so old text-scan falsely triggered).
    state = dict(_confabulated_image_run())
    state["evidence_records"] = {
        "/note/global/n1/attachment/f1/": {"content": "На изображении рекламный баннер."}
    }
    result = grade_image_claim_backed(state)
    assert result.passed is True


def test_image_denial_passes_grader() -> None:
    # Honest "there are no images" answer over an image-less pack must not trip.
    state = dict(_confabulated_image_run())
    state["answer_text"] = "В найденной заметке нет изображений."
    result = grade_image_claim_backed(state)
    assert result.passed is True


def test_grounded_run_has_no_image_affirmation() -> None:
    # Sanity: the healthy fixture makes no image claim, so grade_run stays green.
    result = grade_image_claim_backed(_grounded_run())
    assert result.passed is True


def test_feed_post_contract_rejects_note_evidence() -> None:
    state = {
        "turn_contract": {"corpus": "feed_posts", "output": {"kind": "answer"}},
        "evidence_ids": ["/note/global/series/"],
        "evidence_records": {
            "/note/global/series/": {"kind": "note_chunk", "content": "План серии"}
        },
        "answer_text": "Он пересекается с заметкой.",
    }
    result = grade_result_contract(state)
    assert result.passed is False
    assert "feed_posts corpus violation" in result.reason
