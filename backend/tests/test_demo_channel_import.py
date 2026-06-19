import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.models import Post
from app.services.demo_channel import is_demo_channel_handle
from tests.conftest import TestSessionLocal, writer_auth_headers


@pytest.mark.parametrize(
    "channel",
    ["@demochannel", "@DemoChannel", "demokanal", "@demo_kanal"],
)
def test_is_demo_channel_handle(channel: str) -> None:
    assert is_demo_channel_handle(channel) is True


@pytest.mark.parametrize("channel", ["@other", "@test", ""])
def test_is_demo_channel_handle_rejects_other_channels(channel: str) -> None:
    assert is_demo_channel_handle(channel) is False


@pytest.mark.asyncio
async def test_connect_demo_channel_imports_posts(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    posts_before = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert posts_before.status_code == 200
    assert posts_before.json() == []

    payload = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": "20483651",
        "apiHash": "demo-hash",
        "phone": "+7 999 000-00-00",
        "sessionName": "",
        "channel": "@demochannel",
        "channelTitle": "Демо канал",
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "lastSync": "2026-06-19T12:00:00.000Z",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    put = await client.put("/api/v1/profile/telegram/", headers=writer_auth_headers, json=payload)
    assert put.status_code == 200
    body = put.json()
    assert body["channelStatus"] == "connected"
    assert body["importedPosts"] > 0
    assert body["channelTitle"] == "Демо канал"

    posts_after = await client.get("/api/v1/posts/", headers=writer_auth_headers)
    assert posts_after.status_code == 200
    posts = posts_after.json()
    assert len(posts) == body["importedPosts"]
    assert any(post.get("comments") for post in posts)


@pytest.mark.asyncio
async def test_reconnect_demo_channel_does_not_reimport(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    connected = {
        "authStatus": "connected",
        "authStep": "connected",
        "apiId": "1",
        "apiHash": "hash",
        "phone": "+7 999 000-00-00",
        "sessionName": "",
        "channel": "@demochannel",
        "channelTitle": "Демо канал",
        "channelStatus": "connected",
        "syncMode": "history-and-live",
        "lastSync": "2026-06-19T12:00:00.000Z",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    first = await client.put("/api/v1/profile/telegram/", headers=writer_auth_headers, json=connected)
    assert first.status_code == 200
    imported = first.json()["importedPosts"]

    async with TestSessionLocal() as session:
        count_after_first = await session.scalar(select(func.count()).select_from(Post))
    assert count_after_first == imported

    connected["importedPosts"] = imported
    connected["lastSync"] = "2026-06-19T13:00:00.000Z"
    second = await client.put("/api/v1/profile/telegram/", headers=writer_auth_headers, json=connected)
    assert second.status_code == 200
    assert second.json()["importedPosts"] == imported

    async with TestSessionLocal() as session:
        count_after_second = await session.scalar(select(func.count()).select_from(Post))
    assert count_after_second == imported
