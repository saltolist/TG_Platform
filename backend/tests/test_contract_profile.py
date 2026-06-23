import pytest
from httpx import AsyncClient

from tests.conftest import writer_auth_headers


@pytest.mark.asyncio
async def test_profile_channel_roundtrip(client: AsyncClient, writer_auth_headers: dict) -> None:
    empty = await client.get("/api/v1/profile/channel/", headers=writer_auth_headers)
    assert empty.status_code == 200
    assert empty.json()["core"]["topic"] == ""
    assert empty.json()["rubrics"] == []

    payload = {
        "core": {
            "topic": "Test topic",
            "audience": "Testers",
            "promise": "Quality",
            "angle": "Angle",
            "author": "Author",
        },
        "voice": {"tone": "Calm", "format": "Short", "phrases": "You"},
        "rules": {"must": "Be clear", "avoid": "Noise"},
        "rubrics": [],
    }
    put = await client.put("/api/v1/profile/channel/", headers=writer_auth_headers, json=payload)
    assert put.status_code == 200
    assert put.json()["core"]["topic"] == "Test topic"

    get = await client.get("/api/v1/profile/channel/", headers=writer_auth_headers)
    assert get.json()["core"]["topic"] == "Test topic"


@pytest.mark.asyncio
async def test_profile_ai_roundtrip(client: AsyncClient, writer_auth_headers: dict) -> None:
    payload = {
        "llmModels": [
            {
                "id": "llm-1",
                "provider": "OpenAI",
                "model": "gpt-4o",
                "apiKey": "",
                "active": True,
                "includeInMulti": False,
            }
        ],
        "webSearchModels": [],
        "visionModels": [],
        "imageGenerationModels": [],
        "orchestratorModels": [],
        "webReasonerModels": [],
        "ragReasonerModels": [],
        "multiResponseEnabled": False,
        "systemPrompt": "Test prompt",
    }
    put = await client.put("/api/v1/profile/ai/", headers=writer_auth_headers, json=payload)
    assert put.status_code == 200
    assert put.json()["systemPrompt"] == "Test prompt"

    get = await client.get("/api/v1/profile/ai/", headers=writer_auth_headers)
    assert get.json()["llmModels"][0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_profile_ai_byok_key_revealed_to_owner(client: AsyncClient, writer_auth_headers: dict) -> None:
    payload = {
        "llmModels": [
            {
                "id": "llm-1",
                "provider": "OpenAI",
                "model": "gpt-4o",
                "apiKey": "sk-owner-secret-key",
                "active": True,
                "includeInMulti": False,
            }
        ],
        "webSearchModels": [],
        "visionModels": [],
        "imageGenerationModels": [],
        "orchestratorModels": [],
        "webReasonerModels": [],
        "ragReasonerModels": [],
        "multiResponseEnabled": False,
        "systemPrompt": "",
    }
    put = await client.put("/api/v1/profile/ai/", headers=writer_auth_headers, json=payload)
    assert put.status_code == 200
    assert put.json()["llmModels"][0]["apiKey"] == "sk-**********key"

    get = await client.get("/api/v1/profile/ai/", headers=writer_auth_headers)
    assert get.status_code == 200
    assert get.json()["llmModels"][0]["apiKey"] == "sk-**********key"

    reveal = await client.post(
        "/api/v1/profile/ai/reveal-key/",
        headers=writer_auth_headers,
        json={"modelId": "llm-1", "field": "llmModels"},
    )
    assert reveal.status_code == 200
    assert reveal.json()["apiKey"] == "sk-owner-secret-key"


@pytest.mark.asyncio
async def test_profile_telegram_roundtrip(client: AsyncClient, writer_auth_headers: dict) -> None:
    payload = {
        "authStatus": "idle",
        "authStep": "credentials",
        "apiId": "",
        "apiHash": "",
        "phone": "",
        "sessionName": "",
        "channel": "@test",
        "channelTitle": "Test",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    put = await client.put("/api/v1/profile/telegram/", headers=writer_auth_headers, json=payload)
    assert put.status_code == 200
    assert put.json()["channel"] == "@test"

    get = await client.get("/api/v1/profile/telegram/", headers=writer_auth_headers)
    assert get.json()["channelTitle"] == "Test"
