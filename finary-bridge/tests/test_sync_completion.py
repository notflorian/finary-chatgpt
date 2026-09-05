"""Deterministic terminal timing checks against the exported Code nodes."""

import json
import math
import subprocess
from copy import deepcopy
from datetime import datetime

import pytest
from test_n8n_workflow import _prepare_named_rows, _run_code_node
from test_n8n_workflow_v2 import (
    V2_SCHEMA_PATH,
    V2_WORKFLOW_PATH,
    _empty_workbook,
    _initialize_run,
    _known_eur_snapshot,
    _node,
    _upsert,
)
from workbook_consumer import latest_success


@pytest.fixture(scope="module")
def workflow():
    return json.loads(V2_WORKFLOW_PATH.read_text())


@pytest.fixture(scope="module")
def schema():
    return json.loads(V2_SCHEMA_PATH.read_text())


def _prepare(
    workflow,
    schema,
    *,
    execution_id="7101",
    start="2026-09-05T12:00:00Z",
    prepared_at="2026-09-05T12:00:10Z",
    snapshot=None,
):
    run = _initialize_run(workflow, execution_id=execution_id, now=start)
    snapshot = snapshot or _known_eur_snapshot(start)
    context = _run_code_node(
        workflow,
        "Validate Snapshot",
        named_rows={
            "Initialize Run": [run],
            "Fetch Canonical Schema": [{"statusCode": 200, "body": schema}],
        },
        input_rows=[{"statusCode": 200, "body": snapshot}],
        execution_id=execution_id,
        now=prepared_at,
    )[0]["json"]
    assert context["can_write"] is True
    named = _prepare_named_rows(schema, snapshot)
    named["Validate Snapshot"] = [context]
    prepared = _run_code_node(
        workflow,
        "Prepare Validated Rows",
        named_rows=named,
        input_rows=[{}],
        execution_id=execution_id,
        now=prepared_at,
    )[0]["json"]
    named["Prepare Validated Rows"] = [prepared]
    return named


def _finalize(workflow, named, *, execution_id="7101", now="2026-09-05T12:02:10Z"):
    return _run_code_node(
        workflow,
        "Select Success Run",
        named_rows=named,
        input_rows=[{}],
        execution_id=execution_id,
        now=now,
    )[0]["json"]


@pytest.mark.parametrize("warnings", [False, True], ids=["SUCCESS", "SUCCESS_WITH_WARNINGS"])
def test_delayed_terminal_finalization(workflow, schema, warnings):
    snapshot = _known_eur_snapshot("2026-09-05T11:59:00Z", first_value=None if warnings else 100)
    named = _prepare(workflow, schema, snapshot=snapshot)
    before = deepcopy(named["Prepare Validated Rows"][0])
    terminal = _finalize(workflow, named)
    assert terminal["completed_at"] == "2026-09-05T12:02:10.000Z"
    assert terminal["duration_ms"] == 130000
    assert terminal["status"] == ("SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS")
    assert terminal["warning_count"] == (1 if warnings else 0)
    assert terminal["error_message"] == ("PARTIAL_POSITION_EUR_COVERAGE" if warnings else None)
    columns = schema["sheets"]["sync_runs"]["columns"]
    assert list(terminal) == [column["name"] for column in columns]
    for column in columns:
        value = terminal[column["name"]]
        if value is None:
            assert column["nullable"]
        elif column["type"] == "NUMBER":
            assert isinstance(value, (int, float)) and math.isfinite(value)
        else:
            assert isinstance(value, str)
    assert named["Prepare Validated Rows"][0] == before
    assert datetime.fromisoformat(terminal["completed_at"]).utcoffset() is not None
    assert {
        **terminal,
        "completed_at": before["sync_run_rows"][0]["completed_at"],
        "duration_ms": before["sync_run_rows"][0]["duration_ms"],
    } == before["sync_run_rows"][0]


def test_reversed_finalization_order_uses_actual_terminal_instants(workflow, schema):
    # IDs intentionally sort in the opposite order to finalization.
    a = _prepare(workflow, schema, execution_id="100")
    b = _prepare(workflow, schema, execution_id="900", prepared_at="2026-09-05T12:00:20Z")
    assert (
        a["Prepare Validated Rows"][0]["sync_run_rows"][0]["completed_at"]
        < (b["Prepare Validated Rows"][0]["sync_run_rows"][0]["completed_at"])
    )
    terminal_b = _finalize(workflow, b, execution_id="900", now="2026-09-05T12:01:10Z")
    terminal_a = _finalize(workflow, a, execution_id="100", now="2026-09-05T12:02:10Z")
    assert terminal_b["duration_ms"] == 70000
    assert terminal_a["duration_ms"] == 130000
    assert datetime.fromisoformat(terminal_b["completed_at"]) < datetime.fromisoformat(
        terminal_a["completed_at"]
    )
    workbook = _empty_workbook()
    for rows in ([terminal_a, terminal_b], [terminal_b, terminal_a]):
        workbook["sync_runs"] = rows
        assert latest_success(workbook) == terminal_a


@pytest.mark.parametrize(
    ("start", "prepared_at", "completed_at", "expected_duration", "business_date"),
    [
        (
            "2026-09-05T23:59:50+02:00",
            "2026-09-05T23:59:55+02:00",
            "2026-09-06T00:02:00+02:00",
            130000,
            "2026-09-05",
        ),
        (
            "2026-03-29T01:59:50+01:00",
            "2026-03-29T01:59:55+01:00",
            "2026-03-29T03:02:00+02:00",
            130000,
            "2026-03-29",
        ),
        (
            "2026-10-25T02:59:50+02:00",
            "2026-10-25T02:59:55+02:00",
            "2026-10-25T02:02:00+01:00",
            130000,
            "2026-10-25",
        ),
        ("2026-09-05T12:00:00Z", "2026-09-05T12:00:10Z", "2026-09-05T11:59:59Z", 0, "2026-09-05"),
        (
            "2026-09-05T12:00:00.123Z",
            "2026-09-05T12:00:10Z",
            "2026-09-05T12:02:10.456Z",
            130333,
            "2026-09-05",
        ),
    ],
    ids=["midnight", "spring-forward", "fall-back", "backward-clock", "milliseconds"],
)
def test_epoch_duration_preserves_snapshot_dates(
    workflow,
    schema,
    start,
    prepared_at,
    completed_at,
    expected_duration,
    business_date,
):
    named = _prepare(workflow, schema, start=start, prepared_at=prepared_at)
    before = deepcopy(named["Prepare Validated Rows"][0])
    terminal = _finalize(workflow, named, now=completed_at)
    assert datetime.fromisoformat(terminal["completed_at"]) == datetime.fromisoformat(completed_at)
    assert terminal["duration_ms"] == expected_duration
    assert terminal["started_at"] == before["sync_run_rows"][0]["started_at"]
    assert before["daily_rows"][0]["snapshot_date"] == business_date
    assert {row["snapshot_date"] for row in before["history_rows"]} == {business_date}
    assert {row["generated_at"] for row in before["history_rows"]} == {start}
    assert named["Prepare Validated Rows"][0] == before


@pytest.mark.parametrize("stale", ["prepared", "origin", "both"])
def test_stale_identity_emits_no_success(workflow, schema, stale):
    named = _prepare(workflow, schema)
    if stale in {"prepared", "both"}:
        named["Prepare Validated Rows"][0]["sync_run_rows"][0]["run_id"] = "n8n-execution:old"
    if stale in {"origin", "both"}:
        named["Validate Snapshot"][0]["run"]["run_id"] = "n8n-execution:old"
    with pytest.raises(subprocess.CalledProcessError) as error:
        _finalize(workflow, named)
    assert error.value.stderr == "STALE_EXECUTION_IDENTITY"
    assert error.value.stdout == ""


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        True,
        "1788609600000",
        "invalid",
        [],
        {},
        float("nan"),
        float("inf"),
        -float("inf"),
        1e308,
        -1e308,
        "missing",
    ],
)
def test_invalid_timing_origin_emits_no_success(workflow, schema, invalid):
    named = _prepare(workflow, schema)
    run = named["Validate Snapshot"][0]["run"]
    if invalid == "missing":
        del run["started_epoch_ms"]
    else:
        run["started_epoch_ms"] = invalid
    with pytest.raises(subprocess.CalledProcessError) as error:
        _finalize(workflow, named)
    assert error.value.stderr == "INVALID_RUN_TIMING"
    assert error.value.stdout == ""


def test_invalid_completion_clock_emits_no_success(workflow, schema):
    named = _prepare(workflow, schema)
    with pytest.raises(subprocess.CalledProcessError) as error:
        _finalize(workflow, named, now="invalid")
    assert error.value.stderr == "INVALID_RUN_TIMING"
    assert error.value.stdout == ""


def test_terminal_write_retry_reuses_finalized_payload_and_upsert_key(workflow, schema):
    named = _prepare(workflow, schema)
    terminal = _finalize(workflow, named)
    record = _node(workflow, "Record Successful Sync")
    assert record["retryOnFail"] is True
    assert record["maxTries"] == 3
    assert record["waitBetweenTries"] == 5000
    assert record["parameters"]["operation"] == "appendOrUpdate"
    columns = record["parameters"]["columns"]
    assert columns["matchingColumns"] == ["run_id"]
    assert columns["mappingMode"] == "autoMapInputData"
    assert columns["value"] == {}
    assert "Date" not in json.dumps(record["parameters"])
    assert "Record Successful Sync" not in workflow["connections"]
    # The first response is lost after persistence. Retry only the Sheets node,
    # with its saved input; no Code node or clock runs again.
    persisted = _upsert([], [terminal], columns["matchingColumns"][0])
    retried = _upsert(persisted, [deepcopy(terminal)], columns["matchingColumns"][0])
    assert retried == persisted == [terminal]
    assert retried[0]["completed_at"] == "2026-09-05T12:02:10.000Z"
    assert retried[0]["duration_ms"] == 130000


def _walk_portfolio_path(workflow, named, *, fail_at=None):
    """Execute exported Code nodes/connections; mock Sheets success or exhaustion."""
    queue = ["Select Account Rows"]
    visited = []
    input_rows = [{}]
    terminal = []
    while queue:
        name = queue.pop(0)
        assert name not in visited, "Unexpected cycle or parallel convergence"
        visited.append(name)
        node = _node(workflow, name)
        output = 0
        if node["type"] == "n8n-nodes-base.googleSheets":
            assert node.get("continueOnFail", False) is False
            assert node.get("onError", "stopWorkflow") == "stopWorkflow"
            assert node["retryOnFail"] is True and node["maxTries"] == 3
            if name == fail_at:
                break  # All native retries failed: no normal output is emitted.
            if name == "Record Successful Sync":
                terminal.extend(input_rows)
        elif node["type"] == "n8n-nodes-base.if":
            condition = node["parameters"]["conditions"]["conditions"]
            assert len(condition) == 1
            assert condition[0]["leftValue"] == "={{ $json.has_rows }}"
            assert condition[0]["operator"]["operation"] == "true"
            output = 0 if input_rows[0]["has_rows"] else 1
        else:
            assert node["type"] == "n8n-nodes-base.code"
            items = _run_code_node(
                workflow,
                name,
                named_rows=named,
                input_rows=input_rows,
                execution_id="7101",
                now="2026-09-05T12:02:10Z",
            )
            input_rows = [item["json"] for item in items]
        connections = workflow["connections"].get(name, {}).get("main", [])
        if connections:
            queue.extend(edge["node"] for edge in connections[output])
    return visited, terminal


@pytest.mark.parametrize("coverage", ["COMPLETE", "PARTIAL", "UNAVAILABLE", "COMPLETE_EMPTY"])
def test_finalization_follows_every_required_write_and_stops_on_failure(workflow, schema, coverage):
    snapshot = _known_eur_snapshot("2026-09-05T12:00:00Z")
    if coverage != "COMPLETE":
        snapshot["coverage"]["liabilities"] = coverage.replace("_EMPTY", "")
        snapshot["liabilities"] = []
        snapshot["liabilities_eur"] = 0 if coverage == "COMPLETE_EMPTY" else None
        snapshot["net_worth_eur"] = (
            snapshot["gross_assets_eur"] if coverage == "COMPLETE_EMPTY" else None
        )
    named = _prepare(workflow, schema, snapshot=snapshot)
    expected = ["Upsert Current Accounts", "Upsert Current Positions"]
    if coverage == "COMPLETE":
        expected.append("Upsert Current Liabilities")
    expected.extend(["Upsert Position History", "Upsert Portfolio Daily", "Record Successful Sync"])
    visited, terminal = _walk_portfolio_path(workflow, named)
    assert [name for name in visited if name.startswith(("Upsert", "Record"))] == expected
    assert visited[-3:] == [
        "Upsert Portfolio Daily",
        "Select Success Run",
        "Record Successful Sync",
    ]
    assert terminal[0]["completed_at"] == "2026-09-05T12:02:10.000Z"
    assert terminal[0]["duration_ms"] == 130000
    for required_write in expected[:-1]:
        visited, terminal = _walk_portfolio_path(workflow, named, fail_at=required_write)
        assert terminal == []
        assert "Select Success Run" not in visited
        assert "Record Successful Sync" not in visited


def test_completion_fields_share_one_clock_read(workflow, schema):
    named = _prepare(workflow, schema)
    terminal = _run_code_node(
        workflow,
        "Select Success Run",
        named_rows=named,
        input_rows=[{}],
        execution_id="7101",
        now="2026-09-05T12:02:10Z",
        clock_step_ms=750,
    )[0]["json"]
    assert terminal["completed_at"] == "2026-09-05T12:02:10.000Z"
    assert terminal["duration_ms"] == 130000
