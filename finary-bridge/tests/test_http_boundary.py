"""MCP-only HTTP authorization through the retained SDK and OAuth boundaries."""

import asyncio
import logging
import socket

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp_wire import SyntheticWire
from test_mcp_auth import AuthPeer, consent

from app import main, mcp_auth
from app.mcp_auth import OAuthStore
from app.mcp_client import BoundedTransport
from app.mcp_models import McpSnapshotV3
from app.mcp_optional import BudgetResponse, GoalsResponse, SearchResponse

ROUTES = {
    "/v3/snapshot": McpSnapshotV3,
    "/v3/budget": BudgetResponse,
    "/v3/spending-search": SearchResponse,
    "/v3/goals": GoalsResponse,
}
KEY = "synthetic-local-key"


def forbidden(*args, **kwargs):
    pytest.fail("Unexpected upstream or OAuth-state access")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_startup_health_openapi_and_removed_routes_are_local(monkeypatch):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    monkeypatch.setenv("FINARY_MCP_STATE_PATH", "invalid-relative-path")
    monkeypatch.setattr(main, "NativeMcpClient", forbidden)
    monkeypatch.setattr(mcp_auth, "OAuthStore", forbidden)
    monkeypatch.setattr(mcp_auth, "authorized_http", forbidden)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        document = client.get("/openapi.json").json()
        assert set(document["paths"]) == {"/health", *ROUTES}
        for route, model in ROUTES.items():
            assert set(document["paths"][route]) == {"get"}
            schema = document["paths"][route]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            assert schema == {"$ref": f"#/components/schemas/{model.__name__}"}
        for route in ("/v1/snapshot", "/v2/snapshot"):
            for headers in ({}, {"X-API-Key": KEY}):
                response = client.get(route, headers=headers, follow_redirects=False)
                assert response.status_code == 404
                assert "location" not in response.headers


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("key", [None, "", "incorrect-synthetic-key"])
def test_local_authorization_precedes_construction_and_oauth(monkeypatch, route, key):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    monkeypatch.setattr(main, "NativeMcpClient", forbidden)
    monkeypatch.setattr(mcp_auth, "OAuthStore", forbidden)
    monkeypatch.setattr(mcp_auth, "authorized_http", forbidden)
    response = TestClient(main.app).get(route, headers={} if key is None else {"X-API-Key": key})
    assert response.status_code == 401
    assert response.json() == {"error": {
        "code": "BRIDGE_AUTH_FAILED", "message": "Bridge authentication failed", "retryable": False,
    }}


@pytest.mark.parametrize("configured_key", [None, "", KEY])
@pytest.mark.parametrize("selector", [None, "private_api", "finary_official_mcp", "invalid"])
def test_authorized_requests_use_real_client_without_provider_selection(
    monkeypatch, configured_key, selector,
):
    if configured_key is not None:
        monkeypatch.setenv("FINARY_BRIDGE_API_KEY", configured_key)
    if selector is not None:
        monkeypatch.setenv("FINARY_PROVIDER", selector)
    for name in ("FINARY_EMAIL", "FINARY_PASSWORD", "FINARY_MFA_CODE", "FINARY_SESSION_PATH"):
        monkeypatch.setenv(name, "obsolete-synthetic-value")
    wire = SyntheticWire()
    # Keep the real HTTP dependency and constructor; replace only its transport context.
    monkeypatch.setattr(mcp_auth, "authorized_http", wire.http)
    headers = {"X-API-Key": KEY} if configured_key else {}
    client = TestClient(main.app)
    response = client.get("/v3/snapshot", headers=headers)
    assert response.status_code == 200
    value = McpSnapshotV3.model_validate(response.json())
    assert value.provenance.provider == "finary_official_mcp"
    assert [name for name, _ in wire.calls] == ["get_portfolio_overview", "accounts", "holdings"]
    assert "initialize" in wire.requests
    for route, model in ROUTES.items():
        if route == "/v3/snapshot":
            continue
        response = client.get(route, params={"query": "synthetic"}, headers=headers)
        assert response.status_code == 200
        assert model.model_validate(response.json()).provider == "finary_official_mcp"


@pytest.mark.parametrize("state", ["absent", "relative", "empty", "malformed"])
def test_missing_or_invalid_oauth_state_is_sanitized(monkeypatch, tmp_path, caplog, state):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    if state == "relative":
        monkeypatch.setenv("FINARY_MCP_STATE_PATH", "synthetic-relative")
    elif state in {"empty", "malformed"}:
        path = tmp_path / "oauth" / "state.json"
        path.parent.mkdir(mode=0o700)
        if state == "malformed":
            path.write_text('{"synthetic-sensitive-state":true}')
            path.chmod(0o600)
        monkeypatch.setenv("FINARY_MCP_STATE_PATH", str(path))
    response = TestClient(main.app).get("/v3/snapshot", headers={"X-API-Key": KEY})
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "MCP_AUTH_UNAVAILABLE",
        "message": "Independent Finary MCP authorization is unavailable",
        "retryable": False,
    }
    assert "synthetic-sensitive" not in response.text + caplog.text


def test_real_oauth_renewal_sdk_adapter_service_and_http(monkeypatch, tmp_path, caplog):
    store = OAuthStore(tmp_path / "oauth" / "state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    peer.calls.clear()
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    monkeypatch.setenv("FINARY_MCP_STATE_PATH", str(store.path))
    monkeypatch.setattr(
        mcp_auth, "BoundedTransport", lambda transport: BoundedTransport(
            httpx2.MockTransport(peer.respond)
        ),
    )
    client = TestClient(main.app)
    response = client.get("/v3/snapshot", headers={"X-API-Key": KEY})
    assert response.status_code == 200
    assert peer.token_requests == ["authorization_code", "refresh_token"]
    assert [name for name, _ in peer.calls] == ["get_portfolio_overview", "accounts", "holdings"]
    value = McpSnapshotV3.model_validate(response.json())
    assert value.provenance.provider == "finary_official_mcp"
    peer.reject_refresh = True
    with caplog.at_level(logging.DEBUG):
        response = client.get("/v3/snapshot", headers={"X-API-Key": KEY})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_AUTH_UNAVAILABLE"
    for marker in ("synthetic-access", "synthetic-renewable", "synthetic-secret"):
        assert marker not in response.text + caplog.text


@pytest.mark.parametrize("route,params", [
    ("/v3/budget", {"period": "synthetic-sensitive-invalid"}),
    ("/v3/budget", {"start_date": "2026-01-01"}),
    ("/v3/spending-search", {}),
    ("/v3/spending-search", {"query": " "}),
    ("/v3/spending-search", {"query": "synthetic-sensitive", "direction": "invalid"}),
])
def test_optional_invalid_arguments_fail_before_oauth(monkeypatch, route, params):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    monkeypatch.setattr(mcp_auth, "authorized_http", forbidden)
    response = TestClient(main.app).get(route, params=params, headers={"X-API-Key": KEY})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MCP_INVALID_ARGUMENT"
    assert "synthetic-sensitive" not in response.text


@pytest.mark.parametrize("route,tool", [
    ("/v3/snapshot", "holdings"), ("/v3/budget", "get_budget_overview"),
    ("/v3/spending-search", "search_spending"), ("/v3/goals", "goals"),
])
def test_upstream_errors_are_sanitized_at_real_http_boundary(monkeypatch, caplog, route, tool):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    wire = SyntheticWire()
    wire.tool_error = tool
    monkeypatch.setattr(mcp_auth, "authorized_http", wire.http)
    response = TestClient(main.app).get(
        route, params={"query": "synthetic"}, headers={"X-API-Key": KEY},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MCP_TOOL_ERROR"
    assert not response.json()["error"]["retryable"]
    assert "synthetic" not in response.text + caplog.text
