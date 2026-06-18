import uuid

import pytest
from httpx import AsyncClient

from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.core.security import create_access_token, hash_password
from app.db.models import Post, User
from tests.conftest import TestSessionLocal, guest_auth_headers


def guest_uuid_auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer guest:{uuid.uuid4()}"}


@pytest.fixture
async def presentation_user() -> User:
    async with TestSessionLocal() as session:
        user = User(
            email=PRESENTATION_EMAIL,
            password_hash=hash_password("seed-no-login"),
            is_seed=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def presentation_post(presentation_user: User) -> Post:
    post_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        post = Post(
            id=post_id,
            user_id=presentation_user.id,
            position=0,
            data={"id": str(post_id), "title": "Presentation post", "status": "draft"},
        )
        session.add(post)
        await session.commit()
        return post


@pytest.mark.asyncio
async def test_guest_uuid_token_can_list_posts(
    client: AsyncClient, presentation_post: Post
) -> None:
    response = await client.get("/api/v1/posts/", headers=guest_uuid_auth_headers())
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_invalid_guest_uuid_rejected(client: AsyncClient, presentation_user: User) -> None:
    response = await client.get(
        "/api/v1/posts/",
        headers={"Authorization": "Bearer guest:not-a-valid-uuid"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_presentation_seed_login_forbidden(
    client: AsyncClient, presentation_user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/login/",
        json={"email": PRESENTATION_EMAIL, "password": "seed-no-login"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_demo_seed_login_still_works(client: AsyncClient) -> None:
    async with TestSessionLocal() as session:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password("Demo!2026"),
            is_seed=True,
        )
        session.add(user)
        await session.commit()

    response = await client.post(
        "/api/v1/auth/login/",
        json={"email": DEMO_EMAIL, "password": "Demo!2026"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == DEMO_EMAIL


@pytest.mark.asyncio
async def test_guest_can_list_posts(
    client: AsyncClient, presentation_post: Post
) -> None:
    response = await client.get("/api/v1/posts/", headers=guest_auth_headers())
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Presentation post"


@pytest.mark.asyncio
async def test_guest_cannot_create_post(client: AsyncClient, presentation_user: User) -> None:
    post_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/posts/",
        headers=guest_auth_headers(),
        json={"id": post_id, "title": "New", "status": "draft"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "Read-only account"


@pytest.mark.asyncio
async def test_invalid_token_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/posts/",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_guest_token_without_seeded_user_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/posts/", headers=guest_auth_headers())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_seed_user_jwt_cannot_mutate(client: AsyncClient) -> None:
    async with TestSessionLocal() as session:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password("Demo!2026"),
            is_seed=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token(str(user.id))

    headers = {"Authorization": f"Bearer {token}"}
    post_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/posts/",
        headers=headers,
        json={"id": post_id, "title": "Demo post", "status": "draft"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_can_create_post(client: AsyncClient) -> None:
    async with TestSessionLocal() as session:
        user = User(
            email=f"writer-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("SecretPass123"),
            is_seed=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token(str(user.id))

    post_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/posts/",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": post_id, "title": "Mine", "status": "draft"},
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Mine"
