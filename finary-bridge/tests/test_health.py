"""Tests for local diagnostics endpoints."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app, get_finary_client


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


def test_health_does_not_load_finary_session_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FINARY_SESSION_PATH", "deliberately-relative-and-invalid")
    get_finary_client.cache_clear()
    try:

        async def request_health() -> Response:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                return await client.get("/health")

        response = asyncio.run(request_health())
    finally:
        get_finary_client.cache_clear()

    assert response.status_code == 200
