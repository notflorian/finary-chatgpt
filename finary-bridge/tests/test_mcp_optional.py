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


@pytest.mark.parametrize("period", ["this_month", "last_month", "last_3_months", "year_to_date"])
def test_optional_period_names_do_not_replace_returned_dates(period):
    wire = SyntheticWire()
    value = asyncio.run(OptionalMcpService(wire.client()).budget(PeriodRequest(period=period), NOW))
    assert wire.calls[0][1]["period"] == period
    assert value.view.start_date == wire.values["budget"]["view"]["from"]
    assert value.view.end_date == wire.values["budget"]["view"]["to"]


def test_legitimate_zero_target_floor_and_unpriced_history():
    wire = SyntheticWire()
    raw = wire.values["budget"]
    raw.update(family_expense_total="0", unpriced_transactions_count=1)
    raw["by_category"][0]["target"]["should_reach"] = True
    value = asyncio.run(OptionalMcpService(wire.client()).budget(PeriodRequest(), NOW))
    assert value.family_expense_total == "0" and value.transactions_count > 0
    assert value.unpriced_transactions_count == 1
    assert value.by_category[0].target.should_reach is True
    assert value.by_category[0].target.currency is None
    assert not value.trend_certified


def test_goal_array_changes_create_no_persistent_identity():
    wire = SyntheticWire()
    rows = wire.values["goals"]["goals"]
    rows[1].update(name=rows[0]["name"], goal_type="future-kind", currency="USD")
    rows[1]["plan"]["contribution_frequency"] = "future-cadence"
    first = asyncio.run(OptionalMcpService(wire.client()).goals(NOW))
    rows.reverse()
    second = asyncio.run(OptionalMcpService(wire.client()).goals(NOW))
    assert first.observation_id != second.observation_id
    assert [g.model_dump() for g in first.goals] == [g.model_dump() for g in reversed(second.goals)]
    wire.values["goals"]["goals"] = []
    assert asyncio.run(OptionalMcpService(wire.client()).goals(NOW)).goals == []


def test_nine_action_question_matrix_is_complete_and_schedule_is_bounded():
    import json
    from pathlib import Path

    from app.mcp_validation import CONTRACT

    root = Path(__file__).parents[2]
    guide = (root / "docs/mcp-consumer.md").read_text()
    rows = [line for line in guide.splitlines() if line.startswith("| `")]
    assert {row.split("`")[1] for row in rows} == set(CONTRACT["capabilities"])
    assert len(rows) == 9
    workflow = json.loads((root / "n8n/workflows/finary-mcp-sync.json").read_text())
    routes = [
        n["parameters"]["url"]
        for n in workflow["nodes"]
        if n["type"] == "n8n-nodes-base.httpRequest"
    ]
    assert len(routes) == 2 and sum("/v3/snapshot" in route for route in routes) == 1


def test_access_logs_do_not_include_user_search_labels():
    import logging

    from app.mcp_logging import McpAccessFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "synthetic",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("local", "GET", "/v3/spending-search?query=synthetic-secret-label", "1.1", 200),
        None,
    )
    assert McpAccessFilter().filter(record)
    assert "synthetic-secret-label" not in record.getMessage()
    assert "/v3/spending-search" in record.getMessage()
