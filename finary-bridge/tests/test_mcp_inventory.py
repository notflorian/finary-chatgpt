"""All retained rows are typed and terminal-qualified before reads or writes."""

from copy import deepcopy
from datetime import timedelta
from subprocess import CalledProcessError

import pytest
from mcp_inputs import manual_rows
from mcp_snapshots import NOW
from mcp_workbooks import book_for_consumer, failure, prepare, readback, writes

from app.mcp_consumer import select
from app.mcp_workbook import cell, google_create, initialize, native_inventory, records


@pytest.mark.parametrize("table", manual_rows())
@pytest.mark.parametrize("mutation", ["duplicate", "key", "typed", "formula"])
def test_manual_inputs_are_validated_read_only_at_both_boundaries(table, mutation):
    book = book_for_consumer()
    row = deepcopy(manual_rows()[table])
    book[table] = [row]
    if mutation == "duplicate":
        book[table].append(deepcopy(row))
    elif mutation == "key":
        row[next(iter(row))] = ""
    elif mutation == "formula":
        row[next(iter(row))] = "=1+2"
    else:
        field = {
            "allocation_targets": "target_pct",
            "asset_overrides": "enabled",
            "cashflows": "amount_eur",
        }[table]
        row[field] = "invalid"
    original = deepcopy(book)
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
    with pytest.raises(CalledProcessError):
        prepare(book=book, execution="next")
    assert book == original


@pytest.mark.parametrize("table", manual_rows())
def test_native_formulas_are_allowed_only_in_manual_notes(table):
    native = google_create(initialize("synthetic-writer", 1))
    sheet = next(s for s in native["sheets"] if s["properties"]["title"] == table)
    values = [cell(value) for value in manual_rows()[table].values()]
    names = list(manual_rows()[table])
    values[names.index("notes")] = {"userEnteredValue": {"formulaValue": "=1+2"}}
    sheet["data"][0]["rowData"].append({"values": values})
    inventory = native_inventory(native)
    assert records(inventory)[table][0]["notes"] == "=1+2"
    for column in names:
        if column == "notes":
            continue
        invalid = deepcopy(native)
        target = next(s for s in invalid["sheets"] if s["properties"]["title"] == table)
        target["data"][0]["rowData"][1]["values"][names.index(column)] = {
            "userEnteredValue": {"formulaValue": "=1+2"}
        }
        with pytest.raises(ValueError):
            native_inventory(invalid)


def test_manual_fraction_order_and_preservation():
    book = book_for_consumer()
    for table, row in manual_rows().items():
        book[table] = [row]
    original = deepcopy(book)
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
    prepare(book=book, execution="next")
    assert book == original
    book["allocation_targets"][0]["min_pct"] = 0.9
    with pytest.raises(ValueError):
        records(readback(book))
    with pytest.raises(CalledProcessError):
        prepare(book=book, execution="next")


def partial_book():
    book = book_for_consumer()
    named = prepare(book=book, execution="partial")
    rows = next(
        w["rows"]
        for w in writes(named, execution="partial")
        if w["node"]["parameters"]["sheetName"]["value"] == "source_warnings"
    )
    book["source_warnings"] += rows
    book["sync_runs"] += failure(named, book, execution="partial")
    return book


@pytest.mark.parametrize("mutation", ["orphan", "duplicate", "run", "schema", "content"])
def test_unselected_failed_rows_must_have_one_valid_terminal_and_schema(mutation):
    book = partial_book()
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
    prepare(book=book, execution="recovery")
    if mutation == "orphan":
        book["sync_runs"].pop()
    elif mutation == "duplicate":
        book["sync_runs"].append({**book["sync_runs"][-1], "run_id": "duplicate-terminal"})
    elif mutation == "run":
        book["source_warnings"][-1]["run_id"] = "foreign"
    elif mutation == "schema":
        book["sync_runs"][-1]["workbook_schema"] = "3.0"
    else:
        book["source_warnings"][-1]["code"] = "INVALID"
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
    with pytest.raises(CalledProcessError):
        prepare(book=book, execution="recovery")
