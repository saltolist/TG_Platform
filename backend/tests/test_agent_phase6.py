"""Phase 6: verified EvidencePack, answer output contract and model separation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.pack import build_verified_pack
from app.services.agent.runtime.message_context import evidence_id_aliases
from app.services.agent.runtime.output_contract import (
    OUTPUT_SCHEMA_V1,
    validate_answer_output,
)
from app.services.ai.providers import ProviderSpec


def _record(path: str, kind: str, content: str = "fact") -> EvidenceRecord:
    return EvidenceRecord(
        id=path,
        kind=kind,  # type: ignore[arg-type]
        source_ref=path,
        content=content,
        citation_path=path,
        citation_title=path,
    )


def test_verified_pack_excludes_discovery_and_keeps_every_selected_primary() -> None:
    records = {
        "/note/n1/summary": _record("/note/n1/summary", "search_hit", "summary"),
        "/note/n1/": _record("/note/n1/", "note_chunk", "full note"),
        "/post/p1/": _record("/post/p1/", "post_text", "full post"),
    }
    pack = build_verified_pack(
        records=records,
        evidence_ids=list(records),
        unresolved=["missing attachment"],
        source_ids=["source-note"],
    )
    assert pack.schema == "workspace.evidence-pack/v1"
    assert pack.evidence_ids == ("/note/n1/", "/post/p1/")
    assert pack.to_dict()["unresolved"] == ["missing attachment"]


def test_verified_pack_keeps_authoritative_catalog_records() -> None:
    records = {
        "/posts/": _record(
            "/posts/", "catalog", "Посты пользователя (total=7, shown=7)."
        )
    }
    pack = build_verified_pack(
        records=records,
        evidence_ids=["/posts/"],
        unresolved=[],
        source_ids=["workspace-posts-1"],
    )

    assert pack.evidence_ids == ("/posts/",)
    assert pack.items[0].kind == "catalog"


def test_verified_pack_keeps_catalog_members_for_message_context() -> None:
    records = {
        "/posts/": EvidenceRecord(
            id="/posts/",
            kind="catalog",
            source_ref="/posts/",
            content="catalog",
            citation_path="/posts/",
            citation_title="Список постов",
            metadata={"members": [{"kind": "post", "id": "p1", "title": "Пост 1", "preview": "Карточка"}]},
        )
    }
    pack = build_verified_pack(records=records, evidence_ids=["/posts/"])

    assert pack.items[0].metadata == {
        "members": [{"kind": "post", "id": "p1", "title": "Пост 1", "preview": "Карточка"}]
    }


def test_output_validator_rejects_dangling_factual_citation() -> None:
    result = validate_answer_output(
        {
            "answer": "Fact",
            "claims": [{"text": "Fact", "evidence_ids": ["/note/missing/"]}],
        },
        evidence_ids={"/note/n1/"},
        factual=True,
    )
    assert not result.ok
    assert "dangling_evidence" in " ".join(result.issues)


def test_output_validator_accepts_versioned_grounded_output() -> None:
    result = validate_answer_output(
        {"answer": "Fact", "claims": [{"text": "Fact", "evidence_ids": ["/note/n1/"]}]},
        evidence_ids={"/note/n1/"},
        factual=True,
    )
    assert result.ok
    assert result.schema == OUTPUT_SCHEMA_V1


def test_output_validator_normalizes_supplied_object_ref_claim_aliases() -> None:
    pack = {
        "items": [
            {
                "id": "/note/global/n1/",
                "kind": "note_chunk",
                "source_ref": "/note/global/n1/",
                "citation_path": "/note/global/n1/",
            },
            {
                "id": "/post/p1/",
                "kind": "post_text",
                "source_ref": "post:p1",
                "citation_path": "/post/p1/",
            },
        ]
    }
    aliases = evidence_id_aliases(pack)

    result = validate_answer_output(
        {
            "answer": "Fact",
            "claims": [
                {"text": "Note fact", "evidence_ids": ["note:n1"]},
                {"text": "Post fact", "evidence_ids": ["post:p1"]},
            ],
        },
        evidence_ids={"/note/global/n1/", "/post/p1/"},
        evidence_id_aliases=aliases,
        factual=True,
    )

    assert result.ok
    assert result.claims[0]["evidence_ids"] == ["/note/global/n1/"]
    assert result.claims[1]["evidence_ids"] == ["/post/p1/"]


@pytest.mark.asyncio
async def test_advisory_answer_salvages_complete_text_from_truncated_claims() -> None:
    from app.core.config import Settings
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.agent.runtime.workspace_graph import answer_node

    async def stream(_ctx, **_kwargs):
        yield '{"answer":"Полезная рекомендация.","claims":['

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=__import__("uuid").uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
        answer_spec=ProviderSpec("DeepSeek", "https://answer"),
        answer_model="answer-model",
        answer_api_key="a",
    )
    state = {
        "user_text": "Что посоветуешь?",
        "tool_call": {"type": "read"},
        "turn_contract": {
            "version": 2,
            "requires_workspace": True,
            "answerability_without_evidence": True,
            "task_profile": "recommendation",
            "output": {"kind": "answer"},
        },
        "evidence_ids": ["/note/n1/"],
        "rag_context": "fact",
    }
    with (
        patch(
            "app.services.agent.runtime.workspace_graph.stream_llm_with_deadline",
            side_effect=stream,
        ),
        patch(
            "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
            new_callable=AsyncMock,
        ) as repair,
    ):
        result = await answer_node(
            state, {"configurable": {"runtime_context": ctx}}
        )

    assert result["answer_text"] == "Полезная рекомендация."
    assert result["output_validation"]["ok"] is True
    assert result["answer_repair_count"] == 0
    repair.assert_not_awaited()


@pytest.mark.asyncio
async def test_factual_answer_salvages_complete_text_from_truncated_claims() -> None:
    from app.core.config import Settings
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.agent.runtime.workspace_graph import answer_node

    async def stream(_ctx, **_kwargs):
        yield '{"answer":"Рекомендация опирается на найденную заметку.","claims":['

    ctx = RuntimeContext(
        session_factory=AsyncMock(), user_id=__import__("uuid").uuid4(), user=None,
        tenant_key=None, settings=Settings(), embedding_backend=AsyncMock(), scope="global",
        post_data=None, ai_profile={},
        answer_spec=ProviderSpec("DeepSeek", "https://answer"),
        answer_model="answer-model", answer_api_key="a",
    )
    state = {
        "user_text": "Что посоветуешь?", "tool_call": {"type": "read"},
        "turn_contract": {
            "version": 2, "requires_workspace": True,
            "answerability_without_evidence": False,
            "task_profile": "topical_answer", "output": {"kind": "answer"},
        },
        "evidence_ids": ["/note/n1/"],
        "rag_context": "fact",
    }
    with (
        patch(
            "app.services.agent.runtime.workspace_graph.stream_llm_with_deadline",
            side_effect=stream,
        ),
        patch(
            "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
            new_callable=AsyncMock,
        ) as repair,
    ):
        result = await answer_node(state, {"configurable": {"runtime_context": ctx}})

    assert result["answer_text"].startswith("Рекомендация опирается")
    assert result["output_validation"]["ok"] is True
    assert result["claims"][0]["evidence_ids"] == ["/note/n1/"]
    assert result["answer_repair_count"] == 0
    repair.assert_not_awaited()


@pytest.mark.asyncio
async def test_optional_enrichment_answers_normally_when_workspace_has_no_match() -> None:
    from app.core.config import Settings
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.agent.runtime.workspace_graph import answer_node

    async def stream(_ctx, **_kwargs):
        yield '{"answer":"Да, запускай проверку основного сценария.","claims":[]}'

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=__import__("uuid").uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
        answer_spec=ProviderSpec("DeepSeek", "https://answer"),
        answer_model="answer-model",
        answer_api_key="a",
    )
    state = {
        "user_text": "Стоит ли уже запускать проверку?",
        "tool_call": {"type": "read"},
        "turn_contract": {
            "version": 2,
            "requires_workspace": True,
            "answerability_without_evidence": True,
            "task_profile": "topical_answer",
            "output": {"kind": "answer"},
        },
        "evidence_ids": [],
        "rag_context": "",
    }
    with patch(
        "app.services.agent.runtime.workspace_graph.stream_llm_with_deadline",
        side_effect=stream,
    ) as final_generation:
        result = await answer_node(
            state,
            {
                "configurable": {
                    "runtime_context": ctx,
                    "dialog_context": "Реализация завершена, осталась проверка.",
                }
            },
        )

    messages = final_generation.call_args.kwargs["messages"]
    system_prompt = str(messages[0]["content"])
    user_prompt = str(messages[1]["content"])
    assert result["answer_text"].startswith("Да, запускай проверку")
    assert "Стоит ли уже запускать проверку?" in user_prompt
    assert "Реализация завершена, осталась проверка." in user_prompt
    assert "no_relevant_workspace_evidence" in user_prompt
    assert "всё равно дай полезный ответ из общих знаний" in system_prompt
    assert "Упоминай отсутствие конкретных данных только когда пользователь явно" in system_prompt
    assert result.get("stopped_reason") != "empty_evidence_refusal"


def test_answer_resolver_prefers_active_user_llm_over_orchestrator() -> None:
    from app.core.config import Settings
    from app.db.models import User
    from app.services.ai.orchestrator import resolve_answer_llm

    user = User(email="answer-model@example.com", password_hash="x", is_seed=False)
    resolved = resolve_answer_llm(
        user,
        {
            "llmModels": [{"active": True, "provider": "DeepSeek", "model": "deepseek-chat", "apiKey": "real-key"}],
            "orchestratorModels": [{"active": True, "provider": "OpenAI", "model": "gpt-4.1-mini", "apiKey": "other-key"}],
        },
        Settings(),
    )
    assert resolved is not None
    assert resolved[0].name == "DeepSeek"
    assert resolved[1] == "deepseek-chat"


def test_answer_resolver_honors_selected_active_model_id() -> None:
    from app.core.config import Settings
    from app.db.models import User
    from app.services.ai.orchestrator import resolve_answer_llm

    user = User(email="selected-answer@example.com", password_hash="x", is_seed=False)
    resolved = resolve_answer_llm(
        user,
        {
            "llmModels": [
                {
                    "id": "deepseek-first",
                    "active": True,
                    "provider": "DeepSeek",
                    "model": "deepseek-chat",
                    "apiKey": "deepseek-key",
                },
                {
                    "id": "openai-selected",
                    "active": True,
                    "provider": "OpenAI",
                    "model": "gpt-4.1-mini",
                    "apiKey": "openai-key",
                },
            ],
            "orchestratorModels": [],
        },
        Settings(),
        model_id="openai-selected",
    )

    assert resolved is not None
    assert resolved[0].name == "OpenAI"
    assert resolved[1] == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_answer_uses_answer_model_verified_pack_and_dialog_context() -> None:
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.agent.runtime.workspace_graph import answer_node
    from app.core.config import Settings

    async def stream(_ctx, **_kwargs):
        yield '{"answer":"Fact","claims":[{"text":"Fact","evidence_ids":["/note/n1/"]}]}'

    ctx = RuntimeContext(
        session_factory=AsyncMock(), user_id=__import__("uuid").uuid4(), user=None,
        tenant_key=None, settings=Settings(), embedding_backend=AsyncMock(), scope="post",
        post_data={"id": "p-current", "text": "RAW CURRENT POST"}, ai_profile={},
        reasoner_spec=ProviderSpec("OpenAI", "https://planner"), reasoner_model="planner-model", reasoner_api_key="p",
        answer_spec=ProviderSpec("DeepSeek", "https://answer"), answer_model="answer-model", answer_api_key="a",
    )
    state = {
        "user_text": "Что в заметке?", "tool_call": {"type": "read"},
        "evidence_pack": {"schema": "workspace.evidence-pack/v1", "evidence_ids": ["/note/n1/"],
                          "items": [{"id": "/note/n1/", "title": "N", "citation_path": "/note/n1/", "content": "fact", "kind": "note_chunk"}]},
        "evidence_ids": ["/note/n1/"],
        "evidence_records": {
            "/note/n1/": _record("/note/n1/", "note_chunk", "fact").to_dict(),
            "/post/unselected/": _record("/post/unselected/", "post_text", "UNSELECTED").to_dict(),
        },
        "turn_contract": {"version": 2, "requires_workspace": True, "task_profile": "topical_answer", "output": {"kind": "answer"}},
    }
    with patch("app.services.agent.runtime.workspace_graph.stream_llm_with_deadline", side_effect=stream) as call:
        result = await answer_node(
            state,
            {"configurable": {"runtime_context": ctx, "dialog_context": "старый assistant факт"}},
        )
    assert result["answer_text"] == "Fact"
    assert call.call_args.kwargs["model"] == "answer-model"
    messages = call.call_args.kwargs["messages"]
    system_prompt = str(messages[0]["content"])
    prompt = " ".join(str(item["content"]) for item in messages)
    assert "старый assistant факт" in prompt
    assert "Что в заметке?" in prompt
    assert "RAW CURRENT POST" not in prompt
    assert "UNSELECTED" not in prompt
    assert "workspace_data" in prompt
    assert "Выполни текущий запрос пользователя с учётом его формулировки и диалога" in system_prompt
    assert "не готовый ответ и не замена задачи пользователя" in system_prompt
    assert "единственный источник фактов именно о workspace" in system_prompt
    assert "Отвечай только по EvidencePack" not in system_prompt


@pytest.mark.asyncio
async def test_answer_format_repair_is_single_and_preserves_answer_text() -> None:
    from app.services.agent.runtime.context import RuntimeContext
    from app.services.agent.runtime.workspace_graph import answer_node
    from app.core.config import Settings
    from uuid import uuid4

    async def stream(_ctx, **_kwargs):
        yield '{"answer":"Fact","claims":[{"text":"Fact","evidence_ids":["bad"]}]}'

    ctx = RuntimeContext(
        session_factory=AsyncMock(), user_id=uuid4(), user=None, tenant_key=None,
        settings=Settings(), embedding_backend=AsyncMock(), scope="global", post_data=None, ai_profile={},
        reasoner_spec=ProviderSpec("OpenAI", "https://planner"), reasoner_model="planner", reasoner_api_key="p",
        answer_spec=ProviderSpec("DeepSeek", "https://answer"), answer_model="answer", answer_api_key="a",
    )
    state = {
        "user_text": "Что?", "tool_call": {"type": "read"}, "evidence_ids": ["/note/n1/"],
        "evidence_pack": {"schema": "workspace.evidence-pack/v1", "evidence_ids": ["/note/n1/"],
                          "items": [{"id": "/note/n1/", "title": "N", "citation_path": "/note/n1/", "content": "fact", "kind": "note_chunk"}]},
        "turn_contract": {"version": 2, "requires_workspace": True, "task_profile": "topical_answer", "output": {"kind": "answer"}},
    }
    with (
        patch("app.services.agent.runtime.workspace_graph.stream_llm_with_deadline", side_effect=stream),
        patch("app.services.agent.runtime.workspace_graph.call_llm_with_deadline", new_callable=AsyncMock,
              return_value=json.dumps({"answer": "Fact", "claims": [{"text": "Fact", "evidence_ids": ["/note/n1/"]}]})) as repair,
    ):
        result = await answer_node(state, {"configurable": {"runtime_context": ctx}})
    assert result["answer_text"] == "Fact"
    assert result["answer_repair_count"] == 1
    assert repair.await_count == 1


def test_phase6_flag_is_configurable() -> None:
    from app.core.config import Settings

    assert Settings().agent_answer_phase6_enabled is True
    assert Settings(agent_answer_phase6_enabled="0").agent_answer_phase6_enabled is False


def test_phase6_fixture_gate_passes() -> None:
    from scripts.agent_phase6_answer_report import build_report, check_report

    fixture = Path(__file__).parent / "fixtures/agent_answer_phase6/v1/scenarios.json"
    report = build_report(json.loads(fixture.read_text(encoding="utf-8")))
    assert check_report(report) == []
    assert report["phase6"]["output_schema_compliance"] >= 0.99
    assert report["change"]["answer_input_tokens_median_reduction"] > 0


@pytest.mark.asyncio
async def test_llm_metrics_measure_prompt_cache_eligibility() -> None:
    from app.services.agent.runtime.budget import call_llm_with_deadline

    ctx = SimpleNamespace(deadline_monotonic=None, llm_client=None, llm_metrics=[])
    with patch(
        "app.services.agent.runtime.budget.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value="ok",
    ):
        await call_llm_with_deadline(
            ctx,
            phase="answer.generate",
            messages=[
                {"role": "system", "content": "stable answer prefix"},
                {"role": "user", "content": "question"},
            ],
            spec=ProviderSpec("OpenAI", "https://api.openai.com"),
            model="answer-model",
            api_key="test-key",
        )
    metric = ctx.llm_metrics[0]
    assert metric["prompt_cache_key"]
    assert metric["prompt_cache_eligible_tokens"] > 0
    assert metric["prompt_cache_hit_tokens"] is None
