"""Reference consumer fed by the production SDK/API and exported writer."""

from copy import deepcopy
from datetime import timedelta

import pytest
from test_mcp_integration import NOW
from test_mcp_workflow import empty_book, failure, prepare, readback, writes

from app.mcp_consumer import observation, select


def book_for_consumer():
    book = empty_book()
    for write in writes(prepare(book=book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    return book


def test_production_consumer_uses_official_authority_and_bank_freshness():
    book = book_for_consumer()
    result = select(readback(book), now=NOW + timedelta(minutes=1))
    assert result["overview"]["gross_assets"]["amount"] == "1000.00"
    assert result["current_complete"]
    assert result["detail"]["portfolio_members"][0]["reported_net_worth"]["amount"] == "-20"
    assert not result["performance_available"]
    assert result["series_break"]
    assert select(readback(book), now=NOW + timedelta(hours=49))["stale"]


@pytest.mark.parametrize(
    "mode", ["terminal", "count", "currency", "run", "history", "diagnostic", "member", "provider"]
)
def test_consumer_rejects_corrupted_membership(mode):
    book = book_for_consumer()
    if mode == "terminal":
        book["sync_runs"].append(deepcopy(book["sync_runs"][0]))
    if mode == "count":
        book["sync_runs"][0]["portfolio_members_expected_count"] = 0
    if mode == "currency":
        book["portfolio_members"][0]["reported_net_worth_currency"] = "USD"
    if mode == "run":
        book["portfolio_members"][0]["run_id"] = "foreign"
    if mode == "history":
        book["positions_history"][0]["history_key"] = "foreign"
    if mode == "diagnostic":
        book["source_warnings"][0]["row_key"] = "foreign"
    if mode == "member":
        book["portfolio_members"].append(deepcopy(book["portfolio_members"][0]))
    if mode == "provider":
        book["sync_runs"][0]["provider"] = "finary_private_api"
    with pytest.raises((ValueError, KeyError, TypeError)):
        select(readback(book), now=NOW + timedelta(minutes=1))


def test_history_fallback_never_borrows_current_account_metadata():
    book = book_for_consumer()
    book["accounts_current"][0]["observation_id"] = "later-observation"
    book["accounts_current"][0]["run_id"] = "later-run"
    result = select(readback(book), now=NOW + timedelta(minutes=1))
    assert result["dated_fallback"] and not result["current_complete"]
    assert result["accounts"] is None
    assert result["positions"]


def test_later_failure_does_not_replace_success():
    book = book_for_consumer()
    named = prepare(book=book, execution="later-run")
    book["sync_runs"] += failure(named, book, execution="later-run")
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]


def test_current_and_history_values_must_agree():
    book = book_for_consumer()
    book["positions_current"][0]["current_value_amount"] = "900"
    with pytest.raises(ValueError):
        observation(readback(book), book["sync_runs"][0], now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("table", ["accounts_current", "positions_current"])
def test_extra_foreign_active_row_forces_dated_history(table):
    book = book_for_consumer()
    row = deepcopy(book[table][0])
    key = "account_key" if table == "accounts_current" else "position_key"
    row[key] += ":extra"
    row.update(run_id="interrupted-run", observation_id="interrupted-observation")
    book[table].append(row)
    result = select(readback(book), now=NOW + timedelta(minutes=1))
    assert not result["current_complete"] and result["dated_fallback"]
    assert result["accounts"] is None


@pytest.mark.parametrize("flag", [0, 1, "true", None])
def test_malformed_physical_activity_cannot_certify_current(flag):
    book = book_for_consumer()
    book["positions_current"][0]["is_active"] = flag
    result = select(readback(book), now=NOW + timedelta(minutes=1))
    assert not result["current_complete"] and result["dated_fallback"]


def test_formatted_membership_counts_keep_integer_semantics():
    book = book_for_consumer()
    from app.mcp_consumer import COUNTS

    for column in COUNTS.values():
        if book["sync_runs"][0][column] != "":
            book["sync_runs"][0][column] = str(book["sync_runs"][0][column]) + ".0"
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]
    book["sync_runs"][0]["observations_expected_count"] = True
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))


def test_current_and_history_compare_by_holding_identity_not_sheet_order():
    from mcp_wire import SyntheticWire
    from test_mcp_integration import snapshot

    wire = SyntheticWire()
    second = deepcopy(wire.values["holdings"]["data"][0])
    second["id"] = "synthetic-second-holding"
    wire.values["holdings"]["data"].append(second)
    book = empty_book()
    for write in writes(prepare(snapshot(wire), book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    book["positions_current"].reverse()
    assert select(readback(book), now=NOW + timedelta(minutes=1))["current_complete"]


@pytest.mark.parametrize("mutation", ["eur_value", "holding_id", "source_asset_id", "account_key"])
def test_historical_fallback_rejects_standalone_position_semantic_corruption(mutation):
    book = book_for_consumer()
    book["accounts_current"][0]["observation_id"] = "later-observation"
    row = book["positions_history"][0]
    if mutation == "eur_value":
        row["current_value_amount_eur"] = "999999"
    elif mutation == "holding_id":
        row["holding_id"] = "different-holding"
    elif mutation == "source_asset_id":
        row["source_asset_id"] = "mcp:holding:securities:different-holding"
    else:
        row["account_key"] = "mcp:account:assets:different-account"
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize(
    "field",
    ["currency", "ownership_basis", "scope", "metric", "source_contract_version", "provider"],
)
def test_series_compatibility_requires_each_known_dimension(field):
    from test_mcp_integration import snapshot

    from app.mcp_consumer import compatible

    original = snapshot()["provenance"]
    assert compatible(original, deepcopy(original))
    for value in [None, "different"]:
        assert not compatible(original, {**original, field: value})


def test_dated_fallback_is_independent_of_later_account_metadata():
    book = book_for_consumer()
    first = deepcopy(book["sync_runs"][0])
    for write in writes(prepare(book=book, execution="next"), execution="next"):
        table = write["node"]["parameters"]["sheetName"]["value"]
        key = __import__("test_mcp_workflow").SCHEMA["sheets"][table]["unique_key"]
        for row in write["rows"]:
            book[table] = [r for r in book[table] if r[key] != row[key]] + [row]
    book["accounts_current"][0]["label"] = "Later account label"
    result = observation(readback(book), first, now=NOW + timedelta(minutes=1))
    assert result["dated_fallback"] and not result["current_complete"]
    assert result["accounts"] is None and result["positions"]
    assert result["context"]["observation_id"] == first["observation_id"]


def test_malformed_unprovenanced_current_row_never_counts_as_complete():
    book = book_for_consumer()
    book["positions_current"].append({"position_key": "unrecognized", "is_active": True})
    result = select(readback(book), now=NOW + timedelta(minutes=1))
    assert not result["current_complete"] and result["dated_fallback"]


def test_terminal_current_and_history_counts_cannot_conflict():
    book = book_for_consumer()
    book["sync_runs"][0]["positions_current_expected_count"] = 0
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))


def test_requested_observation_must_use_the_actual_stored_terminal():
    book = book_for_consumer()
    forged = {**book["sync_runs"][0], "writer_generation": 2}
    with pytest.raises(ValueError):
        observation(readback(book), forged, now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("table", ["positions_history", "source_warnings", "observations"])
def test_unidentified_automated_rows_are_not_silently_ignored(table):
    from test_mcp_workflow import SCHEMA

    book = book_for_consumer()
    row = deepcopy(book[table][0])
    row[SCHEMA["sheets"][table]["unique_key"]] = "unidentified"
    row.pop("observation_id", None)
    book[table].append(row)
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
