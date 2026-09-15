"""Timestamp parity at native, normalized, exported writer and retained boundaries."""

import subprocess
from copy import deepcopy
from datetime import timedelta

import pytest
from mcp_snapshots import NOW, snapshot
from mcp_timestamps import TIMESTAMPS
from mcp_wire import connection_wire
from mcp_workbooks import book_for_consumer, prepare, readback

from app.mcp_client import McpFailure
from app.mcp_consumer import select
from app.mcp_models import McpSnapshotV1
from app.mcp_validation import validate


@pytest.mark.parametrize("value,accepted", TIMESTAMPS)
def test_python_timestamp_contract(value, accepted):
    if accepted:
        validate("timestamp", value)
    else:
        with pytest.raises(ValueError, match="MCP contract validation failed"):
            validate("timestamp", value)


@pytest.mark.parametrize("value,accepted", TIMESTAMPS)
def test_exported_snapshot_timestamp_contract(value, accepted):
    normalized = snapshot(connection_wire(None))
    normalized["connections"][0]["last_sync_at"] = value
    if accepted or value is None:
        prepare(normalized)
    else:
        with pytest.raises(subprocess.CalledProcessError) as failed:
            prepare(normalized)
        assert failed.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize("value", ["20260910T12:00:00Z", "2026-09-10T12:00:00,5Z"])
def test_native_unsupported_timestamp_is_rejected(value):
    with pytest.raises(McpFailure) as failed:
        snapshot(connection_wire(value))
    assert failed.value.code == "MCP_MALFORMED_RESPONSE"


def test_hour_24_is_independently_rejected_by_writer():
    normalized = snapshot(connection_wire(None))
    normalized["connections"][0]["last_sync_at"] = "2026-09-10T24:00:00Z"
    with pytest.raises(ValueError):
        McpSnapshotV1.model_validate(normalized)
    with pytest.raises(subprocess.CalledProcessError) as failed:
        book_for_consumer(normalized)
    assert failed.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize("value", [v for v, accepted in TIMESTAMPS if accepted] + [None])
def test_valid_service_writer_reader_round_trip(value):
    normalized = snapshot(connection_wire(value), now=NOW.replace(microsecond=123456))
    assert normalized["connections"][0]["last_successful_sync_at"] == value
    book = book_for_consumer(normalized, now=NOW + timedelta(seconds=1))
    assert select(readback(book), now=NOW + timedelta(minutes=1))
    invalid = deepcopy(book)
    invalid["source_connections"][0]["last_sync_at"] = "2026-09-10T24:00:00Z"
    with pytest.raises(ValueError):
        select(readback(invalid), now=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("value,accepted", TIMESTAMPS)
def test_nullable_connection_model_and_retained_row(value, accepted):
    from app.mcp_models import McpConnection
    from app.mcp_workbook import validate_row

    normalized = {
        "connection_key": "synthetic-connection",
        "institution_key": None,
        "institution_label": None,
        "source_status": None,
        "last_sync_at": value,
        "last_successful_sync_at": None,
        "freshness": "UNKNOWN",
    }
    if accepted or value is None:
        McpConnection.model_validate(normalized)
    else:
        with pytest.raises(ValueError):
            McpConnection.model_validate(normalized)
    row = {
        **normalized,
        "row_key": "synthetic-row",
        "run_id": "n8n-run:synthetic:e6b3bb25-660e-4c9f-9a9a-38279419059f",
        "observation_id": "e6b3bb25-660e-4c9f-9a9a-38279419059f",
    }
    # Empty native cells retain the workbook's documented unknown/null meaning.
    if accepted or value is None or value == "":
        assert validate_row("source_connections", row)["last_sync_at"] == (
            None if value == "" else value
        )
    else:
        with pytest.raises(ValueError):
            validate_row("source_connections", row)


@pytest.mark.parametrize(
    "value",
    [
        "20260910T12:00:00Z",
        "2026-09-10T12:00:00,5Z",
        "2026-09-10T24:00:00Z",
        "2026-09-10T12:00:00.123456Z",
    ],
)
def test_native_timestamp_api_boundary(value, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from app.main import app, get_authenticated_mcp_client

    wire = connection_wire(value)
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "synthetic-local")
    app.dependency_overrides[get_authenticated_mcp_client] = wire.client
    try:
        response = TestClient(app).get("/v1/snapshot", headers={"X-API-Key": "synthetic-local"})
    finally:
        app.dependency_overrides.clear()
    if value.endswith(".123456Z"):
        assert response.status_code == 200
        normalized = response.json()
        assert normalized["connections"][0]["last_successful_sync_at"] == value
        assert prepare(normalized)["Prepare MCP Rows"][0]["snapshot"] == normalized
    else:
        assert response.status_code == 502
        assert response.json() == {
            "error": {
                "code": "MCP_MALFORMED_RESPONSE",
                "message": "Finary MCP response validation failed",
                "retryable": False,
            }
        }
        assert value not in response.text + caplog.text


@pytest.mark.parametrize(
    "value,accepted",
    [
        ("20260910T12:00:00Z", False),
        ("2026-09-10T12:00:00,5Z", False),
        ("2026-09-10T24:00:00Z", False),
        (None, False),
        ("2026-09-10T12:00:00.123456-05:30", True),
    ],
)
def test_optional_goal_creation_uses_timestamp_contract(value, accepted):
    import asyncio

    from mcp_wire import SyntheticWire

    from app.mcp_optional import OptionalMcpService

    wire = SyntheticWire()
    wire.values["goals"]["goals"][0]["created_at"] = value
    if accepted:
        result = asyncio.run(OptionalMcpService(wire.client()).goals(NOW))
        assert result.goals[0].created_at == value
    else:
        with pytest.raises(McpFailure) as failed:
            asyncio.run(OptionalMcpService(wire.client()).goals(NOW))
        assert failed.value.code == "MCP_MALFORMED_RESPONSE"
    assert not any(name in {"get_portfolio_overview", "holdings"} for name, _ in wire.calls)


@pytest.mark.parametrize(
    "state,table,field,value",
    [
        ("unselected", "source_connections", "last_sync_at", "2026-09-10T24:00:00Z"),
        ("unselected", "observations", "generated_at", "20260911T08:00:00Z"),
        ("failed", "source_connections", "last_successful_sync_at", "2026-09-10T24:00:00Z"),
        ("failed", "sync_runs", "completed_at", "2026-09-11T08:00:00,5Z"),
    ],
)
def test_entire_retained_inventory_rejects_malformed_timestamps(state, table, field, value):
    from mcp_workbooks import book_with_two_observations, partial_book

    source = snapshot(connection_wire(None))
    book = (
        book_with_two_observations(source)
        if state == "unselected"
        else partial_book(source, tables=("source_connections",))
    )
    if state == "unselected":
        book["sync_runs"][1]["completed_at"] = "2026-09-11T08:00:01Z"
    assert select(readback(book), now=NOW + timedelta(minutes=1))
    assert prepare(book=book, execution="timestamp-next")
    index = -1 if state == "failed" and table == "sync_runs" else 0
    book[table][index][field] = value
    with pytest.raises(ValueError):
        select(readback(book), now=NOW + timedelta(minutes=1))
    with pytest.raises(subprocess.CalledProcessError) as failed:
        prepare(book=book, execution="timestamp-next")
    assert failed.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "start,end,generated,business_date,accepted",
    [
        (
            "2026-09-11T08:00:00.000002Z",
            "2026-09-11T08:00:00.000001Z",
            "2026-09-11T08:00:00.000003Z",
            "2026-09-11",
            False,
        ),
        (
            "2026-09-11T08:00:00Z",
            "2026-09-11T08:00:00.000002Z",
            "2026-09-11T08:00:00.000001Z",
            "2026-09-11",
            False,
        ),
        (
            "2026-09-11T08:00:00Z",
            "2026-09-11T08:03:00.000001Z",
            "2026-09-11T08:03:00.000001Z",
            "2026-09-11",
            False,
        ),
        (
            "2026-09-10T23:59:59.999999+02:00",
            "2026-09-10T22:00:00Z",
            "2026-09-10T17:00:00.000001-05:00",
            "2026-09-11",
            True,
        ),
        (
            "2026-09-10T21:59:59.999998Z",
            "2026-09-10T21:59:59.999999Z",
            "2026-09-10T21:59:59.999999Z",
            "2026-09-10",
            True,
        ),
    ],
)
def test_collection_instants_preserve_microseconds_and_paris_date(
    start, end, generated, business_date, accepted
):
    normalized = snapshot()
    normalized["provenance"].update(collection_started_at=start, collection_ended_at=end)
    normalized.update(generated_at=generated, snapshot_date=business_date)
    if accepted:
        McpSnapshotV1.model_validate(normalized)
        book = book_for_consumer(normalized)
        assert select(readback(book), now=NOW + timedelta(minutes=1))
        assert book["observations"][0]["generated_at"] == generated
    else:
        with pytest.raises(ValueError):
            McpSnapshotV1.model_validate(normalized)
        with pytest.raises(subprocess.CalledProcessError) as failed:
            prepare(normalized)
        assert failed.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize("equivalent", [False, True])
def test_submillisecond_completion_selection_and_series(equivalent):
    from mcp_workbooks import book_with_two_observations

    book = book_with_two_observations()
    first, second = book["sync_runs"]
    first["completed_at"] = "2026-09-11T10:00:00.000001+02:00"
    second["completed_at"] = (
        "2026-09-11T03:00:00.000001-05:00" if equivalent else "2026-09-11T03:00:00.000002-05:00"
    )
    for _ in range(2):
        if equivalent:
            with pytest.raises(ValueError):
                select(readback(book), now=NOW + timedelta(minutes=1))
        else:
            selected = select(readback(book), now=NOW + timedelta(minutes=1))
            assert selected["context"]["run_id"] == second["run_id"]
        prepared = prepare(book=book, execution="timestamp-next")["Prepare MCP Rows"][0]
        assert prepared["batches"]["sync_runs"][0]["series_break"] is equivalent
        book["sync_runs"].reverse()


@pytest.mark.parametrize(
    "stage", ["Prepare MCP Rows", "Select source_connections", "Finalize MCP Success"]
)
def test_rechecks_reject_timestamp_corruption_after_initial_validation(stage):
    from mcp_artifacts import WORKFLOW
    from n8n_code import _run_code_node

    named = prepare(snapshot(connection_wire(None)))
    if stage == "Prepare MCP Rows":
        row = named["Validate MCP Snapshot"][0]["snapshot"]["connections"][0]
    else:
        row = named["Prepare MCP Rows"][0]["batches"]["source_connections"][0]
    row["last_sync_at"] = "2026-09-10T24:00:00Z"
    with pytest.raises(subprocess.CalledProcessError) as failed:
        _run_code_node(WORKFLOW, stage, named_rows=named, input_rows=[{}], execution_id="mcp-test")
    assert failed.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "age,expected",
    [
        (timedelta(hours=48), "FRESH"),
        (timedelta(hours=48, microseconds=1), "STALE"),
        (timedelta(microseconds=-1), "UNKNOWN"),
    ],
)
def test_source_freshness_keeps_microsecond_boundary(age, expected):
    normalized = snapshot(connection_wire((NOW - age).isoformat()))
    assert normalized["connections"][0]["freshness"] == expected
