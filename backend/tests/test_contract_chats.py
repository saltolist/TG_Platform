import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import sample_global_chat, writer_auth_headers
from tests.contract_schemas import GlobalChatContract, parse_global_chats_list


@pytest.mark.asyncio
async def test_global_chats_crud_contract(client: AsyncClient, writer_auth_headers: dict) -> None:
    chat_id = str(uuid.uuid4())
    payload = sample_global_chat(chat_id)

    create = await client.post("/api/v1/global-chats/", headers=writer_auth_headers, json=payload)
    assert create.status_code == 201
    created = GlobalChatContract.model_validate(create.json())
    assert created.title == payload["title"]

    listed = await client.get("/api/v1/global-chats/", headers=writer_auth_headers)
    assert parse_global_chats_list(listed.json())

    message = await client.post(
        f"/api/v1/global-chats/{chat_id}/messages/",
        headers=writer_auth_headers,
        json={"text": "Follow-up"},
    )
    assert message.status_code == 200
    with_reply = GlobalChatContract.model_validate(message.json())
    assert len(with_reply.history) >= 2
    assert with_reply.history[-2].role == "user"
    assert with_reply.history[-1].role == "ai"
    assert with_reply.history[-1].text

    renamed = await client.patch(
        f"/api/v1/global-chats/{chat_id}/",
        headers=writer_auth_headers,
        json={"title": "Renamed chat"},
    )
    assert renamed.status_code == 200
    assert GlobalChatContract.model_validate(renamed.json()).title == "Renamed chat"

    delete = await client.delete(f"/api/v1/global-chats/{chat_id}/", headers=writer_auth_headers)
    assert delete.status_code == 204
