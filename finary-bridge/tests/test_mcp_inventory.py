"""All retained rows are typed and terminal-qualified before reads or writes."""

from copy import deepcopy
from datetime import timedelta
from subprocess import CalledProcessError

import pytest
from mcp_artifacts import SCHEMA
from mcp_inputs import manual_rows
from mcp_snapshots import NOW, snapshot
from mcp_wire import SyntheticWire
from mcp_workbooks import (
    book_for_consumer,
    book_with_two_observations,
    partial_book,
    prepare,
    readback,
)

from app.mcp_consumer import observation, select
from app.mcp_workbook import (
    CHILD_KEYS,
    cell,
    google_create,
    initialize,
    native_inventory,
    records,
    validate_row,
)


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


@pytest.mark.parametrize(
    "mutation", ["orphan", "duplicate", "run", "schema", "content", "derived_key"]
)
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
    elif mutation == "derived_key":
        book["source_warnings"][-1]["row_key"] = "synthetic-wrong-key"
    else:
        book["source_warnings"][-1]["code"] = "INVALID"
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
    with pytest.raises(CalledProcessError):
        prepare(book=book, execution="recovery")


# Explicit fields keep the corruption cases independent of the key implementation.
DERIVED_COMPONENTS = {
    "account_ownership": ("owner_key", "mcp:owner:people:changed"),
    "source_connections": ("connection_key", "mcp:connection:changed"),
    "position_rates": ("source_field", "expense_ratio"),
    "official_allocation_categories": ("category", "synthetic-changed"),
    "official_allocation_types": ("holding_type", "synthetic-changed"),
    "portfolio_members": ("member_ordinal", 42),
    "source_warnings": ("entity_key", "synthetic-changed"),
    "unsupported_details": ("holding_type", "synthetic-changed"),
    "positions_history": ("snapshot_date", "2026-09-10"),
    "portfolio_daily": ("snapshot_date", "2026-09-10"),
}


def retained_snapshot(table):
    value = snapshot()
    value["connections"] = [
        {
            "connection_key": "synthetic-connection",
            "institution_key": None,
            "institution_label": None,
            "source_status": None,
            "last_sync_at": None,
            "last_successful_sync_at": None,
            "freshness": "UNKNOWN",
        }
    ]
    value["position_rates"] = [
        {
            "position_key": value["positions"][0]["position_key"],
            "source_field": "annual_yield",
            "value": None,
            "unit": "UNVERIFIED",
            "period": "UNVERIFIED",
        }
    ]
    if table == "unsupported_details":
        value["unsupported_details"] = [
            {
                "account_key": value["accounts"][0]["account_key"],
                "holding_type": "synthetic-future",
                "count": 1,
                "reason": "UNSUPPORTED_TYPE",
            }
        ]
        value["positions"] = []
        value["position_rates"] = []
        value["coverage"].update(
            holdings="PARTIAL", detail_semantics="UNVERIFIED", holding_valuation="UNAVAILABLE"
        )
    return value


@pytest.fixture(scope="module", params=DERIVED_COMPONENTS)
def retained_table(request):
    return request.param


@pytest.fixture(scope="module", params=["failed", "older_success", "fallback"])
def retained_inventory(request, retained_table):
    table = retained_table
    if request.param == "failed":
        book = partial_book(retained_snapshot(table), tables=(table,))
        index = -1
        assert book[table][index]["observation_id"] == book["sync_runs"][-1]["observation_id"]
        assert not any(
            r["observation_id"] == book["sync_runs"][-1]["observation_id"]
            for r in book["observations"]
        )
    else:
        book = book_with_two_observations(retained_snapshot(table))
        book["sync_runs"][-1]["completed_at"] = (NOW + timedelta(seconds=1)).isoformat()
        index = 0
    now = NOW + timedelta(minutes=1)
    assert select(readback(book), now=now)["current_complete"]
    if request.param == "fallback":
        # Force independent historical interpretation without borrowing current accounts.
        book["accounts_current"] = []
        result = select(readback(book), now=now)
        assert result["dated_fallback"] and not result["current_complete"]
    records(readback(book))
    terminal = book["sync_runs"][0 if request.param == "failed" else -1]
    observation(readback(book), terminal, now=now)
    prepare(book=book, execution="recovery")
    return book, table, index, terminal


def test_derived_table_coverage_matches_current_contract():
    assert set(DERIVED_COMPONENTS) == set(CHILD_KEYS) | {"positions_history", "portfolio_daily"}
    for table, fields in CHILD_KEYS.items():
        bindings = SCHEMA["mcp_tables"][table]["column_bindings"]
        assert all(bindings[field] == "/" + field for field in fields)


@pytest.mark.parametrize("mutation", ["key", "component"])
def test_every_retained_derived_key_precedes_consumer_selection(retained_inventory, mutation):
    original, table, index, terminal = retained_inventory
    book = deepcopy(original)
    row = book[table][index]
    if mutation == "key":
        row[SCHEMA["sheets"][table]["unique_key"]] = "synthetic-wrong-key"
    else:
        field, value = DERIVED_COMPONENTS[table]
        assert row[field] != value
        row[field] = value
    # These mutations remain schema-valid and physically unique.
    validate_row(table, row)
    key = SCHEMA["sheets"][table]["unique_key"]
    assert len({r[key] for r in book[table]}) == len(book[table])
    before = deepcopy(book)
    with pytest.raises(ValueError):
        records(readback(book))
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
    with pytest.raises(ValueError):
        observation(readback(book), terminal, now=NOW + timedelta(minutes=1))
    with pytest.raises(CalledProcessError) as error:
        prepare(book=book, execution="recovery")
    assert error.value.stderr == "MCP_VALIDATION_FAILED"
    assert book == before


@pytest.mark.parametrize("ordinal", [1, "1", "001", "1.000"])
def test_retained_encoding_and_decoded_ordinals_match_exported_keys(ordinal):
    value = retained_snapshot("portfolio_members")
    value["members"][0]["member_ordinal"] = 1
    value["allocation_categories"][0]["category"] = "synthetic:/%!'()*é雪"
    value["allocation_types"][0]["category"] = value["allocation_categories"][0]["category"]
    entities = [None, "~null", "~value", "synthetic:%2F%25%C3%A9%E9%9B%AA"]
    value["warnings"] = [{"code": "MISSING_ENRICHMENT", "entity_key": e} for e in entities]
    suffixes = [
        "~null",
        "~value~null",
        "~value~value",
        "~valuesynthetic%3A%252F%2525%25C3%25A9%25E9%259B%25AA",
    ]
    # Keys come from the actual exported writer, including nullable sentinel escaping.
    for book, index in [
        (book_for_consumer(value), 0),
        (
            partial_book(
                value,
                tables=("source_warnings", "portfolio_members", "official_allocation_categories"),
            ),
            -1,
        ),
    ]:
        member = book["portfolio_members"][index]
        member["member_ordinal"] = ordinal
        retained = [
            r for r in book["source_warnings"] if r["observation_id"] == member["observation_id"]
        ]
        assert [
            r["row_key"].split(":source_warnings:MISSING_ENRICHMENT:")[1] for r in retained
        ] == suffixes
        category = book["official_allocation_categories"][index]
        assert category["row_key"].endswith(
            ":official_allocation_categories:synthetic%3A%2F%25%21%27%28%29%2A%C3%A9%E9%9B%AA"
        )
        assert member["row_key"].endswith(":portfolio_members:1")
        decoded = records(readback(book))
        assert decoded["portfolio_members"][index]["member_ordinal"] == 1
        assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
        prepare(book=book, execution="recovery")


def test_retained_integral_numeric_ordinal_uses_canonical_key():
    book = partial_book(tables=("portfolio_members",))
    row = book["portfolio_members"][-1]
    row["member_ordinal"] = float(row["member_ordinal"])
    records(readback(book))
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
    prepare(book=book, execution="recovery")


@pytest.mark.parametrize("ordinal", [True, "1.0000000000000001", "1e0", " 1"])
def test_derived_keys_do_not_coerce_invalid_ordinal_cells(ordinal):
    book = partial_book(tables=("portfolio_members",))
    book["portfolio_members"][-1]["member_ordinal"] = ordinal
    with pytest.raises(ValueError):
        records(readback(book))
    with pytest.raises(CalledProcessError):
        prepare(book=book, execution="recovery")


def test_retained_inactive_rows_and_same_day_history_keep_original_identity():
    wire = SyntheticWire()
    wire.values["accounts"]["data"] = []
    wire.values["holdings"]["data"] = []
    book = book_with_two_observations(next_value=snapshot(wire))
    book["sync_runs"][-1]["completed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    first = book["observations"][0]
    assert len(book["portfolio_daily"]) == 2
    assert len({r["snapshot_date"] for r in book["portfolio_daily"]}) == 1
    for table in ("accounts_current", "positions_current"):
        assert book[table]
        for row in book[table]:
            assert row["is_active"] is False
            assert all(
                row[field] == first[field] for field in ("observation_id", "run_id", "generated_at")
            )
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
    previous = observation(readback(book), book["sync_runs"][0], now=NOW + timedelta(minutes=1))
    assert previous["dated_fallback"] and previous["positions"] and previous["accounts"] is None
    before = deepcopy(book)
    prepare(book=book, execution="recovery")
    assert book == before


def test_derived_key_corruption_cannot_be_hidden_by_an_independent_dated_fallback():
    earlier = snapshot()
    prior_time = NOW - timedelta(days=1)
    earlier["snapshot_date"] = prior_time.date().isoformat()
    earlier["generated_at"] = prior_time.isoformat()
    for field in ("collection_started_at", "collection_ended_at"):
        earlier["provenance"][field] = prior_time.isoformat()
    book = book_with_two_observations(earlier)
    book["sync_runs"][-1]["completed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    now = NOW + timedelta(minutes=1)
    assert select(readback(book), now=now)["current_complete"]
    # A schema-valid semantic mismatch disqualifies the newest candidate only.
    book["positions_history"][-1]["current_value_amount_eur"] = "999"
    fallback = select(readback(book), now=now)
    assert fallback["dated_fallback"] and not fallback["current_complete"]
    assert fallback["context"]["snapshot_date"] == earlier["snapshot_date"]
    assert fallback["context"]["observation_id"] == book["sync_runs"][0]["observation_id"]
    assert fallback["accounts"] is None and fallback["positions"]
    prepare(book=book, execution="recovery")
    book["source_warnings"][-1]["row_key"] = "synthetic-wrong-key"
    with pytest.raises(ValueError):
        select(readback(book), now=now)
    with pytest.raises(CalledProcessError) as error:
        prepare(book=book, execution="recovery")
    assert error.value.stderr == "MCP_VALIDATION_FAILED"
