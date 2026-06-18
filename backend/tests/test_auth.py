import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import fetch_email_code


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient) -> None:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"

    send = await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    assert send.status_code == 204

    code = await fetch_email_code(email)
    assert code == "000000"

    verify = await client.post(
        "/api/v1/auth/register/verify/",
        json={"email": email, "code": code},
    )
    assert verify.status_code == 200
    session = verify.json()
    assert session["email"] == email
    assert session["token"]
    assert session["accountId"]

    channel = await client.get("/api/v1/profile/channel/", headers={"Authorization": f"Bearer {session['token']}"})
    assert channel.status_code == 200
    assert channel.json()["rubrics"] == []

    login = await client.post(
        "/api/v1/auth/login/",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    assert login.json()["email"] == email


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login/",
        json={"email": "missing@example.com", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]


@pytest.mark.asyncio
async def test_protected_route_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/posts/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_register_rejected(client: AsyncClient) -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"

    await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    code = await fetch_email_code(email)
    verify = await client.post(
        "/api/v1/auth/register/verify/",
        json={"email": email, "code": code},
    )
    assert verify.status_code == 200

    duplicate = await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    assert duplicate.status_code == 400
