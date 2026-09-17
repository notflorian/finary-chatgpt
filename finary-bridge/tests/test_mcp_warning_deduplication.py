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


def _warning_probe(size, monkeypatch, *, legacy):
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


@pytest.mark.parametrize("size", [250, 500, 1_000])
def test_native_service_warning_deduplication_avoids_accumulated_list_scans(size, monkeypatch):
    baseline, baseline_comparisons = _warning_probe(size, monkeypatch, legacy=True)
    optimized, optimized_comparisons = _warning_probe(size, monkeypatch, legacy=False)

    assert optimized["warnings"] == baseline["warnings"]
    assert optimized["positions"] == baseline["positions"]
    assert optimized["coverage"] == baseline["coverage"]
    assert optimized["overview"] == baseline["overview"]
    warning_count = len(baseline["warnings"])
    assert baseline_comparisons == warning_count * (warning_count - 1) // 2
    assert optimized_comparisons == 0
