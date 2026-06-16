import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailCode, User


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient, db_session: AsyncSession) -> None:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"

    send = await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    assert send.status_code == 204

    result = await db_session.execute(select(EmailCode).where(EmailCode.email == email))
    code_row = result.scalar_one()
    assert code_row.purpose == "register"

    verify = await client.post(
        "/api/v1/auth/register/verify/",
        json={"email": email, "code": code_row.code},
    )
    assert verify.status_code == 200
    session = verify.json()
    assert session["email"] == email
    assert session["token"]
    assert session["accountId"]

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
async def test_duplicate_register_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"

    await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    result = await db_session.execute(select(EmailCode).where(EmailCode.email == email))
    code = result.scalar_one().code
    await client.post(
        "/api/v1/auth/register/verify/",
        json={"email": email, "code": code},
    )

    duplicate = await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    assert duplicate.status_code == 400

    users = await db_session.execute(select(User).where(User.email == email))
    assert users.scalar_one() is not None
