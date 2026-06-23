import uuid

import pytest

from app.services.ai.reply_orchestrator import load_reply_context as _load_reply_context, prefers_server_chat_history as _prefers_server_chat_history
from app.db.models import GlobalChat
from app.schemas.requests import AiReplyRequest
from tests.conftest import TestSessionLocal, sample_global_chat


@pytest.mark.asyncio
async def test_prefers_server_chat_history_for_writer(writer_user) -> None:
    assert _prefers_server_chat_history(writer_user) is True


@pytest.mark.asyncio
async def test_prefers_client_history_for_presentation(presentation_user) -> None:
    assert _prefers_server_chat_history(presentation_user) is False


@pytest.mark.asyncio
async def test_load_reply_context_writer_uses_db_history_only(writer_user) -> None:
    chat_id = str(uuid.uuid4())
    db_history = [{"role": "user", "text": "from db", "contextLabel": "1-0-stamped"}]
    client_history = [{"role": "user", "text": "from client"}]

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=writer_user.id,
                data={**sample_global_chat(chat_id), "history": db_history},
            )
        )
        await session.commit()

        payload = AiReplyRequest(
            text="next",
            scope="global",
            chat_id=chat_id,
            history=client_history,
        )
        history, _, _ = await _load_reply_context(payload, writer_user, session)

    assert history == db_history
    assert history[0].get("contextLabel") == "1-0-stamped"


@pytest.mark.asyncio
async def test_load_reply_context_presentation_merges_client_stamps(presentation_user) -> None:
    chat_id = str(uuid.uuid4())
    db_history = [{"role": "user", "text": "db"}]
    client_history = [
        {"role": "user", "text": "db", "contextLabel": "1-0-overlay"},
    ]

    async with TestSessionLocal() as session:
        session.add(
            GlobalChat(
                id=uuid.UUID(chat_id),
                user_id=presentation_user.id,
                data={**sample_global_chat(chat_id), "history": db_history},
            )
        )
        await session.commit()

        payload = AiReplyRequest(
            text="next",
            scope="global",
            chat_id=chat_id,
            history=client_history,
        )
        history, _, _ = await _load_reply_context(payload, presentation_user, session)

    assert history[0].get("contextLabel") == "1-0-overlay"
