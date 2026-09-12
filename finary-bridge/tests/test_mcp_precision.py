"""Exact precision through the native client and versioned downstream boundary."""

from copy import deepcopy
from subprocess import CalledProcessError

import pytest
from mcp_wire import SyntheticWire
from pydantic import TypeAdapter, ValidationError
from test_mcp_integration import snapshot
from test_mcp_workflow import prepare

from app.mcp_client import McpFailure
from app.mcp_models import McpSnapshotV3
from app.mcp_optional import DecimalText, ReadContext
from app.mcp_validation import CONTRACT


def precise_wire(amount):
    wire = SyntheticWire()
    account = wire.values["accounts"]["data"][0]["attributes"]
    account["balance"] = account["full_value_eur"] = amount
    wire.values["holdings"]["data"][0]["attributes"]["current_value"] = amount
    return wire


@pytest.mark.parametrize("scale", [18, 19, 28, 64])
def test_native_precision_is_preserved_without_float_or_rounding(scale):
    amount = "123456789012345678901234." + "1" * scale
    value = snapshot(precise_wire(amount))
    assert value["provenance"]["source_contract_version"] == CONTRACT["contract_version"]
    assert value["accounts"][0]["native_balance"]["amount"] == amount
    assert value["positions"][0]["current_value"]["amount"] == amount
    assert TypeAdapter(DecimalText).validate_python(amount) == amount
    assert (
        ReadContext.model_fields["source_contract_version"].default == CONTRACT["contract_version"]
    )
    prepare(value)


@pytest.mark.parametrize("amount", ["0." + "1" * 65, "1e-20", "NaN", " 1", True, 1.25])
def test_native_and_optional_decimal_limits_remain_fail_closed(amount):
    with pytest.raises(McpFailure):
        snapshot(precise_wire(amount))
    with pytest.raises(ValidationError):
        TypeAdapter(DecimalText).validate_python(amount)


def test_python_and_exported_js_compare_every_fractional_digit_exactly():
    amount = "1." + "1" * 63
    value = snapshot(precise_wire(amount))
    # Equivalent source scales stay valid; no decimal context or float rounding.
    value["positions"][0]["current_value"]["amount_eur"] = amount + "0"
    McpSnapshotV3.model_validate(value)
    prepare(value)
    different = deepcopy(value)
    different["positions"][0]["current_value"]["amount_eur"] = amount + "1"
    with pytest.raises(ValidationError):
        McpSnapshotV3.model_validate(different)
    with pytest.raises(CalledProcessError):
        prepare(different)


def test_prior_source_contract_is_not_silently_relabelled():
    value = snapshot()
    value["provenance"]["source_contract_version"] = "1.0.0"
    with pytest.raises(ValidationError):
        McpSnapshotV3.model_validate(value)
    with pytest.raises(CalledProcessError):
        prepare(value)
