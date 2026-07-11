"""Tests for optional LLM plan alignment auditor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.ai.rag import NODE_NOTE_CHUNK
from app.services.ai.rag_plan_alignment import (
    PlanAlignmentVerdict,
    audit_plan_alignment_llm,
    evaluate_plan_alignment,
)
from app.services.ai.rag_retrieval_brief import build_retrieval_brief
from app.services.ai.rag_retrieval_plan import RetrievalPlan, RetrievalPlanStep


def _welcome_query() -> str:
    return "Какое изображение подойдет моему приветственному посту?"


@pytest.mark.asyncio
async def test_audit_plan_alignment_llm_overrides_on_accept() -> None:
    brief = build_retrieval_brief(user_text=_welcome_query(), scope="global")
    plan = RetrievalPlan(
        goal="test",
        steps=[
            RetrievalPlanStep(
                tool="OpenPost",
                args={"post_id": "721c63fe"},
                purpose="L1",
            ),
        ],
    )
    deterministic = evaluate_plan_alignment(
        brief=brief,
        plan=plan,
        l1_results=[
            {
                "node_type": NODE_NOTE_CHUNK,
                "post_id": "721c63fe",
                "note_id": "n1",
                "chunk_text": "images",
                "similarity": 0.5,
            }
        ],
        scope="global",
    )
    assert not deterministic.aligned

    llm_raw = (
        '{"aligned": true, "reasoning": "План всё же ок", "blockers": [], "fix": ""}'
    )
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=llm_raw,
    ):
        verdict = await audit_plan_alignment_llm(
            user_text=_welcome_query(),
            brief=brief,
            plan=plan,
            l1_results=[],
            deterministic_verdict=deterministic,
            spec=object(),  # type: ignore[arg-type]
            model="gpt-test",
            api_key="key",
        )

    assert verdict.aligned
    assert verdict.reason == "llm_auditor_accept"
    assert any("[align-llm]" in line for line in verdict.ledger_lines)
