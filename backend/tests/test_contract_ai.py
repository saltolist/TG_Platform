import json

import pytest
from httpx import AsyncClient

from app.db.models import User
from app.services.ai.stub import generate_reply
from tests.conftest import guest_auth_headers


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
async def test_ai_reply_contract(client: AsyncClient, presentation_user: User, scope: str) -> None:
    response = await client.post(
        "/api/v1/ai/reply/",
        headers=guest_auth_headers(),
        json={"text": "Hello AI", "scope": scope},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    reply = parse_sse_text(response.text)
    assert reply == generate_reply("Hello AI", scope=scope)
    assert reply.strip()
