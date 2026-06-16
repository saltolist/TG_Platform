import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import fetch_email_code
from tests.contract_schemas import parse_auth_session


@pytest.mark.asyncio
async def test_login_session_is_uuid_account_id(client: AsyncClient) -> None:
    email = f"login-contract-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"

    await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    code = await fetch_email_code(email)
    await client.post("/api/v1/auth/register/verify/", json={"email": email, "code": code})

    login = await client.post(
        "/api/v1/auth/login/",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    session = parse_auth_session(login.json())
    assert session.email == email
    assert session.token


@pytest.mark.asyncio
async def test_forgot_password_flow(client: AsyncClient) -> None:
    email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecretPass123"
    new_password = "NewSecret456"

    await client.post(
        "/api/v1/auth/register/send-code/",
        json={"email": email, "password": password},
    )
    code = await fetch_email_code(email)
    await client.post("/api/v1/auth/register/verify/", json={"email": email, "code": code})

    send = await client.post("/api/v1/auth/forgot-password/send-code/", json={"email": email})
    assert send.status_code == 204

    reset_code = await fetch_email_code(email)
    reset = await client.post(
        "/api/v1/auth/forgot-password/reset/",
        json={"email": email, "code": reset_code, "password": new_password},
    )
    assert reset.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login/",
        json={"email": email, "password": password},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login/",
        json={"email": email, "password": new_password},
    )
    assert new_login.status_code == 200
    parse_auth_session(new_login.json())
