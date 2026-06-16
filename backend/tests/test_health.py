import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_root(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_api_v1(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
