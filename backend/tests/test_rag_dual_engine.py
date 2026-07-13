"""Dual-engine RAG L2 routing tests."""

from __future__ import annotations

from app.core.config import Settings


def test_rag_l2_engine_defaults_langgraph() -> None:
    assert Settings().rag_l2_engine == "langgraph"


def test_agent_runtime_engine_defaults_langgraph() -> None:
    assert Settings().agent_runtime_engine == "langgraph"
