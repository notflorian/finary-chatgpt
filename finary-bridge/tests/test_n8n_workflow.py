"""Executable and structural checks for the n8n synchronization workflow."""

from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / "n8n" / "workflows" / "finary-daily-sync.json"
SCHEMA_PATH = REPOSITORY_ROOT / "docs" / "google-sheets-schema.json"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sheets_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _node(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def _headers(schema: dict[str, Any], sheet_name: str) -> dict[str, str]:
    return {
        column["name"]: column["name"]
        for column in schema["sheets"][sheet_name]["columns"]
    }


def _run_code_node(
    workflow: dict[str, Any],
    node_name: str,
    *,
    named_rows: dict[str, list[dict[str, Any]]],
    input_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to execute n8n Code node tests")
    code = _node(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const namedRows = {json.dumps(named_rows)};
const inputRows = {json.dumps(input_rows)};
const $ = (name) => ({{
  first: () => ({{ json: (namedRows[name] || [{{}}])[0] }}),
  all: () => (namedRows[name] || []).map((json) => ({{ json }})),
}});
const $input = {{
  first: () => ({{ json: inputRows[0] || {{}} }}),
  all: () => inputRows.map((json) => ({{ json }})),
}};
(async () => {{
{code}
}})().then((result) => process.stdout.write(JSON.stringify(result))).catch((error) => {{
  process.stderr.write(String(error && error.message ? error.message : error));
  process.exit(2);
}});
"""
    completed = subprocess.run(  # noqa: S603
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _snapshot() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "coverage": {"liabilities": "COMPLETE"},
        "generated_at": "2026-08-20T07:30:12+02:00",
        "reference_currency": "EUR",
        "gross_assets_eur": 150.0,
        "liabilities_eur": 10.0,
        "net_worth_eur": 140.0,
        "accounts": [
            {
                "account_key": "finary:account:account-001",
                "source": "finary",
                "source_account_id": "account-001",
                "name": "Synthetic PEA",
                "institution": "Synthetic Institution",
                "account_type": "PEA",
                "owner": None,
                "currency": "EUR",
                "market_value_eur": 150.0,
                "metadata": {},
            }
        ],
        "positions": [
            {
                "position_key": "finary:account-001:asset:securities:101",
                "source": "finary",
                "source_asset_id": "securities:101",
                "account_key": "finary:account:account-001",
                "name": "Synthetic Fund",
                "ticker": "SYN",
                "isin": "XX0000000001",
                "asset_class": "OTHER",
                "asset_subclass": None,
                "region": None,
                "quantity": 2.0,
                "unit_price": 50.0,
                "currency": "EUR",
                "fx_to_eur": 1.0,
                "market_value_native": 100.0,
                "market_value_eur": 100.0,
                "cost_basis_eur": 80.0,
                "unrealized_pnl_eur": None,
                "unrealized_pnl_pct": None,
                "metadata": {},
            },
            {
                "position_key": "finary:account-001:asset:cryptos:101",
                "source": "finary",
                "source_asset_id": "cryptos:101",
                "account_key": "finary:account:account-001",
                "name": "Synthetic Coin",
                "ticker": "SYC",
                "isin": None,
                "asset_class": "CRYPTO",
                "asset_subclass": None,
                "region": None,
                "quantity": 1.0,
                "unit_price": 50.0,
                "currency": None,
                "fx_to_eur": None,
                "market_value_native": 50.0,
                "market_value_eur": None,
                "cost_basis_eur": 40.0,
                "unrealized_pnl_eur": None,
                "unrealized_pnl_pct": None,
                "metadata": {},
            },
        ],
        "liabilities": [
            {
                "liability_key": "finary:liability:loan-001",
                "source": "finary",
                "source_liability_id": "loan-001",
                "name": "Synthetic Loan",
                "liability_type": "LOAN",
                "institution": None,
                "outstanding_eur": 10.0,
                "interest_rate": None,
                "monthly_payment_eur": None,
                "end_date": None,
                "metadata": {},
            }
        ],
    }


def _prepare_named_rows(
    schema: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    context = {
        "can_write": True,
        "run": {
            "run_id": "20260820-073012",
            "started_at": "2026-08-20T07:30:12+02:00",
            "started_epoch_ms": 0,
        },
        "schema": schema,
        "snapshot": snapshot,
    }
    preflight_names = {
        "Preflight Overrides Header": "asset_overrides",
        "Preflight Accounts Header": "accounts_current",
        "Preflight Positions Header": "positions_current",
        "Preflight Liabilities Header": "liabilities_current",
        "Preflight History Header": "positions_history",
        "Preflight Daily Header": "portfolio_daily",
        "Preflight Sync Header": "sync_runs",
    }
    named = {"Validate Snapshot": [context]}
    named.update(
        {node_name: [_headers(schema, sheet)] for node_name, sheet in preflight_names.items()}
    )
    named.update(
        {
            "Read Asset Overrides": [
                {
                    "override_key": "override-001",
                    "source_asset_id": "securities:101",
                    "isin": None,
                    "ticker": None,
                    "name_match": None,
                    "custom_asset_class": "EQUITY",
                    "custom_asset_subclass": "WORLD_EQUITY",
                    "custom_region": "GLOBAL",
                    "notes": "Synthetic",
                    "enabled": True,
                }
            ],
            "Read Current Accounts": [],
            "Read Current Positions": [],
            "Read Current Liabilities": [],
            "Read Portfolio Daily": [],
        }
    )
    return named


def _validate_snapshot_failure(
    workflow: dict[str, Any],
    schema: dict[str, Any],
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
) -> dict[str, Any]:
    run = {
        "run_id": "20260820-073012",
        "started_at": "2026-08-20T07:30:12+02:00",
        "started_epoch_ms": 0,
    }
    return _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [run],
            "Fetch Canonical Schema": [{"statusCode": 200, "body": schema}],
        },
        input_rows=[
            {
                "statusCode": status_code,
                "body": {
                    "error": {
                        "code": code,
                        "message": message,
                        "retryable": retryable,
                    }
                },
            }
        ],
    )[0]["json"]


def test_workflow_uses_expected_triggers_and_runtime_schema(
    workflow: dict[str, Any],
) -> None:
    assert workflow["name"] == "Finary - Daily Sync"
    assert workflow["settings"]["timezone"] == "Europe/Paris"
    schedule = _node(workflow, "Daily 07:30 Europe Paris")
    assert schedule["parameters"]["rule"]["interval"] == [
        {"field": "cronExpression", "expression": "30 7 * * *"}
    ]
    assert _node(workflow, "Manual Trigger")["type"] == "n8n-nodes-base.manualTrigger"
    schema_request = _node(workflow, "Fetch Canonical Schema")
    assert "FINARY_SCHEMA_URL" in schema_request["parameters"]["url"]
    assert "http://schema-server/google-sheets-schema.json" in (
        schema_request["parameters"]["url"]
    )
    assert schema_request["parameters"]["options"]["response"]["response"][
        "responseFormat"
    ] == "text"


def test_only_standard_nodes_and_no_manual_sheet_writes(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    allowed = {
        "n8n-nodes-base.manualTrigger",
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.if",
        "n8n-nodes-base.googleSheets",
    }
    assert {node["type"] for node in workflow["nodes"]} <= allowed
    manual_sheets = {
        name
        for name, definition in sheets_schema["sheets"].items()
        if definition["sheet_ownership"] == "manual"
    }
    write_nodes = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.googleSheets"
        and node["parameters"].get("operation") in {"append", "appendOrUpdate", "update"}
    ]
    assert write_nodes
    assert all(
        node["parameters"]["sheetName"]["value"] not in manual_sheets
        for node in write_nodes
    )
    assert all(node["parameters"]["operation"] == "appendOrUpdate" for node in write_nodes)


def test_every_google_sheets_read_executes_once(
    workflow: dict[str, Any],
) -> None:
    read_nodes = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.googleSheets"
        and node["parameters"].get("operation", "read") == "read"
    ]
    assert read_nodes
    assert all(node.get("executeOnce") is True for node in read_nodes)


def test_workflow_has_no_destructive_operation_or_embedded_credential(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    serialized = json.dumps(workflow)
    assert '"credentials"' not in serialized
    assert '"operation": "clear"' not in serialized
    assert '"operation": "delete"' not in serialized
    managed = {
        "accounts_current",
        "positions_current",
        "liabilities_current",
        "positions_history",
        "portfolio_daily",
        "sync_runs",
    }
    write_targets = {
        node["parameters"]["sheetName"]["value"]
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.googleSheets"
        and node["parameters"].get("operation") == "appendOrUpdate"
    }
    assert write_targets == managed
    assert managed <= set(sheets_schema["sheets"])


def test_every_write_derives_schema_and_uses_canonical_unique_key(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    for node in workflow["nodes"]:
        if node["type"] != "n8n-nodes-base.googleSheets":
            continue
        if node["parameters"].get("operation") != "appendOrUpdate":
            continue
        sheet = node["parameters"]["sheetName"]["value"]
        columns = node["parameters"]["columns"]
        assert sheets_schema["sheets"][sheet]["unique_key"] in columns["matchingColumns"]
        assert f"schema.sheets.{sheet}.columns.map" in columns["schema"]
        assert node["parameters"]["options"]["allowEmptyValues"] is True
        assert node["parameters"]["options"]["handlingExtraData"] == "error"


def test_structured_bridge_failure_cannot_reach_portfolio_writes(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    run = {
        "run_id": "20260820-073012",
        "started_at": "2026-08-20T07:30:12+02:00",
        "started_epoch_ms": 0,
    }
    result = _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [run],
            "Fetch Canonical Schema": [{"statusCode": 200, "body": sheets_schema}],
        },
        input_rows=[
            {
                "statusCode": 503,
                "body": {
                    "error": {
                        "code": "FINARY_FEATURE_UNAVAILABLE",
                        "message": "private detail must not pass through",
                        "retryable": False,
                    }
                },
            }
        ],
    )[0]["json"]
    assert result["can_write"] is False
    assert result["failure"] == {
        "code": "FINARY_FEATURE_UNAVAILABLE",
        "message": "Required Finary data is unavailable",
        "retryable": False,
    }
    false_branch = workflow["connections"]["Snapshot Is Valid"]["main"][1]
    assert false_branch == [
        {"node": "Preflight Failure Sync Header", "type": "main", "index": 0}
    ]


def test_bridge_auth_failure_reaches_sanitized_failed_sync_run(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    sensitive_marker = "SYNTHETIC_API_KEY_MUST_NOT_LEAK"
    context = _validate_snapshot_failure(
        workflow,
        sheets_schema,
        status_code=401,
        code="BRIDGE_AUTH_FAILED",
        message=sensitive_marker,
        retryable=True,
    )

    assert context["can_write"] is False
    assert context["failure"] == {
        "code": "BRIDGE_AUTH_FAILED",
        "message": "Bridge authentication failed",
        "retryable": False,
    }

    failed_run = _run_code_node(
        workflow,
        "Prepare Failed Run",
        named_rows={"Validate Snapshot": [context]},
        input_rows=[_headers(sheets_schema, "sync_runs")],
    )[0]["json"]
    assert failed_run["status"] == "FAILED"
    assert failed_run["error_code"] == "BRIDGE_AUTH_FAILED"
    assert failed_run["error_message"] == "Bridge authentication failed"
    assert sensitive_marker not in json.dumps([context, failed_run])

    false_branch = workflow["connections"]["Snapshot Is Valid"]["main"][1]
    assert false_branch == [
        {"node": "Preflight Failure Sync Header", "type": "main", "index": 0}
    ]
    assert workflow["connections"]["Preflight Failure Sync Header"]["main"][0] == [
        {"node": "Prepare Failed Run", "type": "main", "index": 0}
    ]
    assert workflow["connections"]["Prepare Failed Run"]["main"][0] == [
        {"node": "Record Failed Sync", "type": "main", "index": 0}
    ]
    record_node = _node(workflow, "Record Failed Sync")
    assert record_node["parameters"]["sheetName"]["value"] == "sync_runs"
    assert record_node["parameters"]["operation"] == "appendOrUpdate"
    assert "Record Failed Sync" not in workflow["connections"]


@pytest.mark.parametrize(
    ("status_code", "code", "expected_failure"),
    [
        (
            502,
            "FINARY_AUTH_FAILED",
            {
                "code": "FINARY_AUTH_FAILED",
                "message": "Unable to authenticate with Finary",
                "retryable": False,
            },
        ),
        (
            418,
            "UNKNOWN_SYNTHETIC_FAILURE",
            {
                "code": "BRIDGE_REQUEST_FAILED",
                "message": "Bridge snapshot request failed",
                "retryable": False,
            },
        ),
    ],
)
def test_snapshot_failure_keeps_finary_auth_distinct_and_unknown_errors_generic(
    status_code: int,
    code: str,
    expected_failure: dict[str, Any],
    workflow: dict[str, Any],
    sheets_schema: dict[str, Any],
) -> None:
    sensitive_marker = "SYNTHETIC_UPSTREAM_DETAIL_MUST_NOT_LEAK"
    context = _validate_snapshot_failure(
        workflow,
        sheets_schema,
        status_code=status_code,
        code=code,
        message=sensitive_marker,
        retryable=True,
    )

    assert context["can_write"] is False
    assert context["failure"] == expected_failure
    assert sensitive_marker not in json.dumps(context)


def test_complete_snapshot_passes_prewrite_gate(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    run = {
        "run_id": "20260820-073012",
        "started_at": "2026-08-20T07:30:12+02:00",
        "started_epoch_ms": 0,
    }
    result = _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [run],
            "Fetch Canonical Schema": [{"statusCode": 200, "body": sheets_schema}],
        },
        input_rows=[{"statusCode": 200, "body": _snapshot()}],
    )[0]["json"]
    assert result["can_write"] is True
    assert result["snapshot"]["gross_assets_eur"] == 150.0


def test_suspicious_empty_snapshot_fails_prewrite_gate(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    snapshot = _snapshot()
    snapshot["positions"] = []
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
            "Fetch Canonical Schema": [{"statusCode": 200, "body": sheets_schema}],
        },
        input_rows=[{"statusCode": 200, "body": snapshot}],
    )[0]["json"]
    assert result["can_write"] is False
    assert result["failure"]["code"] == "SNAPSHOT_VALIDATION_FAILED"


def test_prepare_rows_is_null_safe_category_aware_and_idempotent(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    snapshot = _snapshot()
    named = _prepare_named_rows(sheets_schema, snapshot)
    first = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]
    second = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]

    positions = {row["source_asset_id"]: row for row in first["position_rows"]}
    assert set(positions) == {"securities:101", "cryptos:101"}
    assert positions["securities:101"]["asset_class"] == "EQUITY"
    assert positions["securities:101"]["weight_portfolio"] == 1.0
    assert positions["cryptos:101"]["market_value_eur"] is None
    assert positions["cryptos:101"]["weight_portfolio"] is None
    assert first["daily_rows"][0]["gross_assets_eur"] == 150.0
    assert first["daily_rows"][0]["crypto_eur"] is None
    assert first["daily_rows"][0]["liabilities_eur"] == 10.0
    assert "PARTIAL_POSITION_EUR_COVERAGE" in first["warnings"]
    assert [row["history_key"] for row in first["history_rows"]] == [
        row["history_key"] for row in second["history_rows"]
    ]


def test_missing_current_rows_are_retained_as_inactive(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    named = _prepare_named_rows(sheets_schema, _snapshot())
    old = {
        column["name"]: None
        for column in sheets_schema["sheets"]["positions_current"]["columns"]
    }
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
    result = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]
    inactive = next(
        row
        for row in result["position_rows"]
        if row["position_key"] == old["position_key"]
    )
    assert inactive["is_active"] is False
    assert all(row["position_key"] != old["position_key"] for row in result["history_rows"])


def test_next_day_creates_new_history_and_daily_keys(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    first_snapshot = _snapshot()
    second_snapshot = deepcopy(first_snapshot)
    second_snapshot["generated_at"] = "2026-08-21T07:30:12+02:00"
    first = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(sheets_schema, first_snapshot),
        input_rows=[{}],
    )[0]["json"]
    second = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=_prepare_named_rows(sheets_schema, second_snapshot),
        input_rows=[{}],
    )[0]["json"]
    assert first["daily_rows"][0]["snapshot_date"] == "2026-08-20"
    assert second["daily_rows"][0]["snapshot_date"] == "2026-08-21"
    assert set(row["history_key"] for row in first["history_rows"]).isdisjoint(
        row["history_key"] for row in second["history_rows"]
    )


def test_count_change_warning_thresholds_are_applied(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    named = _prepare_named_rows(sheets_schema, _snapshot())
    account_template = {
        column["name"]: None
        for column in sheets_schema["sheets"]["accounts_current"]["columns"]
    }
    position_template = {
        column["name"]: None
        for column in sheets_schema["sheets"]["positions_current"]["columns"]
    }
    named["Read Current Accounts"] = [
        {
            **account_template,
            "account_key": f"finary:account:old-{index}",
            "is_active": True,
        }
        for index in range(4)
    ]
    named["Read Current Positions"] = [
        {
            **position_template,
            "position_key": f"finary:old-{index}:asset:securities:{index}",
            "is_active": True,
        }
        for index in range(4)
    ]
    result = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]
    assert "ACCOUNT_COUNT_CHANGE_OVER_30_PERCENT" in result["warnings"]
    assert "POSITION_COUNT_CHANGE_OVER_30_PERCENT" in result["warnings"]


def test_ambiguous_highest_precedence_override_fails(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    named = _prepare_named_rows(sheets_schema, _snapshot())
    named["Read Asset Overrides"].append(
        {**deepcopy(named["Read Asset Overrides"][0]), "override_key": "override-002"}
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Prepare Validated Rows",
            named_rows=named,
            input_rows=[{}],
        )
    assert "AMBIGUOUS_ASSET_OVERRIDE" in error.value.stderr


def test_header_drift_fails_before_row_preparation(
    workflow: dict[str, Any], sheets_schema: dict[str, Any]
) -> None:
    named = _prepare_named_rows(sheets_schema, _snapshot())
    named["Preflight Positions Header"][0].pop("position_key")
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_code_node(
            workflow,
            "Prepare Validated Rows",
            named_rows=named,
            input_rows=[{}],
        )
    assert "SHEETS_HEADER_MISMATCH:positions_current" in error.value.stderr
