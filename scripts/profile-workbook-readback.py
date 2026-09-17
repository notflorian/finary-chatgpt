#!/usr/bin/env python3
"""Profile bounded synthetic native workbook readback without portfolio values."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "finary-bridge"))
sys.path.insert(0, str(ROOT / "finary-bridge" / "tests"))

from app import mcp_consumer, mcp_workbook
from mcp_snapshots import NOW
from mcp_workbooks import (
    book_with_retained_observations,
    native_observation,
)


class CountedObservationId(str):
    comparisons = 0

    def __eq__(self, other: object) -> bool:
        type(self).comparisons += 1
        return super().__eq__(other)

    __hash__ = str.__hash__


def instrument_terminal_ids(native: dict[str, object]) -> None:
    sheets = native["sheets"]
    assert isinstance(sheets, list)
    terminal_sheet = next(
        sheet for sheet in sheets if sheet["properties"]["title"] == "sync_runs"
    )
    rows = terminal_sheet["data"][0]["rowData"]
    headers = [cell["userEnteredValue"]["stringValue"] for cell in rows[0]["values"]]
    observation_index = headers.index("observation_id")
    for row in rows[1:]:
        entered = row["values"][observation_index]["userEnteredValue"]
        entered["stringValue"] = CountedObservationId(entered["stringValue"])


def profile(size: int) -> dict[str, object]:
    book = book_with_retained_observations(size)
    native, _ = native_observation(book)
    expected_run = book["sync_runs"][-1]["run_id"]
    instrument_terminal_ids(native)
    counters = {"inventory_passes": 0, "row_validations": 0, "header_builds": 0,
                "column_validator_builds": 0}

    inventory_boundary = (
        "_validated_inventory" if hasattr(mcp_workbook, "_validated_inventory") else "records"
    )
    original_inventory_boundary = getattr(mcp_workbook, inventory_boundary)
    original_validate_row = mcp_workbook.validate_row
    original_headers = mcp_workbook.headers
    original_validator = mcp_workbook.Draft202012Validator

    def counted_inventory_boundary(inventory):
        counters["inventory_passes"] += 1
        return original_inventory_boundary(inventory)

    def counted_validate_row(table, row):
        counters["row_validations"] += 1
        return original_validate_row(table, row)

    def counted_headers():
        counters["header_builds"] += 1
        return original_headers()

    def counted_validator(*args, **kwargs):
        counters["column_validator_builds"] += 1
        return original_validator(*args, **kwargs)

    setattr(mcp_workbook, inventory_boundary, counted_inventory_boundary)
    if inventory_boundary == "records":
        mcp_consumer.records = counted_inventory_boundary
    mcp_workbook.validate_row = counted_validate_row
    mcp_consumer.validate_row = counted_validate_row
    mcp_workbook.headers = counted_headers
    mcp_workbook.Draft202012Validator = counted_validator
    CountedObservationId.comparisons = 0
    try:
        started = perf_counter()
        if hasattr(mcp_consumer, "select_native"):
            result = mcp_consumer.select_native(native, now=NOW + timedelta(minutes=1))
        else:
            inventory = mcp_workbook.native_inventory(native)
            result = mcp_consumer.select(inventory, now=NOW + timedelta(minutes=1))
        elapsed = perf_counter() - started
    finally:
        setattr(mcp_workbook, inventory_boundary, original_inventory_boundary)
        if inventory_boundary == "records":
            mcp_consumer.records = original_inventory_boundary
        mcp_workbook.validate_row = original_validate_row
        mcp_consumer.validate_row = original_validate_row
        mcp_workbook.headers = original_headers
        mcp_workbook.Draft202012Validator = original_validator
    assert result["context"]["run_id"] == expected_run
    return {
        "observations": size,
        "rows_including_metadata": sum(len(rows) for rows in book.values()),
        **counters,
        "terminal_id_comparisons": CountedObservationId.comparisons,
        "elapsed_seconds": round(elapsed, 6),
        "current_complete": result["current_complete"],
    }


def main() -> None:
    for size in (1, 10, 100):
        print(json.dumps(profile(size), sort_keys=True))


if __name__ == "__main__":
    main()
