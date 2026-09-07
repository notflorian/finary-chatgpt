"""Run the exported graph in Compose-pinned n8n with synthetic external I/O.

No production credentials, network, session files, containers or volumes are
used. Code/If nodes and connections are unchanged, including read continuation,
row fan-out, identity and terminal finalization. These are engine executions,
not the workbook simulator or a reimplementation of n8n scheduling.
"""

import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_n8n_workflow_v2 import (
    _apply_prepared_writes,
    _empty_workbook,
    _known_eur_snapshot,
    _prepare_for_run,
    _upsert,
)
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_zero_positions import NOW, zero_snapshot
from workbook_consumer import select_assets, select_liabilities

ROOT = Path(__file__).parents[2]
WRITES = {
    "Upsert Current Accounts": "accounts_current",
    "Upsert Current Positions": "positions_current",
    "Upsert Current Liabilities": "liabilities_current",
    "Upsert Position History": "positions_history",
    "Upsert Portfolio Daily": "portfolio_daily",
    "Record Successful Sync": "sync_runs",
    "Record Failed Sync": "sync_runs",
}


@pytest.fixture(scope="module")
def runtime_image():
    image = re.search(r"image: (n8nio/n8n:[^\s]+)", (ROOT / "docker-compose.yml").read_text())[1]
    assert image.startswith("n8nio/n8n:2.35.5@sha256:")
    required = os.environ.get("FINARY_REQUIRE_N8N_RUNTIME") == "1"
    if shutil.which("docker"):
        check = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=15
        )
        if check.returncode == 0:
            return image
    if required:
        pytest.fail("Compose-pinned n8n Docker runtime is required but unavailable")
    pytest.skip("Compose-pinned n8n Docker runtime unavailable; required in isolated CI")


def _substitute_io(workflow, schema, snapshot, workbook, *, fail_at=None):
    exported = deepcopy(workflow)
    exported["id"] = "SyntheticZeroPositions58"
    exported["name"] = "Synthetic issue 58 runtime regression"
    exported["settings"].pop("errorWorkflow", None)
    for node in exported["nodes"]:
        kind = node["type"]
        if kind not in {"n8n-nodes-base.httpRequest", "n8n-nodes-base.googleSheets"}:
            continue
        name = node["name"]
        if kind == "n8n-nodes-base.httpRequest":
            value = schema if name == "Fetch Canonical Schema" else snapshot
            code = f"return [{{json: {{statusCode: 200, body: {json.dumps(value)}}}}}];"
        elif name in WRITES:
            # Keep the real retry policy and fail closed when its attempts exhaust.
            code = (
                "throw new Error('SYNTHETIC_WRITE_FAILURE');"
                if name == fail_at
                else (
                    "const items = $input.all();\n"
                    "if (!items.length || items.some(item => !Object.keys(item.json).length)) "
                    "throw new Error('SYNTHETIC_EMPTY_WRITE');\nreturn items;"
                )
            )
        else:
            sheet = node["parameters"]["sheetName"]["value"]
            if name.startswith("Preflight"):
                rows = [
                    {
                        column["name"]: column["name"]
                        for column in schema["sheets"][sheet]["columns"]
                    }
                ]
            else:
                rows = workbook.get(sheet, [])
            # Empty reads really emit zero items; n8n must apply alwaysOutputData.
            code = f"return {json.dumps(rows)}.map(json => ({{json}}));"
        node["type"] = "n8n-nodes-base.code"
        node["typeVersion"] = 2
        node["parameters"] = {"mode": "runOnceForAllItems", "jsCode": code}
    return exported


def _execute(tmp_path, image, exported):
    fixture = tmp_path / "workflow.json"
    fixture.write_text(json.dumps(exported))
    # n8n persists a genuine execution ID in an ephemeral SQLite database.
    container_name = f"finary-issue58-{uuid4().hex}"
    command = [
        "docker",
        "run",
        "--name",
        container_name,
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "-e",
        "N8N_USER_FOLDER=/tmp/n8n-synthetic",
        "-e",
        "N8N_DIAGNOSTICS_ENABLED=false",
        "-e",
        "N8N_ENCRYPTION_KEY=synthetic-runtime-only-key",
        "-e",
        "N8N_PERSONALIZATION_ENABLED=false",
        "-e",
        "N8N_LOG_LEVEL=info",
        "--mount",
        f"type=bind,src={fixture},dst=/tmp/workflow.json,readonly",
        "--entrypoint",
        "sh",
        image,
        "-c",
        "n8n import:workflow --input=/tmp/workflow.json >/tmp/import.log 2>&1 "
        "&& n8n execute --id=SyntheticZeroPositions58 --rawOutput",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=150)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=15)
    # CLI logs can surround rawOutput, and failed executions also contain runData.
    for match in re.finditer(r"(?m)^\{", result.stdout):
        try:
            execution, _ = json.JSONDecoder().raw_decode(result.stdout[match.start() :])
        except json.JSONDecodeError:
            continue
        if "resultData" in execution.get("data", {}):
            return execution
    pytest.fail(f"No n8n execution evidence: {result.stdout[-4000:]} {result.stderr[-2000:]}")


def _output(run_data, name):
    calls = run_data[name]
    assert len(calls) == 1, f"Duplicate execution: {name}"
    return [item["json"] for item in calls[0]["data"]["main"][0]]


def _assert_success(execution, exported, schema, book, *, zero, coverage):
    result = execution["data"]["resultData"]
    assert not result.get("error"), result.get("error")
    run_data = result["runData"]
    prepared = _output(run_data, "Prepare Validated Rows")[0]
    expected = ["Upsert Current Accounts"]
    if prepared["position_rows"]:
        expected.append("Upsert Current Positions")
    if prepared["liability_rows"]:
        expected.append("Upsert Current Liabilities")
    if prepared["history_rows"]:
        expected.append("Upsert Position History")
    expected.extend(["Upsert Portfolio Daily", "Record Successful Sync"])
    actual = sorted(
        (name for name in WRITES if name in run_data),
        key=lambda name: run_data[name][0]["executionIndex"],
    )
    assert actual == expected
    for name in expected:
        rows = _output(run_data, name)
        assert rows and all(rows)  # No placeholder holding or empty Sheets item.
        sheet = WRITES[name]
        book[sheet] = _upsert(book[sheet], rows, schema["sheets"][sheet]["unique_key"])
    terminal = _output(run_data, "Record Successful Sync")[0]
    origin = _output(run_data, "Initialize Run")[0]
    assert terminal["run_id"] == origin["run_id"]
    assert terminal["run_id"].startswith("n8n-execution:")
    completed = datetime.fromisoformat(terminal["completed_at"].replace("Z", "+00:00"))
    assert terminal["duration_ms"] == max(
        0, completed.timestamp() * 1000 - origin["started_epoch_ms"]
    )
    for name in expected[:-1]:
        call = run_data[name][0]
        assert completed.timestamp() * 1000 >= call["startTime"] + call["executionTime"]
        assert call["executionIndex"] < run_data["Select Success Run"][0]["executionIndex"]
    assert terminal["positions_count"] == (0 if zero else 2)
    assert terminal["liability_coverage"] == coverage
    assert terminal["status"] == prepared["sync_run_rows"][0]["status"]
    assert terminal["status"] in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
    for node in exported["nodes"]:
        if node["name"].startswith("Read "):
            assert node["executeOnce"] and node["alwaysOutputData"]
            assert len(run_data[node["name"]]) == 1
    state = select_assets(book, now=NOW)
    assert state.current_complete and state.source == "current"
    assert len(state.positions) == terminal["positions_count"]
    if zero:
        assert state.positions == state.history == []
        assert state.daily["gross_assets_eur"] == 100
    return run_data


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("coverage", ["COMPLETE", "PARTIAL", "UNAVAILABLE"])
def test_runtime_zero_branches(runtime_image, tmp_path, workflow, schema, populated, coverage):
    book = _empty_workbook()
    if populated:
        prepared = _prepare_for_run(
            workflow, schema, _known_eur_snapshot("2026-08-20T07:30:00+02:00"), book, "populated"
        )
        _apply_prepared_writes(schema, book, prepared)
    before = deepcopy(book)
    exported = _substitute_io(workflow, schema, zero_snapshot(coverage), book)
    execution = _execute(tmp_path, runtime_image, exported)
    data = _assert_success(execution, exported, schema, book, zero=True, coverage=coverage)
    assert "Select History Rows" not in data and "Upsert Position History" not in data
    assert book["positions_history"] == before["positions_history"]
    assert book["positions_current"] == [
        {**row, "is_active": False} for row in before["positions_current"]
    ]
    if not populated:
        assert "Select Position Rows" not in data
        assert _output(data, "Read Current Positions") == [{}]
        assert book["positions_current"] == []
    if coverage != "COMPLETE":
        assert book["liabilities_current"] == before["liabilities_current"]
        assert select_liabilities(book).complete is populated
    else:
        assert select_liabilities(book).liabilities_eur == 0


@pytest.mark.parametrize(
    "fail_at",
    [
        None,
        "Upsert Current Accounts",
        "Upsert Current Positions",
        "Upsert Current Liabilities",
        "Upsert Position History",
        "Upsert Portfolio Daily",
    ],
)
def test_runtime_nonempty_and_write_failure(runtime_image, tmp_path, workflow, schema, fail_at):
    book = _empty_workbook()
    exported = _substitute_io(
        workflow, schema, _known_eur_snapshot("2026-08-20T07:30:00+02:00"), book, fail_at=fail_at
    )
    execution = _execute(tmp_path, runtime_image, exported)
    if fail_at is None:
        _assert_success(execution, exported, schema, book, zero=False, coverage="COMPLETE")
    else:
        result = execution["data"]["resultData"]
        assert "SYNTHETIC_WRITE_FAILURE" in result["error"]["message"]
        assert fail_at in result["runData"]
        assert "Select Success Run" not in result["runData"]
        assert "Record Successful Sync" not in result["runData"]


def test_runtime_unproven_empty_never_writes_portfolio(runtime_image, tmp_path, workflow, schema):
    snapshot = zero_snapshot()
    del snapshot["coverage"]["position_collections"]
    exported = _substitute_io(workflow, schema, snapshot, _empty_workbook())
    execution = _execute(tmp_path, runtime_image, exported)
    data = execution["data"]["resultData"]["runData"]
    assert [name for name in WRITES if name in data] == ["Record Failed Sync"]
    terminal = _output(data, "Record Failed Sync")[0]
    assert terminal["status"] == "FAILED"
    assert terminal["positions_count"] is None


def test_runtime_repeated_zero_run_keeps_keys_and_terminal_unique(
    runtime_image,
    tmp_path,
    workflow,
    schema,
):
    book = _empty_workbook()
    snapshot = zero_snapshot("COMPLETE")
    for _ in range(2):
        exported = _substitute_io(workflow, schema, snapshot, book)
        execution = _execute(tmp_path, runtime_image, exported)
        _assert_success(execution, exported, schema, book, zero=True, coverage="COMPLETE")
        # Each fresh isolated database uses the same real execution ID, testing
        # an identical execution-key upsert as well as empty input on the rerun.
        assert len(book["sync_runs"]) == len(book["portfolio_daily"]) == 1
        assert book["positions_current"] == book["positions_history"] == []


def test_runtime_zero_daily_failure_blocks_terminal(runtime_image, tmp_path, workflow, schema):
    exported = _substitute_io(
        workflow, schema, zero_snapshot(), _empty_workbook(), fail_at="Upsert Portfolio Daily"
    )
    result = _execute(tmp_path, runtime_image, exported)["data"]["resultData"]
    assert "SYNTHETIC_WRITE_FAILURE" in result["error"]["message"]
    assert "Upsert Portfolio Daily" in result["runData"]
    assert "Upsert Position History" not in result["runData"]
    assert "Record Successful Sync" not in result["runData"]


@pytest.mark.parametrize(
    "case", ["account-name", "account-currency", "position-class", "liability-name"]
)
def test_runtime_required_snapshot_fields_never_reach_portfolio(
    runtime_image, tmp_path, workflow, schema, case,
):
    snapshot = _known_eur_snapshot("2026-08-20T07:30:00+02:00")
    if case == "account-name":
        del snapshot["accounts"][0]["name"]
    elif case == "account-currency":
        snapshot["accounts"][0]["currency"] = "EURO"
    elif case == "position-class":
        del snapshot["positions"][0]["asset_class"]
    else:
        snapshot["liabilities"][0]["name"] = None
    exported = _substitute_io(workflow, schema, snapshot, _empty_workbook())
    data = _execute(tmp_path, runtime_image, exported)["data"]["resultData"]["runData"]
    assert [name for name in WRITES if name in data] == ["Record Failed Sync"]
    assert "Prepare Validated Rows" not in data
    terminal = _output(data, "Record Failed Sync")[0]
    assert terminal["status"] == "FAILED" and terminal["positions_count"] is None
    assert terminal["error_code"] == "SNAPSHOT_VALIDATION_FAILED"
    assert len(terminal["error_message"]) < 180


@pytest.mark.parametrize(
    "case", ["retained-required-cell", "late-history-undefined", "late-daily-enum"]
)
def test_runtime_prepared_contract_blocks_the_first_portfolio_write(
    runtime_image, tmp_path, workflow, schema, case,
):
    from test_prewrite_validation import mutated_preparation

    book = _empty_workbook()
    snapshot = _known_eur_snapshot("2026-08-20T07:30:00+02:00")
    if case == "retained-required-cell":
        initial = _prepare_for_run(workflow, schema, snapshot, book, "synthetic-before")
        _apply_prepared_writes(schema, book, initial)
        book["liabilities_current"][0]["name"] = None
        snapshot = zero_snapshot("COMPLETE")
        expected_path = "liabilities_current.name"
    else:
        mutation = (
            "prepared.history_rows[0].name = undefined;"
            if case == "late-history-undefined"
            else "prepared.daily_rows[0].liability_coverage = 'invalid';"
        )
        # Controlled output fault only. The complete snapshot, real gate and
        # graph remain intact; an input-only validator cannot catch this.
        workflow = mutated_preparation(workflow, mutation)
        expected_path = (
            "positions_history.name" if case == "late-history-undefined"
            else "portfolio_daily.liability_coverage"
        )
    exported = _substitute_io(workflow, schema, snapshot, book)
    result = _execute(tmp_path, runtime_image, exported)["data"]["resultData"]
    # The n8n runner splits Error("CODE:path") into description and message.
    assert result["error"]["description"] == "CONTRACT_VALIDATION_FAILED"
    assert result["error"]["message"].startswith(expected_path + " [line ")
    data = result["runData"]
    assert _output(data, "Validate Snapshot")[0]["can_write"] is True
    assert "Prepare Validated Rows" in data
    assert not any(name in data for name in WRITES)
    assert "Select Account Rows" not in data
    assert "Select Success Run" not in data
