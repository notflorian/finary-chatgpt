"""Warning collection behavior through the adapter and native service path."""

from copy import deepcopy
from typing import cast

import pytest
from mcp_snapshots import snapshot
from mcp_wire import SyntheticWire
from pydantic import ValidationError

from app.mcp_adapter import Detail
from app.mcp_models import McpWarning


def test_warning_identities_preserve_first_seen_order_and_entity_distinctions():
    detail = Detail()
    for code, entity in (
        ("MISSING_ENRICHMENT", "opaque-a"),
        ("STALE_SOURCE", None),
        ("MISSING_ENRICHMENT", "opaque-b"),
        ("MISSING_ENRICHMENT", None),
        ("STALE_SOURCE", "opaque-a"),
        ("MISSING_ENRICHMENT", "opaque-a"),
        ("STALE_SOURCE", None),
    ):
        detail.warn(code, entity)

    assert [(warning.code, warning.entity_key) for warning in detail.warnings] == [
        ("MISSING_ENRICHMENT", "opaque-a"),
        ("STALE_SOURCE", None),
        ("MISSING_ENRICHMENT", "opaque-b"),
        ("MISSING_ENRICHMENT", None),
        ("STALE_SOURCE", "opaque-a"),
    ]


def test_invalid_warning_is_validated_before_deduplication_and_preserves_state():
    detail = Detail()
    detail.warn("MISSING_ENRICHMENT", "opaque-a")
    before = list(detail.warnings)

    with pytest.raises(ValidationError):
        detail.warn("MISSING_ENRICHMENT", cast(str, []))

    assert detail.warnings == before


def test_detail_instances_and_service_collections_keep_separate_warning_state():
    first, second = Detail(), Detail()
    first.warn("MISSING_ENRICHMENT", "opaque-a")
    second.warn("MISSING_ENRICHMENT", "opaque-a")
    assert len(first.warnings) == len(second.warnings) == 1

    initial = snapshot()
    repeated = snapshot()
    assert initial["warnings"] == repeated["warnings"]


def test_service_warning_added_after_adapter_collection_is_preserved():
    wire = SyntheticWire()
    wire.values["overview"]["balance_sheet"]["unvalued_liability_count"] = 1

    result = snapshot(wire)

    assert result["coverage"]["debt_valuation"] == "PARTIAL"
    assert [warning for warning in result["warnings"] if warning["code"] == "UNVALUED_DEBT"] == [
        {"code": "UNVALUED_DEBT", "entity_key": None}
    ]


def _warning_probe(size, monkeypatch, *, legacy=False):
    wire = SyntheticWire()
    holding = wire.values["holdings"]["data"][0]
    wire.values["holdings"]["data"] = [
        {**deepcopy(holding), "id": f"synthetic-holding-{index}"} for index in range(size)
    ]
    wire.values["holdings"]["included"] = []
    comparisons = 0
    original_equals = McpWarning.__eq__

    def counted_equals(self, other):
        nonlocal comparisons
        comparisons += 1
        return original_equals(self, other)

    with monkeypatch.context() as patched:
        patched.setattr(McpWarning, "__eq__", counted_equals)
        if legacy:

            def legacy_warn(self, code, entity=None):
                warning = McpWarning.model_validate({"code": code, "entity_key": entity})
                if warning not in self.warnings:
                    self.warnings.append(warning)

            patched.setattr(Detail, "warn", legacy_warn)
        result = snapshot(wire)

    return result, comparisons


def _expected_warning_probe(size):
    keys = [
        f"mcp:account:assets:synthetic-a:holding:security-holdings:synthetic-holding-{index}"
        for index in range(size)
    ]
    warnings = [
        {"code": "OWNERSHIP_WORDING_CONFLICT", "entity_key": None},
        *({"code": "MISSING_ENRICHMENT", "entity_key": key} for key in keys),
        {"code": "UNVERIFIED_DETAIL", "entity_key": None},
    ]
    position = {
        "account_key": "mcp:account:assets:synthetic-a",
        "asset_class": "OTHER",
        "buying_price": {
            "amount": "30.00",
            "amount_eur": None,
            "currency": "USD",
            "eur_basis": "UNAVAILABLE",
        },
        "buying_price_basis": "UNVERIFIED",
        "current_value": {
            "amount": "90.00",
            "amount_eur": "90.00",
            "currency": "EUR",
            "eur_basis": "SOURCE_EUR",
        },
        "entity_updated_at": None,
        "holding_type": "security-holdings",
        "label": None,
        "product_key": None,
        "quantity": "2",
        "quantity_unit": "UNITS",
        "value_ownership_basis": "UNVERIFIED",
    }
    positions = [
        {
            **position,
            "holding_id": f"synthetic-holding-{index}",
            "position_key": key,
            "source_asset_id": f"mcp:holding:security-holdings:synthetic-holding-{index}",
        }
        for index, key in enumerate(keys)
    ]
    coverage = {
        "accounts": "COMPLETE",
        "holdings": "COMPLETE",
        "debt_detail": "UNAVAILABLE",
        "account_valuation": "COMPLETE",
        "holding_valuation": "COMPLETE",
        "debt_valuation": "COMPLETE",
        "overview_quality": "REPORTED_COMPLETE",
        "detail_semantics": "UNVERIFIED",
        "source_freshness": "NOT_APPLICABLE",
        "debt_detail_basis": "UNVERIFIED",
    }
    def money(amount):
        return {
            "amount": amount,
            "currency": "EUR",
            "amount_eur": amount,
            "eur_basis": "SOURCE_EUR",
        }
    overview = {
        "gross_assets": money("1000.00"),
        "financial_assets": money("600.00"),
        "reported_liabilities": money("200.00"),
        "reported_net_worth": money("800.00"),
        "unvalued_liability_count": 0,
        "source_completeness": "complete",
        "preferred_wealth_metric": "financial_assets",
    }
    return warnings, positions, coverage, overview


def test_legacy_negative_control_detects_accumulated_list_scans(monkeypatch):
    size = 25
    result, comparisons = _warning_probe(size, monkeypatch, legacy=True)
    warnings, positions, coverage, overview = _expected_warning_probe(size)

    assert result["warnings"] == warnings
    assert result["positions"] == positions
    assert result["coverage"] == coverage
    assert result["overview"] == overview
    warning_count = len(warnings)
    assert comparisons == warning_count * (warning_count - 1) // 2


@pytest.mark.parametrize("size", [250, 500, 1_000])
def test_native_service_warning_deduplication_avoids_accumulated_list_scans(size, monkeypatch):
    optimized, optimized_comparisons = _warning_probe(size, monkeypatch)
    warnings, positions, coverage, overview = _expected_warning_probe(size)

    assert optimized["warnings"] == warnings
    assert optimized["positions"] == positions
    assert optimized["coverage"] == coverage
    assert optimized["overview"] == overview
    assert optimized_comparisons == 0
