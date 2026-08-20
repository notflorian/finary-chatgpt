"""Tests for local diagnostics endpoints."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def test_health_returns_expected_service_metadata() -> None:
    """The health check remains local and exposes the documented response."""

    async def request_health() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": "finary-bridge",
        "version": "0.1.0",
    }
