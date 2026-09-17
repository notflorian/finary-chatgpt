"""Read-local validation reuse preserves complete workbook safety boundaries."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta

import pytest
from mcp_snapshots import NOW
from mcp_workbooks import (
    book_with_retained_observations,
    native_observation,
    partial_book,
    readback,
)

from app import mcp_workbook
from app.mcp_consumer import select, select_native
from app.mcp_workbook import records


class CountedObservationId(str):
    comparisons = 0

    def __eq__(self, other: object) -> bool:
        type(self).comparisons += 1
        return super().__eq__(other)

    __hash__ = str.__hash__


def native_cell(native, table, row_index, column):
    sheet = next(item for item in native["sheets"] if item["properties"]["title"] == table)
    rows = sheet["data"][0]["rowData"]
    headers = [cell["userEnteredValue"]["stringValue"] for cell in rows[0]["values"]]
    return rows[row_index + 1]["values"][headers.index(column)]


def counted_terminal_comparisons(size):
    inventory = readback(book_with_retained_observations(size))
    for row in inventory["sheets"]["sync_runs"]["rows"]:
        row["observation_id"] = CountedObservationId(row["observation_id"])
    CountedObservationId.comparisons = 0
    records(inventory)
    return CountedObservationId.comparisons


def test_native_selection_validates_every_inventory_row_once(monkeypatch):
    book = book_with_retained_observations(10)
    native, _ = native_observation(book)
    expected = Counter(
        {
            table: len(rows)
            for table, rows in book.items()
            if table != "README" and rows
        }
    )
    actual = Counter()
    original = mcp_workbook.validate_row

    def counted_validate_row(table, row):
        actual[table] += 1
        return original(table, row)

    monkeypatch.setattr(mcp_workbook, "validate_row", counted_validate_row)
    result = select_native(native, now=NOW + timedelta(minutes=1))
    assert result["current_complete"]
    assert actual == expected


def test_native_selection_reuses_fixed_headers_and_column_validators(monkeypatch):
    native, _ = native_observation(book_with_retained_observations(10))
    copied_headers = mcp_workbook.headers()
    copied_headers["positions_history"].clear()
    assert mcp_workbook.headers()["positions_history"]

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("fixed workbook metadata was rebuilt during readback")

    monkeypatch.setattr(mcp_workbook, "headers", unexpected_rebuild)
    monkeypatch.setattr(mcp_workbook, "Draft202012Validator", unexpected_rebuild)
    assert select_native(native, now=NOW + timedelta(minutes=1))["current_complete"]


def test_terminal_membership_work_scales_with_rows_not_rows_times_terminals():
    small = counted_terminal_comparisons(10)
    large = counted_terminal_comparisons(100)
    assert small > 0
    assert large < small * 12
    assert large < 50 * 100


@pytest.mark.parametrize("entrypoint", ["native", "inventory"])
@pytest.mark.parametrize("mutation", ["duplicate_terminal", "mismatched_run"])
def test_terminal_ambiguity_and_run_mismatch_fail_closed(entrypoint, mutation):
    book = book_with_retained_observations(2)
    if mutation == "duplicate_terminal":
        duplicate = deepcopy(book["sync_runs"][-1])
        duplicate["run_id"] = "n8n-run:duplicate:00000000-0000-4000-8000-000000000099"
        book["sync_runs"].append(duplicate)
    else:
        book["positions_history"][0]["run_id"] = "n8n-run:mismatched"
    with pytest.raises(ValueError):
        if entrypoint == "native":
            select_native(native_observation(book)[0], now=NOW + timedelta(minutes=1))
        else:
            select(readback(book), now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("entrypoint", ["native", "inventory"])
def test_unselected_failed_rows_are_validated_before_selection(entrypoint):
    book = partial_book()
    book["source_warnings"][-1]["code"] = "INVALID"
    with pytest.raises(ValueError):
        if entrypoint == "native":
            select_native(native_observation(book)[0], now=NOW + timedelta(minutes=1))
        else:
            select(readback(book), now=NOW + timedelta(minutes=1))


def test_native_and_inventory_inputs_are_revalidated_after_mutation():
    book = book_with_retained_observations(2)
    inventory = readback(book)
    native, _ = native_observation(book)
    now = NOW + timedelta(minutes=1)
    assert select(inventory, now=now)["current_complete"]
    assert select_native(native, now=now)["current_complete"]

    inventory["sheets"]["positions_history"]["rows"][0]["current_value_amount"] = "bad"
    native_cell(native, "positions_history", 0, "current_value_amount")["userEnteredValue"] = {
        "stringValue": "bad"
    }
    with pytest.raises(ValueError):
        select(inventory, now=now)
    with pytest.raises(ValueError):
        select_native(native, now=now)
