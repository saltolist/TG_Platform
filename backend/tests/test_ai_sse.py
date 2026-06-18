import json

import pytest
from httpx import AsyncClient

from app.db.models import User
from app.services.ai.stub import generate_reply
from tests.conftest import guest_auth_headers, writer_auth_headers


def parse_sse_text(body: str) -> str:
    chunks: list[str] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = json.loads(block[6:])
        chunks.append(str(payload.get("text", "")))
    return "".join(chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "post"])
async def test_ai_reply_sse_stub_for_guest(
    client: AsyncClient, presentation_user: User, scope: str
) -> None:
    response = await client.post(
        "/api/v1/ai/reply/",
        headers=guest_auth_headers(),
        json={"text": "Hello AI", "scope": scope},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = parse_sse_text(response.text)
    assert text == generate_reply("Hello AI", scope=scope)


@pytest.mark.asyncio
async def test_ai_reply_sse_422_for_real_account_without_key(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/ai/reply/",
        headers=writer_auth_headers,
        json={"text": "Hello AI", "scope": "global"},
    )
    assert response.status_code == 422
    assert response.json()["error"]


def test_format_sse_data_roundtrip() -> None:
    from app.services.ai.sse import format_sse_data

    block = format_sse_data('тест "кавычки"')
    assert block.startswith("data: ")
    assert block.endswith("\n\n")
    payload = json.loads(block[6:].strip())
    assert payload["text"] == 'тест "кавычки"'
