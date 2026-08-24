"""Tests for local diagnostics endpoints."""

import asyncio
import tomllib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.config import SERVICE_VERSION
from app.main import app, get_finary_client

BRIDGE_ROOT = Path(__file__).parents[1]


def test_package_and_service_versions_agree() -> None:
    project = tomllib.loads(
        (BRIDGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["version"] == SERVICE_VERSION == "1.0.0"


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
        "version": "1.0.0",
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
