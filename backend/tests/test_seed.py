import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.db.models import Post, User
from app.db.seed import run_seed
from tests.conftest import TestSessionLocal, guest_auth_headers


async def _seed() -> None:
    async with TestSessionLocal() as session:
        await run_seed(session)


@pytest.mark.asyncio
async def test_seed_creates_accounts_idempotently() -> None:
    await _seed()
    await _seed()

    async with TestSessionLocal() as session:
        for email in (PRESENTATION_EMAIL, DEMO_EMAIL):
            result = await session.execute(select(User).where(User.email == email))
            users = result.scalars().all()
            assert len(users) == 1
            assert users[0].is_seed is True


@pytest.mark.asyncio
async def test_guest_sees_presentation_posts_after_seed(client: AsyncClient) -> None:
    await _seed()
    response = await client.get("/api/v1/posts/", headers=guest_auth_headers())
    assert response.status_code == 200
    posts = response.json()
    assert len(posts) >= 9
    assert any(p.get("id") == "21" for p in posts)


@pytest.mark.asyncio
async def test_seed_preserves_registered_users() -> None:
    await _seed()

    async with TestSessionLocal() as session:
        session.add(
            User(
                email="registered@example.com",
                password_hash="hash",
                is_seed=False,
            )
        )
        await session.commit()

    await _seed()

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "registered@example.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.is_seed is False


@pytest.mark.asyncio
async def test_demo_login_after_seed(client: AsyncClient) -> None:
    await _seed()
    response = await client.post(
        "/api/v1/auth/login/",
        json={"email": DEMO_EMAIL, "password": "Demo!2026"},
    )
    assert response.status_code == 200
    session = response.json()
    assert session["email"] == DEMO_EMAIL
    assert session["accountId"]

    posts = await client.get("/api/v1/posts/")
    assert posts.status_code == 200
    assert len(posts.json()) >= 5


@pytest.mark.asyncio
async def test_presentation_user_has_pages_profile(client: AsyncClient) -> None:
    await _seed()
    channel = await client.get("/api/v1/profile/channel/", headers=guest_auth_headers())
    ai = await client.get("/api/v1/profile/ai/", headers=guest_auth_headers())
    telegram = await client.get("/api/v1/profile/telegram/", headers=guest_auth_headers())
    assert channel.status_code == 200
    assert ai.status_code == 200
    assert telegram.status_code == 200
    assert channel.json().get("core", {}).get("topic")
    assert len(ai.json().get("llmModels", [])) >= 2
    assert telegram.json().get("channelStatus") == "connected"


@pytest.mark.asyncio
async def test_seeded_posts_match_frontend_contract(client: AsyncClient) -> None:
    await _seed()
    response = await client.get("/api/v1/posts/", headers=guest_auth_headers())
    assert response.status_code == 200
    from tests.contract_schemas import parse_posts_list

    posts = parse_posts_list(response.json())
    assert len(posts) >= 9
    assert any(post.id == "21" for post in posts)
