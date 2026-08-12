from app.services.agent.runtime.message_context import (
    build_message_context_manifest,
    validate_manifest,
)
from app.services.agent.runtime.referent_resolution import (
    candidate_envelope,
    resolve_from_candidates,
    validate_resolution,
)
from app.services.agent.runtime.output_contract import validate_answer_output
from app.services.agent.runtime.turn_contract import build_turn_contract
from app.services.ai.rag_dialog_ledger import LedgerEntity, TurnSnapshot


def _pack():
    return {
        "schema": "workspace.evidence-pack/v2",
        "evidence_ids": ["card-1", "post-full"],
        "items": [
            {
                "id": "card-1",
                "kind": "semantic_card",
                "title": "Первый",
                "citation_path": "/post/p1/",
                "source_ref": "post:p1",
                "content": "Тема",
                "fidelity": "semantic_card",
                "provenance": {"source_revision": 12, "ref": "post:p1"},
            },
            {
                "id": "post-full",
                "kind": "post_text",
                "title": "Второй",
                "citation_path": "/post/p2/",
                "source_ref": "post:p2",
                "content": "Полный текст",
                "fidelity": "full_text",
                "metadata": {"card_text": "Короткая карточка второго поста"},
                "provenance": {"source_revision": 3, "ref": "post:p2"},
            },
            {
                "id": "catalog",
                "kind": "catalog",
                "title": "Каталог",
                "citation_path": "/posts/",
                "source_ref": "/posts/",
                "content": "служебный",
                "fidelity": "catalog",
                "metadata": {"members": [
                    {"kind": "post", "id": "p1"},
                    {"kind": "post", "id": "p2"},
                ]},
            },
        ],
    }


def test_manifest_only_cites_validated_claims_and_excludes_catalog():
    manifest = build_message_context_manifest(
        message_id="message-1",
        run_id="run-1",
        source_turn_id="run-1",
        evidence_pack=_pack(),
        claims=[{"text": "Тема", "evidence_ids": ["card-1"]}],
        used_context_refs=["post:p2", "post:unknown"],
        answer_text="Ответ",
    )
    assert manifest.cited_evidence == ("card-1",)
    assert {item.ref for item in manifest.context_refs} == {"post:p1", "post:p2"}
    assert not any(item.kind == "catalog" for item in manifest.context_refs)
    assert manifest.reference_sets == ()
    refs = {item.ref: item for item in manifest.context_refs}
    assert refs["post:p1"].role == "claim_support"
    assert refs["post:p2"].role == "used_context"
    assert refs["post:p2"].summary == "Короткая карточка второго поста"
    assert manifest.artifacts[0].ref.startswith("artifact:sha256:")
    assert validate_manifest(manifest.model_dump(mode="json")) == []

    catalog_manifest = build_message_context_manifest(
        message_id="message-2",
        run_id="run-2",
        source_turn_id="run-2",
        evidence_pack=_pack(),
        claims=[{"text": "Два поста", "evidence_ids": ["catalog"]}],
    )
    assert {item.ref for item in catalog_manifest.context_refs} == {"post:p1", "post:p2"}
    assert all(item.role == "claim_support" for item in catalog_manifest.context_refs)


def test_referent_resolution_handles_subset_and_rejects_invented_ids():
    candidates = [
        {"ref": f"post:p{i}", "kind": "post", "position": i, "source_set_ref": "turn-1:posts"}
        for i in range(1, 6)
    ]
    result = resolve_from_candidates("Второй и четвёртый", candidates)
    assert result["references"][0]["selection_mode"] == "explicit_subset"
    assert result["references"][0]["target_ids"] == ["post:p2", "post:p4"]
    first_two = resolve_from_candidates("Первые два", candidates)
    assert first_two["references"][0]["target_ids"] == ["post:p1", "post:p2"]
    predicate = resolve_from_candidates(
        "Посты про ИИ",
        [
            {**item, "title": "ИИ" if item["ref"] == "post:p3" else "Другое"}
            for item in candidates
        ],
    )
    assert predicate["references"][0]["selection_mode"] == "predicate"
    assert predicate["references"][0]["target_ids"] == ["post:p3"]
    assert validate_resolution(result, candidate_refs={item["ref"] for item in candidates}) == []
    assert validate_resolution(
        {**result, "references": [{**result["references"][0], "target_ids": ["post:ghost"]}]},
        candidate_refs={item["ref"] for item in candidates},
    ) == ["invented_target:post:ghost"]


def test_referent_resolution_complement_is_bounded():
    candidates = [
        {"ref": f"post:p{i}", "kind": "post", "position": i, "source_set_ref": "turn-1:posts"}
        for i in range(1, 6)
    ]
    result = resolve_from_candidates(
        "А теперь остальные",
        candidates,
        previous_selected_refs=("post:p2", "post:p4"),
    )
    assert result["references"][0]["selection_mode"] == "complement"
    assert result["references"][0]["target_ids"] == ["post:p1", "post:p3", "post:p5"]


def test_complement_keeps_original_set_across_subset_manifest():
    newest_subset = {
        "source_turn_id": "turn-2",
        "context_refs": [{"ref": "post:p2", "kind": "post"}, {"ref": "post:p4", "kind": "post"}],
        "reference_sets": [
            {"ref": "set:turn-2:post", "kind": "post", "ordered_members": ["post:p2"], "selected_members": ["post:p2"]},
            {"ref": "set:turn-2:post-2", "kind": "post", "ordered_members": ["post:p4"], "selected_members": ["post:p4"]},
        ],
    }
    original = {
        "source_turn_id": "turn-1",
        "context_refs": [],
        "reference_sets": [{
            "ref": "set:turn-1:posts", "kind": "post",
            "ordered_members": [f"post:p{i}" for i in range(1, 6)],
            "selected_members": [f"post:p{i}" for i in range(1, 6)],
        }],
    }
    envelope = candidate_envelope(manifests=(newest_subset, original))
    result = resolve_from_candidates(
        "Остальные", envelope, previous_selected_refs=("post:p2", "post:p4")
    )
    assert result["references"][0]["source_set_ref"] == "set:turn-1:posts"
    assert result["references"][0]["target_ids"] == ["post:p1", "post:p3", "post:p5"]


def test_answer_contract_filters_unsupported_refs_and_requires_full_text_for_exact_claims():
    validation = validate_answer_output(
        {
            "answer": "Точная дата",
            "claims": [{
                "text": "Точная дата",
                "evidence_ids": ["card-1"],
                "claim_scope": "exact",
            }],
            "used_context_refs": ["post:p1", "post:invented"],
        },
        evidence_ids={"card-1"},
        evidence_fidelity={"card-1": "semantic_card"},
        supplied_context_refs={"post:p1"},
        factual=True,
    )
    assert not validation.ok
    assert "claims[0].exact_claim_requires_full_text" in validation.issues
    assert "used_context_ref_not_supplied:post:invented" in validation.issues
    assert validation.used_context_refs == ("post:p1",)


def test_turn_contract_binds_positional_followup_to_previous_set_without_corpus_search():
    ledger = (
        TurnSnapshot(
            turn_id="00000000-0000-0000-0000-000000000001",
            recorded_at="2026-01-01T00:00:00+00:00",
            user_text="Опиши все посты",
            target_post_id=None,
            target_evidence_gap=None,
            entities=(
                LedgerEntity(
                    entity_type="entity_set",
                    ref="turn-1:posts",
                    members=tuple(
                        {"kind": "post", "id": f"p{i}", "title": f"Пост {i}"}
                        for i in range(1, 6)
                    ),
                ),
            ),
        ),
    )
    contract = build_turn_contract(
        user_text="Второй и четвёртый",
        history=[],
        scope="global",
        dialog_ledger=ledger,
    )
    target = contract["target_contract"]
    assert [item["id"] for item in target["targets"]] == ["p2", "p4"]
    assert target["referent_resolution"]["references"][0]["selection_mode"] == "explicit_subset"
    assert all(source["scope"]["mode"] == "targets" for source in contract["source_requirements"])
    assert all(source["budget"]["search_calls"] == 0 for source in contract["source_requirements"])


def test_turn_contract_resolves_previous_assistant_artifact_without_search():
    manifest = {
        "schema": "workspace.message-context/v1",
        "message_id": "m1",
        "run_id": "run-1",
        "source_turn_id": "run-1",
        "context_refs": [],
        "reference_sets": [],
        "artifacts": [{
            "ref": "artifact:sha256:abc",
            "kind": "assistant_answer",
            "content_hash": "sha256:abc",
            "source_turn_id": "run-1",
            "role": "derived_output",
        }],
    }
    contract = build_turn_contract(
        user_text="Сделай его короче",
        history=[{"role": "ai", "text": "Предыдущий ответ"}],
        scope="global",
        message_manifests=(manifest,),
    )
    target = contract["target_contract"]
    assert target["targets"][0]["kind"] == "dialog_artifact"
    assert target["referent_resolution"]["references"][0]["target_type"] == "artifact"
    assert contract["source_requirements"] == []


def test_turn_contract_does_not_create_dialog_artifact_when_legacy_resolver_is_off():
    contract = build_turn_contract(
        user_text="Напиши мне текст этого поста",
        history=[{"role": "ai", "text": "Предлагаю тему, которой ещё нет в БД"}],
        scope="global",
        semantic_referent_enabled=False,
    )

    assert contract["target"] is None
    assert contract["target_contract"]["targets"] == []
    assert contract["target_contract"]["target_mode"] == "corpus"
