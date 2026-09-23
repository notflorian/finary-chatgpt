"""Read-local validation reuse preserves complete workbook safety boundaries."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta

import pytest
from mcp_snapshots import NOW
from mcp_workbooks import (
    book_with_retained_observations,
    failure,
    native_observation,
    partial_book,
    prepare,
    readback,
)

from app import mcp_consumer, mcp_workbook
from app.mcp_consumer import observation, select, select_native
from app.mcp_workbook import native_inventory, records


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


@pytest.mark.parametrize("fallback", [False, True])
def test_consumer_schema_work_is_limited_to_selected_candidates(monkeypatch, fallback):
    book = book_with_retained_observations(10)
    native, _ = native_observation(book)
    calls = Counter()
    original_validate = mcp_consumer.validate
    original_normalized = mcp_consumer.normalized

    def counted_validate(name, value):
        if name == "uuid":
            calls["uuid"] += 1
        return original_validate(name, value)

    def counted_normalized(table, row):
        if table == "observations":
            calls["observations"] += 1
        return original_normalized(table, row)

    monkeypatch.setattr(mcp_consumer, "validate", counted_validate)
    monkeypatch.setattr(mcp_consumer, "normalized", counted_normalized)
    result = select_native(native, now=NOW if fallback else NOW + timedelta(minutes=1))

    assert result["context"]["run_id"] == book["sync_runs"][0 if fallback else -1]["run_id"]
    assert result["current_complete"] is not fallback
    assert result["dated_fallback"] is fallback
    assert calls["uuid"] == 0
    assert 1 <= calls["observations"] <= (10 if fallback else 2)


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


@pytest.mark.parametrize("entrypoint", ["native", "inventory", "observation"])
def test_unselected_failed_rows_are_validated_before_selection(entrypoint):
    book = partial_book()
    book["source_warnings"][-1]["code"] = "INVALID"
    with pytest.raises(ValueError):
        if entrypoint == "native":
            select_native(native_observation(book)[0], now=NOW + timedelta(minutes=1))
        elif entrypoint == "observation":
            observation(readback(book), book["sync_runs"][0], now=NOW + timedelta(minutes=1))
        else:
            select(readback(book), now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("entrypoint", ["native", "inventory", "observation"])
@pytest.mark.parametrize(
    "field,value",
    [("observation_id", "invalid"), ("run_id", ""), ("coverage_accounts", "INVALID")],
)
def test_unselected_older_rows_fail_inventory_gate(entrypoint, field, value):
    book = book_with_retained_observations(2)
    book["observations"][0][field] = value
    with pytest.raises(ValueError):
        if entrypoint == "native":
            select_native(native_observation(book)[0], now=NOW + timedelta(minutes=1))
        elif entrypoint == "observation":
            observation(readback(book), book["sync_runs"][-1], now=NOW + timedelta(minutes=1))
        else:
            select(readback(book), now=NOW + timedelta(minutes=1))


def test_public_inputs_are_revalidated_after_mutation():
    book = book_with_retained_observations(2)
    inventory = readback(book)
    native, _ = native_observation(book)
    now = NOW + timedelta(minutes=1)
    assert select(inventory, now=now)["current_complete"]
    assert select_native(native, now=now)["current_complete"]
    assert observation(inventory, book["sync_runs"][-1], now=now)["current_complete"]

    inventory["sheets"]["positions_history"]["rows"][0]["current_value_amount"] = "bad"
    native_cell(native, "positions_history", 0, "current_value_amount")["userEnteredValue"] = {
        "stringValue": "bad"
    }
    with pytest.raises(ValueError):
        select(inventory, now=now)
    with pytest.raises(ValueError):
        select_native(native, now=now)
    with pytest.raises(ValueError):
        observation(inventory, book["sync_runs"][-1], now=now)


@pytest.fixture(scope="module")
def book_with_early_failures():
    book = book_with_retained_observations(2)
    for index in range(2):
        execution = f"early-failure-{index}"
        named = prepare(book=book, execution=execution)
        # Failure before preparation has no observation to bind to the terminal.
        named.pop("Prepare MCP Rows")
        terminal = failure(named, book, execution=execution)
        assert len(terminal) == 1 and terminal[0]["status"] == "FAILED"
        assert terminal[0]["observation_id"] in (None, "")
        book["sync_runs"] += terminal
    return book


@pytest.mark.parametrize("fallback", [False, True])
def test_early_failures_without_observations_preserve_selection(book_with_early_failures, fallback):
    book = deepcopy(book_with_early_failures)
    if fallback:
        book["accounts_current"] = []
    now = NOW + timedelta(minutes=1)
    successful = {**book, "sync_runs": book["sync_runs"][:-2]}
    expected = select(readback(successful), now=now)
    assert expected["dated_fallback"] is fallback
    inventory = readback(book)
    native, _ = native_observation(book)
    decoded = records(inventory)
    assert all(row["observation_id"] is None for row in decoded["sync_runs"][-2:])
    assert select(inventory, now=now) == expected
    assert select(native_inventory(native), now=now) == expected
    assert select_native(native, now=now) == expected


@pytest.mark.parametrize("mutation", ["duplicate_run", "duplicate_observation", "schema", "orphan"])
def test_early_failures_do_not_bypass_terminal_integrity(book_with_early_failures, mutation):
    book = deepcopy(book_with_early_failures)
    if mutation == "duplicate_run":
        book["sync_runs"][-1]["run_id"] = book["sync_runs"][-2]["run_id"]
    elif mutation == "duplicate_observation":
        book["sync_runs"][-1]["observation_id"] = book["sync_runs"][0]["observation_id"]
    elif mutation == "schema":
        book["sync_runs"][-1]["workbook_schema"] = "invalid"
    else:
        book["sync_runs"][0] = {
            **book["sync_runs"][-1], "run_id": book["sync_runs"][0]["run_id"]
        }
        mcp_workbook.validate_row("sync_runs", book["sync_runs"][0])
    inventory = readback(book)
    native, _ = native_observation(book)
    with pytest.raises(ValueError):
        records(inventory)
    with pytest.raises(ValueError):
        native_inventory(native)
    with pytest.raises(ValueError):
        select(inventory, now=NOW + timedelta(minutes=1))
    with pytest.raises(ValueError):
        select_native(native, now=NOW + timedelta(minutes=1))
