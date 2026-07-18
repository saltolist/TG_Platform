"""Tests for Dialog Evidence Ledger (ADR-009 v1)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.ai.note_citations import NoteCite
from app.services.ai.rag_dialog_ledger import (
    append_turn,
    build_snapshot_from_evidence_records,
    build_snapshot_from_agent_state,
    chat_ledger_key,
    clear_ledger,
    format_ledger_for_planner,
    ledger_chat_id,
    ledger_hydrated_attachments,
    load_ledger,
)
from app.services.ai.rag_tools import AgentState
from app.db.models import User
from tests.conftest import TestSessionLocal


def _state() -> AgentState:
    return AgentState(
        session=AsyncMock(),
        user_id=uuid4(),
        scope="global",
        tenant_key=None,
        embedding_backend=AsyncMock(),
        base_post_data=None,
    )


def test_chat_ledger_key_global_and_post_scoped() -> None:
    assert chat_ledger_key(scope="global", chat_id="abc") == "global:abc"
    assert chat_ledger_key(scope="post", chat_id="c1", post_id="p1") == "post:p1:c1"
    assert chat_ledger_key(scope="global", chat_id=None) is None


def test_ledger_chat_id_prefers_post_chat_for_post_scope() -> None:
    assert ledger_chat_id(scope="global", chat_id="g1", post_chat_id="pc1") == "g1"
    assert ledger_chat_id(scope="post", chat_id="g1", post_chat_id="pc1") == "pc1"
    assert ledger_chat_id(scope="post", chat_id="g1", post_chat_id=None) is None


def test_build_snapshot_captures_hydrated_attachment() -> None:
    state = _state()
    ref = "attachment:704a2ddd-1111-2222-3333-444444444444"
    state.resolved_target_post_id = "721c63fe-aaaa-bbbb-cccc-dddddddddddd"
    state.listed_image_attachment_refs = [ref]
    state.visited.add(f"hydrate:vision:{ref}")
    state.opened_posts["721c63fe-aaaa-bbbb-cccc-dddddddddddd"] = {
        "id": "721c63fe-aaaa-bbbb-cccc-dddddddddddd",
        "text": "Больше никаких переключений",
    }
    state.context_blocks.append(
        (
            NoteCite(
                path=(
                    "/note/post/721c63fe-aaaa-bbbb-cccc-dddddddddddd/"
                    "ee175834-note/attachment/704a2ddd-1111-2222-3333-444444444444/"
                ),
                title="anime.png",
            ),
            "аниме, девушки, сезон 4",
        )
    )

    snapshot = build_snapshot_from_agent_state(state, user_text="картинки для переключений")

    attachments = [e for e in snapshot.entities if e.entity_type == "attachment"]
    assert len(attachments) == 1
    assert attachments[0].ref == ref
    assert attachments[0].hydrated is True
    assert "девушки" in (attachments[0].vision_preview or "")


def test_build_snapshot_fills_attachment_post_id_from_target() -> None:
    state = _state()
    ref = "attachment:704a2ddd-1111-2222-3333-444444444444"
    host_post_id = "721c63fe-aaaa-bbbb-cccc-dddddddddddd"
    state.resolved_target_post_id = host_post_id
    state.listed_image_attachment_refs = [ref]
    state.visited.add(f"hydrate:vision:{ref}")
    state.context_blocks.append(
        (
            NoteCite(
                path=f"/note/global/ee175834-note/attachment/704a2ddd-1111-2222-3333-444444444444/",
                title="anime.png",
            ),
            "аниме, девушки",
        )
    )

    snapshot = build_snapshot_from_agent_state(state, user_text="переключений")
    attachments = [entity for entity in snapshot.entities if entity.entity_type == "attachment"]
    assert len(attachments) == 1
    assert attachments[0].post_id == host_post_id


@pytest.mark.asyncio
async def test_ledger_store_load_and_hydrated_filter(writer_user: User) -> None:
    user_id = writer_user.id
    key = "global:test-chat"
    async with TestSessionLocal() as session:
        await clear_ledger(session, user_id=user_id, chat_key=key)
        state = _state()
        ref = "attachment:img1"
        state.listed_image_attachment_refs = [ref]
        state.visited.add(f"hydrate:vision:{ref}")
        state.context_blocks.append(
            (NoteCite(path="/note/global/n1/attachment/img1/", title="a.png"), "preview")
        )
        await append_turn(
            session,
            user_id=user_id,
            chat_key=key,
            snapshot=build_snapshot_from_agent_state(state, user_text="turn 2"),
        )
        await session.commit()

        ledger = await load_ledger(session, user_id=user_id, chat_key=key)
        assert len(ledger) == 1
        hydrated = ledger_hydrated_attachments(ledger)
        assert len(hydrated) == 1
        assert hydrated[0].ref == ref

        formatted = format_ledger_for_planner(ledger)
        assert "Dialog evidence ledger" in formatted
        assert ref in formatted
        await clear_ledger(session, user_id=user_id, chat_key=key)
        await session.commit()


@pytest.mark.asyncio
async def test_append_turn_respects_cap(writer_user: User) -> None:
    user_id = writer_user.id
    key = "global:cap-test"
    async with TestSessionLocal() as session:
        await clear_ledger(session, user_id=user_id, chat_key=key)
        for index in range(12):
            state = _state()
            await append_turn(
                session,
                user_id=user_id,
                chat_key=key,
                snapshot=build_snapshot_from_agent_state(state, user_text=f"turn {index}"),
            )
        await session.commit()
        ledger = await load_ledger(session, user_id=user_id, chat_key=key)
        assert len(ledger) == 10
        assert ledger[0].user_text == "turn 2"
        await clear_ledger(session, user_id=user_id, chat_key=key)
        await session.commit()


@pytest.mark.asyncio
async def test_ledger_survives_session_reopen(writer_user: User) -> None:
    user_id = writer_user.id
    key = "global:persist-test"
    async with TestSessionLocal() as session:
        await clear_ledger(session, user_id=user_id, chat_key=key)
        snapshot = build_snapshot_from_agent_state(_state(), user_text="persist me")
        await append_turn(
            session,
            user_id=user_id,
            chat_key=key,
            snapshot=snapshot,
        )
        await session.commit()

    async with TestSessionLocal() as fresh_session:
        ledger = await load_ledger(fresh_session, user_id=user_id, chat_key=key)
        assert len(ledger) == 1
        assert ledger[0].user_text == "persist me"
        await clear_ledger(fresh_session, user_id=user_id, chat_key=key)
        await fresh_session.commit()


def test_seed_hydrated_dialog_artifacts_replays_ledger_vision() -> None:
    from app.services.ai.rag_dialog_ledger import (
        LedgerEntity,
        TurnSnapshot,
        seed_hydrated_attachments_from_ledger,
    )

    ref = "attachment:704a2ddd"
    state = _state()
    ledger = (
        TurnSnapshot(
            turn_id="t2",
            recorded_at="2026-07-11T00:00:00+00:00",
            user_text="переключений",
            target_post_id="721c63fe",
            target_evidence_gap=None,
            entities=(
                LedgerEntity(
                    entity_type="attachment",
                    ref=ref,
                    post_id=None,
                    note_id="ee175834",
                    vision_preview="аниме, девушки",
                    hydrated=True,
                ),
            ),
        ),
    )

    seeded = seed_hydrated_attachments_from_ledger(
        state,
        user_text="А как же картинка с девушками?",
        ledger=ledger,
    )

    assert seeded == (ref,)
    assert f"hydrate:vision:{ref}" in state.visited
    assert any("девушки" in plain for _cite, plain in state.context_blocks)


def test_is_referential_distinguishes_same_instance_vs_new_predicate() -> None:
    from app.services.ai.rag_dialog_ledger import is_referential

    # Referential: points at objects already discussed.
    assert is_referential("Расскажи про неё подробнее")
    assert is_referential("А что в этой заметке?")
    assert is_referential("Покажи файл из них")
    # New predicate: same category, but not the same instances — must NOT
    # be treated as referential, or the search narrows to already-discussed
    # objects (chat 63dfb9e4 regression: "а сколько с изображениями?" got
    # answered against only the 2 notes opened for a prior question).
    assert not is_referential("А сколько с изображениями?")
    assert not is_referential("Сколько всего у меня заметок?")
    assert not is_referential("Какие посты самые популярные?")


def test_evidence_snapshot_keeps_full_assistant_artifact() -> None:
    draft = "Заголовок\n\n" + ("Полный текст поста. " * 80)
    snapshot = build_snapshot_from_evidence_records(
        user_text="Напиши пост",
        evidence_ids=[],
        records={},
        answer_text=draft,
        artifact_kind="post_draft",
        turn_id=str(uuid4()),
    )

    artifact = next(entity for entity in snapshot.entities if entity.entity_type == "post_draft")
    assert artifact.content == draft.strip()
    assert len(artifact.content or "") > 400
    rendered = format_ledger_for_planner((snapshot,))
    assert "Полный текст поста" in rendered


def test_referential_hints_from_ledger_only_for_referential_followups() -> None:
    from app.services.ai.rag_dialog_ledger import (
        LedgerEntity,
        TurnSnapshot,
        referential_hints_from_ledger,
    )

    ledger = (
        TurnSnapshot(
            turn_id="t1",
            recorded_at="2026-07-16T00:00:00+00:00",
            user_text="Сколько заметок про систему?",
            target_post_id=None,
            target_evidence_gap=None,
            entities=(
                LedgerEntity(entity_type="note", note_id="9fd458be", post_id=None),
                LedgerEntity(entity_type="post", post_id="42", title="Дайджест"),
            ),
        ),
    )

    # Referential follow-up: reuse the ledger objects directly.
    hints = referential_hints_from_ledger("А что там написано про неё?", ledger)
    assert any("OpenNote note_id=9fd458be" in h for h in hints)
    assert any("OpenPost post_id=42" in h for h in hints)

    # New-predicate follow-up: no hints — must search the full category, not
    # just the 2 objects already discussed.
    assert referential_hints_from_ledger("А сколько всего заметок с картинками?", ledger) == []

    # No ledger: nothing to hint regardless of phrasing.
    assert referential_hints_from_ledger("Расскажи про неё", ()) == []
