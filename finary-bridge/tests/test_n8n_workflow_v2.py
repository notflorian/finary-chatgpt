"""Executable and structural checks for the inactive schema 2.x workflows."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from test_n8n_workflow import (
    _headers,
    _prepare_named_rows,
    _run_code_node,
    _snapshot,
)

ROOT = Path(__file__).parents[2]
V2_WORKFLOW_PATH = ROOT / "n8n" / "workflows" / "finary-daily-sync.json"
V2_ERROR_PATH = ROOT / "n8n" / "workflows" / "finary-error-handler.json"
V2_SCHEMA_PATH = ROOT / "docs" / "google-sheets-schema.json"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return json.loads(V2_WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))


def _node(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def _v2_snapshot(coverage: str = "COMPLETE") -> dict[str, Any]:
    snapshot = deepcopy(_snapshot())
    snapshot["schema_version"] = "2.0"
    snapshot["coverage"] = {"liabilities": coverage}
    if coverage != "COMPLETE":
        snapshot["liabilities"] = []
        snapshot["liabilities_eur"] = None
        snapshot["net_worth_eur"] = None
    return snapshot


def _run_validation(
    workflow: dict[str, Any], schema: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    return _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [
                {
                    "run_id": "20260820-073012",
                    "started_at": "2026-08-20T07:30:12+02:00",
                    "started_epoch_ms": 0,
                }
            ],
            "Fetch Canonical Schema": [{"statusCode": 200, "body": schema}],
        },
        input_rows=[{"statusCode": 200, "body": snapshot}],
    )[0]["json"]


def _initialize_run(
    workflow: dict[str, Any], *, execution_id: str, now: str
) -> dict[str, Any]:
    return _run_code_node(
        workflow,
        "Initialize Run",
        named_rows={},
        input_rows=[{}],
        execution_id=execution_id,
        now=now,
    )[0]["json"]


def _empty_workbook() -> dict[str, list[dict[str, Any]]]:
    return {
        "accounts_current": [],
        "positions_current": [],
        "liabilities_current": [],
        "positions_history": [],
        "portfolio_daily": [],
        "sync_runs": [],
    }


def _prepare_for_run(
    workflow: dict[str, Any],
    schema: dict[str, Any],
    snapshot: dict[str, Any],
    workbook: dict[str, list[dict[str, Any]]],
    run_id: str,
) -> dict[str, Any]:
    named = _prepare_named_rows(schema, snapshot)
    named["Validate Snapshot"][0]["run"] = {
        "run_id": run_id,
        "started_at": snapshot["generated_at"],
        "started_epoch_ms": 0,
    }
    named["Read Current Accounts"] = deepcopy(workbook["accounts_current"])
    named["Read Current Positions"] = deepcopy(workbook["positions_current"])
    named["Read Current Liabilities"] = deepcopy(workbook["liabilities_current"])
    named["Read Portfolio Daily"] = deepcopy(workbook["portfolio_daily"])
    return _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]


def _upsert(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    rows = {str(row[key]): deepcopy(row) for row in existing}
    for row in incoming:
        rows[str(row[key])] = deepcopy(row)
    return list(rows.values())


def _apply_prepared_writes(
    schema: dict[str, Any],
    workbook: dict[str, list[dict[str, Any]]],
    prepared: dict[str, Any],
    *,
    stop_after: str = "success",
    history_limit: int | None = None,
    completed_at: str = "2026-08-20T05:31:00Z",
) -> None:
    write_sets = (
        ("accounts_current", "account_rows"),
        ("positions_current", "position_rows"),
        ("liabilities_current", "liability_rows"),
    )
    for sheet_name, prepared_name in write_sets:
        workbook[sheet_name] = _upsert(
            workbook[sheet_name],
            prepared[prepared_name],
            schema["sheets"][sheet_name]["unique_key"],
        )
        if stop_after == sheet_name:
            return

    history_rows = prepared["history_rows"]
    if history_limit is not None:
        history_rows = history_rows[:history_limit]
    workbook["positions_history"] = _upsert(
        workbook["positions_history"],
        history_rows,
        schema["sheets"]["positions_history"]["unique_key"],
    )
    if stop_after == "positions_history" or history_limit is not None:
        return

    workbook["portfolio_daily"] = _upsert(
        workbook["portfolio_daily"],
        prepared["daily_rows"],
        schema["sheets"]["portfolio_daily"]["unique_key"],
    )
    if stop_after == "portfolio_daily":
        return

    success_rows = deepcopy(prepared["sync_run_rows"])
    success_rows[0]["completed_at"] = completed_at
    workbook["sync_runs"] = _upsert(
        workbook["sync_runs"],
        success_rows,
        schema["sheets"]["sync_runs"]["unique_key"],
    )


def _latest_complete_position_state(
    workbook: dict[str, list[dict[str, Any]]],
    snapshot_date: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]] | None:
    if snapshot_date is None:
        dates = [
            row.get("snapshot_date")
            for row in workbook["portfolio_daily"]
            if isinstance(row.get("snapshot_date"), str)
        ]
        if not dates:
            return None
        snapshot_date = max(dates)

    daily = [
        row
        for row in workbook["portfolio_daily"]
        if row.get("snapshot_date") == snapshot_date
    ]
    if len(daily) != 1 or not isinstance(daily[0].get("run_id"), str):
        return None
    run_id = daily[0]["run_id"]

    successful = [
        row
        for row in workbook["sync_runs"]
        if row.get("run_id") == run_id
        if row.get("status") in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
        and isinstance(row.get("completed_at"), str)
    ]
    if len(successful) != 1:
        return None
    selected_run = successful[0]
    try:
        datetime.fromisoformat(selected_run["completed_at"].replace("Z", "+00:00"))
    except ValueError:
        return None
    history = [
        row
        for row in workbook["positions_history"]
        if row.get("snapshot_date") == snapshot_date and row.get("run_id") == run_id
    ]
    position_keys = [row["position_key"] for row in history]
    if (
        len(history) != selected_run["positions_count"]
        or len(position_keys) != len(set(position_keys))
    ):
        return None
    return selected_run, history, daily[0]


def _known_eur_snapshot(
    generated_at: str,
    *,
    include_first: bool = True,
    include_second: bool = True,
    first_value: float | None = 100.0,
    second_value: float | None = 50.0,
    added_value: float | None = None,
) -> dict[str, Any]:
    snapshot = _v2_snapshot("COMPLETE")
    snapshot["generated_at"] = generated_at
    first, second = snapshot["positions"]
    first.update(
        {
            "currency": "EUR" if first_value is not None else None,
            "fx_to_eur": 1.0 if first_value is not None else None,
            "market_value_native": first_value if first_value is not None else 100.0,
            "market_value_eur": first_value,
        }
    )
    second.update(
        {
            "currency": "EUR" if second_value is not None else None,
            "fx_to_eur": 1.0 if second_value is not None else None,
            "market_value_native": second_value if second_value is not None else 50.0,
            "market_value_eur": second_value,
        }
    )
    positions = []
    if include_first:
        positions.append(first)
    if include_second:
        positions.append(second)
    if added_value is not None:
        added = deepcopy(first)
        added.update(
            {
                "position_key": "finary:account-001:asset:securities:added",
                "source_asset_id": "securities:added",
                "name": "Synthetic Added Fund",
                "ticker": "ADD",
                "isin": "XX0000000002",
                "market_value_native": added_value,
                "market_value_eur": added_value,
            }
        )
        positions.append(added)
    snapshot["positions"] = positions
    known_values = [
        value
        for value in (
            first_value if include_first else None,
            second_value if include_second else None,
            added_value,
        )
        if value is not None
    ]
    gross_assets = sum(known_values)
    snapshot["accounts"][0]["market_value_eur"] = gross_assets
    snapshot["gross_assets_eur"] = gross_assets
    snapshot["net_worth_eur"] = gross_assets - snapshot["liabilities_eur"]
    return snapshot


def test_v2_workflow_is_inactive_and_targets_only_v2_configuration(
    workflow: dict[str, Any],
) -> None:
    serialized = json.dumps(workflow)
    assert workflow["name"] == "Finary - Daily Sync"
    assert workflow["active"] is False
    assert "/v2/snapshot" in serialized
    assert "FINARY_SCHEMA_URL" in serialized
    assert "google-sheets-schema.json" in serialized
    assert "FINARY_GOOGLE_SHEET_ID" in serialized
    assert '"credentials"' not in serialized


def test_v2_workflow_preserves_operational_node_safety(
    workflow: dict[str, Any],
) -> None:
    sheet_nodes = [
        node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.googleSheets"
    ]
    reads = [node for node in sheet_nodes if node["parameters"].get("operation", "read") == "read"]
    writes = [
        node for node in sheet_nodes if node["parameters"].get("operation") == "appendOrUpdate"
    ]
    assert reads and all(node.get("executeOnce") is True for node in reads)
    assert writes and all(node.get("executeOnce") is not True for node in writes)
    assert workflow["settings"]["executionTimeout"] == 300
    assert all(node["retryOnFail"] is True for node in sheet_nodes)


def test_success_marker_follows_history_and_daily_writes(
    workflow: dict[str, Any],
) -> None:
    expected_success_suffix = {
        "Upsert Position History": "Select Daily Row",
        "Select Daily Row": "Upsert Portfolio Daily",
        "Upsert Portfolio Daily": "Select Success Run",
        "Select Success Run": "Record Successful Sync",
    }

    for source, target in expected_success_suffix.items():
        assert workflow["connections"][source]["main"] == [
            [{"node": target, "type": "main", "index": 0}]
        ]
    assert "Record Successful Sync" not in workflow["connections"]


@pytest.mark.parametrize(
    ("first_time", "second_time"),
    [
        ("2026-09-05T12:00:00.100Z", "2026-09-05T12:00:00.900Z"),
        ("2026-09-05T12:00:00.100Z", "2026-09-05T12:00:00.100Z"),
        ("2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"),
    ],
)
def test_initialize_run_uses_distinct_n8n_execution_identity(
    workflow: dict[str, Any], first_time: str, second_time: str
) -> None:
    first = _initialize_run(workflow, execution_id="4101", now=first_time)
    second = _initialize_run(workflow, execution_id="4102", now=second_time)

    assert first["run_id"] == "n8n-execution:4101"
    assert second["run_id"] == "n8n-execution:4102"
    assert first["run_id"] != second["run_id"]


def test_same_second_partial_rewrite_cannot_borrow_successful_completion(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first_run = _initialize_run(
        workflow,
        execution_id="4201",
        now="2026-09-05T12:00:00.100Z",
    )
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-09-05T14:00:00.100+02:00"),
        workbook,
        first_run["run_id"],
    )
    _apply_prepared_writes(
        schema,
        workbook,
        first,
        completed_at="2026-09-05T12:00:01Z",
    )
    selected = _latest_complete_position_state(workbook, "2026-09-05")
    assert selected is not None
    assert sum(row["market_value_eur"] for row in selected[1]) == 150.0

    second_run = _initialize_run(
        workflow,
        execution_id="4202",
        now="2026-09-05T12:00:00.900Z",
    )
    second = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-09-05T14:00:00.900+02:00",
            first_value=110.0,
        ),
        workbook,
        second_run["run_id"],
    )
    _apply_prepared_writes(schema, workbook, second, history_limit=1)

    assert sum(row["market_value_eur"] for row in workbook["positions_history"]) == 160.0
    assert workbook["portfolio_daily"][0]["gross_assets_eur"] == 150.0
    assert _latest_complete_position_state(workbook, "2026-09-05") is None


def test_execution_identity_propagates_to_rows_and_correlation(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    run = _initialize_run(
        workflow,
        execution_id="4301",
        now="2026-09-05T12:10:00Z",
    )
    prepared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-09-05T14:10:00+02:00"),
        _empty_workbook(),
        run["run_id"],
    )

    assert all(row["last_seen_run_id"] == run["run_id"] for row in prepared["account_rows"])
    assert all(row["last_seen_run_id"] == run["run_id"] for row in prepared["position_rows"])
    assert all(row["last_seen_run_id"] == run["run_id"] for row in prepared["liability_rows"])
    assert all(row["run_id"] == run["run_id"] for row in prepared["history_rows"])
    assert prepared["daily_rows"][0]["run_id"] == run["run_id"]
    assert prepared["sync_run_rows"][0]["run_id"] == run["run_id"]

    snapshot_node = _node(workflow, "Fetch Snapshot")
    correlation = next(
        header
        for header in snapshot_node["parameters"]["headerParameters"]["parameters"]
        if header["name"] == "X-Correlation-ID"
    )
    assert correlation["value"] == "={{ $('Initialize Run').first().json.run_id }}"


def test_interleaved_executions_are_incomplete_until_fresh_recovery(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-09-05T14:20:00+02:00"),
        workbook,
        _initialize_run(
            workflow,
            execution_id="4401",
            now="2026-09-05T12:20:00Z",
        )["run_id"],
    )
    second = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-09-05T14:20:01+02:00",
            first_value=110.0,
        ),
        workbook,
        _initialize_run(
            workflow,
            execution_id="4402",
            now="2026-09-05T12:20:01Z",
        )["run_id"],
    )

    workbook["positions_history"] = _upsert(
        workbook["positions_history"],
        first["history_rows"][:1],
        schema["sheets"]["positions_history"]["unique_key"],
    )
    workbook["positions_history"] = _upsert(
        workbook["positions_history"],
        second["history_rows"][1:],
        schema["sheets"]["positions_history"]["unique_key"],
    )
    workbook["portfolio_daily"] = _upsert(
        workbook["portfolio_daily"],
        first["daily_rows"],
        schema["sheets"]["portfolio_daily"]["unique_key"],
    )
    workbook["sync_runs"] = _upsert(
        workbook["sync_runs"],
        first["sync_run_rows"],
        schema["sheets"]["sync_runs"]["unique_key"],
    )
    assert _latest_complete_position_state(workbook, "2026-09-05") is None

    workbook["portfolio_daily"] = _upsert(
        workbook["portfolio_daily"],
        second["daily_rows"],
        schema["sheets"]["portfolio_daily"]["unique_key"],
    )
    workbook["sync_runs"] = _upsert(
        workbook["sync_runs"],
        second["sync_run_rows"],
        schema["sheets"]["sync_runs"]["unique_key"],
    )
    assert _latest_complete_position_state(workbook, "2026-09-05") is None

    recovery = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-09-05T14:30:00+02:00",
            first_value=110.0,
        ),
        workbook,
        _initialize_run(
            workflow,
            execution_id="4403",
            now="2026-09-05T12:30:00Z",
        )["run_id"],
    )
    _apply_prepared_writes(
        schema,
        workbook,
        recovery,
        completed_at="2026-09-05T12:31:00Z",
    )
    selected = _latest_complete_position_state(workbook, "2026-09-05")
    assert selected is not None
    assert selected[0]["run_id"] == "n8n-execution:4403"
    assert {row["market_value_eur"] for row in selected[1]} == {110.0, 50.0}


def test_repeating_prepared_writes_is_idempotent(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    prepared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-09-05T14:40:00+02:00"),
        workbook,
        _initialize_run(
            workflow,
            execution_id="4501",
            now="2026-09-05T12:40:00Z",
        )["run_id"],
    )

    _apply_prepared_writes(schema, workbook, prepared)
    first_state = deepcopy(workbook)
    _apply_prepared_writes(schema, workbook, prepared)

    assert workbook == first_state


def test_saved_data_retry_cannot_publish_stale_execution_identity(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    prepared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-09-05T14:50:00+02:00"),
        _empty_workbook(),
        "n8n-execution:4601",
    )

    matching = _run_code_node(
        workflow,
        "Select Success Run",
        named_rows={"Prepare Validated Rows": [prepared]},
        input_rows=[{}],
        execution_id="4601",
    )
    assert matching[0]["json"]["run_id"] == "n8n-execution:4601"

    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Select Success Run",
            named_rows={"Prepare Validated Rows": [prepared]},
            input_rows=[{}],
            execution_id="4602",
        )
    assert "STALE_EXECUTION_IDENTITY" in error.value.stderr


def test_text_schema_full_response_shape_passes_validation(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    result = _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [
                {
                    "run_id": "20260820-073012",
                    "started_at": "2026-08-20T07:30:12+02:00",
                    "started_epoch_ms": 0,
                }
            ],
            "Fetch Canonical Schema": [{"statusCode": 200, "data": json.dumps(schema)}],
        },
        input_rows=[{"statusCode": 200, "body": _v2_snapshot("UNAVAILABLE")}],
    )[0]["json"]

    assert result["can_write"] is True
    assert result["schema"]["schema_version"] == "2.1"


@pytest.mark.parametrize("coverage", ["COMPLETE", "PARTIAL", "UNAVAILABLE"])
def test_all_coverage_states_pass_v2_prewrite_validation(
    coverage: str, workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    result = _run_validation(workflow, schema, _v2_snapshot(coverage))
    assert result["can_write"] is True
    assert result["snapshot"]["coverage"]["liabilities"] == coverage


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_coverage_rejects_numeric_liability_totals(
    coverage: str, workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    snapshot = _v2_snapshot(coverage)
    snapshot["liabilities_eur"] = 0.0
    snapshot["net_worth_eur"] = snapshot["gross_assets_eur"]
    result = _run_validation(workflow, schema, snapshot)
    assert result["can_write"] is False
    assert result["failure"]["code"] == "SNAPSHOT_VALIDATION_FAILED"


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_coverage_writes_assets_but_preserves_liability_state(
    coverage: str, workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    snapshot = _v2_snapshot(coverage)
    named = _prepare_named_rows(schema, snapshot)
    named["Read Current Liabilities"] = [
        {
            **_headers(schema, "liabilities_current"),
            "liability_key": "finary:liability:last-known",
            "source": "finary",
            "source_liability_id": "last-known",
            "is_active": True,
        }
    ]
    result = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]

    assert result["account_rows"]
    assert result["position_rows"]
    assert result["history_rows"]
    assert result["liability_rows"] == []
    assert result["daily_rows"][0]["liability_coverage"] == coverage
    assert result["daily_rows"][0]["liabilities_eur"] is None
    assert result["daily_rows"][0]["net_worth_eur"] is None
    assert result["sync_run_rows"][0]["status"] == "SUCCESS_WITH_WARNINGS"
    assert result["sync_run_rows"][0]["liability_coverage"] == coverage


def test_complete_coverage_can_update_liabilities(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    snapshot = _v2_snapshot("COMPLETE")
    result = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, snapshot),
        input_rows=[{}],
    )[0]["json"]
    assert len(result["liability_rows"]) == 1
    assert result["daily_rows"][0]["liability_coverage"] == "COMPLETE"
    assert result["daily_rows"][0]["net_worth_eur"] == 140.0


def test_complete_known_empty_coverage_inactivates_last_known_liability(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    snapshot = _v2_snapshot("COMPLETE")
    snapshot["liabilities"] = []
    snapshot["liabilities_eur"] = 0.0
    snapshot["net_worth_eur"] = snapshot["gross_assets_eur"]
    named = _prepare_named_rows(schema, snapshot)
    named["Read Current Liabilities"] = [
        {
            **_headers(schema, "liabilities_current"),
            "liability_key": "finary:liability:last-known",
            "source": "finary",
            "source_liability_id": "last-known",
            "outstanding_eur": 10.0,
            "is_active": True,
        }
    ]

    result = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]

    assert len(result["liability_rows"]) == 1
    assert result["liability_rows"][0]["is_active"] is False
    assert result["daily_rows"][0]["liability_coverage"] == "COMPLETE"


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_partial_write_rerun_repairs_by_deterministic_upsert(
    coverage: str, workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    prepared = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, _v2_snapshot(coverage)),
        input_rows=[{}],
    )[0]["json"]

    def upsert(
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        key: str,
    ) -> list[dict[str, Any]]:
        by_key = {row[key]: deepcopy(row) for row in existing}
        for row in incoming:
            by_key[row[key]] = deepcopy(row)
        return list(by_key.values())

    # Simulate a failure after the current-state writes but before history and
    # daily writes. The liability sheet represents prior complete state and is
    # deliberately outside the incomplete-coverage write set.
    accounts = upsert([], prepared["account_rows"], "account_key")
    positions = upsert([], prepared["position_rows"], "position_key")
    liabilities = [{"liability_key": "finary:liability:last-known", "is_active": True}]
    history: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []

    # A same-snapshot rerun repairs the missing suffix and replaces, rather
    # than duplicates, the already-written deterministic rows.
    accounts = upsert(accounts, prepared["account_rows"], "account_key")
    positions = upsert(positions, prepared["position_rows"], "position_key")
    history = upsert(history, prepared["history_rows"], "history_key")
    daily = upsert(daily, prepared["daily_rows"], "snapshot_date")

    assert len(accounts) == len(prepared["account_rows"])
    assert len(positions) == len(prepared["position_rows"])
    assert len(history) == len(prepared["history_rows"])
    assert len(daily) == 1
    assert liabilities == [{"liability_key": "finary:liability:last-known", "is_active": True}]


def test_v2_same_day_rerun_is_deterministic(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    snapshot = _v2_snapshot("UNAVAILABLE")
    named = _prepare_named_rows(schema, snapshot)
    first = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]
    second = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]

    assert [row["history_key"] for row in first["history_rows"]] == [
        row["history_key"] for row in second["history_rows"]
    ]
    assert first["daily_rows"][0]["snapshot_date"] == second["daily_rows"][0]["snapshot_date"]


def test_same_day_disappearance_has_distinct_successful_history_membership(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T07:30:12+02:00"),
        workbook,
        "20260820-073012",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        first,
        completed_at="2026-08-20T05:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["status"] == "SUCCESS"
    assert sum(row["market_value_eur"] for row in selected[1]) == 150.0

    disappeared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:12+02:00", include_first=False
        ),
        workbook,
        "20260820-083012",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        disappeared,
        completed_at="2026-08-20T06:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["status"] == "SUCCESS_WITH_WARNINGS"
    assert selected[0]["run_id"] == "20260820-083012"
    assert [row["position_key"] for row in selected[1]] == [
        "finary:account-001:asset:cryptos:101"
    ]
    assert sum(row["market_value_eur"] for row in selected[1]) == 50.0
    assert selected[2]["gross_assets_eur"] == 50.0
    assert len(workbook["positions_history"]) == 2
    assert sum(row["market_value_eur"] for row in workbook["positions_history"]) == 150.0

    identical = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:12+02:00", include_first=False
        ),
        workbook,
        "20260820-084012",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        identical,
        completed_at="2026-08-20T06:41:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-084012"
    assert len(selected[1]) == 1
    assert len(workbook["positions_history"]) == 2

    changed = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T09:30:12+02:00",
            include_first=False,
            second_value=60.0,
            added_value=20.0,
        ),
        workbook,
        "20260820-093012",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        changed,
        completed_at="2026-08-20T07:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert {row["market_value_eur"] for row in selected[1]} == {60.0, 20.0}
    assert len(workbook["positions_history"]) == 3

    reappeared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T10:30:12+02:00",
            first_value=90.0,
            second_value=60.0,
        ),
        workbook,
        "20260820-103012",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        reappeared,
        completed_at="2026-08-20T08:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert {row["position_key"] for row in selected[1]} == {
        "finary:account-001:asset:securities:101",
        "finary:account-001:asset:cryptos:101",
    }
    assert next(
        row
        for row in selected[1]
        if row["position_key"] == "finary:account-001:asset:securities:101"
    )["market_value_eur"] == 90.0
    assert len(workbook["positions_history"]) == 3


def test_v2_next_day_creates_new_history_and_daily_keys(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    first_snapshot = _v2_snapshot("UNAVAILABLE")
    second_snapshot = deepcopy(first_snapshot)
    second_snapshot["generated_at"] = "2026-08-21T07:30:12+02:00"
    first = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, first_snapshot),
        input_rows=[{}],
    )[0]["json"]
    second = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(schema, second_snapshot),
        input_rows=[{}],
    )[0]["json"]

    assert first["daily_rows"][0]["snapshot_date"] != second["daily_rows"][0]["snapshot_date"]
    assert {row["history_key"] for row in first["history_rows"]}.isdisjoint(
        row["history_key"] for row in second["history_rows"]
    )


def test_prior_date_history_remains_unchanged(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T23:30:00+02:00"),
        workbook,
        "20260820-233000",
    )
    _apply_prepared_writes(schema, workbook, first)
    prior_rows = deepcopy(workbook["positions_history"])

    next_day = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-21T07:30:00+02:00", include_first=False
        ),
        workbook,
        "20260821-073000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        next_day,
        completed_at="2026-08-21T05:31:00Z",
    )

    assert [
        row for row in workbook["positions_history"] if row["snapshot_date"] == "2026-08-20"
    ] == prior_rows
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert {row["snapshot_date"] for row in selected[1]} == {"2026-08-21"}
    prior_selected = _latest_complete_position_state(workbook, "2026-08-20")
    assert prior_selected is not None
    assert prior_selected[1] == prior_rows


def test_partial_history_write_is_detected_and_identical_retry_recovers(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T07:30:00+02:00"),
        workbook,
        "20260820-073000",
    )
    _apply_prepared_writes(schema, workbook, first)
    assert _latest_complete_position_state(workbook) is not None

    interrupted = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:00+02:00", first_value=110.0
        ),
        workbook,
        "20260820-083000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        interrupted,
        history_limit=1,
    )
    workbook["sync_runs"].append(
        {
            "run_id": "20260820-083000",
            "completed_at": "2026-08-20T06:31:00Z",
            "status": "FAILED",
            "positions_count": None,
        }
    )

    assert _latest_complete_position_state(workbook) is None

    retry = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:00+02:00", first_value=110.0
        ),
        workbook,
        "20260820-084000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        retry,
        completed_at="2026-08-20T06:41:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-084000"
    assert {row["market_value_eur"] for row in selected[1]} == {110.0, 50.0}


def test_current_write_interruption_and_changed_retry_recover_membership(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T07:30:00+02:00"),
        workbook,
        "20260820-073000",
    )
    _apply_prepared_writes(schema, workbook, first)

    interrupted = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:00+02:00", include_first=False
        ),
        workbook,
        "20260820-083000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        interrupted,
        stop_after="positions_current",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-073000"

    changed_retry = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:45:00+02:00",
            include_first=False,
            second_value=60.0,
            added_value=20.0,
        ),
        workbook,
        "20260820-084500",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        changed_retry,
        completed_at="2026-08-20T06:46:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-084500"
    assert {row["market_value_eur"] for row in selected[1]} == {60.0, 20.0}


def test_daily_write_without_success_is_not_complete_and_retry_recovers(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    first = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T07:30:00+02:00"),
        workbook,
        "20260820-073000",
    )
    _apply_prepared_writes(schema, workbook, first)

    interrupted = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:00+02:00", include_first=False
        ),
        workbook,
        "20260820-083000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        interrupted,
        stop_after="portfolio_daily",
    )
    assert _latest_complete_position_state(workbook) is None

    retry = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:31:00+02:00", include_first=False
        ),
        workbook,
        "20260820-083100",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        retry,
        completed_at="2026-08-20T06:32:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-083100"
    assert len(selected[1]) == 1


def test_success_with_warnings_preserves_unknown_eur_without_zero_or_absence_marker(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    workbook = _empty_workbook()
    unknown = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T07:30:00+02:00", first_value=None
        ),
        workbook,
        "20260820-073000",
    )
    _apply_prepared_writes(schema, workbook, unknown)
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["status"] == "SUCCESS_WITH_WARNINGS"
    assert len(selected[1]) == 2
    assert any(row["market_value_eur"] is None for row in selected[1])

    disappeared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(
            "2026-08-20T08:30:00+02:00", include_first=False
        ),
        workbook,
        "20260820-083000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        disappeared,
        completed_at="2026-08-20T06:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert len(selected[1]) == 1
    assert all(
        row["position_key"] != "finary:account-001:asset:securities:101"
        for row in selected[1]
    )
    assert all(row["market_value_eur"] != 0 for row in workbook["positions_history"])


@pytest.mark.parametrize(
    ("generated_at", "expected_date"),
    [
        ("2026-01-15T23:30:00Z", "2026-01-16"),
        ("2026-07-15T22:30:00Z", "2026-07-16"),
        ("2026-03-29T00:30:00Z", "2026-03-29"),
        ("2026-03-29T01:30:00Z", "2026-03-29"),
    ],
)
def test_history_uses_europe_paris_date_across_utc_and_dst_boundaries(
    generated_at: str,
    expected_date: str,
    workflow: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    prepared = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot(generated_at),
        _empty_workbook(),
        "20260329-TEST",
    )

    assert {row["snapshot_date"] for row in prepared["history_rows"]} == {
        expected_date
    }
    assert prepared["daily_rows"][0]["snapshot_date"] == expected_date


def test_legacy_history_rows_are_retained_but_not_complete_membership(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    run_column = next(
        column
        for column in schema["sheets"]["positions_history"]["columns"]
        if column["name"] == "run_id"
    )
    assert run_column["nullable"] is True
    workbook = _empty_workbook()
    workbook["positions_history"] = [
        {
            "history_key": "2026-08-19:finary:account-001:asset:securities:legacy",
            "snapshot_date": "2026-08-19",
            "position_key": "finary:account-001:asset:securities:legacy",
            "market_value_eur": 75.0,
        }
    ]
    workbook["sync_runs"] = [
        {
            "run_id": "20260819-073000",
            "completed_at": "2026-08-19T05:31:00Z",
            "status": "SUCCESS",
            "positions_count": 1,
        }
    ]
    assert _latest_complete_position_state(workbook) is None

    current = _prepare_for_run(
        workflow,
        schema,
        _known_eur_snapshot("2026-08-20T07:30:00+02:00"),
        workbook,
        "20260820-073000",
    )
    _apply_prepared_writes(
        schema,
        workbook,
        current,
        completed_at="2026-08-20T05:31:00Z",
    )
    selected = _latest_complete_position_state(workbook)
    assert selected is not None
    assert selected[0]["run_id"] == "20260820-073000"
    assert any(row["position_key"].endswith(":legacy") for row in workbook["positions_history"])


def test_v2_missing_position_becomes_inactive_under_unavailable_liabilities(
    workflow: dict[str, Any], schema: dict[str, Any]
) -> None:
    named = _prepare_named_rows(schema, _v2_snapshot("UNAVAILABLE"))
    old = {column["name"]: None for column in schema["sheets"]["positions_current"]["columns"]}
    old.update(
        {
            "position_key": "finary:account-001:asset:securities:old",
            "source": "finary",
            "source_asset_id": "securities:old",
            "account_key": "finary:account:account-001",
            "market_value_native": 12.0,
            "is_active": True,
        }
    )
    named["Read Current Positions"] = [old]
    result = _run_code_node(workflow, "Prepare Validated Rows", named_rows=named, input_rows=[{}])[
        0
    ]["json"]

    inactive = next(
        row for row in result["position_rows"] if row["position_key"] == old["position_key"]
    )
    assert inactive["is_active"] is False
    assert result["liability_rows"] == []


def test_v2_error_handler_is_separate_inactive_and_coverage_compatible(
    schema: dict[str, Any],
) -> None:
    workflow = json.loads(V2_ERROR_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(workflow)
    assert workflow["name"] == "Finary - Error Handler"
    assert workflow["active"] is False
    assert "FINARY_SCHEMA_URL" in serialized
    assert "FINARY_GOOGLE_SHEET_ID" in serialized
    assert "liability_coverage: null" in serialized
    assert [column["name"] for column in schema["sheets"]["sync_runs"]["columns"]]

    result = _run_code_node(
        workflow,
        "Prepare Sanitized Failure",
        named_rows={
            "Workflow Error Trigger": [
                {
                    "execution": {
                        "id": "synthetic-execution",
                        "error": {"message": "429 private-project-detail"},
                        "lastNodeExecuted": "Read Current Positions",
                    }
                }
            ],
            "Fetch Operational Schema": [{"statusCode": 200, "body": schema}],
        },
        input_rows=[],
    )[0]["json"]
    assert result["row"]["liability_coverage"] is None
    assert result["row"]["error_code"] == "GOOGLE_RATE_LIMITED"
    assert "private-project-detail" not in result["row"]["error_message"]
