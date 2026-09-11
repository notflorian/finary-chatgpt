"""Synthetic proof that live diagnostics do not reveal portfolio or error values."""

import asyncio
import json

import pytest
from mcp_live_diagnostics import install_diagnostics
from mcp_wire import SyntheticWire

from app.mcp_client import McpFailure
from app.services.mcp_snapshot_service import McpSnapshotService


@pytest.mark.parametrize("failure", ["contract", "native", "remote_schema", "normalization"])
def test_live_diagnostics_preserve_failure_and_hide_private_values(monkeypatch, capsys, failure):
    wire = SyntheticWire()
    if failure == "contract":
        wire.values["overview"].pop("view")
        wire.values["overview"]["_reading_note"] = {"synthetic-private-key": "synthetic-secret"}
    elif failure == "remote_schema":
        catalog = wire.catalog()
        catalog[0]["outputSchema"] = {"type": "object", "required": ["synthetic-private-key"]}
        wire.catalog_pages = {None: {"tools": catalog}}
    elif failure == "normalization":
        wire.values["overview"]["view"]["scope"] = "synthetic-private-value"
    else:
        original = wire.respond

        def respond(request):
            response = original(request)
            if json.loads(request.content).get("method") == "tools/call":
                value = response.json()
                value["result"]["content"][0]["text"] = "synthetic-secret-non-json"
                import httpx2

                return httpx2.Response(200, json=value)
            return response

        wire.respond = respond

    report = install_diagnostics(monkeypatch)
    with pytest.raises(McpFailure) as stopped:
        asyncio.run(McpSnapshotService(wire.client()).snapshot())
    report(stopped.value)
    output = capsys.readouterr().out
    diagnostic = json.loads(output)["structural_diagnostic"]
    assert diagnostic["tool"] == "get_portfolio_overview"
    assert (
        diagnostic["stage"]
        == {
            "contract": "CONTRACT_VALIDATION",
            "native": "NATIVE_RESULT_DECODING",
            "remote_schema": "SDK_OUTPUT_SCHEMA",
            "normalization": "NORMALIZATION",
        }[failure]
    )
    if failure == "contract":
        assert diagnostic["contract"] == "overview_output"
        assert any(rule.get("missing_fields") == ["view"] for rule in diagnostic["rules"])
    if failure == "native":
        assert diagnostic["native_shape"]["content"] == ["INVALID_JSON"]
    assert "synthetic-private" not in output
    assert "synthetic-secret" not in output
    assert "instance" not in output


def test_live_diagnostics_leave_valid_production_collection_unchanged(monkeypatch, capsys):
    install_diagnostics(monkeypatch)
    result = asyncio.run(McpSnapshotService(SyntheticWire().client()).snapshot())
    assert result.schema_version == "3.0"
    assert capsys.readouterr().out == ""
