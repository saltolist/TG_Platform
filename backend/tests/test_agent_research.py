"""Research subgraph unit tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.agent.research.evidence import EvidenceRecord
from app.services.agent.research.graph import (
    CURRENT_POST_NOTE_PREVIEW_CHARS,
    _compact_state_snapshot,
    _current_post_note_catalog,
    unopened_prefetch_hits,
    parse_tool_action,
    research_planner_node,
    route_research_after_tool,
    run_research_graph,
    validate_observations,
)
from app.services.agent.research.material_plan import normalize_candidates
from app.services.ai.rag_tools import ToolOutcome
from app.services.agent.research.pack import build_evidence_pack
from app.services.agent.research.verifier import verify_evidence
from app.services.agent.runtime.context import RuntimeContext
from app.services.agent.runtime.turn_contract import build_turn_contract
from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_tools import AgentState


def test_current_post_note_catalog_exposes_all_valid_note_cards() -> None:
    long_body = "x" * (CURRENT_POST_NOTE_PREVIEW_CHARS + 20)
    catalog = _current_post_note_catalog(
        {
            "id": "post-1",
            "notes": [
                "invalid",
                {"id": "", "title": "missing id"},
                {
                    "id": "note-1",
                    "title": "\n  First title  \nSecond title",
                    "body": long_body,
                    "status": "active",
                    "files": [
                        {"id": "image-1", "type": "image/png"},
                        {"id": "doc-1", "mimeType": "application/pdf"},
                        "invalid",
                    ],
                },
                {
                    "id": "note-2",
                    "title": "",
                    "body": "\n  Body title\nMore text",
                    "files": [],
                },
            ],
        }
    )

    assert [item["ref"] for item in catalog] == ["note:note-1", "note:note-2"]
    assert catalog[0]["title"] == "First title"
    assert catalog[0]["preview"] == "x" * CURRENT_POST_NOTE_PREVIEW_CHARS + "…"
    assert catalog[0]["parent_post_id"] == "post-1"
    assert catalog[0]["attachment_count"] == 2
    assert catalog[0]["image_count"] == 1
    assert catalog[0]["source_requirement_id"] == "workspace-notes"
    assert catalog[1]["title"] == "Body title"
    normalized = normalize_candidates(catalog)
    assert normalized[0]["card_origin"] == "current_post_catalog"


def test_compact_snapshot_includes_current_post_note_registry() -> None:
    catalog = _current_post_note_catalog(
        {
            "id": "post-1",
            "notes": [
                {
                    "id": "note-1",
                    "title": "Local note",
                    "body": "Short preview",
                    "files": [{"id": "image-1", "type": "image/jpeg"}],
                }
            ],
        }
    )
    snapshot = json.loads(
        _compact_state_snapshot(
            state={"user_text": "Question", "current_post_notes": catalog},
            records={},
            sufficiency={},
        )
    )

    assert snapshot["current_post_notes"][0]["ref"] == "note:note-1"
    assert snapshot["current_post_notes"][0]["parent_post_id"] == "post-1"
    assert snapshot["current_post_notes"][0]["attachment_count"] == 1
    assert snapshot["current_post_notes"][0]["image_count"] == 1
    assert "Short preview" in snapshot["current_post_notes"][0]["preview"]


def test_current_post_catalog_cards_do_not_trigger_unopened_prefetch_guard() -> None:
    catalog = _current_post_note_catalog(
        {
            "id": "post-1",
            "notes": [{"id": "note-1", "title": "Local note", "body": "Preview"}],
        }
    )
    assert unopened_prefetch_hits(catalog, {}) == []


def test_parse_tool_action_finish() -> None:
    action = parse_tool_action('{"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": []}}')
    assert action is not None
    assert action.tool == "FinishRetrieval"


def test_no_progress_guard_stops_repeated_tool_loop() -> None:
    assert route_research_after_tool(
        {"step_count": 2, "max_steps": 10, "no_progress_count": 2}
    ) == "verify"


@pytest.mark.asyncio
async def test_execute_tool_dispatches_list_post_media() -> None:
    from app.services.agent.research.graph import ToolAction, _execute_tool

    with patch(
        "app.services.agent.research.graph.tool_list_post_media",
    ) as mocked:
        mocked.return_value = "sentinel"
        result = await _execute_tool(
            object(), ToolAction(tool="ListPostMedia", args={"post_id": "p1"})
        )
    mocked.assert_called_once()
    assert mocked.call_args.kwargs["post_id"] == "p1"
    assert result == "sentinel"


@pytest.mark.asyncio
async def test_execute_tool_forwards_post_id_to_hydrate_attachment() -> None:
    """file:-refs (post media) can only resolve with post_id — the dispatch must
    forward it, otherwise a post's own documents/images are unreachable."""
    from app.services.agent.research.graph import ToolAction, _execute_tool

    with patch(
        "app.services.agent.research.graph.tool_hydrate_attachment",
        new_callable=AsyncMock,
        return_value="ok",
    ) as mocked:
        await _execute_tool(
            object(),
            ToolAction(
                tool="HydrateAttachment",
                args={"ref": "file:mk1", "mode": "text", "post_id": "p1"},
            ),
        )
    assert mocked.await_args.kwargs["post_id"] == "p1"
    assert mocked.await_args.kwargs["ref"] == "file:mk1"


@pytest.mark.asyncio
async def test_execute_tool_forwards_note_id_to_hydrate_attachment() -> None:
    """Regression for chat 63dfb9e4: attachment:-refs (note files) can only
    resolve with note_id (tool_hydrate_attachment/_resolve_attachment_record
    hard-require it), but the dispatch dropped it entirely — every planner
    call with a correct note_id still failed with missing_note_id, burning 5
    straight steps with no way to ever succeed."""
    from app.services.agent.research.graph import ToolAction, _execute_tool

    with patch(
        "app.services.agent.research.graph.tool_hydrate_attachment",
        new_callable=AsyncMock,
        return_value="ok",
    ) as mocked:
        await _execute_tool(
            object(),
            ToolAction(
                tool="HydrateAttachment",
                args={"ref": "attachment:f1", "mode": "vision", "note_id": "n1"},
            ),
        )
    assert mocked.await_args.kwargs["note_id"] == "n1"
    assert mocked.await_args.kwargs["ref"] == "attachment:f1"


class _FakeSessionCtx:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


def _tool_node_ctx() -> RuntimeContext:
    ctx = RuntimeContext(
        session_factory=lambda: _FakeSessionCtx(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
    )
    ctx.bind_agent_state = lambda session: AgentState(  # type: ignore[method-assign]
        session=session,
        user_id=ctx.user_id,
        scope="global",
        tenant_key=None,
        embedding_backend=ctx.embedding_backend,
    )
    return ctx


@pytest.mark.asyncio
async def test_research_tool_node_refunds_step_on_recoverable_error() -> None:
    """A recoverable precondition error ("сначала OpenPost") must not consume a
    step — otherwise a single mis-ordered call eats the budget the run needs to
    reach the evidence (observed in chat 4159bd36: ListPostNotes before OpenPost
    burned the step that would have opened the post holding the images)."""
    from app.services.agent.research.graph import research_tool_node

    ctx = _tool_node_ctx()
    state = {
        "tool_action": {"tool": "ListPostNotes", "args": {"post_id": "p1"}},
        "step_count": 5,
        "step_refunds": 0,
    }
    with patch(
        "app.services.agent.research.graph._execute_tool",
        new_callable=AsyncMock,
        return_value=ToolOutcome(summary="сначала OpenPost", error="post_not_open"),
    ), patch(
        "app.services.agent.research.graph.records_from_agent_state",
        return_value={},
    ):
        result = await research_tool_node(state, {"configurable": {"runtime_context": ctx}})

    assert result["step_count"] == 4
    assert result["step_refunds"] == 1


@pytest.mark.asyncio
async def test_research_tool_node_refund_capped() -> None:
    """Refunds are bounded — a planner stuck repeating a broken call can't get an
    unbounded free ride and loop forever."""
    from app.services.agent.research.graph import (
        MAX_STEP_REFUNDS,
        research_tool_node,
    )

    ctx = _tool_node_ctx()
    state = {
        "tool_action": {"tool": "ListPostNotes", "args": {"post_id": "p1"}},
        "step_count": 5,
        "step_refunds": MAX_STEP_REFUNDS,
    }
    with patch(
        "app.services.agent.research.graph._execute_tool",
        new_callable=AsyncMock,
        return_value=ToolOutcome(summary="сначала OpenPost", error="post_not_open"),
    ), patch(
        "app.services.agent.research.graph.records_from_agent_state",
        return_value={},
    ):
        result = await research_tool_node(state, {"configurable": {"runtime_context": ctx}})

    assert result["step_count"] == 5
    assert result["step_refunds"] == MAX_STEP_REFUNDS


@pytest.mark.asyncio
async def test_research_tool_node_does_not_refund_real_result() -> None:
    """A successful tool call (no error) pays its step — refund is only for
    recoverable precondition guidance, not normal progress."""
    from app.services.agent.research.graph import research_tool_node

    ctx = _tool_node_ctx()
    state = {
        "tool_action": {"tool": "OpenPost", "args": {"post_id": "p1"}},
        "step_count": 3,
        "step_refunds": 0,
    }
    with patch(
        "app.services.agent.research.graph._execute_tool",
        new_callable=AsyncMock,
        return_value=ToolOutcome(summary="Открыт пост p1."),
    ), patch(
        "app.services.agent.research.graph.records_from_agent_state",
        return_value={},
    ):
        result = await research_tool_node(state, {"configurable": {"runtime_context": ctx}})

    assert result["step_count"] == 3
    assert result["step_refunds"] == 0


@pytest.mark.asyncio
async def test_exact_note_contract_finishes_without_planner_llm() -> None:
    """An authoritative recent-note target is already grounded by seed, so a
    semantic planner must not wander into neighboring notes."""
    from app.services.ai.providers import ProviderSpec

    ctx = _tool_node_ctx()
    ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
    ctx.reasoner_model = "gpt-4o-mini"
    ctx.reasoner_api_key = "test-key"
    note_path = "/note/global/new-note/"
    state = {
        "user_text": "Прочитай эту заметку",
        "step_count": 0,
        "max_steps": 4,
        "evidence_records": {
            note_path: EvidenceRecord(
                id=note_path,
                kind="note_chunk",
                source_ref=note_path,
                content="Новая стратегия канала.",
                citation_path=note_path,
                citation_title="Стратегия",
            ).to_dict()
        },
        "turn_contract": {
            "corpus": "exact_note",
            "target": {"kind": "recent_note", "id": "new-note"},
            "success_criteria": ["use exact note"],
        },
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
    ) as mock_llm:
        result = await research_planner_node(
            state,
            {
                "configurable": {
                    "runtime_context": ctx,
                    "turn_contract": state["turn_contract"],
                }
            },
        )

    assert result["tool_action"]["tool"] == "FinishRetrieval"
    assert result["tool_action"]["args"]["evidence_ids"] == [note_path]
    mock_llm.assert_not_awaited()


def test_parse_tool_action_preserves_reasoning() -> None:
    """agent-runtime-sprints §3.1: reasoning/observations/gap must survive the
    parse, not be discarded — the planner's thought is the point of the schema."""
    action = parse_tool_action(
        '{"observations": ["пост 721 notes=1"], "reasoning": "нужен текст заметки",'
        ' "gap": "note content missing", "tool": "OpenNote", "args": {"note_id": "n1"}}'
    )
    assert action is not None
    assert action.observations == ("пост 721 notes=1",)
    assert action.reasoning == "нужен текст заметки"
    assert action.gap == "note content missing"
    assert action.tool == "OpenNote"


def test_parse_tool_action_backward_compat_without_reasoning() -> None:
    """Older/degenerate JSON without the thought fields must still parse —
    parse_tool_action must not require the new keys."""
    action = parse_tool_action('{"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": ["e1"]}}')
    assert action is not None
    assert action.observations == ()
    assert action.reasoning == ""
    assert action.gap == ""


def test_verify_evidence_ready() -> None:
    rec = EvidenceRecord(
        id="e1",
        kind="note_chunk",
        source_ref="note:n1",
        content="hello",
        citation_path="/note/global/n1/",
        citation_title="n1",
    )
    result = verify_evidence(
        finish={"status": "ready", "evidence_ids": ["e1"]},
        records={"e1": rec},
    )
    assert result.ok is True


def test_validate_observations_flags_fabricated() -> None:
    """agent-runtime-sprints §3.2: an observation that matches nothing in the
    transcript or evidence records is cosmetic reasoning, not real grounding."""
    rec = EvidenceRecord(
        id="/note/global/n1/",
        kind="note_chunk",
        source_ref="note:n1",
        content="план запуска",
        citation_path="/note/global/n1/",
        citation_title="План",
    )
    fabricated = validate_observations(
        ("выдуманный факт про акции",),
        transcript=["step 1: OpenNote → открыта заметка План"],
        records={"/note/global/n1/": rec},
    )
    assert fabricated == ["выдуманный факт про акции"]


def test_validate_observations_accepts_grounded() -> None:
    rec = EvidenceRecord(
        id="/note/global/n1/",
        kind="note_chunk",
        source_ref="note:n1",
        content="план запуска",
        citation_path="/note/global/n1/",
        citation_title="План",
    )
    fabricated = validate_observations(
        ("План — заметка n1",),
        transcript=["step 1: OpenNote → открыта заметка План"],
        records={"/note/global/n1/": rec},
    )
    assert fabricated == []


def test_validate_observations_empty_first_step_is_not_flagged() -> None:
    assert validate_observations((), transcript=[], records={}) == []


def test_validate_observations_blank_transcript_line_does_not_disable_check() -> None:
    """A blank transcript line must not ground everything: "" is a substring
    of any observation, so it would otherwise silently pass fabrications."""
    fabricated = validate_observations(
        ("выдуманный факт",),
        transcript=["", "   "],
        records={},
    )
    assert fabricated == ["выдуманный факт"]


def test_build_evidence_pack_dedup() -> None:
    rec = EvidenceRecord(
        id="e1",
        kind="note_chunk",
        source_ref="note:n1",
        content="alpha beta",
        citation_path="/note/global/n1/",
        citation_title="Note",
    )
    ctx, cites = build_evidence_pack(records={"e1": rec}, evidence_ids=["e1"])
    assert "alpha" in ctx
    assert len(cites) == 1
    assert isinstance(cites[0], NoteCite)


def test_build_evidence_pack_small_item_survives_budget_overflow() -> None:
    """Regression for chat 63dfb9e4: research opened 4 large notes plus one
    small note carrying the decisive fact ("files=2, два PNG"). Greedily
    filling max_chars in evidence_ids order let the large notes alone exceed
    the budget, hard-dropping the small note entirely — the answer model then
    said "0 заметок с изображениями" despite research having verified one.
    Every opened item must get at least a floor allocation."""
    big_text = "x" * 8000
    small_text = "Заметка 'Варианты изображений для поста': files=2, два PNG."
    records = {
        "big1": EvidenceRecord(
            id="big1", kind="note_chunk", source_ref="note:big1", content=big_text,
            citation_path="/note/global/big1/", citation_title="Big Note 1",
        ),
        "big2": EvidenceRecord(
            id="big2", kind="note_chunk", source_ref="note:big2", content=big_text,
            citation_path="/note/global/big2/", citation_title="Big Note 2",
        ),
        "small": EvidenceRecord(
            id="small", kind="note_chunk", source_ref="note:small", content=small_text,
            citation_path="/note/global/small/", citation_title="Small Note",
        ),
    }
    ctx, cites = build_evidence_pack(
        records=records, evidence_ids=["big1", "big2", "small"], max_chars=12000,
    )
    assert "files=2, два PNG" in ctx
    assert any(c.path == "/note/global/small/" for c in cites)


def test_verify_evidence_empty_ids_fails() -> None:
    """agent-runtime-sprints §1.3: an empty citation set is never a valid finish."""
    rec = EvidenceRecord(
        id="/note/global/n1/",
        kind="note_chunk",
        source_ref="/note/global/n1/",
        content="content",
        citation_path="/note/global/n1/",
        citation_title="n1",
    )
    result = verify_evidence(
        finish={"status": "ready", "evidence_ids": []},
        records={"/note/global/n1/": rec},
    )
    assert result.ok is False
    assert "no_evidence_ids" in result.errors


def test_verify_evidence_partial_rejects_empty_content() -> None:
    """agent-runtime-sprints §1.3: partial still must ground on non-empty content."""
    rec = EvidenceRecord(
        id="/post/3/",
        kind="post_text",
        source_ref="/post/3/",
        content="   ",
        citation_path="/post/3/",
        citation_title="Post 3",
    )
    result = verify_evidence(
        finish={"status": "partial", "evidence_ids": ["/post/3/"]},
        records={"/post/3/": rec},
    )
    assert result.ok is False
    assert "empty_evidence_content" in result.errors


@pytest.mark.asyncio
async def test_verify_node_salvages_records_when_budget_exhausted() -> None:
    """When step budget runs out mid-exploration (last action is NOT FinishRetrieval),
    verify must synthesize a partial finish over collected records instead of
    discarding them — otherwise gathered listings yield a false 'нет данных'."""
    from app.services.agent.research.graph import research_verify_node

    rec = EvidenceRecord(
        id="/global/notes/",
        kind="search_hit",
        source_ref="/global/notes/",
        content="Заметки вне постов:\n- note:g1 title='Система'",
        citation_path="/global/notes/",
        citation_title="Заметки вне постов",
    )
    state = {
        "evidence_records": {"/global/notes/": rec.to_dict()},
        # Budget ran out on a read tool, not an explicit finish.
        "tool_action": {"tool": "ListPostNotes", "args": {"post_id": "p1"}},
        "repair_count": 0,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is True
    finish = result["finish_retrieval"]
    assert finish["status"] == "partial"
    assert finish["evidence_ids"] == ["/global/notes/"]
    assert "step_budget_exhausted" in finish["unresolved"]


@pytest.mark.asyncio
async def test_verify_node_does_not_salvage_on_explicit_finish() -> None:
    """An explicit FinishRetrieval with no cites must still fail (§1.3) — the
    salvage path is only for budget exhaustion, not for a planner that chose
    to finish empty."""
    from app.services.agent.research.graph import research_verify_node

    rec = EvidenceRecord(
        id="/global/notes/",
        kind="search_hit",
        source_ref="/global/notes/",
        content="Заметки вне постов",
        citation_path="/global/notes/",
        citation_title="Заметки вне постов",
    )
    state = {
        "evidence_records": {"/global/notes/": rec.to_dict()},
        "tool_action": {"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": []}},
        "repair_count": 0,
    }
    result = await research_verify_node(state, config={})
    # Repair is allowed on the first empty finish → not yet verified.
    assert result["verification_ok"] is False


@pytest.mark.asyncio
async def test_verify_node_bounces_finish_on_unopened_prefetch_hit() -> None:
    """agent note-prefetch: the seed surfaced a relevant note, but the planner
    tried to FinishRetrieval without ever opening it (the "серия" failure). The
    prefetch gate must refuse the finish once and emit an OpenNote repair hint."""
    from app.services.agent.research.graph import research_verify_node

    rec = EvidenceRecord(
        id="/posts/",
        kind="search_hit",
        source_ref="/posts/",
        content="Посты пользователя",
        citation_path="/posts/",
        citation_title="Посты",
    )
    state = {
        "evidence_records": {"/posts/": rec.to_dict()},
        "tool_action": {"tool": "FinishRetrieval", "args": {"status": "ready", "evidence_ids": ["/posts/"]}},
        "prefetch_hits": [
            {"ref": "note:27a2f06d", "label": "note:27a2f06d", "similarity": 0.72, "node_type": "note_chunk"},
        ],
        "repair_count": 0,
        "max_steps": 8,
        "step_count": 2,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is False
    assert result["prefetch_repair_count"] == 1
    assert any("unopened_prefetch" in h for h in result["research_hints"])


@pytest.mark.asyncio
async def test_verify_node_allows_finish_when_prefetch_hit_opened() -> None:
    """Once the surfaced note is opened into evidence, the prefetch gate must not
    fire — a cited finish over materialized evidence goes straight through."""
    from app.services.agent.research.graph import research_verify_node

    note = EvidenceRecord(
        id="/note/global/27a2f06d/",
        kind="note_chunk",
        source_ref="/note/global/27a2f06d/",
        content="Серия постов до 6-го: Пост 2… Пост 6.",
        citation_path="/note/global/27a2f06d/",
        citation_title="Серия постов до 6-го",
    )
    state = {
        "evidence_records": {"/note/global/27a2f06d/": note.to_dict()},
        "tool_action": {
            "tool": "FinishRetrieval",
            "args": {"status": "ready", "evidence_ids": ["/note/global/27a2f06d/"]},
        },
        "prefetch_hits": [
            {"ref": "note:27a2f06d", "label": "note:27a2f06d", "similarity": 0.72, "node_type": "note_chunk"},
        ],
        "repair_count": 0,
        "max_steps": 8,
        "step_count": 3,
    }
    result = await research_verify_node(state, config={})
    assert result["verification_ok"] is True


def test_records_from_agent_state_uses_natural_ids() -> None:
    """agent-runtime-sprints §1.2: records key on citation path, no hash indirection."""
    from types import SimpleNamespace

    from app.services.agent.research.evidence import records_from_agent_state

    cite = NoteCite(path="/post/3/", title="Post 3")
    agent_state = SimpleNamespace(
        context_blocks=[(cite, "post body")],
        visited=[],
    )
    records = records_from_agent_state(agent_state)
    assert set(records) == {"/post/3/"}
    assert records["/post/3/"].content == "post body"
    assert records["/post/3/"].kind == "post_text"


@pytest.mark.asyncio
async def test_answer_node_passes_empty_discovery_to_final_generation() -> None:
    """Empty discovery informs final generation instead of terminating the turn."""
    from app.services.agent.runtime.workspace_graph import answer_node
    from app.services.ai.providers import ProviderSpec

    async def stream(_ctx, **_kwargs):
        yield (
            '{"answer":"По workspace охват не найден; проверьте доступность аналитики.",'
            '"claims":[]}'
        )

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
        answer_spec=ProviderSpec("DeepSeek", "https://answer"),
        answer_model="answer-model",
        answer_api_key="key",
    )
    state = {
        "user_text": "какой охват у поста 3?",
        "tool_call": {"type": "read"},
        "evidence_ids": [],
        "evidence_pack": {
            "schema": "workspace.evidence-pack/v1",
            "evidence_ids": [],
            "items": [],
            "unresolved": ["analytics_not_found"],
        },
        "search_ledger": [
            {
                "tool": "SearchNodes",
                "source_requirement_id": "workspace-analytics",
            }
        ],
    }
    with patch(
        "app.services.agent.runtime.workspace_graph.stream_llm_with_deadline",
        side_effect=stream,
    ) as final_generation:
        result = await answer_node(state, {"configurable": {"runtime_context": ctx}})

    prompt = final_generation.call_args.kwargs["messages"][1]["content"]
    assert "no_relevant_workspace_evidence" in prompt
    assert "analytics_not_found" in prompt
    assert "какой охват у поста 3?" in prompt
    assert "проверьте доступность аналитики" in result["answer_text"]
    assert result["claims"] == []
    assert result.get("stopped_reason") != "empty_evidence_refusal"


def _reasoner_ctx() -> RuntimeContext:
    from app.services.ai.providers import ProviderSpec

    ctx = RuntimeContext(
        session_factory=AsyncMock(),
        user_id=uuid4(),
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=AsyncMock(),
        scope="global",
        post_data=None,
        ai_profile={},
    )
    ctx.reasoner_spec = ProviderSpec("OpenAI", "https://api.openai.com")
    ctx.reasoner_model = "gpt-4o-mini"
    ctx.reasoner_api_key = "test-key"
    return ctx


@pytest.mark.asyncio
async def test_workspace_agent_node_forwards_dialog_context_to_classifier_prompt() -> None:
    """agent-runtime-sprints §2.1: classifier must see dialog_context, not just
    the current turn, so it can route stylistic follow-ups to "finish" instead
    of a doomed re-search."""
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    state = {"user_text": "Покороче можешь?"}
    config = {
        "configurable": {
            "runtime_context": ctx,
            "dialog_context": "Пользователь: Какой охват у поста 3?\nАссистент: Охват 1200 просмотров.",
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"type": "finish"}',
    ) as mock_llm:
        result = await workspace_agent_node(state, config)

    assert result["current_tool"] == "finish"
    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Охват 1200 просмотров" in user_content
    assert "Покороче можешь?" in user_content


@pytest.mark.asyncio
async def test_workspace_agent_node_reuses_only_verified_context_refs() -> None:
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    ctx.known_context_refs = (
        {"ref": "note:n1", "kind": "note", "revision": 2},
    )
    state = {"user_text": "Раскрой подробнее материал из прошлого ответа"}
    config = {"configurable": {"runtime_context": ctx}}
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"reuse_context","context_refs":["note:n1","post:invented"]}'
        ),
    ):
        result = await workspace_agent_node(state, config)

    assert result["current_tool"] == "reuse_context"
    assert result["known_context_refs"] == ["note:n1"]
    assert result["search_query"] == ""


@pytest.mark.asyncio
async def test_workspace_contract_forces_recent_note_request_to_read() -> None:
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    contract = {
        "intent": "inspect_note",
        "corpus": "exact_note",
        "target": {"kind": "recent_note", "id": "n-new"},
        "requires_workspace": True,
        "search_query": "Открыть конкретную заметку n-new",
    }
    ctx.turn_contract = contract
    state = {
        "user_text": "Я создал заметку. Что дальше?",
        "turn_contract": contract,
    }
    config = {
        "configurable": {
            "runtime_context": ctx,
            "turn_contract": contract,
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"type": "finish", "search_query": "общий совет"}',
    ):
        result = await workspace_agent_node(state, config)

    assert result["current_tool"] == "read"
    assert result["search_query"] == "Открыть конкретную заметку n-new"


@pytest.mark.asyncio
async def test_answer_node_forwards_dialog_context_on_finish_path() -> None:
    """agent-runtime-sprints §2.1: a "finish" turn (no research pack) must still
    let the model answer from dialog_context — e.g. "покороче" needs the prior
    answer's text, not the empty-evidence refusal."""
    from app.services.agent.runtime.workspace_graph import REFUSAL_TEXT, answer_node

    ctx = _reasoner_ctx()
    state = {
        "user_text": "Покороче можешь?",
        "tool_call": {"type": "finish"},
        "evidence_ids": [],
        "rag_context": "",
    }
    config = {
        "configurable": {
            "runtime_context": ctx,
            "dialog_context": "Пользователь: Какой охват у поста 3?\nАссистент: Охват 1200 просмотров.",
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"answer": "1200.", "claims": []}',
    ) as mock_llm:
        result = await answer_node(state, config)

    # No research pack was produced, but the finish path never hits the
    # empty-evidence guard — that guard only fires when tool_call == "read".
    assert result["answer_text"] != REFUSAL_TEXT
    assert result["answer_text"] == "1200."
    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Охват 1200 просмотров" in user_content


@pytest.mark.asyncio
async def test_advisory_research_without_evidence_still_answers_with_full_context() -> None:
    from app.services.agent.runtime.workspace_graph import REFUSAL_TEXT, answer_node

    ctx = _reasoner_ctx()
    ctx.channel_profile = {
        "core": {"topic": "Архитектура пространственных систем"},
        "voice": {"tone": "Практичный"},
    }
    contract = build_turn_contract(
        user_text=(
            "Мне надо изменить профиль канала под новое направление в целом "
            "пространственной системы. Что посоветуешь?"
        ),
        history=[],
        scope="global",
    )
    state = {
        "user_text": contract["goal"],
        "turn_contract": contract,
        "tool_call": {"type": "read"},
        "evidence_ids": [],
        "rag_context": "",
    }
    config = {
        "configurable": {
            "runtime_context": ctx,
            "turn_contract": contract,
            "dialog_context": "Пользователь ранее описал пространственную систему.",
        }
    }
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"answer":"Сначала зафиксируйте новое позиционирование.","claims":[]}',
    ) as mock_llm:
        result = await answer_node(state, config)

    assert result["answer_text"] != REFUSAL_TEXT
    assert result["answer_text"] == "Сначала зафиксируйте новое позиционирование."
    messages = mock_llm.await_args.kwargs["messages"]
    assert "Архитектура пространственных систем" in messages[0]["content"]
    assert "Пользователь ранее описал" in messages[1]["content"]
    assert contract["goal"] in messages[1]["content"]


@pytest.mark.asyncio
async def test_answer_node_grounded_system_prompt_warns_against_narrowing_scope() -> None:
    """Regression for chat 63dfb9e4: a follow-up with a new predicate ("а
    сколько с изображениями?") must not be answered as if the evidence from
    the 2 previously-discussed notes covers the whole category. The grounded
    system prompt must tell the model to honour the full evidence set, not
    just the objects named in the dialog frame."""
    from app.services.agent.runtime.workspace_graph import answer_node

    ctx = _reasoner_ctx()
    state = {
        "user_text": "А сколько с изображениями?",
        "tool_call": {"type": "read"},
        "evidence_ids": ["/note/9fd458be/"],
        "rag_context": "note:9fd458be — нет вложений",
    }
    config = {"configurable": {"runtime_context": ctx}}
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"answer": "0", "claims": []}',
    ) as mock_llm:
        await answer_node(state, config)

    messages = mock_llm.await_args.kwargs.get("messages")
    system_content = messages[0]["content"]
    assert "Не сужай ответ до подмножества" in system_content


@pytest.mark.asyncio
async def test_answer_node_states_evidence_object_count_explicitly() -> None:
    """Regression for chat 63dfb9e4: research opened 4 notes (evidence covers
    all 4), but the answer only discussed the 2 named in the prior dialog turn
    ("заметки про систему") and silently dropped the other 2. Spelling out the
    object count in the user content — rather than relying on the model to
    count evidence blocks itself — is what should stop that drop."""
    from app.services.agent.runtime.workspace_graph import answer_node

    ctx = _reasoner_ctx()
    state = {
        "user_text": "А сколько заметок с изображениями?",
        "tool_call": {"type": "read"},
        "evidence_ids": ["/note/a/", "/note/b/", "/note/c/", "/note/d/"],
        "evidence_titles": ["Заметка A", "Заметка B", "Заметка C", "Заметка D"],
        "rag_context": "note:a — files=0\n\nnote:b — files=0\n\nnote:c — files=0\n\nnote:d — files=0",
    }
    config = {"configurable": {"runtime_context": ctx}}
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"answer": "0", "claims": []}',
    ) as mock_llm:
        await answer_node(state, config)

    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Evidence охватывает 4 объектов" in user_content
    assert "Заметка A" in user_content
    assert "Заметка D" in user_content


@pytest.mark.asyncio
async def test_planner_node_records_step_with_reasoning() -> None:
    """agent-runtime-sprints §3.1/§3.3: the planner node must accumulate a
    planner_steps entry carrying observations/reasoning/gap/tool/args, so
    the executor can emit it and a golden test can assert on it."""
    ctx = _reasoner_ctx()
    state = {
        "user_text": "Что в заметке n1?",
        "research_transcript": ["step 1: OpenPost → пост 721 notes=1"],
        "evidence_records": {},
        "step_count": 1,
        "max_steps": 4,
    }
    config = {"configurable": {"runtime_context": ctx}}
    scripted = (
        '{"observations": ["пост 721 notes=1"], "reasoning": "нужен текст заметки, '
        'метаданных мало", "gap": "note content missing", "tool": "OpenNote", '
        '"args": {"note_id": "n1", "post_id": "721"}}'
    )
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=scripted,
    ):
        result = await research_planner_node(state, config)

    steps = result["planner_steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["reasoning"] == "нужен текст заметки, метаданных мало"
    assert step["gap"] == "note content missing"
    assert step["tool"] == "OpenNote"
    assert step["args"] == {"note_id": "n1", "post_id": "721"}
    assert "repair_hint" not in step


@pytest.mark.asyncio
async def test_planner_node_flags_fabricated_observation_with_repair_hint() -> None:
    """agent-runtime-sprints §3.2: a planner step whose observation matches
    nothing in transcript/evidence gets a repair-hint appended to
    research_hints, which the planner already reads on the next turn."""
    ctx = _reasoner_ctx()
    state = {
        "user_text": "Что в заметке n1?",
        "research_transcript": ["step 1: OpenPost → пост 721 notes=1"],
        "evidence_records": {},
        "research_hints": [],
        "step_count": 1,
        "max_steps": 4,
    }
    config = {"configurable": {"runtime_context": ctx}}
    scripted = (
        '{"observations": ["выдуманная метрика роста 300%"], "reasoning": "...",'
        ' "gap": "...", "tool": "OpenNote", "args": {"note_id": "n1"}}'
    )
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=scripted,
    ):
        result = await research_planner_node(state, config)

    step = result["planner_steps"][0]
    assert "repair_hint" in step
    assert any("cosmetic_observations" in hint for hint in result["research_hints"])


@pytest.mark.asyncio
async def test_planner_node_emits_unparsed_repair_hint_on_invalid() -> None:
    """agent-invalid-loop: an unparseable planner emission (e.g. JSON truncated
    at max_tokens) becomes tool=Invalid, and must append an unparsed_output
    repair hint so the next turn self-corrects instead of looping the same
    broken output until the step budget drains."""
    ctx = _reasoner_ctx()
    state = {
        "user_text": "Про что мне написать пост?",
        "research_transcript": ["step 1: ListPosts → 5 постов"],
        "evidence_records": {},
        "research_hints": [],
        "step_count": 1,
        "max_steps": 10,
    }
    config = {"configurable": {"runtime_context": ctx}}
    # Truncated mid-object — no closing brace, unparseable (the real failure).
    truncated = '{"observations": ["5 постов"], "reasoning": "нужно открыть", "tool": "OpenNote", "args":'
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=truncated,
    ):
        result = await research_planner_node(state, config)

    assert result["planner_steps"][0]["tool"] == "Invalid"
    assert any("unparsed_output" in hint for hint in result["research_hints"])


@pytest.mark.asyncio
async def test_reasoning_influences_tool_choice_via_scripted_planner() -> None:
    """agent-runtime-sprints §3.1 exit criterion: the planner's stated
    reasoning/gap correspond to the tool it actually picks — scripted here
    (no live LLM), but this is the wiring golden would assert on."""
    ctx = _reasoner_ctx()
    state = {
        "user_text": "Что в заметке 721?",
        "research_transcript": ["step 1: OpenPost → пост 721 notes=1"],
        "evidence_records": {},
        "step_count": 1,
        "max_steps": 4,
    }
    config = {"configurable": {"runtime_context": ctx}}
    scripted = (
        '{"observations": ["пост 721 notes=1"], "reasoning": "нужен текст заметки '
        '721, метаданных мало", "gap": "note content missing", "tool": "OpenNote", '
        '"args": {"note_id": "n1", "post_id": "721"}}'
    )
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=scripted,
    ):
        result = await research_planner_node(state, config)

    step = result["planner_steps"][0]
    assert "заметки" in step["reasoning"]
    assert step["tool"] == "OpenNote"
    assert result["tool_action"]["tool"] == "OpenNote"


@pytest.mark.asyncio
async def test_run_research_graph_without_llm_uses_context_blocks() -> None:
    session = AsyncMock()
    session.commit = AsyncMock()

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    agent_state = AgentState(
        session=session,
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        embedding_backend=AsyncMock(),
    )
    cite = NoteCite(path="/note/global/n1/", title="n1")
    agent_state.context_blocks.append((cite, "seeded content"))

    ctx = RuntimeContext(
        session_factory=_Factory(),
        user_id=agent_state.user_id,
        user=None,
        tenant_key=None,
        settings=Settings(),
        embedding_backend=agent_state.embedding_backend,
        scope="global",
        post_data=None,
        ai_profile={},
        agent_tool_state=agent_state,
    )

    with (
        patch("app.services.ai.llm.complete_chat_completion", new_callable=AsyncMock),
        patch(
            "app.services.agent.research.graph._workspace_inventory",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "app.services.ai.rag_tools.retrieve_for_chat",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await run_research_graph(
            ctx,
            user_text="test",
            max_steps=1,
            spec=None,
            model="",
            api_key="",
        )

    assert "seeded content" in result.rag_context or result.stopped_reason

    # Deterministic graders must pass on real graph output, not just fixtures
    # (agent-runtime-sprints Фаза 0): no dangling citation, no claim on empty pack.
    from app.services.agent.runtime.graders import grade_run

    report = grade_run(
        {
            "rag_context": result.rag_context,
            "evidence_ids": list(result.evidence_ids or []),
            "evidence_records": {eid: {} for eid in (result.evidence_ids or [])},
            "claims": [],
            "answer_text": result.rag_context,
            "stopped_reason": result.stopped_reason,
        }
    )
    assert report.ok, report.failures


@pytest.mark.asyncio
async def test_workspace_agent_node_forwards_post_text_for_edit_intent() -> None:
    """Bug fix: the classifier could not produce a correct edit_post payload
    because it never saw the post it was asked to edit — it silently fell
    back to "read"/"finish" instead of proposing edit_post."""
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    ctx.scope = "post"
    ctx.post_data = {"id": "post-1", "text": "Запуск 2 июля в 2 часа."}
    state = {"user_text": "убери цифру 2 из текста"}
    config = {"configurable": {"runtime_context": ctx}}

    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=(
            '{"type": "post_proposal", "command": "edit_post", '
            '"payload": {"post_id": "post-1", "patch": {"text": "Запуск июля в часа."}}}'
        ),
    ) as mock_llm:
        result = await workspace_agent_node(state, config)

    messages = mock_llm.await_args.kwargs.get("messages")
    user_content = messages[1]["content"]
    assert "Текущий пост (id=post-1)" in user_content
    assert "Запуск 2 июля в 2 часа." in user_content
    assert result["current_tool"] == "post_proposal"
    assert result["tool_call"]["command"] == "edit_post"


@pytest.mark.asyncio
async def test_workspace_agent_node_skips_post_block_when_no_post_data() -> None:
    """Global-scope runs (no post_data) must not gain a "Текущий пост" block."""
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    state = {"user_text": "какой охват у поста 3?"}
    config = {"configurable": {"runtime_context": ctx}}

    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value='{"type": "read"}',
    ) as mock_llm:
        await workspace_agent_node(state, config)

    messages = mock_llm.await_args.kwargs.get("messages")
    assert "Текущий пост (id=" not in messages[1]["content"]


@pytest.mark.asyncio
async def test_global_edit_proposal_is_normalized_to_required_workspace_read() -> None:
    """A classifier mistake in global chat must search, never fall through to
    a text-only answer or create a targetless mutation proposal."""
    from app.services.agent.runtime.workspace_graph import workspace_agent_node

    ctx = _reasoner_ctx()
    state = {"user_text": "Измени мою запланированную серию"}
    config = {"configurable": {"runtime_context": ctx}}
    with patch(
        "app.services.ai.llm.complete_chat_completion",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"post_proposal","command":"edit_post","payload":{},'
            '"search_query":"запланированная серия"}'
        ),
    ):
        result = await workspace_agent_node(state, config)

    assert result["current_tool"] == "read"
    assert result["tool_call"]["type"] == "read"
    assert result["tool_call"]["global_mutation_fallback"] is True
    assert result["tool_call"]["requested_command"] == "edit_post"
    required = {
        item["kind"]
        for item in result["turn_contract"]["source_requirements"]
        if item.get("required")
    }
    assert required == {"notes", "posts"}


def test_all_workspace_outcomes_research_before_terminal_dispatch() -> None:
    from app.services.agent.runtime.workspace_graph import (
        route_after_research,
        route_workspace_call,
    )

    for call_type in ("read", "finish", "post_proposal", "media_proposal"):
        assert route_workspace_call({"tool_call": {"type": call_type}}) == "seed"
    assert route_workspace_call({"current_tool": "finish", "direct_finish": True}) == "answer"
    assert route_workspace_call({"current_tool": "read", "direct_finish": True}) == "seed"

    assert route_after_research({"tool_call": {"type": "finish"}}) == "answer"
    assert route_after_research(
        {"scope": "post", "tool_call": {"type": "post_proposal", "command": "edit_post"}}
    ) == "build_action_proposal"
    assert route_after_research(
        {"scope": "post", "tool_call": {"type": "post_proposal", "command": "schedule_post"}}
    ) == "resolve_schedule_time"
    assert route_after_research(
        {"scope": "global", "tool_call": {"type": "post_proposal", "command": "edit_post"}}
    ) == "answer"
    assert route_after_research(
        {"tool_call": {"type": "media_proposal"}}
    ) == "build_media_proposal"


@pytest.mark.asyncio
async def test_media_proposal_keeps_researched_workspace_context() -> None:
    from app.services.agent.runtime.workspace_graph import build_media_proposal_node

    ctx = _reasoner_ctx()
    ctx.settings.agent_media_enabled = True
    ctx.ai_profile = {
        "imageGenerationModels": [
            {"id": "img-1", "provider": "OpenAI", "model": "dall-e-3", "active": True}
        ]
    }
    state = {
        "run_id": str(uuid4()),
        "user_id": str(ctx.user_id),
        "tool_call": {"type": "media_proposal", "kind": "image", "prompt": "Обложка серии"},
        "evidence_pack_schema": "workspace.evidence-pack/v1",
        "evidence_pack": {},
        "rag_context": "Проверенная серия: публикации запланированы на пятницу.",
    }
    result = await build_media_proposal_node(
        state,
        {"configurable": {"runtime_context": ctx}},
    )

    proposal = (result["interrupt"] or {}).get("proposal") or {}
    assert proposal["workspace_context"] == "Проверенная серия: публикации запланированы на пятницу."
