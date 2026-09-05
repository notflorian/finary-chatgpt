"""Structural and executable checks for production operations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_n8n_workflow import _run_code_node

ROOT = Path(__file__).parents[2]
DAILY_PATH = ROOT / "n8n" / "workflows" / "finary-daily-sync.json"
ERROR_PATH = ROOT / "n8n" / "workflows" / "finary-error-handler.json"
SCHEMA_PATH = ROOT / "docs" / "google-sheets-schema.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _node(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def _run_error_classifier(
    trigger: dict[str, Any], existing: list[dict[str, Any]]
) -> dict[str, Any]:
    workflow = _load(ERROR_PATH)
    schema = _load(SCHEMA_PATH)
    named = {
        "Workflow Error Trigger": [trigger],
        "Fetch Operational Schema": [{"statusCode": 200, "data": json.dumps(schema)}],
    }
    return _run_code_node(
        workflow,
        "Prepare Sanitized Failure",
        named_rows=named,
        input_rows=existing,
        execution_id="handler-99",
    )[0]["json"]


def _trigger(
    message: str,
    step: str = "Read Current Positions",
    *,
    execution_id: str = "execution-42",
    retry_of: str | None = None,
) -> dict[str, Any]:
    return {
        "execution": {
            "id": execution_id,
            "error": {"message": message, "stack": "private stack"},
            "lastNodeExecuted": step,
            "mode": "trigger",
            "retryOf": retry_of,
        },
        "workflow": {"id": "daily", "name": "Finary - Daily Sync"},
    }


def test_workflows_are_inactive_bounded_and_use_standard_nodes() -> None:
    daily = _load(DAILY_PATH)
    error = _load(ERROR_PATH)
    assert daily["active"] is False
    assert error["active"] is False
    assert daily["settings"]["executionTimeout"] == 300
    assert error["settings"]["executionTimeout"] == 120
    assert _node(error, "Workflow Error Trigger")["type"] == ("n8n-nodes-base.errorTrigger")
    allowed = {
        "n8n-nodes-base.errorTrigger",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.if",
        "n8n-nodes-base.googleSheets",
    }
    assert {node["type"] for node in error["nodes"]} <= allowed


@pytest.mark.parametrize("path", [DAILY_PATH, ERROR_PATH])
def test_google_nodes_have_finite_native_retry_without_credentials(path: Path) -> None:
    workflow = _load(path)
    sheets = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.googleSheets"]
    assert sheets
    assert all(node.get("retryOnFail") is True for node in sheets)
    assert all(node.get("maxTries") == 3 for node in sheets)
    assert all(node.get("waitBetweenTries") == 5000 for node in sheets)
    assert '"credentials"' not in json.dumps(workflow)


def test_read_nodes_execute_once_and_write_nodes_process_all_rows() -> None:
    for workflow in (_load(DAILY_PATH), _load(ERROR_PATH)):
        sheets = [
            node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.googleSheets"
        ]
        reads = [node for node in sheets if node["parameters"].get("operation", "read") == "read"]
        writes = [
            node for node in sheets if node["parameters"].get("operation") == "appendOrUpdate"
        ]
        assert reads and writes
        assert all(node.get("executeOnce") is True for node in reads)
        assert all(node.get("executeOnce") is not True for node in writes)


def test_error_workflow_can_only_write_sanitized_sync_telemetry() -> None:
    workflow = _load(ERROR_PATH)
    schema_request = _node(workflow, "Fetch Operational Schema")
    assert (
        schema_request["parameters"]["options"]["response"]["response"]["responseFormat"] == "text"
    )
    writes = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.googleSheets"
        and node["parameters"].get("operation") == "appendOrUpdate"
    ]
    assert [node["parameters"]["sheetName"]["value"] for node in writes] == ["sync_runs"]
    serialized = json.dumps(workflow).lower()
    assert '"operation": "delete"' not in serialized
    assert '"operation": "clear"' not in serialized


@pytest.mark.parametrize(
    ("message", "step", "expected"),
    [
        ("429 RESOURCE_EXHAUSTED secret-token", "Read Asset Overrides", "GOOGLE_RATE_LIMITED"),
        ("401 credential rejected", "Read Current Accounts", "GOOGLE_AUTH_FAILED"),
        ("503 service unavailable", "Upsert Current Positions", "GOOGLE_TEMPORARY_FAILURE"),
        ("workflow execution timed out", "Read Current Positions", "WORKFLOW_TIMEOUT"),
        ("unexpected write failure", "Record Successful Sync", "WRITE_FAILED"),
    ],
)
def test_operational_errors_are_stably_classified_and_sanitized(
    message: str, step: str, expected: str
) -> None:
    result = _run_error_classifier(_trigger(message, step), [])
    assert result["row"]["error_code"] == expected
    assert result["row"]["run_id"] == "n8n-execution:execution-42"
    assert "secret-token" not in json.dumps(result)
    assert "private stack" not in json.dumps(result)
    assert result["row"]["gross_assets_eur"] is None


@pytest.mark.parametrize("status", ["SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED"])
def test_terminal_run_is_never_overwritten_and_last_success_ignores_failures(
    status: str,
) -> None:
    existing = [
        {
            "run_id": "older-success",
            "status": "SUCCESS",
            "completed_at": "2026-08-20T08:00:00+02:00",
        },
        {
            "run_id": "newer-failure",
            "status": "FAILED",
            "completed_at": "2026-08-21T08:00:00+02:00",
        },
        {
            "run_id": "n8n-execution:execution-42",
            "status": status,
            "completed_at": "2026-08-21T09:00:00+02:00",
        },
    ]
    result = _run_error_classifier(_trigger("failure"), existing)
    assert result["should_record"] is False
    expected_success = (
        "2026-08-20T08:00:00+02:00" if status == "FAILED" else "2026-08-21T09:00:00+02:00"
    )
    assert result["diagnostics"]["last_success_at"] == expected_success


@pytest.mark.parametrize("custom_context", [False, True])
def test_error_workflow_uses_failed_source_execution_not_retry_or_handler_identity(
    custom_context: bool,
) -> None:
    existing = [
        {
            "run_id": "n8n-execution:original-41",
            "status": "SUCCESS",
            "completed_at": "2026-09-05T12:00:00Z",
        }
    ]
    trigger = _trigger(
        "synthetic retry failure", execution_id="retry-42", retry_of="original-41"
    )
    if custom_context:
        trigger["execution"]["executionContext"] = {"run_id": "synthetic-wrong-context"}
        trigger["execution"]["error"]["context"] = {"run_id": "synthetic-wrong-error"}
        trigger["error"] = {"context": {"run_id": "synthetic-wrong-top-level"}}
    result = _run_error_classifier(trigger, existing)

    assert result["row"]["run_id"] == "n8n-execution:retry-42"
    assert result["diagnostics"]["execution_id"] == "retry-42"
    assert result["should_record"] is True
    persisted = {row["run_id"]: row for row in existing}
    persisted[result["row"]["run_id"]] = result["row"]
    assert persisted["n8n-execution:original-41"]["status"] == "SUCCESS"
    assert persisted["n8n-execution:retry-42"]["status"] == "FAILED"


@pytest.mark.parametrize("source_id", [None, "", 42, False, [], {}, ["42"]])
def test_error_workflow_refuses_unsupported_source_execution_identity(source_id: Any) -> None:
    # n8n documents a string ID; other JSON types are defensive malformed inputs.
    trigger = _trigger("synthetic-sensitive-message")
    trigger["execution"]["id"] = source_id
    _assert_source_identity_rejected(trigger)


@pytest.mark.parametrize("missing", ["id", "execution", "trigger_failure"])
def test_error_workflow_refuses_missing_source_execution_identity(missing: str) -> None:
    trigger = _trigger("synthetic failure")
    if missing == "id":
        del trigger["execution"]["id"]
    else:
        del trigger["execution"]
    if missing == "trigger_failure":
        # Documented trigger failures need not contain an execution at all.
        trigger["trigger"] = {"error": {"message": "synthetic-sensitive-message"}}
    _assert_source_identity_rejected(trigger)


def _assert_source_identity_rejected(trigger: dict[str, Any]) -> None:
    trigger["error"] = {"context": {"run_id": "synthetic-wrong-context"}}
    if "execution" in trigger:
        trigger["execution"].update(
            {"retryOf": "original-41", "executionContext": {"run_id": "synthetic-wrong-context"}}
        )
    with pytest.raises(subprocess.CalledProcessError) as error:
        _run_error_classifier(trigger, [])
    assert error.value.stderr == "SOURCE_EXECUTION_ID_UNAVAILABLE"
    assert error.value.stdout == ""


def test_recorded_failure_replay_selects_no_additional_terminal_write() -> None:
    trigger = _trigger("synthetic failure", "Upsert Current Positions")
    first = _run_error_classifier(trigger, [])
    assert first["should_record"] is True
    selected = _run_code_node(
        _load(ERROR_PATH),
        "Select Failure Row",
        named_rows={"Prepare Sanitized Failure": [first]},
        input_rows=[first],
    )
    assert selected == [{"json": first["row"]}]
    replay = _run_error_classifier(trigger, [selected[0]["json"]])
    assert replay["should_record"] is False


@pytest.mark.parametrize("step", ["Read Current Positions", "synthetic-sensitive-node"])
def test_failure_output_does_not_leak_sensitive_error_fields(step: str) -> None:
    trigger = _trigger("synthetic-sensitive-message", step)
    trigger["execution"]["error"].update(
        {
            "description": "synthetic-sensitive-description",
            "stack": "synthetic-sensitive-stack",
            "name": "synthetic-sensitive-error-name",
        }
    )
    result = _run_error_classifier(trigger, [])
    assert "synthetic-sensitive" not in json.dumps(result)
    assert result["diagnostics"]["failing_step"] == (
        step if step == "Read Current Positions" else "Unknown step"
    )
    financial_columns = (
        "gross_assets_eur", "liabilities_eur", "net_worth_eur",
        "previous_net_worth_eur", "net_worth_change_pct",
    )
    assert all(result["row"][column] is None for column in financial_columns)
    write = _node(_load(ERROR_PATH), "Record Operational Failure")["parameters"]
    assert write["columns"]["mappingMode"] == "autoMapInputData"
    assert write["options"]["cellFormat"] == "RAW"
    assert write["options"]["allowEmptyValues"] is True
    assert not write["options"].get("useAppend", False)


def test_error_terminal_write_is_only_reachable_through_new_failure_branch() -> None:
    workflow = _load(ERROR_PATH)
    condition = _node(workflow, "Failure Is New")["parameters"]["conditions"]
    assert len(condition["conditions"]) == 1
    assert condition["conditions"][0]["leftValue"] == "={{ $json.should_record }}"
    assert condition["conditions"][0]["operator"] == {
        "type": "boolean", "operation": "true", "singleValue": True,
    }
    edges = {
        (source, branch, edge["node"])
        for source, outputs in workflow["connections"].items()
        for branch, connections in enumerate(outputs["main"])
        for edge in connections
    }
    assert edges == {
        ("Workflow Error Trigger", 0, "Fetch Operational Schema"),
        ("Fetch Operational Schema", 0, "Read Sync Runs"),
        ("Read Sync Runs", 0, "Prepare Sanitized Failure"),
        ("Prepare Sanitized Failure", 0, "Failure Is New"),
        ("Failure Is New", 0, "Select Failure Row"),
        ("Select Failure Row", 0, "Record Operational Failure"),
    }
    write = _node(workflow, "Record Operational Failure")["parameters"]
    assert write["operation"] == "appendOrUpdate"
    assert write["columns"]["matchingColumns"] == ["run_id"]


def test_compose_defines_persistent_local_operational_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "n8n_data:/home/node/.n8n" in compose
    assert "schema-server:" in compose
    assert "http://schema-server/google-sheets-schema.json" in compose
    assert "127.0.0.1:${N8N_PORT:-5678}:5678" in compose
    assert "EXECUTIONS_TIMEOUT_MAX" in compose
