"""Reference consumer fed by the production SDK/API and exported writer."""

from copy import deepcopy
from datetime import timedelta

import pytest
from test_mcp_integration import NOW
from test_mcp_workflow import empty_book, prepare, writes

from app.mcp_consumer import observation, select


def book_for_consumer():
    book = empty_book()
    for write in writes(prepare(book=book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    return book


def test_production_consumer_uses_official_authority_and_bank_freshness():
    book = book_for_consumer()
    result = select(book, now=NOW + timedelta(minutes=1))
    assert result["overview"]["gross_assets"]["amount"] == "1000.00"
    assert result["current_complete"]
    assert result["detail"]["portfolio_members"][0]["reported_net_worth"]["amount"] == "-20"
    assert not result["performance_available"]
    assert result["series_break"]
    assert select(book, now=NOW + timedelta(hours=49))["stale"]


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
        select(book, now=NOW + timedelta(minutes=1))


def test_history_fallback_never_borrows_current_account_metadata():
    book = book_for_consumer()
    book["accounts_current"][0]["observation_id"] = "later-observation"
    book["accounts_current"][0]["run_id"] = "later-run"
    result = select(book, now=NOW + timedelta(minutes=1))
    assert result["dated_fallback"] and not result["current_complete"]
    assert result["accounts"] is None
    assert result["positions"]


def test_later_failure_does_not_replace_success():
    book = book_for_consumer()
    terminal = deepcopy(book["sync_runs"][0])
    terminal.update(run_id="later-run", observation_id="later-observation", status="FAILED")
    book["sync_runs"].append(terminal)
    assert select(book, now=NOW + timedelta(minutes=1))["current_complete"]


def test_current_and_history_values_must_agree():
    book = book_for_consumer()
    book["positions_current"][0]["mcp_current_value_amount"] = "900"
    with pytest.raises(ValueError):
        observation(book, book["sync_runs"][0], now=NOW + timedelta(minutes=1))
