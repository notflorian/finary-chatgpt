"""MCP-only HTTP authorization through the retained SDK and OAuth boundaries."""

import asyncio
import logging
import socket

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp_auth_peer import AuthPeer, consent
from mcp_wire import SyntheticWire

from app import main, mcp_auth
from app.mcp_auth import OAuthStore
from app.mcp_client import BoundedTransport
from app.mcp_models import McpSnapshotV1
from app.mcp_optional import BudgetResponse, GoalsResponse, SearchResponse

ROUTES = {
    "/v1/snapshot": McpSnapshotV1,
    "/v1/budget": BudgetResponse,
    "/v1/spending-search": SearchResponse,
    "/v1/goals": GoalsResponse,
}
KEY = "synthetic-local-key"
ROUTE_CALLS = {
    "/v1/snapshot": ["get_portfolio_overview", "accounts", "holdings"],
    "/v1/budget": ["get_budget_overview"],
    "/v1/spending-search": ["search_spending"],
    "/v1/goals": ["goals", "accounts"],
}


def forbidden(*args, **kwargs):
    pytest.fail("Unexpected upstream or OAuth-state access")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def no_schema_fetch(monkeypatch):
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("Unexpected schema network retrieval")

    monkeypatch.setattr("urllib.request.urlopen", reject)
    yield
    assert attempts == []


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
@pytest.mark.parametrize("route,tool", [
    ("/v1/snapshot", "get_budget_overview"),
    ("/v1/snapshot", "get_portfolio_overview"),
    ("/v1/snapshot", "accounts"),
    ("/v1/snapshot", "holdings"),
    ("/v1/budget", "get_portfolio_overview"),
    ("/v1/budget", "get_budget_overview"),
    ("/v1/spending-search", "get_budget_overview"),
    ("/v1/spending-search", "accounts"),
    ("/v1/spending-search", "holdings"),
    ("/v1/spending-search", "search_spending"),
    ("/v1/goals", "get_budget_overview"),
    ("/v1/goals", "goals"),
    ("/v1/goals", "accounts"),
])
def test_tool_schema_validation_is_scoped_to_invocations(
    monkeypatch, caplog, no_schema_fetch, route, tool, field,
):
    wire = SyntheticWire()
    catalog = wire.catalog()
    selected = next(item for item in catalog if item["name"] == tool)
    selected[field] = {"type": "object", "$ref": "https://synthetic.invalid/schema"}
    wire.catalog_pages = {None: {"tools": catalog}}
    monkeypatch.setattr(mcp_auth, "authorized_http", wire.http)

    response = TestClient(main.app).get(route, params={"query": "synthetic"})

    expected_calls = ROUTE_CALLS[route]
    if tool in expected_calls:
        assert response.status_code == 503
        assert response.json() == {"error": {
            "code": "MCP_CAPABILITY_UNAVAILABLE",
            "message": "Required Finary MCP capability is unavailable",
            "retryable": False,
        }}
        assert "synthetic" not in response.text + caplog.text
        expected_calls = expected_calls[:expected_calls.index(tool)]
        assert len(wire.calls) <= len(expected_calls)
        expected_calls = expected_calls[:len(wire.calls)]
    else:
        assert response.status_code == 200
        ROUTES[route].model_validate(response.json())
    assert [name for name, _ in wire.calls] == expected_calls
    assert "tools/list" in wire.requests and "initialize" in wire.requests


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("incompatible_holdings", [False, True])
def test_holdings_pagination_schema_only_applies_when_used(
    monkeypatch, route, incompatible_holdings,
):
    wire = SyntheticWire()
    if incompatible_holdings:
        catalog = wire.catalog()
        holdings = next(tool for tool in catalog if tool["name"] == "holdings")
        holdings["inputSchema"]["properties"]["offset"] = {"type": "integer"}
        wire.catalog_pages = {None: {"tools": catalog}}
    monkeypatch.setattr(mcp_auth, "authorized_http", wire.http)

    response = TestClient(main.app).get(route, params={"query": "synthetic"})

    expected_calls = ROUTE_CALLS[route]
    if incompatible_holdings and route == "/v1/snapshot":
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MCP_CAPABILITY_UNAVAILABLE"
        expected_calls = expected_calls[:-1]
        assert len(wire.calls) <= len(expected_calls)
        expected_calls = expected_calls[:len(wire.calls)]
    else:
        assert response.status_code == 200
        ROUTES[route].model_validate(response.json())
    assert [name for name, _ in wire.calls] == expected_calls


@pytest.mark.parametrize("mutation", ["duplicate", "cursor", "inputSchema", "outputSchema"])
def test_unused_tools_still_require_valid_catalog_envelopes(monkeypatch, mutation):
    wire = SyntheticWire()
    catalog = wire.catalog()
    page = {"tools": catalog}
    unused = next(tool for tool in catalog if tool["name"] == "get_budget_overview")
    if mutation == "duplicate":
        catalog.append(unused)
    elif mutation == "cursor":
        page["nextCursor"] = ""
    else:
        unused[mutation] = ["synthetic-invalid-schema-envelope"]
    wire.catalog_pages = {None: page}
    monkeypatch.setattr(mcp_auth, "authorized_http", wire.http)

    response = TestClient(main.app).get("/v1/snapshot")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MCP_PROTOCOL_ERROR"
    assert "synthetic" not in response.text
    assert wire.calls == []


@pytest.mark.parametrize("configured_key", [None, KEY])
def test_startup_health_openapi_and_unsupported_routes_are_local(monkeypatch, configured_key):
    if configured_key is None:
        monkeypatch.delenv("FINARY_BRIDGE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("FINARY_BRIDGE_API_KEY", configured_key)
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
        for route in (
            f"/v{version}/{endpoint}"
            for version in (2, 3)
            for endpoint in ("snapshot", "budget", "spending-search", "goals")
        ):
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
    response = client.get("/v1/snapshot", headers=headers)
    assert response.status_code == 200
    value = McpSnapshotV1.model_validate(response.json())
    assert value.provenance.provider == "finary_official_mcp"
    assert value.schema_version == "1.0"
    assert value.provenance.source_contract_version == "1.0.0"
    assert [name for name, _ in wire.calls] == ["get_portfolio_overview", "accounts", "holdings"]
    assert "initialize" in wire.requests
    for route, model in ROUTES.items():
        if route == "/v1/snapshot":
            continue
        response = client.get(route, params={"query": "synthetic"}, headers=headers)
        assert response.status_code == 200
        optional = model.model_validate(response.json())
        assert optional.provider == "finary_official_mcp"
        assert optional.schema_version == "1.0"
        assert optional.source_contract_version == "1.0.0"


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
    response = TestClient(main.app).get("/v1/snapshot", headers={"X-API-Key": KEY})
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
    response = client.get("/v1/snapshot", headers={"X-API-Key": KEY})
    assert response.status_code == 200
    assert peer.token_requests == ["authorization_code", "refresh_token"]
    assert [name for name, _ in peer.calls] == ["get_portfolio_overview", "accounts", "holdings"]
    value = McpSnapshotV1.model_validate(response.json())
    assert value.provenance.provider == "finary_official_mcp"
    assert value.schema_version == "1.0"
    assert value.provenance.source_contract_version == "1.0.0"
    peer.reject_refresh = True
    with caplog.at_level(logging.DEBUG):
        response = client.get("/v1/snapshot", headers={"X-API-Key": KEY})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_AUTH_UNAVAILABLE"
    for marker in ("synthetic-access", "synthetic-renewable", "synthetic-secret"):
        assert marker not in response.text + caplog.text


@pytest.mark.parametrize("route,params", [
    ("/v1/budget", {"period": "synthetic-sensitive-invalid"}),
    ("/v1/budget", {"start_date": "2026-01-01"}),
    ("/v1/spending-search", {}),
    ("/v1/spending-search", {"query": " "}),
    ("/v1/spending-search", {"query": "synthetic-sensitive", "direction": "invalid"}),
])
def test_optional_invalid_arguments_fail_before_oauth(monkeypatch, route, params):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", KEY)
    monkeypatch.setattr(mcp_auth, "authorized_http", forbidden)
    response = TestClient(main.app).get(route, params=params, headers={"X-API-Key": KEY})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MCP_INVALID_ARGUMENT"
    assert "synthetic-sensitive" not in response.text


@pytest.mark.parametrize("route,tool", [
    ("/v1/snapshot", "holdings"), ("/v1/budget", "get_budget_overview"),
    ("/v1/spending-search", "search_spending"), ("/v1/goals", "goals"),
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
