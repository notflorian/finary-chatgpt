"""Synthetic proof that live diagnostics do not reveal portfolio or error values."""

import asyncio
import json

import pytest
from mcp_live_diagnostics import decimal_shape, install_diagnostics
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


@pytest.mark.parametrize(
    "value,syntax,fraction",
    [
        ("1.234e-5", "SCIENTIFIC_NOTATION", False),
        ("0.1234567890123456789", "PLAIN_DECIMAL", True),
        ("+00023.50", "PLAIN_DECIMAL", False),
        (" 23.50 ", "PLAIN_DECIMAL", False),
        ("NaN", "NON_FINITE", None),
        ("synthetic-secret", "OTHER_TEXT", None),
        ("1e999999999999999999999999", "UNSUPPORTED_DECIMAL", None),
    ],
)
def test_decimal_shape_never_reports_digits_or_values(value, syntax, fraction):
    result = decimal_shape(value)
    assert result["syntax"] == syntax
    if fraction is not None:
        assert result["fraction_limit_exceeded"] is fraction
    output = json.dumps(result)
    assert value not in output
    assert not any(character.isdigit() for character in output)


def test_live_account_decimal_failure_reports_shape_only(monkeypatch, capsys):
    wire = SyntheticWire()
    wire.values["accounts"]["data"][0]["attributes"]["balance"] = "1.234e-5"
    report = install_diagnostics(monkeypatch)
    with pytest.raises(McpFailure) as stopped:
        asyncio.run(McpSnapshotService(wire.client()).snapshot())
    report(stopped.value)
    output = capsys.readouterr().out
    diagnostic = json.loads(output)["structural_diagnostic"]
    assert diagnostic["contract"] == "account_observed"
    assert any(
        rule.get("decimal_shape", {}).get("syntax") == "SCIENTIFIC_NOTATION"
        for rule in diagnostic["rules"]
    )
    assert "1.234" not in output


def test_decimal_shape_checks_exact_trimming_without_rounding():
    padded = decimal_shape("0.123456789012345678000")
    assert padded["fraction_limit_exceeded"] is True
    assert padded["exact_value_fits_bounds"] is True
    precise = decimal_shape("0.123456789012345678001")
    assert precise["exact_value_fits_bounds"] is False
