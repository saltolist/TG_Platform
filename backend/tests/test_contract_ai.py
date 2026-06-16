import pytest
from httpx import AsyncClient

from tests.conftest import writer_auth_headers
from tests.contract_schemas import parse_ai_reply


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "post"])
async def test_ai_reply_contract(
    client: AsyncClient, writer_auth_headers: dict, scope: str
) -> None:
    response = await client.post(
        "/api/v1/ai/reply/",
        headers=writer_auth_headers,
        json={"text": "Hello AI", "scope": scope},
    )
    assert response.status_code == 200
    reply = parse_ai_reply(response.json())
    assert reply.text.strip()
