"""Credential-free consumer regressions using exported n8n preparation logic."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

import pytest
from test_n8n_workflow_v2 import (
    _apply_prepared_writes,
    _empty_workbook,
    _known_eur_snapshot,
    _latest_complete_position_state,
    _prepare_for_run,
    _run_validation,
    _upsert,
)
from test_n8n_workflow_v2 import (
    schema as schema,
)
from test_n8n_workflow_v2 import (
    workflow as workflow,
)
from workbook_consumer import (
    active_members,
    latest_success,
    select_assets,
    select_liabilities,
)

NOW = datetime.fromisoformat("2026-08-20T12:00:00+02:00")
A, B, C = "n8n-execution:900", "n8n-execution:10", "n8n-execution:2"
Workbook = dict[str, list[dict[str, Any]]]


def _prepare(workflow, schema, workbook, run_id, timestamp, **changes):
    coverage = changes.pop("coverage", "COMPLETE")
    snapshot = _known_eur_snapshot(timestamp, **changes)
    if coverage != "COMPLETE":
        snapshot.update(liabilities=[], liabilities_eur=None, net_worth_eur=None)
        snapshot["coverage"]["liabilities"] = coverage
    return _prepare_snapshot(workflow, schema, workbook, run_id, snapshot)


def _prepare_snapshot(workflow, schema, workbook, run_id, snapshot):
    assert _run_validation(workflow, schema, snapshot)["can_write"] is True
    return _prepare_for_run(workflow, schema, snapshot, workbook, run_id)


@pytest.fixture
def workbook(workflow, schema) -> Workbook:
    book = _empty_workbook()
    for sheet in ("allocation_targets", "asset_overrides", "cashflows"):
        book[sheet] = [{"synthetic_manual_note": sheet}]
    prepared = _prepare(workflow, schema, book, A, "2026-08-20T07:30:00+02:00")
    _apply_prepared_writes(schema, book, prepared)
    return book


def test_successful_current_state_has_explicit_membership_and_sources(workbook):
    state = select_assets(workbook, now=NOW)
    assert state.latest_success_run_id == state.run_id == state.aggregate_run_id == A
    assert state.source == "current" and state.current_complete
    assert not state.dated_fallback and not state.stale
    assert len(state.accounts) == 1 and len(state.positions) == 2
    assert {row["position_key"] for row in state.positions} == {
        row["position_key"] for row in state.history
    }
    assert state.daily["gross_assets_eur"] == 150
    liability = select_liabilities(workbook)
    assert liability.complete and liability.reference_run_id == A
    assert liability.liabilities_eur == 10


@pytest.mark.parametrize(
    ("stop_after", "limit", "memberships"),
    [
        ("accounts_current", None, {A}),
        ("positions_current", 1, {A, B}),
        ("positions_current", None, {B}),
        ("liabilities_current", None, {B}),
    ],
)
def test_interrupted_b_cannot_enrich_validated_a(
    workflow, schema, workbook, stop_after, limit, memberships
):
    prepared = _prepare(workflow, schema, workbook, B, "2026-08-20T08:30:00+02:00", first_value=110)
    _apply_prepared_writes(schema, workbook, prepared, stop_after=stop_after, current_limit=limit)
    # Reproduce the old interpretation independently: its history passes, but
    # filtering is_active alone accepts B or a mixed A/B current table.
    legacy = _latest_complete_position_state(workbook)
    assert legacy[0]["run_id"] == A
    assert sum(row["market_value_eur"] for row in legacy[1]) == 150
    physical_active = [row for row in workbook["positions_current"] if row["is_active"]]
    assert {row["last_seen_run_id"] for row in physical_active} == memberships
    if stop_after != "accounts_current":
        assert sum(row["market_value_eur"] for row in physical_active) == 160
    assert [row["run_id"] for row in workbook["sync_runs"]] == [A]

    state = select_assets(workbook, now=NOW)
    assert state.latest_success_run_id == state.run_id == A
    assert state.source == "history" and not state.current_complete
    assert state.accounts is None
    assert state.positions == legacy[1]
    assert state.daily["gross_assets_eur"] == 150
    assert state.snapshot_date == "2026-08-20" and state.dated_fallback
    assert set(state.positions[0]) == {
        column["name"] for column in schema["sheets"]["positions_history"]["columns"]
    }
    assert not {"account_name", "account_type", "institution", "region", "weight_portfolio"} & (
        state.positions[0].keys()
    )


@pytest.mark.parametrize(
    "sheet,key,count_field",
    [
        ("accounts_current", "account_key", "accounts_count"),
        ("positions_current", "position_key", "positions_count"),
    ],
)
@pytest.mark.parametrize(
    "anomaly",
    [
        "extra",
        "missing",
        "duplicate",
        "foreign",
        "missing_run",
        "blank_key",
        "invalid_key",
        "bad_flag",
        "inactive_bad_flag",
        "inactive_duplicate",
    ],
)
def test_entire_current_tables_are_checked_before_filtering(
    workbook, sheet, key, count_field, anomaly
):
    rows = workbook[sheet]
    if anomaly in {"extra", "duplicate", "inactive_duplicate"}:
        added = deepcopy(rows[0])
        if anomaly == "extra":
            added[key] += "-extra"
        if anomaly == "inactive_duplicate":
            added["is_active"] = False
            added["last_seen_run_id"] = "retained-old-run"
        rows.append(added)
    elif anomaly == "missing":
        rows.pop()
    elif anomaly == "foreign":
        rows[0]["last_seen_run_id"] = B
    elif anomaly == "missing_run":
        del rows[0]["last_seen_run_id"]
    elif anomaly == "blank_key":
        rows[0][key] = ""
    elif anomaly == "invalid_key":
        rows[0][key] = "not-a-canonical-key"
    elif anomaly == "bad_flag":
        rows[0]["is_active"] = "yes"
    else:
        rows.append({key: rows[0][key] + "-old", "is_active": "", "last_seen_run_id": A})
    assert active_members(rows, key, workbook["sync_runs"][0], count_field) is None
    state = select_assets(workbook, now=NOW)
    assert not state.current_complete and state.source == "history" and state.run_id == A


@pytest.mark.parametrize("field", ["accounts_count", "positions_count"])
@pytest.mark.parametrize("invalid", [None, "", " ", True, False, -1, 1.5, "NaN", "Infinity", "2,0"])
def test_invalid_counts_never_become_zero_or_complete(workbook, field, invalid):
    workbook["sync_runs"][0][field] = invalid
    state = select_assets(workbook, now=NOW)
    assert not state.current_complete
    assert state.source == ("unavailable" if field == "positions_count" else "history")
    # Validated gross assets do not depend on reconstructing position detail.
    assert state.aggregate_run_id == A
    assert state.aggregate_daily["gross_assets_eur"] == 150


@pytest.mark.parametrize("counts", [(1, 2), (1.0, 2.0), ("1", "2"), ("1.0", "2e0"), (" 1 ", "2")])
@pytest.mark.parametrize("flags", [True, "TRUE"])
def test_supported_sheets_representations(workbook, counts, flags):
    run = workbook["sync_runs"][0]
    run["accounts_count"], run["positions_count"] = counts
    for sheet in ("accounts_current", "positions_current"):
        for row in workbook[sheet]:
            row["is_active"] = flags
    assert select_assets(workbook, now=NOW).current_complete


@pytest.mark.parametrize("flag", [None, "", 0, 1, "false", "true", " TRUE ", "unknown"])
def test_activity_flags_are_not_coerced(workbook, flag):
    workbook["positions_current"][0]["is_active"] = flag
    assert select_assets(workbook, now=NOW).source == "history"


def test_positions_reference_validated_accounts_and_history_keys(workbook):
    workbook["positions_current"][0]["account_key"] = "finary:account:missing"
    assert select_assets(workbook, now=NOW).source == "history"
    workbook["positions_current"][0]["account_key"] = workbook["accounts_current"][0]["account_key"]
    # Same count and same run are insufficient for a current/history join.
    workbook["positions_current"][0]["position_key"] += "-changed"
    state = select_assets(workbook, now=NOW)
    assert state.source == "history" and state.run_id == A


@pytest.mark.parametrize("successful", [True, False])
def test_inactivation_keeps_last_observation_but_requires_complete_membership(
    workflow, schema, workbook, successful
):
    prepared = _prepare(
        workflow, schema, workbook, B, "2026-08-20T08:30:00+02:00", include_first=False
    )
    inactive = next(row for row in prepared["position_rows"] if not row["is_active"])
    assert inactive["last_seen_run_id"] == A
    assert inactive["last_seen_at"] == "2026-08-20T07:30:00+02:00"
    if successful:
        _apply_prepared_writes(schema, workbook, prepared, completed_at="2026-08-20T06:31:00Z")
        state = select_assets(workbook, now=NOW)
        assert state.current_complete and state.run_id == B
        assert len(state.positions) == 1 and len(workbook["positions_history"]) == 2
        assert {row["run_id"] for row in workbook["positions_history"]} == {A, B}
    else:
        # Only the inactivation lands. Every remaining active row still says A;
        # checking IDs alone would miss the now-incomplete prior portfolio.
        workbook["positions_current"] = _upsert(
            workbook["positions_current"], [inactive], "position_key"
        )
        assert {row["last_seen_run_id"] for row in workbook["positions_current"]} == {A}
        state = select_assets(workbook, now=NOW)
        assert state.source == "history" and state.run_id == A
        assert len(state.positions) == 2 and not state.current_complete


def test_account_disappearance_and_partial_account_write(workflow, schema, workbook):
    snapshot = _known_eur_snapshot("2026-08-20T08:30:00+02:00")
    second = {
        **snapshot["accounts"][0],
        "account_key": "finary:account:second",
        "source_account_id": "second",
        "market_value_eur": 0,
    }
    snapshot["accounts"].append(second)
    prepared = _prepare_snapshot(workflow, schema, workbook, B, snapshot)
    _apply_prepared_writes(schema, workbook, prepared, completed_at="2026-08-20T06:31:00Z")
    assert select_assets(workbook, now=NOW).current_complete
    gone = _prepare(workflow, schema, workbook, C, "2026-08-20T09:30:00+02:00")
    _apply_prepared_writes(schema, workbook, gone, stop_after="accounts_current", current_limit=1)
    assert select_assets(workbook, now=NOW).source == "history"
    _apply_prepared_writes(schema, workbook, gone, completed_at="2026-08-20T07:31:00Z")
    state = select_assets(workbook, now=NOW)
    assert state.current_complete and len(state.accounts) == 1
    retained = workbook["accounts_current"][1]
    assert retained["is_active"] is False and retained["last_seen_run_id"] == B


@pytest.mark.parametrize(
    "stop_after,history_limit", [("positions_history", 1), ("portfolio_daily", None)]
)
def test_same_day_overwrite_cannot_recover_from_terminal_success_alone(
    workflow, schema, workbook, stop_after, history_limit
):
    prepared = _prepare(workflow, schema, workbook, B, "2026-08-20T08:30:00+02:00", first_value=110)
    _apply_prepared_writes(
        schema, workbook, prepared, stop_after=stop_after, history_limit=history_limit
    )
    state = select_assets(workbook, now=NOW)
    assert state.latest_success_run_id == A
    assert not state.current_complete and state.source == "unavailable"
    assert state.run_id is None and state.positions is None and state.accounts is None
    if stop_after == "positions_history":
        assert state.aggregate_run_id == A and state.aggregate_daily["gross_assets_eur"] == 150
    else:
        assert state.aggregate_daily is None


def test_older_date_fallback_is_explicit_and_independent(workflow, schema, workbook):
    older = _prepare(workflow, schema, workbook, "legacy-old", "2026-08-17T07:30:00+02:00")
    # Historical insertion only: do not change today's valid current state.
    workbook["positions_history"] += older["history_rows"]
    workbook["portfolio_daily"] += older["daily_rows"]
    older["sync_run_rows"][0]["completed_at"] = "2026-08-17T05:31:00Z"
    workbook["sync_runs"] += older["sync_run_rows"]
    interrupted = _prepare(
        workflow, schema, workbook, B, "2026-08-20T08:30:00+02:00", first_value=110
    )
    _apply_prepared_writes(schema, workbook, interrupted, history_limit=1)
    state = select_assets(workbook, now=NOW)
    assert state.latest_success_run_id == A and state.run_id == "legacy-old"
    assert state.source == "history" and state.dated_fallback and state.stale
    assert state.snapshot_date == "2026-08-17"
    assert state.completed_at == "2026-08-17T05:31:00Z"
    assert state.accounts is None and state.positions == older["history_rows"]
    assert state.aggregate_run_id == A  # Separately usable newer aggregates.
    assert state.aggregate_daily["snapshot_date"] == "2026-08-20"


@pytest.mark.parametrize(
    "anomaly",
    ["duplicate", "foreign_duplicate", "missing_key", "missing_run", "date", "daily_duplicate"],
)
def test_history_anomalies_are_not_deduplicated_or_reconstructed(workbook, anomaly):
    workbook["accounts_current"][0]["last_seen_run_id"] = B
    row = workbook["positions_history"][0]
    if anomaly in {"duplicate", "foreign_duplicate"}:
        duplicate = deepcopy(row)
        if anomaly == "foreign_duplicate":
            duplicate["run_id"] = B
        workbook["positions_history"].append(duplicate)
    elif anomaly == "missing_key":
        row["position_key"] = ""
    elif anomaly == "missing_run":
        row["run_id"] = ""
    elif anomaly == "date":
        row["generated_at"] = "2026-08-19T07:30:00+02:00"
    else:
        workbook["portfolio_daily"].append(deepcopy(workbook["portfolio_daily"][0]))
    assert select_assets(workbook, now=NOW).source == "unavailable"


def test_sequential_recovery_preserves_history_and_manual_sheets(workflow, schema, workbook):
    manual = {
        name: deepcopy(workbook[name])
        for name in ("cashflows", "asset_overrides", "allocation_targets")
    }
    original_history = deepcopy(workbook["positions_history"])
    interrupted = _prepare(
        workflow, schema, workbook, B, "2026-08-21T07:30:00+02:00", first_value=110
    )
    _apply_prepared_writes(
        schema, workbook, interrupted, stop_after="positions_current", current_limit=1
    )
    assert select_assets(workbook, now=NOW).source == "history"
    recovery = _prepare(workflow, schema, workbook, C, "2026-08-21T08:30:00+02:00", first_value=110)
    _apply_prepared_writes(schema, workbook, recovery, completed_at="2026-08-21T06:31:00Z")
    state = select_assets(workbook, now=datetime.fromisoformat("2026-08-21T10:00:00+02:00"))
    assert state.current_complete and state.run_id == state.latest_success_run_id == C
    assert (
        state.source == "current" and sum(row["market_value_eur"] for row in state.positions) == 160
    )
    assert all(row in workbook["positions_history"] for row in original_history)
    for sheet, rows in workbook.items():
        if sheet not in manual:
            key = schema["sheets"][sheet]["unique_key"]
            assert len(rows) == len({row[key] for row in rows})
    assert {name: workbook[name] for name in manual} == manual


def test_upsert_harness_preserves_duplicate_physical_rows(workbook):
    rows = workbook["positions_current"]
    rows.append(deepcopy(rows[0]))
    incoming = {**rows[0], "last_seen_run_id": B}
    written = _upsert(rows, [incoming], "position_key")
    assert len(written) == 3
    assert [row["last_seen_run_id"] for row in written] == [B, A, A]


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
@pytest.mark.parametrize("day", ["20", "21"])
def test_complete_liabilities_survive_newer_incomplete_assets(
    workflow, schema, workbook, coverage, day
):
    prepared = _prepare(
        workflow,
        schema,
        workbook,
        B,
        f"2026-08-{day}T08:30:00+02:00",
        coverage=coverage,
        first_value=110,
    )
    _apply_prepared_writes(schema, workbook, prepared, completed_at=f"2026-08-{day}T06:31:00Z")
    assets = select_assets(workbook, now=NOW)
    assert assets.current_complete and assets.run_id == B
    assert assets.daily["liabilities_eur"] is None and assets.daily["net_worth_eur"] is None
    liability = select_liabilities(workbook)
    assert liability.complete and liability.reference_run_id == A
    assert liability.rows == workbook["liabilities_current"]
    assert liability.snapshot_at == "2026-08-20T07:30:00+02:00"
    assert liability.snapshot_date == "2026-08-20"
    assert liability.completed_at == "2026-08-20T05:31:00Z"
    if day == "20":
        assert not any(row["run_id"] == A for row in workbook["portfolio_daily"])


@pytest.mark.parametrize("inactivate_only", [False, True])
def test_failed_complete_liability_writes_are_rejected(workflow, schema, workbook, inactivate_only):
    snapshot = _known_eur_snapshot("2026-08-20T08:30:00+02:00")
    snapshot["liabilities"].append(
        {
            **snapshot["liabilities"][0],
            "liability_key": "finary:liability:second",
            "source_liability_id": "second",
            "outstanding_eur": 20,
        }
    )
    snapshot.update(liabilities_eur=30, net_worth_eur=120)
    complete = _prepare_snapshot(workflow, schema, workbook, B, snapshot)
    _apply_prepared_writes(schema, workbook, complete, completed_at="2026-08-20T06:31:00Z")
    assert select_liabilities(workbook).reference_run_id == B
    snapshot["generated_at"] = "2026-08-20T09:30:00+02:00"
    snapshot["liabilities"].pop()
    snapshot.update(liabilities_eur=10, net_worth_eur=140)
    failed = _prepare_snapshot(workflow, schema, workbook, C, snapshot)
    if inactivate_only:
        inactive = next(row for row in failed["liability_rows"] if not row["is_active"])
        assert inactive["last_seen_run_id"] == B
        workbook["liabilities_current"] = _upsert(
            workbook["liabilities_current"], [inactive], "liability_key"
        )
    else:
        _apply_prepared_writes(
            schema, workbook, failed, stop_after="liabilities_current", current_limit=1
        )
        assert {row["last_seen_run_id"] for row in workbook["liabilities_current"]} == {B, C}
    liability = select_liabilities(workbook)
    assert liability.reference_run_id == B and not liability.complete and liability.rows is None


@pytest.mark.parametrize(
    "anomaly",
    ["missing", "extra", "duplicate", "bad_count", "missing_count", "bad_flag", "missing_run"],
)
def test_liability_membership_anomalies(workbook, anomaly):
    rows = workbook["liabilities_current"]
    if anomaly == "missing":
        rows.clear()
    elif anomaly in {"extra", "duplicate"}:
        duplicate = deepcopy(rows[0])
        if anomaly == "extra":
            duplicate["liability_key"] += "-extra"
        rows.append(duplicate)
    elif anomaly in {"bad_count", "missing_count"}:
        workbook["sync_runs"][0]["liabilities_count"] = -1 if anomaly == "bad_count" else ""
    elif anomaly == "bad_flag":
        rows[0]["is_active"] = 1
    else:
        rows[0]["last_seen_run_id"] = ""
    assert not select_liabilities(workbook).complete


@pytest.mark.parametrize("retained", [False, True])
def test_authoritative_zero_requires_success_complete_and_zero_count(
    workflow, schema, workbook, retained
):
    if not retained:
        workbook = _empty_workbook()
    snapshot = _known_eur_snapshot("2026-08-20T08:30:00+02:00")
    snapshot.update(liabilities=[], liabilities_eur=0, net_worth_eur=150)
    prepared = _prepare_snapshot(workflow, schema, workbook, B, snapshot)
    _apply_prepared_writes(schema, workbook, prepared, completed_at="2026-08-20T06:31:00Z")
    liability = select_liabilities(workbook)
    assert liability.complete and liability.rows == [] and liability.liabilities_eur == 0
    assert liability.reference_run_id == B
    if retained:
        assert workbook["liabilities_current"][0]["last_seen_run_id"] == A
        assert workbook["liabilities_current"][0]["is_active"] is False
    # Same-day daily replacement does not destroy the successful zero evidence.
    newer = _prepare(
        workflow, schema, workbook, C, "2026-08-20T09:30:00+02:00", coverage="UNAVAILABLE"
    )
    _apply_prepared_writes(schema, workbook, newer, completed_at="2026-08-20T07:31:00Z")
    liability = select_liabilities(workbook)
    assert liability.complete and liability.reference_run_id == B and liability.rows == []
    assert liability.snapshot_at is None and liability.snapshot_date is None
    assert liability.completed_at == "2026-08-20T06:31:00Z"  # Only provenance still available.
    workbook["sync_runs"] = [row for row in workbook["sync_runs"] if row["run_id"] != B]
    assert not select_liabilities(workbook).complete


def test_no_evidence_is_unavailable():
    workbook = _empty_workbook()
    assert select_assets(workbook, now=NOW).source == "unavailable"
    assert not select_liabilities(workbook).complete


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_empty_table_and_zero_count_do_not_prove_zero(workflow, schema, coverage):
    workbook = _empty_workbook()
    prepared = _prepare(
        workflow, schema, workbook, A, "2026-08-20T07:30:00+02:00", coverage=coverage
    )
    _apply_prepared_writes(schema, workbook, prepared)
    assert workbook["sync_runs"][0]["liabilities_count"] == 0
    assert select_assets(workbook, now=NOW).current_complete
    assert not select_liabilities(workbook).complete


def test_blank_eur_and_gross_assets_remain_authoritative_in_fallback(workflow, schema):
    workbook = _empty_workbook()
    snapshot = _known_eur_snapshot("2026-08-20T07:30:00+02:00", second_value=None)
    snapshot["accounts"][0]["market_value_eur"] = 500
    snapshot.update(gross_assets_eur=500, net_worth_eur=490)
    prepared = _prepare_snapshot(workflow, schema, workbook, A, snapshot)
    _apply_prepared_writes(schema, workbook, prepared)
    # Sheets renders nullable values as blank cells.
    for rows in workbook.values():
        for row in rows:
            for key, value in row.items():
                if value is None:
                    row[key] = ""
    workbook["positions_current"][0]["last_seen_run_id"] = B
    state = select_assets(workbook, now=NOW)
    assert state.source == "history" and state.run_id == A
    assert state.positions[1]["market_value_eur"] == "" and state.positions[1]["currency"] == ""
    assert state.daily["gross_assets_eur"] == 500
    assert state.daily["crypto_eur"] == "" and state.daily["financial_assets_eur"] == ""
    assert state.positions[0]["market_value_eur"] == 100  # Known subset is not gross assets.
    assert "PARTIAL_POSITION_EUR_COVERAGE" in workbook["sync_runs"][0]["error_message"]
    assert state.accounts is None and "region" not in state.positions[0]


@pytest.mark.parametrize(
    "anomaly",
    [
        "success_duplicate",
        "failed_duplicate",
        "missing_id",
        "naive_time",
        "invalid_time",
        "missing_time",
    ],
)
def test_terminal_evidence_must_be_unique_and_timezone_aware(workbook, anomaly):
    run = workbook["sync_runs"][0]
    if anomaly.endswith("duplicate"):
        duplicate = deepcopy(run)
        if anomaly == "failed_duplicate":
            duplicate["status"] = "FAILED"
        workbook["sync_runs"].append(duplicate)
    elif anomaly == "missing_id":
        run["run_id"] = ""
    elif anomaly == "naive_time":
        run["completed_at"] = "2026-08-20T07:31:00"
    elif anomaly == "invalid_time":
        run["completed_at"] = "invalid"
    else:
        del run["completed_at"]
    assert latest_success(workbook) is None
    assert select_assets(workbook, now=NOW).source == "unavailable"
    assert not select_liabilities(workbook).complete


def test_parsed_completion_order_ignores_ids_row_order_and_later_failure(workbook):
    earlier = {
        **workbook["sync_runs"][0],
        "run_id": "zzzz",
        "completed_at": "2026-08-20T07:00:00+02:00",
    }
    failed = {
        **earlier,
        "run_id": "failure",
        "status": "FAILED",
        "completed_at": "2026-08-20T10:00:00Z",
    }
    workbook["sync_runs"] += [earlier, failed]
    assert latest_success(workbook)["run_id"] == A  # 05:31Z is later than 07:00+02:00.
    assert select_assets(workbook, now=NOW).current_complete
    earlier["completed_at"] = "2026-08-20T07:31:00+02:00"
    assert latest_success(workbook) is None  # Equal instants: no ID tie-break.
    state = select_assets(workbook, now=NOW)
    assert state.latest_success_run_id is None and state.source == "history"
    assert state.run_id == A and state.dated_fallback


def test_failed_complete_write_after_incomplete_assets_has_no_liability_fallback(
    workflow, schema, workbook
):
    incomplete = _prepare(
        workflow, schema, workbook, B, "2026-08-20T08:30:00+02:00", coverage="PARTIAL"
    )
    _apply_prepared_writes(schema, workbook, incomplete, completed_at="2026-08-20T06:31:00Z")
    failed = _prepare(workflow, schema, workbook, C, "2026-08-20T09:30:00+02:00")
    _apply_prepared_writes(schema, workbook, failed, stop_after="liabilities_current")
    assets = select_assets(workbook, now=NOW)
    assert assets.source == "history" and assets.run_id == B
    assert assets.daily["liabilities_eur"] is None and assets.daily["net_worth_eur"] is None
    liabilities = select_liabilities(workbook)
    assert liabilities.reference_run_id == A and not liabilities.complete
    assert liabilities.rows is None  # No enrichment from retained complete history exists.


def test_current_membership_and_daily_aggregates_have_independent_availability(workbook):
    workbook["positions_history"].pop()
    state = select_assets(workbook, now=NOW)
    assert state.current_complete and state.source == "current" and state.run_id == A
    assert state.history is None and state.daily["gross_assets_eur"] == 150
    workbook["liabilities_current"].clear()
    assert not select_liabilities(workbook).complete
    assert state.daily["liabilities_eur"] == 10  # Dated aggregate survives unavailable details.
    workbook["portfolio_daily"].clear()
    state = select_assets(workbook, now=NOW)
    assert state.current_complete and state.run_id == A
    assert state.daily is None and state.aggregate_daily is None
    assert state.snapshot_date is None  # No invented snapshot date or gross total.


@pytest.mark.parametrize(
    "field,value",
    [
        ("gross_assets_eur", 999),
        ("liabilities_eur", ""),
        ("net_worth_eur", None),
        ("liability_coverage", "UNAVAILABLE"),
        ("generated_at", "2026-08-19T07:30:00+02:00"),
    ],
)
def test_inconsistent_daily_evidence_cannot_supply_fallback_or_aggregates(workbook, field, value):
    workbook["accounts_current"][0]["last_seen_run_id"] = B
    workbook["portfolio_daily"][0][field] = value
    state = select_assets(workbook, now=NOW)
    assert state.source == "unavailable" and state.aggregate_daily is None
    assert select_liabilities(workbook).complete  # Independent COMPLETE evidence survives.


@pytest.mark.parametrize("count_value", [0, 0.0, "0", "0.0", "0e0"])
def test_zero_counts_with_retained_inactive_rows_are_supported(
    workflow, schema, workbook, count_value
):
    snapshot = _known_eur_snapshot("2026-08-20T08:30:00+02:00")
    snapshot.update(liabilities=[], liabilities_eur=0, net_worth_eur=150)
    prepared = _prepare_snapshot(workflow, schema, workbook, B, snapshot)
    _apply_prepared_writes(schema, workbook, prepared, completed_at="2026-08-20T06:31:00Z")
    workbook["sync_runs"][-1]["liabilities_count"] = count_value
    workbook["liabilities_current"][0]["is_active"] = "FALSE"
    assert select_liabilities(workbook).complete


def test_amount_consistency_preserves_exported_float_arithmetic(workflow, schema):
    workbook = _empty_workbook()
    snapshot = _known_eur_snapshot("2026-08-20T07:30:00+02:00")
    snapshot["liabilities"][0]["outstanding_eur"] = 0.1
    snapshot["liabilities"].append(
        {
            **snapshot["liabilities"][0],
            "liability_key": "finary:liability:second",
            "source_liability_id": "second",
            "outstanding_eur": 0.2,
        }
    )
    snapshot["liabilities_eur"] = 0.1 + 0.2
    snapshot["net_worth_eur"] = snapshot["gross_assets_eur"] - snapshot["liabilities_eur"]
    prepared = _prepare_snapshot(workflow, schema, workbook, A, snapshot)
    _apply_prepared_writes(schema, workbook, prepared)
    workbook["accounts_current"][0]["last_seen_run_id"] = B
    assert select_assets(workbook, now=NOW).source == "history"
    assert select_liabilities(workbook).complete
    workbook["liabilities_current"][0]["outstanding_eur"] = 1
    assert not select_liabilities(workbook).complete


@pytest.mark.parametrize("time", [None, "", "2026-08-20T07:30:00"])
def test_missing_liability_observation_time_is_not_invented(workbook, time):
    workbook["liabilities_current"][0]["last_seen_at"] = time
    assert not select_liabilities(workbook).complete
