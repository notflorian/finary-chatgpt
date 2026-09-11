"""Synthetic native wire -> SDK -> adapter -> service/API integration regressions."""

import asyncio
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult
from mcp_wire import SyntheticWire
from test_finary_mcp_contract import MANIFEST, materialize, snapshot_error, validator

from app.main import app, get_authenticated_mcp_client
from app.mcp_client import McpFailure, decode_result
from app.mcp_models import McpSnapshotV3
from app.services.mcp_snapshot_service import McpSnapshotService

NOW = datetime.fromisoformat("2026-09-11T10:00:00+02:00")


def snapshot(wire=None, **kwargs):
    return asyncio.run(
        McpSnapshotService(
            (wire or SyntheticWire()).client(), clock=lambda: NOW, **kwargs
        ).snapshot()
    ).model_dump()


def test_native_protocol_real_path_and_authority():
    wire = SyntheticWire()
    value = snapshot(wire)
    assert "server/discover" in wire.requests
    assert "initialize" in wire.requests
    assert value["overview"]["gross_assets"]["amount"] == "1000.00"
    assert value["overview"]["financial_assets"]["amount"] == "600.00"
    assert value["accounts"][0]["full_value_eur"] == "250.00"
    assert value["accounts"][0]["direct_owners_value_eur"] == "375.00"
    assert value["ownership"][0]["ownership_share"] == "1.5"
    assert value["members"][0]["reported_net_worth"]["amount"] == "-20"
    assert value["coverage"]["debt_detail"] == "UNAVAILABLE"
    assert value["positions"][0]["buying_price"]["amount_eur"] is None
    assert [name for name, _ in wire.calls] == ["get_portfolio_overview", "accounts", "holdings"]
    assert all("prompt" not in args for _, args in wire.calls)
    assert snapshot_error(value) is None
    validator("#/$defs/snapshot_v3").validate(value)


def test_pagination_and_distinct_holding_identity():
    wire = SyntheticWire()
    second = deepcopy(wire.values["holdings"]["data"][0])
    second["id"] = "same-product-different-holding"
    wire.values["holdings"]["data"].append(second)
    value = snapshot(wire, page_limit=1)
    assert len(value["positions"]) == 2
    assert [a["offset"] for n, a in wire.calls if n == "holdings"] == [0, 1]


@pytest.mark.parametrize("mode", ["total", "offset", "parent", "repeat", "empty", "has_more"])
def test_broken_pagination_aborts(mode):
    wire = SyntheticWire()
    second = deepcopy(wire.values["holdings"]["data"][0])
    second["id"] = "second"
    wire.values["holdings"]["data"].append(second)

    def mutate(name, args, value):
        if name != "holdings" or args["offset"] == 0:
            return value
        if mode == "total":
            value["meta"]["total"] += 1
        if mode == "offset":
            value["meta"]["offset"] = 0
        if mode == "parent":
            value["data"][0]["relationships"]["asset"]["data"]["id"] = "other"
        if mode == "repeat":
            value["data"][0]["id"] = "synthetic-h1"
        if mode == "empty":
            value["data"] = []
        if mode == "has_more":
            value["meta"]["has_more"] = True
        return value

    wire.mutate = mutate
    with pytest.raises(McpFailure):
        snapshot(wire, page_limit=1)


def test_empty_and_unsupported_have_different_write_sets():
    empty = SyntheticWire()
    empty.values["holdings"]["data"] = []
    assert snapshot(empty)["coverage"]["holding_valuation"] == "COMPLETE"
    unsupported = SyntheticWire()
    unsupported.values["holdings"]["data"][0]["type"] = "unobserved-loans"
    value = snapshot(unsupported)
    assert value["positions"] == []
    assert value["coverage"]["holdings"] == "PARTIAL"
    assert value["unsupported_details"][0]["count"] == 1


@pytest.mark.parametrize("currency,unknown", [("EUR", False), ("USD", False), ("USD", True)])
def test_native_valuation_and_view_currency(currency, unknown):
    wire = SyntheticWire()
    wire.values["overview"]["view"]["currency"] = currency
    row = wire.values["holdings"]["data"][0]["attributes"]
    row.update(current_value=None if unknown else "90.00", current_value_currency=currency)
    value = snapshot(wire)
    assert value["coverage"]["holding_valuation"] == ("UNAVAILABLE" if unknown else "COMPLETE")
    if currency == "USD":
        assert value["overview"]["gross_assets"]["amount_eur"] is None
        assert value["accounts"][0]["full_value_eur"] == "250.00"


@pytest.mark.parametrize("code", ["tool", "malformed", "auth"])
def test_failures_sanitized_through_api(code, monkeypatch):
    wire = SyntheticWire()
    if code == "tool":
        wire.tool_error = "holdings"
    if code == "malformed":
        wire.values["holdings"]["data"][0]["attributes"]["current_value"] = (
            "secret-synthetic-invalid"
        )
    if code == "auth":
        wire.http_status = lambda name, args: 403
    app.dependency_overrides[get_authenticated_mcp_client] = wire.client
    try:
        response = TestClient(app).get("/v3/snapshot")
        assert response.status_code >= 500
        assert "synthetic" not in response.text
        assert set(response.json()["error"]) == {"code", "message", "retryable"}
    finally:
        app.dependency_overrides.clear()


def test_auth_precedes_provider_and_health(monkeypatch):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "synthetic-bridge-key")
    monkeypatch.setenv("FINARY_PROVIDER", "finary_official_mcp")
    monkeypatch.delenv("FINARY_MCP_STATE_PATH", raising=False)
    client = TestClient(app)
    assert client.get("/v3/snapshot").status_code == 401
    assert client.get("/health").status_code == 200
    response = client.get("/v3/snapshot", headers={"X-API-Key": "synthetic-bridge-key"})
    assert response.json()["error"]["code"] == "MCP_AUTH_UNAVAILABLE"


@pytest.mark.parametrize(
    "case",
    [c for c in MANIFEST["cases"] if c["schema"] == "#/$defs/snapshot_v3"],
    ids=lambda c: c["id"],
)
def test_runtime_models_preserve_contract_oracle(case):
    value = materialize(case)
    accepted = validator(case["schema"]).is_valid(value) and snapshot_error(value) is None
    if accepted:
        assert McpSnapshotV3.model_validate(value).model_dump() == value
    else:
        with pytest.raises(ValueError):
            McpSnapshotV3.model_validate(value)


@pytest.mark.parametrize("text", ['{"data":1,"data":2}', '{"data":2}', "sensitive arbitrary prose"])
def test_native_conflicting_payloads(text):
    result = CallToolResult.model_validate(
        {"content": [{"type": "text", "text": text}], "structuredContent": {"data": 1}}
    )
    with pytest.raises(McpFailure):
        decode_result(result)


def test_generated_model_and_package_parity():
    root = Path(__file__).parents[2]
    subprocess.run(
        [sys.executable, str(root / "scripts/build-mcp-models.py"), "--check"], check=True
    )
    assert (root / "docs/finary-mcp-contract.json").read_bytes() == (
        root / "finary-bridge/app/mcp-contract.json"
    ).read_bytes()
