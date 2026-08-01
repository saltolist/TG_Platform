from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.services.agent.runtime.budget import PhaseDeadlineExceeded
from app.services.agent.runtime.turn_contract import (
    RunBudget,
    SourceBudget,
    build_turn_contract,
    covered_source_ids,
    evidence_matches_source,
    missing_required_sources,
)
from app.services.agent.runtime.workspace_graph import workspace_agent_node
from app.services.agent.runtime.workspace_graph import WORKSPACE_SYSTEM


def test_explicit_links_are_authoritative_multi_targets_and_never_semantic_hits() -> None:
    contract = build_turn_contract(
        user_text="Сопоставь /note/global/rules-1/ с /post/post-1/ и /post/post-2/",
        history=[],
        scope="global",
    )

    target_contract = contract["target_contract"]
    assert target_contract["target_mode"] == "set"
    assert [(item["kind"], item["id"]) for item in target_contract["targets"]] == [
        ("note", "rules-1"),
        ("post", "post-1"),
        ("post", "post-2"),
    ]
    assert all(item["resolved_by"] == "explicit_link" for item in target_contract["targets"])
    assert {event["target_id"] for event in target_contract["resolution_events"]} == {
        "rules-1", "post-1", "post-2"
    }
    assert all(source["scope"]["mode"] == "targets" for source in contract["source_requirements"])


def test_planner_prompt_omits_explicitly_excluded_referents_from_resolved_goal() -> None:
    assert "назови только активный референт" in WORKSPACE_SYSTEM
    assert "не упоминай даже с отрицанием" in WORKSPACE_SYSTEM
    assert "вырази обе уже запрошенные стороны как явные retrieval predicates" in WORKSPACE_SYSTEM
    assert "что указал draft/proposed record" in WORKSPACE_SYSTEM


def test_open_post_is_a_target_with_open_object_provenance() -> None:
    contract = build_turn_contract(
        user_text="Как тебе этот пост?",
        history=[],
        scope="post",
        open_post={"id": "post-open", "text": "Заголовок\nТекст"},
    )

    assert contract["target_contract"]["target_mode"] == "mixed"
    assert contract["target_contract"]["corpora"] == [{
        "kind": "workspace",
        "role": "context",
        "scope": "current_user",
    }]
    assert contract["target_contract"]["targets"] == [
        {
            "kind": "post",
            "id": "post-open",
            "role": "subject",
            "authoritative": True,
            "confidence": 1.0,
                "resolved_by": "open_object",
                "source_turn_id": None,
                "source_user_text": None,
                "title": "Заголовок",
            "parent_post_id": None,
            "content": None,
        }
    ]


def test_ledger_multi_target_and_equal_candidate_ambiguity() -> None:
    ledger = (
        SimpleNamespace(
            turn_id="turn-1",
            entities=(
                SimpleNamespace(entity_type="post", post_id="p1", title="P1"),
                SimpleNamespace(entity_type="post", post_id="p2", title="P2"),
            ),
        ),
    )
    multi = build_turn_contract(
        user_text="Что общего у этих постов?", history=[], scope="global", dialog_ledger=ledger
    )
    assert multi["target_contract"]["target_mode"] == "set"
    assert [item["id"] for item in multi["target_contract"]["targets"]] == ["p1", "p2"]

    ambiguous = build_turn_contract(
        user_text="Что в этом посте?", history=[], scope="global", dialog_ledger=ledger
    )
    assert ambiguous["target_contract"]["target_mode"] == "ambiguous"
    assert ambiguous["target_contract"]["ambiguities"][0]["candidate_ids"] == ["p1", "p2"]


def test_catalog_entity_set_resolves_referential_followup_to_the_same_objects() -> None:
    ledger = (
        SimpleNamespace(
            turn_id="turn-catalog",
            entities=(
                SimpleNamespace(
                    entity_type="entity_set",
                    members=tuple(
                        {"kind": "post", "id": f"p{index}", "title": f"P{index}"}
                        for index in range(1, 6)
                    ),
                ),
            ),
        ),
    )
    contract = build_turn_contract(
        user_text="Что это за посты?", history=[], scope="global", dialog_ledger=ledger
    )

    assert contract["target_contract"]["target_mode"] == "set"
    assert [item["id"] for item in contract["target_contract"]["targets"]] == [
        "p1", "p2", "p3", "p4", "p5"
    ]
    assert contract["execution_mode"] == "fast"


def test_required_and_optional_sources_have_independent_contracts() -> None:
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Сколько постов и изображений в workspace?", history=[], scope="global"
    )
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts", "images"],
        classifier_requires_evidence=True,
    )
    sources = {source["kind"]: source for source in contract["source_requirements"]}
    assert sources["posts"]["required"] is True
    assert sources["notes"]["required"] is False
    assert sources["notes"]["evidence_granularity"] == "semantic_card"
    assert sources["images"]["required"] is True
    assert contract["budgets"]["search_calls"] >= sum(
        source["budget"]["search_calls"] for source in contract["source_requirements"]
    )
    assert missing_required_sources(contract, {sources["posts"]["source_id"]}) == (
        sources["images"]["source_id"],
    )
    assert missing_required_sources(
        contract, {sources["posts"]["source_id"], sources["images"]["source_id"]}
    ) == ()


def test_contract_revision_and_goal_are_carried_across_referential_turn() -> None:
    prior = build_turn_contract(user_text="Прочитай /note/global/n1/", history=[], scope="global")
    current = build_turn_contract(
        user_text="А что в ней главное?",
        history=[],
        scope="global",
        dialog_ledger=(SimpleNamespace(turn_id="turn-1", entities=()),),
        prior_contract=prior,
    )
    assert current["revision"] == prior["revision"] + 1
    assert current["parent_revision"] == prior["revision"]
    assert prior["goal"] in current["goal"]


def test_open_post_precedes_unrelated_ledger_for_post_scope() -> None:
    ledger = (
        SimpleNamespace(
            turn_id="turn-note",
            entities=(
                SimpleNamespace(entity_type="note", note_id="old-note", title="Old note"),
            ),
        ),
    )
    current_post = build_turn_contract(
        user_text="Добавь цифру 3 в конце этого поста",
        history=[],
        scope="post",
        open_post={"id": "current-post", "text": "Draft"},
        dialog_ledger=ledger,
    )
    target = current_post["target_contract"]["targets"][0]
    assert (target["kind"], target["id"], target["resolved_by"]) == (
        "post",
        "current-post",
        "open_object",
    )

    current_note = build_turn_contract(
        user_text="Что там в этой заметке?",
        history=[],
        scope="post",
        open_post={"id": "current-post", "text": "Draft"},
        dialog_ledger=ledger,
    )
    note_target = current_note["target_contract"]["targets"][0]
    assert (note_target["kind"], note_target["id"], note_target["resolved_by"]) == (
        "note",
        "old-note",
        "dialog_ledger",
    )


def test_post_scope_keeps_workspace_corpus_alongside_open_post() -> None:
    contract = build_turn_contract(
        user_text="Этот пост получился не слишком большим, относительно других постов?",
        history=[],
        scope="post",
        open_post={"id": "current-post", "text": "Draft"},
    )

    target = contract["target_contract"]
    assert target["target_mode"] == "mixed"
    assert target["corpora"] == [{
        "kind": "workspace",
        "role": "context",
        "scope": "current_user",
    }]
    sources = {item["source_id"]: item for item in contract["source_requirements"]}
    assert sources["target-post-1"]["required"] is True
    assert sources["workspace-posts"]["kind"] == "posts"
    assert sources["workspace-notes"]["kind"] == "notes"


def test_post_scope_classifier_applies_complete_coverage_to_workspace_only() -> None:
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Этот пост получился не слишком большим, относительно других постов?",
        history=[],
        scope="post",
        open_post={"id": "current-post", "text": "Draft"},
    )
    classified = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[{
            "kind": "posts",
            "coverage": "complete",
            "evidence_granularity": "catalog",
        }],
    )

    sources = {item["source_id"]: item for item in classified["source_requirements"]}
    assert sources["target-post-1"]["required"] is True
    assert sources["target-post-1"]["coverage"] == "relevant"
    assert sources["target-post-1"]["evidence_granularity"] == "full_text"
    assert sources["workspace-posts"]["required"] is True
    assert sources["workspace-posts"]["coverage"] == "complete"
    assert sources["workspace-posts"]["evidence_granularity"] == "catalog"
    assert sources["workspace-notes"]["required"] is False


def test_v1_flag_is_a_real_rollback() -> None:
    contract = build_turn_contract(
        user_text="Прочитай /note/global/n1/", history=[], scope="global", v2_enabled=False
    )
    assert contract["version"] == 1
    assert "target_contract" not in contract


def test_schema_rejects_local_budget_overrun_and_mutation() -> None:
    with pytest.raises(ValidationError):
        SourceBudget(search_calls=0, rewrite_calls=1, candidate_limit=1, deep_reads=0)
    with pytest.raises(ValidationError):
        RunBudget(
            soft_deadline_ms=100,
            hard_deadline_ms=50,
            planner_calls=0,
            search_calls=0,
            search_rewrites_per_intent=0,
            deep_reads=0,
            tool_calls=0,
        )
    with pytest.raises(ValidationError):
        RunBudget(
            soft_deadline_ms=100,
            hard_deadline_ms=200,
            bootstrap_deadline_ms=101,
            planner_calls=0,
            search_calls=0,
            search_rewrites_per_intent=0,
            deep_reads=0,
            tool_calls=0,
        )


def test_scope_and_freshness_are_rechecked_at_evidence_boundary() -> None:
    source = {
        "kind": "notes",
        "scope": {"mode": "targets", "target_ids": ["note-7"]},
        "freshness": {"mode": "exact_revision", "revision": 3},
    }
    record = {
        "kind": "note_chunk",
        "metadata": {"revision": 3},
    }
    assert evidence_matches_source(source, evidence_id="/note/global/note-7/", record=record)
    assert not evidence_matches_source(source, evidence_id="/note/global/other/", record=record)
    assert not evidence_matches_source(
        source,
        evidence_id="/note/global/note-7/",
        record={"kind": "note_chunk", "metadata": {"revision": 2}},
    )


def test_semantic_cards_only_cover_their_own_object_kind() -> None:
    contract = {
        "source_requirements": [
            {
                "source_id": "workspace-notes",
                "kind": "notes",
                "required": True,
                "scope": {"mode": "corpus", "corpus": "workspace"},
                "freshness": {"mode": "latest_available"},
                "min_evidence": 1,
                "evidence_granularity": "semantic_card",
            },
            {
                "source_id": "workspace-posts",
                "kind": "posts",
                "required": True,
                "scope": {"mode": "corpus", "corpus": "workspace"},
                "freshness": {"mode": "latest_available"},
                "min_evidence": 1,
                "evidence_granularity": "semantic_card",
            },
        ]
    }
    post_cards = {
        f"/post/p{index}/": {
            "kind": "semantic_card",
            "source_ref": f"post:p{index}",
            "metadata": {"ref": f"post:p{index}"},
        }
        for index in range(5)
    }

    covered = covered_source_ids(contract, post_cards)

    assert covered == frozenset({"workspace-posts"})
    assert missing_required_sources(contract, covered) == ("workspace-notes",)

    covered = covered_source_ids(
        contract,
        {
            **post_cards,
            "/note/global/series/": {
                "kind": "semantic_card",
                "source_ref": "note:series",
                "metadata": {"ref": "note:series"},
            },
        },
    )
    assert covered == frozenset({"workspace-notes", "workspace-posts"})


def test_required_source_gap_blocks_ready_but_optional_gap_does_not() -> None:
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Сколько постов и изображений в workspace?", history=[], scope="global"
    )
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["posts"],
        classifier_requires_evidence=True,
    )
    sources = {source["kind"]: source for source in contract["source_requirements"]}
    records = {
        "/posts/": {
            "kind": "catalog",
            "metadata": {},
        }
    }
    covered = covered_source_ids(contract, records)
    assert sources["posts"]["source_id"] in covered
    assert missing_required_sources(contract, covered) == ()


@pytest.mark.asyncio
async def test_exact_link_skips_classifier_llm() -> None:
    contract = build_turn_contract(
        user_text="Прочитай /note/global/n1/", history=[], scope="global"
    )
    ctx = SimpleNamespace(
        reasoner_spec=object(),
        reasoner_model="planner",
        reasoner_api_key="secret",
        turn_contract=contract,
        scope="global",
        post_data=None,
    )
    state = {"user_text": "Прочитай /note/global/n1/", "turn_contract": contract}
    with patch(
        "app.services.ai.llm.complete_chat_completion", new_callable=AsyncMock
    ) as mock_llm:
        result = await workspace_agent_node(
            state,
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert result["tool_call"]["type"] == "read"
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_implicit_resolver_set_keeps_classifier_for_fidelity() -> None:
    contract = build_turn_contract(
        user_text="Про что они?",
        history=[],
        scope="global",
        dialog_ledger=(
            SimpleNamespace(
                turn_id="turn-set",
                entities=(
                    SimpleNamespace(
                        entity_type="entity_set",
                        members=({"kind": "post", "id": "p1", "title": "P1"},
                                 {"kind": "post", "id": "p2", "title": "P2"}),
                    ),
                ),
            ),
        ),
    )
    ctx = SimpleNamespace(
        reasoner_spec=object(),
        reasoner_model="planner",
        reasoner_api_key="secret",
        turn_contract=contract,
        scope="global",
        post_data=None,
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"read","required_sources":["posts"],'
            '"source_requirements":[{"kind":"posts","coverage":"complete",'
            '"evidence_granularity":"semantic_card"}],"search_query":"темы постов"}'
        ),
    ) as mock_llm:
        result = await workspace_agent_node(
            {"user_text": "Про что они?", "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    mock_llm.assert_awaited_once()
    assert result["turn_contract"]["source_requirements"]
    assert all(
        item["evidence_granularity"] == "semantic_card"
        for item in result["turn_contract"]["source_requirements"]
    )
    assert all(
        item["coverage"] == "relevant"
        for item in result["turn_contract"]["source_requirements"]
    )


@pytest.mark.asyncio
async def test_classifier_cannot_expand_self_contained_question_without_dialog() -> None:
    question = "Can support safely leave right after midnight?"
    contract = build_turn_contract(user_text=question, history=[], scope="global")
    ctx = SimpleNamespace(
        reasoner_spec=object(),
        reasoner_model="planner",
        reasoner_api_key="secret",
        turn_contract=contract,
        scope="global",
        post_data=None,
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"read","required_sources":["notes"],'
            '"search_query":"Can support leave, or is continued coverage required?"}'
        ),
    ):
        result = await workspace_agent_node(
            {"user_text": question, "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert result["search_query"] == question
    assert all(
        source["query_goal"] == question
        for source in result["turn_contract"]["source_requirements"]
    )


@pytest.mark.asyncio
async def test_classifier_promotes_only_semantically_required_source() -> None:
    contract = build_turn_contract(
        user_text="Сколько у меня постов?", history=[], scope="global"
    )
    ctx = SimpleNamespace(
        reasoner_spec=object(),
        reasoner_model="planner",
        reasoner_api_key="secret",
        turn_contract=contract,
        scope="global",
        post_data=None,
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"read","required_sources":["posts"],'
            '"search_query":"полный каталог постов пользователя"}'
        ),
    ):
        result = await workspace_agent_node(
            {"user_text": "Сколько у меня постов?", "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    sources = {item["kind"]: item for item in result["turn_contract"]["source_requirements"]}
    assert result["tool_call"]["type"] == "read"
    assert result["search_query"] == "Сколько у меня постов?"
    assert sources["posts"]["required"] is True
    assert sources["notes"]["required"] is False
    assert sources["notes"]["evidence_granularity"] == "semantic_card"
    assert result["turn_contract"]["answerability_without_evidence"] is False


@pytest.mark.asyncio
async def test_classifier_phase_deadline_falls_back_to_typed_workspace_sources() -> None:
    question = "Какие объекты описаны в моем workspace?"
    contract = build_turn_contract(user_text=question, history=[], scope="global")
    ctx = SimpleNamespace(
        reasoner_spec=object(),
        reasoner_model="planner",
        reasoner_api_key="secret",
        turn_contract=contract,
        scope="global",
        post_data=None,
        deadline_monotonic=None,
        llm_client=None,
        llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        side_effect=PhaseDeadlineExceeded("slow bootstrap"),
    ) as classifier:
        result = await workspace_agent_node(
            {"user_text": question, "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert classifier.await_args.kwargs["phase_timeout_s"] == 10.0
    assert result["tool_call"]["type"] == "read"
    assert result["tool_call"]["bootstrap_fallback"] == "phase_deadline"
    assert result["search_query"] == question
    sources = result["turn_contract"]["source_requirements"]
    assert {source["kind"] for source in sources} == {"notes", "posts"}
    assert all(source["required"] is True for source in sources)
    assert result["turn_contract"]["answerability_without_evidence"] is False


@pytest.mark.asyncio
async def test_classifier_finish_skips_optional_workspace_enrichment() -> None:
    contract = build_turn_contract(user_text="Идти тестировать?", history=[], scope="global")
    ctx = SimpleNamespace(
        reasoner_spec=object(), reasoner_model="planner", reasoner_api_key="secret",
        turn_contract=contract, scope="global", post_data=None,
        deadline_monotonic=None, llm_client=None, llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"finish","required_sources":[],'
            '"search_query":"тестирование текущего направления"}'
        ),
    ) as classifier:
        result = await workspace_agent_node(
            {"user_text": "Идти тестировать?", "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert result["tool_call"]["type"] == "finish"
    assert result["direct_finish"] is True
    assert result["turn_contract"]["answerability_without_evidence"] is True
    assert {
        item["kind"] for item in result["turn_contract"]["source_requirements"]
    } == {"notes", "posts"}
    assert all(
        item["evidence_granularity"] == "semantic_card"
        for item in result["turn_contract"]["source_requirements"]
    )
    classifier_prompt = classifier.await_args.kwargs["messages"][1]["content"]
    assert "requires_workspace" not in classifier_prompt
    assert "source_requirements" not in classifier_prompt


@pytest.mark.asyncio
async def test_v2_read_without_required_sources_remains_optional_enrichment() -> None:
    contract = build_turn_contract(user_text="Идти тестировать?", history=[], scope="global")
    ctx = SimpleNamespace(
        reasoner_spec=object(), reasoner_model="planner", reasoner_api_key="secret",
        turn_contract=contract, scope="global", post_data=None,
        deadline_monotonic=None, llm_client=None, llm_metrics=[],
    )
    with patch(
        "app.services.agent.runtime.workspace_graph.call_llm_with_deadline",
        new_callable=AsyncMock,
        return_value=(
            '{"type":"read","requires_evidence":false,"required_sources":[],'
            '"search_query":"стоит ли переходить к тестированию"}'
        ),
    ):
        result = await workspace_agent_node(
            {"user_text": "Идти тестировать?", "turn_contract": contract},
            {"configurable": {"runtime_context": ctx, "turn_contract": contract}},
        )

    assert result["tool_call"]["type"] == "read"
    assert result["turn_contract"]["answerability_without_evidence"] is True
    assert all(
        item["required"] is False
        for item in result["turn_contract"]["source_requirements"]
    )
    assert all(
        item["evidence_granularity"] == "semantic_card"
        for item in result["turn_contract"]["source_requirements"]
    )


def test_classifier_keeps_every_explicit_factual_source() -> None:
    from app.services.agent.runtime.workspace_graph import _apply_classifier_source_policy

    contract = build_turn_contract(
        user_text="Сопоставь заметки с опубликованными постами", history=[], scope="global"
    )
    contract = _apply_classifier_source_policy(
        contract,
        required_sources=["notes", "posts"],
        classifier_requires_evidence=True,
        classified_source_requirements=[
            {
                "kind": "notes",
                "coverage": "relevant",
                "evidence_granularity": "semantic_card",
            },
            {
                "kind": "posts",
                "coverage": "relevant",
                "evidence_granularity": "full_text",
            },
        ],
    )

    sources = {source["kind"]: source for source in contract["source_requirements"]}
    assert set(sources) == {"notes", "posts"}
    assert all(source["required"] for source in sources.values())
    assert sources["notes"]["evidence_granularity"] == "semantic_card"
    assert sources["posts"]["evidence_granularity"] == "full_text"


def test_phase2_golden_target_accuracy_is_at_least_95_percent() -> None:
    note_ledger = (
        SimpleNamespace(
            turn_id="turn-note",
            entities=(SimpleNamespace(entity_type="note", note_id="ledger-note", title="Ledger"),),
        ),
    )
    posts_ledger = (
        SimpleNamespace(
            turn_id="turn-posts",
            entities=(
                SimpleNamespace(entity_type="post", post_id="ledger-p1", title="P1"),
                SimpleNamespace(entity_type="post", post_id="ledger-p2", title="P2"),
            ),
        ),
    )
    cases = [
        ({"user_text": "Открой /note/global/n1/"}, ("exact", ["n1"])),
        ({"user_text": "Открой /note/post/p1/n2/"}, ("exact", ["n2"])),
        ({"user_text": "Открой /post/p1/"}, ("exact", ["p1"])),
        ({"user_text": "Сравни /post/p1/ и /post/p2/"}, ("set", ["p1", "p2"])),
        ({"user_text": "Сравни /note/global/n1/ и /post/p1/"}, ("set", ["n1", "p1"])),
        ({"user_text": "Проверь пост 123"}, ("exact", ["123"])),
        ({"user_text": "Проверь заметку note-1234"}, ("exact", ["note-1234"])),
        ({"user_text": "Открой https://app.test/post/url-post/"}, ("exact", ["url-post"])),
        ({"user_text": "Открой https://app.test/note/global/url-note/"}, ("exact", ["url-note"])),
        ({"user_text": "Сравни /post/p1/ и снова /post/p1/"}, ("exact", ["p1"])),
        ({"user_text": "Как тебе этот пост?", "scope": "post", "open_post": {"id": "open-p"}}, ("mixed", ["open-p"])),
        ({"user_text": "Я создал заметку. Что дальше?", "recent_note": {"id": "recent-n", "title": "N"}}, ("exact", ["recent-n"])),
        ({"user_text": "Что там в этой заметке?", "dialog_ledger": note_ledger}, ("exact", ["ledger-note"])),
        ({"user_text": "Что общего у этих постов?", "dialog_ledger": posts_ledger}, ("set", ["ledger-p1", "ledger-p2"])),
        ({"user_text": "Что в этом посте?", "dialog_ledger": posts_ledger}, ("ambiguous", [])),
        ({"user_text": "Что написано в заметках workspace?"}, ("corpus", [])),
        ({"user_text": "Не пересекается ли он с имеющимися постами?", "history": [{"role": "ai", "text": "Пост 4 — тема"}]}, ("corpus", None)),
        ({"user_text": "Напиши этот пост в стиле моих постов", "history": [{"role": "ai", "text": "Пост 3 — тема"}]}, ("corpus", None)),
        ({"user_text": "Проверь post 12345678"}, ("exact", ["12345678"])),
        ({"user_text": "Сравни /note/global/a/ и /note/global/b/"}, ("set", ["a", "b"])),
    ]
    correct = 0
    for raw, (expected_mode, expected_ids) in cases:
        kwargs = {"history": [], "scope": "global", **raw}
        contract = build_turn_contract(**kwargs)
        actual = contract["target_contract"]
        ids = [item["id"] for item in actual["targets"]]
        if actual["target_mode"] == expected_mode and (expected_ids is None or ids == expected_ids):
            correct += 1

    assert correct / len(cases) >= 0.95


@pytest.mark.asyncio
async def test_versioned_contract_round_trips_through_dialog_ledger(writer_user) -> None:
    from tests.conftest import TestSessionLocal
    from app.services.ai.rag_dialog_ledger import (
        TurnSnapshot,
        append_turn,
        clear_ledger,
        load_ledger,
    )

    contract = build_turn_contract(
        user_text="Прочитай /note/global/round-trip-note/", history=[], scope="global"
    )
    key = "phase2:round-trip"
    async with TestSessionLocal() as session:
        await clear_ledger(session, user_id=writer_user.id, chat_key=key)
        await append_turn(
            session,
            user_id=writer_user.id,
            chat_key=key,
            snapshot=TurnSnapshot(
                turn_id="36b8c7d4-9f20-4d28-88a2-6d190e14bf10",
                recorded_at="2026-07-19T00:00:00+00:00",
                user_text="Прочитай /note/global/round-trip-note/",
                target_post_id=None,
                target_evidence_gap=None,
                entities=(),
                turn_contract=contract,
            ),
        )
        await session.commit()
        loaded = await load_ledger(session, user_id=writer_user.id, chat_key=key)

    assert loaded[-1].turn_contract["revision"] == contract["revision"]
    assert loaded[-1].turn_contract["target_contract"]["targets"][0]["id"] == "round-trip-note"
