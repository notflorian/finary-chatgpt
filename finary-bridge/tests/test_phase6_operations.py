"""Structural and executable checks for Phase 6 operations."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

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
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to execute n8n Code node tests")
    workflow = _load(ERROR_PATH)
    schema = _load(SCHEMA_PATH)
    code = _node(workflow, "Prepare Sanitized Failure")["parameters"]["jsCode"]
    named = {
        "Workflow Error Trigger": [trigger],
        "Fetch Operational Schema": [{"statusCode": 200, "data": json.dumps(schema)}],
    }
    harness = f"""
const namedRows = {json.dumps(named)};
const inputRows = {json.dumps(existing)};
const $ = (name) => ({{ first: () => ({{ json: (namedRows[name] || [{{}}])[0] }}) }});
const $input = {{ all: () => inputRows.map((json) => ({{ json }})) }};
(async () => {{
{code}
}})().then((result) => process.stdout.write(JSON.stringify(result))).catch((error) => {{
  process.stderr.write(String(error && error.message ? error.message : error));
  process.exit(2);
}});
"""
    completed = subprocess.run(  # noqa: S603
        ["node", "-e", harness], check=True, capture_output=True, text=True
    )
    return json.loads(completed.stdout)[0]["json"]


def _trigger(message: str, step: str = "Read Current Positions") -> dict[str, Any]:
    return {
        "execution": {
            "id": "execution-42",
            "error": {"message": message, "stack": "private stack"},
            "lastNodeExecuted": step,
            "mode": "trigger",
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


def test_terminal_run_is_never_overwritten_and_last_success_ignores_failures() -> None:
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
            "status": "FAILED",
            "completed_at": "2026-08-21T09:00:00+02:00",
        },
    ]
    result = _run_error_classifier(_trigger("failure"), existing)
    assert result["should_record"] is False
    assert result["diagnostics"]["last_success_at"] == ("2026-08-20T08:00:00+02:00")


def test_compose_defines_persistent_local_operational_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "n8n_data:/home/node/.n8n" in compose
    assert "schema-server:" in compose
    assert "http://schema-server/google-sheets-schema.json" in compose
    assert "127.0.0.1:${N8N_PORT:-5678}:5678" in compose
    assert "EXECUTIONS_TIMEOUT_MAX" in compose
