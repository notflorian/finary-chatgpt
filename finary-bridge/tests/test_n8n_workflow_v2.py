"""Executable and structural checks for the inactive schema 2.0 workflows."""

from __future__ import annotations

import json
from copy import deepcopy
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
    assert result["schema"]["schema_version"] == "2.0"


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
