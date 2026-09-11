"""Optional capabilities stay independent and preserve source limitations."""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mcp_wire import SyntheticWire
from test_mcp_integration import NOW

from app.main import app, get_authenticated_mcp_client
from app.mcp_client import McpFailure
from app.mcp_optional import OptionalMcpService, PeriodRequest, SearchRequest


def test_budget_keeps_unknown_history_and_zero():
    wire = SyntheticWire()
    value = asyncio.run(OptionalMcpService(wire.client()).budget(PeriodRequest(), NOW))
    assert value.family_expense_total == "80.00"
    assert value.history_quality == "UNVERIFIED" and not value.trend_certified
    assert value.expense_split.family_recurring_expense == "0"
    assert value.by_category[0].target.currency is None
    assert value.by_category[0].monthly_average_denominator == 12
    assert value.family_savings_rate_percent is None
    assert [name for name, _ in wire.calls] == ["get_budget_overview"]


def test_contradictory_history_and_notes_are_not_an_accounting_algorithm():
    wire = SyntheticWire()
    wire.values["budget"]["period_note"] = "No transactions; synthetic contradictory prose"
    wire.values["budget"]["view"].update(history_from="2026-09-11", history_to="2026-08-01")
    value = asyncio.run(OptionalMcpService(wire.client()).budget(PeriodRequest(), NOW))
    assert value.history_quality == "INCONSISTENT"
    assert value.family_expense_total == "80.00"
    assert "prose" not in value.model_dump_json()


@pytest.mark.parametrize(
    "arguments",
    [
        {"start_date": "2026-01-01"},
        {"end_date": "2026-01-01"},
        {"start_date": "2026-02-29", "end_date": "2026-03-01"},
        {"start_date": "2026-09-11", "end_date": "2026-09-12"},
        {"start_date": "2026-09-11", "end_date": "2026-09-01"},
    ],
)
def test_invalid_period_never_calls_provider(arguments):
    wire = SyntheticWire()
    with pytest.raises(McpFailure):
        asyncio.run(OptionalMcpService(wire.client()).budget(PeriodRequest(**arguments), NOW))
    assert not wire.calls


def test_leap_day_and_paired_dates_preserved():
    request = PeriodRequest(start_date="2024-02-29", end_date="2024-03-01")
    assert request.arguments(date(2026, 9, 11))["start_date"] == "2024-02-29"


def test_search_requires_explicit_label_preserves_returned_filter():
    with pytest.raises(ValueError):
        SearchRequest(query="  ")
    wire = SyntheticWire()
    request = SearchRequest(query="  Synthetic-Label  ", direction="income")
    value = asyncio.run(OptionalMcpService(wire.client()).search(request, NOW))
    assert wire.calls == [
        (
            "search_spending",
            {"period": "this_month", "query": "  Synthetic-Label  ", "direction": "income"},
        )
    ]
    assert value.matched_query == "synthetic-label"
    assert value.matched_transactions_count == 3
    assert value.result_kind == "LABEL_SUBSTRING_AGGREGATE"


def test_goals_are_complete_plans_without_progress_or_durable_identity():
    wire = SyntheticWire()
    wire.values["goals"]["goals"][0]["funding_account_ids"].append("unresolved")
    value = asyncio.run(OptionalMcpService(wire.client()).goals(NOW))
    assert len(value.goals) == 3
    assert value.funding_reference_coverage == "PARTIAL"
    assert value.goals[1].target_month == "2028-06"
    assert value.goals[0].plan.target_coverage_months == "6"
    assert value.goals[1].plan.contribution_amount is None
    assert value.goals[2].plan.kind == "unavailable"
    assert value.goals[0].contributor_labels == [None]
    assert "progress" not in value.model_dump_json()
    assert [name for name, _ in wire.calls] == ["goals", "accounts"]


def test_optional_routes_are_protected_and_versioned(monkeypatch):
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "synthetic-local")
    client = TestClient(app)
    for path in ("/v3/goals", "/v3/budget", "/v3/spending-search?query=synthetic"):
        assert client.get(path).status_code == 401
    wire = SyntheticWire()
    app.dependency_overrides[get_authenticated_mcp_client] = wire.client
    try:
        assert client.get("/v3/goals").json()["identity_basis"] == "COMPLETE_RESPONSE_ONLY"
        assert client.get("/v3/budget").status_code == 200
        assert client.get("/v3/spending-search?query=synthetic").status_code == 200
    finally:
        app.dependency_overrides.clear()
