import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.constants import DEMO_EMAIL
from app.core.security import create_access_token, hash_password
from app.db.models import Profile, User
from app.services.ai.stub import generate_reply
from tests.conftest import TestSessionLocal, guest_auth_headers, writer_auth_headers


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


@pytest.mark.asyncio
async def test_demo_fixture_api_key_returns_stub_reply(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    settings = Settings(openai_api_key="", deepseek_api_key="")
    monkeypatch.setattr("app.api.v1.ai.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.ai.keys.get_settings", lambda: settings)

    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == DEMO_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password("Demo!2026"),
                is_seed=True,
            )
            session.add(user)
            await session.flush()
        profile = await session.get(Profile, user.id)
        if profile is None:
            profile = Profile(user_id=user.id, ai={})
            session.add(profile)
        profile.ai = {
            "systemPrompt": "Test",
            "llmModels": [
                {
                    "id": "llm-1",
                    "provider": "OpenAI",
                    "model": "gpt-4o",
                    "apiKey": "sk-openai-demo",
                    "active": True,
                }
            ],
        }
        await session.commit()
        token = create_access_token(str(user.id))

    response = await client.post(
        "/api/v1/ai/reply/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "text": "Hello AI",
            "scope": "global",
            "llmId": "llm-1",
            "provider": "OpenAI",
            "model": "gpt-4o",
            "apiKey": "sk-openai-demo",
        },
    )
    assert response.status_code == 200
    assert parse_sse_text(response.text) == generate_reply("Hello AI", scope="global")


def test_format_sse_data_roundtrip() -> None:
    from app.services.ai.sse import format_sse_data

    block = format_sse_data('тест "кавычки"')
    assert block.startswith("data: ")
    assert block.endswith("\n\n")
    payload = json.loads(block[6:].strip())
    assert payload["text"] == 'тест "кавычки"'
