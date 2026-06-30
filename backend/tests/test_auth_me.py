import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import fetch_email_code


@pytest.mark.asyncio
async def test_auth_me_requires_cookie_or_bearer(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_returns_session_from_cookie(client: AsyncClient) -> None:
    email = f"me-{uuid.uuid4().hex[:8]}@example.com"
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
    assert verify.json().get("token") is None

    me = await client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["accountId"]
    assert body.get("token") is None


@pytest.mark.asyncio
async def test_auth_me_supports_bearer_fallback(client: AsyncClient, writer_auth_headers) -> None:
    response = await client.get("/api/v1/auth/me/", headers=writer_auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"]
    assert body["accountId"]


@pytest.mark.asyncio
async def test_logout_clears_auth_cookie(client: AsyncClient) -> None:
    """Regression test: logout must return the SAME injected Response object,
    otherwise the Set-Cookie deletion header is silently dropped and the
    browser keeps authenticating the old user after "logout".
    """
    email = f"logout-{uuid.uuid4().hex[:8]}@example.com"
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
    assert "access_token" in client.cookies

    me_before = await client.get("/api/v1/auth/me/")
    assert me_before.status_code == 200

    logout = await client.post("/api/v1/auth/logout/")
    assert logout.status_code == 204
    set_cookie = logout.headers.get("set-cookie", "")
    assert "access_token" in set_cookie
    assert "access_token" not in client.cookies

    me_after = await client.get("/api/v1/auth/me/")
    assert me_after.status_code == 401
