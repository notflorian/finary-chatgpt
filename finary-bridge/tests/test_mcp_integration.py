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


def test_native_catalog_pagination_and_repeated_cursor():
    wire = SyntheticWire()
    tools = wire.catalog()
    wire.catalog_pages = {
        None: {"tools": tools[:2], "nextCursor": "next"},
        "next": {"tools": tools[2:]},
    }
    assert snapshot(wire)["coverage"]["accounts"] == "COMPLETE"
    assert wire.requests.count("tools/list") == 2
    wire.catalog_pages["next"]["nextCursor"] = "next"
    with pytest.raises(McpFailure):
        snapshot(wire)


def test_missing_detail_is_qualified_but_missing_overview_fails():
    wire = SyntheticWire()
    wire.tools.remove("holdings")
    assert snapshot(wire)["coverage"]["holdings"] == "UNAVAILABLE"
    wire.tools.remove("accounts")
    assert snapshot(wire)["coverage"]["accounts"] == "UNAVAILABLE"
    wire.tools.remove("get_portfolio_overview")
    with pytest.raises(McpFailure):
        snapshot(wire)


@pytest.mark.parametrize("mode", ["zero-debt", "unvalued", "assets-only"])
def test_debt_quality_through_native_production_path(mode):
    wire = SyntheticWire()
    sheet = wire.values["overview"]["balance_sheet"]
    if mode == "zero-debt":
        sheet["owned_liabilities_direct"] = "0"
        sheet["owned_net_worth_direct"] = sheet["owned_gross_assets_direct"]
    if mode == "unvalued":
        sheet["unvalued_liability_count"] = 1
    if mode == "assets-only":
        sheet["completeness"] = "assets_only"
        sheet["owned_liabilities_direct"] = None
        sheet["owned_net_worth_direct"] = None
    result = snapshot(wire)
    assert (
        result["coverage"]["debt_valuation"]
        == {"zero-debt": "COMPLETE", "unvalued": "PARTIAL", "assets-only": "UNAVAILABLE"}[mode]
    )
    assert result["coverage"]["debt_detail"] == "UNAVAILABLE"


@pytest.mark.parametrize("mode", ["manual", "stale", "broken", "never"])
def test_native_bank_sync_is_separate_from_ingestion(mode):
    wire = SyntheticWire()
    account = wire.values["accounts"]["data"][0]
    if mode == "manual":
        account["relationships"].pop("institution_connection", None)
    else:
        account["relationships"]["institution_connection"] = {
            "data": {"type": "institution-connections", "id": "synthetic-bank"}
        }
        wire.values["accounts"]["included"].append(
            {
                "type": "institution-connections",
                "id": "synthetic-bank",
                "attributes": {
                    "last_successful_sync_at": None
                    if mode == "never"
                    else "2026-09-01T10:00:00+02:00",
                    "updated_at": NOW.isoformat(),
                    "error_message": "Synthetic private bank error" if mode == "broken" else None,
                },
                "relationships": {},
            }
        )
    result = snapshot(wire)
    assert (
        result["coverage"]["source_freshness"]
        == {"manual": "NOT_APPLICABLE", "stale": "STALE", "broken": "BROKEN", "never": "UNKNOWN"}[
            mode
        ]
    )
    assert "private bank error" not in str(result)


def test_empty_second_account_is_retrieved_without_name_deduplication():
    wire = SyntheticWire()
    second = deepcopy(wire.values["accounts"]["data"][0])
    second["id"] = "synthetic-second"
    wire.values["accounts"]["data"].append(second)

    def mutate(name, args, value):
        if name == "holdings" and args["account_id"] == "synthetic-second":
            value["data"] = []
            value["meta"].update(total=0, has_more=False)
        return value

    wire.mutate = mutate
    value = snapshot(wire)
    assert len(value["accounts"]) == 2 and len(value["positions"]) == 1
    assert wire.requests.count("tools/call") == 4


def test_transient_rate_limit_is_bounded_and_sanitized():
    wire = SyntheticWire()
    wire.http_status = lambda name, args: 429
    with pytest.raises(McpFailure) as failed:
        snapshot(wire)
    assert failed.value.code == "MCP_RATE_LIMITED"
    assert len(wire.calls) == 3


def test_multiple_accounts_share_one_connection_record():
    wire = SyntheticWire()
    first = wire.values["accounts"]["data"][0]
    first["relationships"]["institution_connection"] = {
        "data": {"type": "institution-connections", "id": "synthetic-shared"}
    }
    second = deepcopy(first)
    second["id"] = "synthetic-other"
    wire.values["accounts"]["data"].append(second)
    wire.values["accounts"]["included"].append(
        {
            "type": "institution-connections",
            "id": "synthetic-shared",
            "attributes": {"last_successful_sync_at": NOW.isoformat()},
            "relationships": {},
        }
    )

    def mutate(name, args, value):
        if name == "holdings" and args["account_id"] == second["id"]:
            value["data"] = []
            value["meta"].update(total=0, has_more=False)
        return value

    wire.mutate = mutate
    value = snapshot(wire)
    assert len(value["accounts"]) == 2 and len(value["connections"]) == 1
    assert value["coverage"]["source_freshness"] == "FRESH"


@pytest.mark.parametrize(
    "body", [b'{"result":1,"result":2}', b'{"result":NaN}', b'{"result":Infinity}']
)
def test_raw_json_is_validated_before_sdk_parsing(body):
    import httpx2

    from app.mcp_client import LimitedStream

    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield body[:5]
            yield body[5:]

    async def read():
        return b"".join([chunk async for chunk in LimitedStream(Chunks(), "application/json")])

    with pytest.raises(McpFailure):
        asyncio.run(read())


@pytest.mark.parametrize("duplicate", [False, True])
def test_sse_multiline_event_is_bounded_before_sdk_decoding(duplicate):
    import httpx2

    from app.mcp_client import LimitedStream

    body = b'event: message\r\ndata: {"jsonrpc":"2.0",\r\ndata: "id":1,"result":{}}\r\n\r\n'
    if duplicate:
        body = body.replace(b'"result":{}', b'"result":{},"result":{}')

    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self):
            for offset in range(0, len(body), 7):
                yield body[offset : offset + 7]

    async def read():
        return b"".join([chunk async for chunk in LimitedStream(Chunks(), "text/event-stream")])

    if duplicate:
        with pytest.raises(McpFailure):
            asyncio.run(read())
    else:
        assert asyncio.run(read()) == body


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_discovery_rejects_external_schema_fetches(field, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected schema network retrieval")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    wire = SyntheticWire()
    tools = wire.catalog()
    tools[0][field] = {"type": "object", "$ref": "https://untrusted.invalid/schema"}
    wire.catalog_pages = {None: {"tools": tools}}
    with pytest.raises(McpFailure) as failure:
        snapshot(wire)
    assert failure.value.code == "MCP_CAPABILITY_UNAVAILABLE"
    assert not wire.calls
