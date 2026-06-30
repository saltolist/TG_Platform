import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_csp_report_accepts_legacy_payload(client: AsyncClient) -> None:
    payload = b'{"csp-report":{"violated-directive":"script-src","blocked-uri":"inline"}}'
    response = await client.post(
        "/api/v1/csp-report/",
        content=payload,
        headers={"Content-Type": "application/csp-report"},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_csp_report_accepts_empty_body(client: AsyncClient) -> None:
    response = await client.post("/api/v1/csp-report/")
    assert response.status_code == 204
