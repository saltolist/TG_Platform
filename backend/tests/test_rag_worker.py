"""Tests for RAG worker enqueue and inline file reconciliation."""

from __future__ import annotations

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.models import GlobalNote, Post, User
from app.services.ai.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    local_embedding_model_key,
)
from app.services.ai.rag import (
    NODE_ATTACHMENT_TEXT,
    NODE_MEDIA_META,
    NODE_POST_TEXT,
    index_note,
)
from app.services.ai.rag_worker import (
    _index_note_file_nodes,
    _index_post_media_nodes,
    _process_job,
    enqueue_post_rag_delete_jobs,
    enqueue_post_text_job,
    is_post_deleted,
    startup_backfill_all,
)
from app.services.ai.semantic_summary import DISCOVERY_SUMMARY_VERSION, SELECTOR_SUMMARY_VERSION
from tests.conftest import TestSessionLocal, sample_global_note


@pytest.mark.asyncio
async def test_enqueue_post_text_job_inserts_job_row() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    post_id = "post-abc"

    with patch("app.services.ai.rag_worker.get_settings") as mock_settings:
        mock_settings.return_value.rag_enabled = True
        await enqueue_post_text_job(session, user_id, post_id)

    session.execute.assert_awaited_once()
    call_args = session.execute.await_args
    params = call_args.args[1]
    assert params["uid"] == str(user_id)
    assert params["op"] == "upsert"
    assert params["scope"] == "global"
    assert params["nid"] == post_id
    assert params["nt"] == NODE_POST_TEXT
    assert params["fid"] == ""


@pytest.mark.asyncio
async def test_enqueue_post_text_job_skips_when_rag_disabled() -> None:
    session = AsyncMock()
    with patch("app.services.ai.rag_worker.get_settings") as mock_settings:
        mock_settings.return_value.rag_enabled = False
        await enqueue_post_text_job(session, uuid.uuid4(), "p1")
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_model_key", "expected_jobs"),
    [
        (f"local:{DEFAULT_LOCAL_EMBEDDING_MODEL}", 1),
        (local_embedding_model_key(DEFAULT_LOCAL_EMBEDDING_MODEL), 0),
    ],
)
async def test_startup_backfill_is_model_fingerprint_aware(
    writer_user: User,
    stored_model_key: str,
    expected_jobs: int,
) -> None:
    note_id = "fingerprint-note"
    note_data = sample_global_note(note_id)
    stored_backend = MagicMock()
    stored_backend.model_key = stored_model_key
    stored_backend.dim = 4
    stored_backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    async with TestSessionLocal() as session:
        session.add(
            GlobalNote(
                id=uuid.uuid4(),
                user_id=writer_user.id,
                data=note_data,
            )
        )
        await session.flush()
        await index_note(
            session,
            writer_user.id,
            "global",
            note_id,
            note_data["title"],
            note_data["body"],
            stored_backend,
            discovery_summary_version=DISCOVERY_SUMMARY_VERSION,
            discovery_summary_model=f"extractive:v{DISCOVERY_SUMMARY_VERSION}",
            selector_summary="Fresh selector summary",
            selector_summary_version=SELECTOR_SUMMARY_VERSION,
        )
        await session.commit()

    current_backend = MagicMock()
    current_backend.model_key = local_embedding_model_key(DEFAULT_LOCAL_EMBEDDING_MODEL)
    settings = get_settings().model_copy(update={"rag_enabled": True})
    with (
        patch("app.services.ai.rag_worker.get_settings", return_value=settings),
        patch(
            "app.services.ai.embeddings.resolve_embedding_backend",
            return_value=current_backend,
        ),
    ):
        await startup_backfill_all(TestSessionLocal)

    async with TestSessionLocal() as session:
        jobs = await session.scalar(
            text(
                "SELECT count(*) FROM embedding_jobs "
                "WHERE user_id = :uid AND note_id = :nid AND node_type = :nt"
            ),
            {"uid": str(writer_user.id), "nid": note_id, "nt": "note_chunk"},
        )
    assert jobs == expected_jobs


async def _create_backfill_note(email: str, note_id: str) -> User:
    async with TestSessionLocal() as session:
        user = User(
            email=email,
            password_hash="test-hash",
            is_seed=False,
        )
        session.add(user)
        await session.flush()
        session.add(
            GlobalNote(
                id=uuid.uuid4(),
                user_id=user.id,
                data=sample_global_note(note_id),
            )
        )
        await session.commit()
        await session.refresh(user)
        return user


async def _run_startup_backfill_with_email(email: str) -> None:
    backend = MagicMock()
    backend.model_key = local_embedding_model_key(DEFAULT_LOCAL_EMBEDDING_MODEL)
    settings = get_settings().model_copy(
        update={
            "rag_enabled": True,
            "rag_startup_backfill_user_email": email,
        }
    )
    with (
        patch("app.services.ai.rag_worker.get_settings", return_value=settings),
        patch(
            "app.services.ai.embeddings.resolve_embedding_backend",
            return_value=backend,
        ),
    ):
        await startup_backfill_all(TestSessionLocal)


async def _backfill_job_counts_by_user(*users: User) -> dict[uuid.UUID, int]:
    async with TestSessionLocal() as session:
        return {
            user.id: int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM embedding_jobs "
                        "WHERE user_id = :uid AND op = 'upsert'"
                    ),
                    {"uid": str(user.id)},
                )
                or 0
            )
            for user in users
        }


@pytest.mark.asyncio
async def test_startup_backfill_empty_email_preserves_all_users() -> None:
    first = await _create_backfill_note("backfill-one@example.com", "note-one")
    second = await _create_backfill_note("backfill-two@example.com", "note-two")

    await _run_startup_backfill_with_email("")

    assert await _backfill_job_counts_by_user(first, second) == {
        first.id: 1,
        second.id: 1,
    }


@pytest.mark.asyncio
async def test_startup_backfill_email_only_enqueues_matching_user() -> None:
    first = await _create_backfill_note("backfill-one@example.com", "note-one")
    second = await _create_backfill_note("backfill-two@example.com", "note-two")

    await _run_startup_backfill_with_email("  BACKFILL-TWO@example.com ")

    assert await _backfill_job_counts_by_user(first, second) == {
        first.id: 0,
        second.id: 1,
    }


@pytest.mark.asyncio
async def test_startup_backfill_unmatched_email_enqueues_nothing() -> None:
    first = await _create_backfill_note("backfill-one@example.com", "note-one")
    second = await _create_backfill_note("backfill-two@example.com", "note-two")

    await _run_startup_backfill_with_email("missing@example.com")

    assert await _backfill_job_counts_by_user(first, second) == {
        first.id: 0,
        second.id: 0,
    }


@pytest.mark.asyncio
async def test_index_note_file_nodes_indexes_attachment_text() -> None:
    user_id = uuid.uuid4()
    note_id = "note-1"
    file_id = "file-1"
    payload = base64.b64encode(b"Attachment body").decode("ascii")
    data_url = f"data:text/plain;base64,{payload}"
    note_data = {
        "files": [
            {"id": file_id, "name": "notes.txt", "type": "text/plain", "url": data_url},
        ]
    }

    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    with (
        patch("app.services.ai.rag_worker.remove_file_nodes_for_parent", new_callable=AsyncMock) as mock_remove,
        patch("app.services.ai.rag_worker.upsert_attachment_extraction", new_callable=AsyncMock) as mock_cache,
        patch("app.services.ai.rag_worker.index_text_node", new_callable=AsyncMock) as mock_index,
    ):
        await _index_note_file_nodes(
            session,
            user_id,
            "global",
            note_id,
            note_data,
            backend,
            max_chars=4000,
            post_id=None,
            tenant_key="",
        )

    mock_remove.assert_awaited_once()
    mock_cache.assert_awaited_once()
    mock_index.assert_awaited_once()
    call = mock_index.await_args
    assert call.args[3] == NODE_ATTACHMENT_TEXT
    assert call.args[5] == file_id
    assert "Attachment body" in call.args[6]


@pytest.mark.asyncio
async def test_index_note_file_nodes_falls_back_to_media_meta() -> None:
    user_id = uuid.uuid4()
    note_data = {
        "files": [
            {"id": "img-1", "name": "diagram.png", "type": "image/png", "url": "https://x/y.png"},
        ]
    }

    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    with (
        patch("app.services.ai.rag_worker.remove_file_nodes_for_parent", new_callable=AsyncMock),
        patch("app.services.ai.rag_worker.upsert_attachment_extraction", new_callable=AsyncMock) as mock_cache,
        patch("app.services.ai.rag_worker.index_text_node", new_callable=AsyncMock) as mock_index,
    ):
        await _index_note_file_nodes(
            session,
            user_id,
            "global",
            "note-2",
            note_data,
            backend,
            max_chars=4000,
            post_id=None,
            tenant_key="",
        )

    mock_cache.assert_not_awaited()
    call = mock_index.await_args
    assert call.args[3] == NODE_MEDIA_META
    assert "diagram.png" in call.args[6]


@pytest.mark.asyncio
async def test_index_post_media_nodes_indexes_media_meta() -> None:
    user_id = uuid.uuid4()
    post_id = "post-1"
    post_data = {"media": [{"name": "cover.jpg", "mediaKey": "mk-9"}]}

    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    with (
        patch("app.services.ai.rag_worker.remove_file_nodes_for_parent", new_callable=AsyncMock) as mock_remove,
        patch("app.services.ai.rag_worker.index_text_node", new_callable=AsyncMock) as mock_index,
    ):
        await _index_post_media_nodes(
            session,
            user_id,
            post_id,
            post_data,
            backend,
            max_chars=4000,
        )

    mock_remove.assert_awaited_once()
    mock_index.assert_awaited_once()
    call = mock_index.await_args
    assert call.args[3] == NODE_MEDIA_META
    assert call.args[5] == "mk-9"


@pytest.mark.asyncio
async def test_index_note_file_nodes_isolates_per_file_failures() -> None:
    user_id = uuid.uuid4()
    good_payload = base64.b64encode(b"ok").decode("ascii")
    note_data = {
        "files": [
            {"id": "bad", "name": "bad.bin", "type": "application/octet-stream", "url": "not-a-data-url"},
            {"id": "good", "name": "ok.txt", "type": "text/plain", "url": f"data:text/plain;base64,{good_payload}"},
        ]
    }

    session = AsyncMock()
    backend = MagicMock()
    backend.model_key = "local:test"
    backend.dim = 4
    backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    with (
        patch("app.services.ai.rag_worker.remove_file_nodes_for_parent", new_callable=AsyncMock),
        patch("app.services.ai.rag_worker.upsert_attachment_extraction", new_callable=AsyncMock) as mock_cache,
        patch("app.services.ai.rag_worker.index_text_node", new_callable=AsyncMock) as mock_index,
    ):
        await _index_note_file_nodes(
            session,
            user_id,
            "global",
            "note-3",
            note_data,
            backend,
            max_chars=4000,
            post_id=None,
            tenant_key="",
        )

    # bad file -> media_meta fallback (no cache); good file -> attachment_text
    assert mock_cache.await_count == 1
    assert mock_index.await_count == 2
    node_types = {call.args[3] for call in mock_index.await_args_list}
    assert NODE_MEDIA_META in node_types
    assert NODE_ATTACHMENT_TEXT in node_types


def test_is_post_deleted() -> None:
    assert is_post_deleted({"status": "deleted"})
    assert not is_post_deleted({"status": "published"})


@pytest.mark.asyncio
async def test_enqueue_post_text_job_skips_deleted_post_data() -> None:
    session = AsyncMock()
    with patch("app.services.ai.rag_worker.get_settings") as mock_settings:
        mock_settings.return_value.rag_enabled = True
        await enqueue_post_text_job(
            session,
            uuid.uuid4(),
            "p1",
            post_data={"status": "deleted"},
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_post_rag_delete_jobs_enqueues_post_and_notes() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    with patch("app.services.ai.rag_worker.get_settings") as mock_settings:
        mock_settings.return_value.rag_enabled = True
        await enqueue_post_rag_delete_jobs(
            session,
            user_id,
            {
                "id": "post-1",
                "notes": [{"id": "note-1"}],
            },
        )
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_process_post_text_upsert_indexes_canonical_id_from_stale_job_key(
    writer_user: User,
) -> None:
    row_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=row_id,
                user_id=writer_user.id,
                position=0,
                data={
                    "id": "3",
                    "status": "published",
                    "text": "Canonical body",
                    "telegramMessageId": "3",
                },
            )
        )
        await session.commit()

    async with TestSessionLocal() as session:
        backend = MagicMock()
        backend.model_key = "local:test"
        backend.dim = 4
        backend.embed_passages = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

        with (
            patch("app.services.ai.rag_worker.get_settings") as mock_settings,
            patch(
                "app.services.ai.embeddings.resolve_embedding_backend",
                return_value=backend,
            ),
            patch(
                "app.services.ai.rag_worker.purge_post_text_embeddings",
                new_callable=AsyncMock,
            ) as mock_purge,
            patch(
                "app.services.ai.rag_worker.index_text_node",
                new_callable=AsyncMock,
            ) as mock_index,
            patch(
                "app.services.ai.rag_worker._index_post_media_nodes",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.return_value.rag_max_note_chars = 4000
            await _process_job(
                "job-1",
                writer_user.id,
                "upsert",
                "global",
                str(row_id),
                str(row_id),
                "",
                NODE_POST_TEXT,
                "",
                session,
            )

        mock_purge.assert_awaited_once()
        purge_aliases = mock_purge.await_args.args[2]
        assert "3" in purge_aliases
        assert str(row_id) in purge_aliases

        mock_index.assert_awaited_once()
        assert mock_index.await_args.args[4] == "3"
        assert mock_index.await_args.kwargs["post_id"] == "3"


@pytest.mark.asyncio
async def test_process_post_text_delete_purges_all_aliases(writer_user: User) -> None:
    row_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        session.add(
            Post(
                id=row_id,
                user_id=writer_user.id,
                position=0,
                data={"id": "2", "status": "deleted", "text": "Gone"},
            )
        )
        await session.commit()

    async with TestSessionLocal() as session:
        with patch(
            "app.services.ai.rag_worker.purge_post_text_embeddings",
            new_callable=AsyncMock,
        ) as mock_purge:
            await _process_job(
                "job-2",
                writer_user.id,
                "delete",
                "global",
                "2",
                "2",
                "",
                NODE_POST_TEXT,
                "",
                session,
            )

        mock_purge.assert_awaited_once()
        aliases = mock_purge.await_args.args[2]
        assert "2" in aliases
        assert str(row_id) in aliases


@pytest.mark.asyncio
async def test_process_post_text_upsert_purges_orphan_when_post_missing(
    writer_user: User,
) -> None:
    async with TestSessionLocal() as session:
        with patch(
            "app.services.ai.rag_worker.purge_post_text_embeddings",
            new_callable=AsyncMock,
        ) as mock_purge:
            await _process_job(
                "job-3",
                writer_user.id,
                "upsert",
                "global",
                "missing-post",
                "missing-post",
                "",
                NODE_POST_TEXT,
                "",
                session,
            )

        mock_purge.assert_awaited_once_with(
            session, writer_user.id, {"missing-post"}
        )


@pytest.mark.asyncio
async def test_enqueue_post_rag_delete_jobs_uses_db_row_id_when_given() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    with patch("app.services.ai.rag_worker.get_settings") as mock_settings:
        mock_settings.return_value.rag_enabled = True
        await enqueue_post_rag_delete_jobs(
            session,
            user_id,
            {"id": "post-1", "notes": []},
            db_row_id="db-uuid-1",
        )
    params = session.execute.await_args.args[1]
    assert params["nid"] == "db-uuid-1"
