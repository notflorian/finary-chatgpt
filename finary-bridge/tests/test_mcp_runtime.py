"""Real pinned engine and installed Sheets connector with synthetic I/O only."""

import subprocess
from copy import deepcopy
from datetime import timedelta

import pytest
from mcp_artifacts import SCHEMA, WORKFLOW
from mcp_snapshots import NOW, snapshot
from mcp_wire import SyntheticWire
from mcp_workbooks import empty_book, prepare, readback, writes
from n8n_runtime import _execute, _output
from n8n_runtime import runtime_image as runtime_image
from sheets_connector import connector as connector

from app.mcp_consumer import observation


def substitute(value, book, fail_at=None):
    import json

    workflow = deepcopy(WORKFLOW)
    workflow["id"] = "SyntheticMcpIntegration"
    for node in workflow["nodes"]:
        if node["type"] not in {"n8n-nodes-base.httpRequest", "n8n-nodes-base.googleSheets"}:
            continue
        if node["type"] == "n8n-nodes-base.httpRequest":
            data = SCHEMA if node["name"] == "Fetch MCP Schema" else value
            code = "return [{json:{statusCode:200,body:" + json.dumps(data) + "}}];"
        elif node["parameters"].get("operation") == "appendOrUpdate":
            code = (
                "throw new Error('SYNTHETIC_WRITE_FAILURE');"
                if node["name"] == fail_at
                else "return $input.all();"
            )
        else:
            table = node["parameters"]["sheetName"]["value"]
            data = (
                [{c["name"]: c["name"] for c in SCHEMA["sheets"][table]["columns"]}]
                if (node["name"].startswith("Preflight ") or node["name"].endswith(" Header"))
                else book[table]
            )
            code = "return " + json.dumps(data) + ".map(json=>({json}));"
        node["type"] = "n8n-nodes-base.code"
        node["typeVersion"] = 2
        node["parameters"] = {"mode": "runOnceForAllItems", "jsCode": code}
    return workflow


@pytest.mark.parametrize("mode", ["normal", "empty", "unsupported", "malformed", "write_failure"])
def test_real_engine_control_flow(runtime_image, tmp_path, mode):
    wire = SyntheticWire()
    precise_amount = "1." + "1" * 64
    if mode == "normal":
        wire.values["accounts"]["data"][0]["attributes"]["balance"] = precise_amount
        wire.values["accounts"]["data"][0]["attributes"]["full_value_eur"] = precise_amount
        wire.values["holdings"]["data"][0]["attributes"]["current_value"] = precise_amount
    if mode == "empty":
        wire.values["holdings"]["data"] = []
    if mode == "unsupported":
        wire.values["holdings"]["data"][0]["type"] = "future-holdings"
    value = snapshot(wire)
    if mode == "malformed":
        value["members"][0]["reported_net_worth"]["currency"] = "USD"
    workflow = substitute(
        value, empty_book(), "Write portfolio_members" if mode == "write_failure" else None
    )
    execution = _execute(
        tmp_path,
        runtime_image,
        workflow,
        environment={
            "FINARY_MCP_WRITER_ID": "synthetic-writer",
            "FINARY_MCP_WRITER_GENERATION": "1",
            "FINARY_MCP_GOOGLE_SHEET_ID": "synthetic-book",
            "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
        },
    )
    result = execution["data"]["resultData"]
    data = result["runData"]
    if mode in {"malformed", "write_failure"}:
        assert "Record MCP Success" not in data
        assert _output(data, "Record MCP Failure")[0]["status"] == "FAILED"
        if mode == "malformed":
            assert not any(name.startswith("Write ") for name in data)
        return
    assert not result.get("error"), result.get("error")
    terminal = _output(data, "Record MCP Success")[0]
    assert terminal["run_id"] == _output(data, "Initialize MCP Run")[0]["run_id"]
    for name in data:
        if name.startswith("Write "):
            rows = _output(data, name)
            assert rows and all(rows)
            assert (
                data[name][0]["executionIndex"] < data["Finalize MCP Success"][0]["executionIndex"]
            )
        if name.startswith("Read "):
            assert len(data[name]) == 1
    if mode in {"empty", "unsupported"}:
        assert "Write positions_current" not in data
        assert "Write positions_history" not in data
    assert terminal["positions_current_expected_count"] == (
        "" if mode == "unsupported" else 0 if mode == "empty" else 1
    )
    assert "liabilities_current_expected_count" not in terminal
    if mode == "normal":
        assert _output(data, "Write positions_current")[0]["current_value_amount"] == precise_amount


def test_native_fixture_null_known_null_through_installed_connector(connector):
    book = empty_book()
    for index, amount in enumerate((None, "0", None)):
        wire = SyntheticWire()
        wire.values["holdings"]["data"][0]["attributes"]["current_value"] = amount
        value = snapshot(wire)
        named = prepare(value, book, execution=f"mcp-{index}")
        emitted = writes(named, execution=f"mcp-{index}")
        result = connector(SCHEMA, book, emitted)
        book = result["workbook"]
        current = book["positions_current"][0]
        assert current["current_value_amount"] == ("" if amount is None else amount)
        assert current["current_value_amount_eur"] == ("" if amount is None else amount)
        assert current["is_active"] is True
        assert book["portfolio_members"][-1]["reported_net_worth_amount"] == "-20"
        accepted = observation(
            readback(book), book["sync_runs"][-1], now=NOW + timedelta(minutes=1)
        )
        assert accepted["current_complete"]
    assert len(book["portfolio_daily"]) == 3 and len(book["positions_history"]) == 3
    assert any(
        u["column"] == "current_value_amount" and u["value"] == "" for u in result["updates"]
    )
    assert connector(SCHEMA, book, emitted)["workbook"] == book


def test_native_full_precision_through_installed_connector_and_consumer(connector):
    from mcp_wire import precise_wire

    amount = "123456789012345678901234." + "1" * 64
    value = snapshot(precise_wire(amount))
    result = connector(SCHEMA, empty_book(), writes(prepare(value)))
    book = result["workbook"]
    assert book["positions_current"][0]["current_value_amount"] == amount
    assert book["accounts_current"][0]["native_balance_amount"] == amount
    accepted = observation(readback(book), book["sync_runs"][-1], now=NOW + timedelta(minutes=1))
    assert accepted["current_complete"]


def test_installed_reads_preserve_manual_formulas_and_reject_automated_formulas(connector):
    book = empty_book()
    book["asset_overrides"] = [
        {
            "override_key": "exact",
            "source_asset_id": snapshot()["positions"][0]["source_asset_id"],
            "custom_asset_class": "CRYPTO",
            "notes": "=1+2",
            "enabled": True,
        }
    ]
    read_nodes = [n for n in WORKFLOW["nodes"] if n["name"].startswith("Read ")]
    read_rows = connector(SCHEMA, book, [], read_nodes)["reads"]
    assert read_rows["asset_overrides"][0]["notes"] == "=1+2"
    named = prepare(snapshot(), read_rows)
    assert (
        named["Prepare MCP Rows"][0]["batches"]["positions_current"][0]["asset_class"] == "CRYPTO"
    )
    book = connector(SCHEMA, book, writes(named))["workbook"]
    book["positions_current"][0]["current_value_amount"] = "=1+2"
    read_rows = connector(SCHEMA, book, [], read_nodes)["reads"]
    with pytest.raises(subprocess.CalledProcessError) as rejected:
        prepare(snapshot(), read_rows, execution="next-run")
    assert rejected.value.stderr == "MCP_VALIDATION_FAILED"


@pytest.mark.parametrize("all_responses_lost", [False, True])
def test_native_terminal_response_loss_preserves_finalized_identity(
    runtime_image, tmp_path, all_responses_lost
):
    workflow = substitute(snapshot(), empty_book())
    terminal = next(n for n in workflow["nodes"] if n["name"] == "Record MCP Success")
    terminal["parameters"]["jsCode"] = """
const fs=require('fs'),path='/tmp/mcp-synthetic-terminal.json';
const payload=JSON.stringify($input.all());
if(!fs.existsSync(path)){
  fs.writeFileSync(path,payload,{mode:0o600});
  throw new Error('SYNTHETIC_RESPONSE_LOSS');
}
if(fs.readFileSync(path,'utf8')!==payload)throw new Error('CHANGED_FINALIZED_PAYLOAD');
""" + (
        "throw new Error('SYNTHETIC_RESPONSE_LOSS');"
        if all_responses_lost
        else "return $input.all();"
    )
    if all_responses_lost:
        node = next(n for n in workflow["nodes"] if n["name"] == "Failure Terminal Read")
        node["parameters"]["jsCode"] = (
            "return JSON.parse(require('fs').readFileSync("
            "'/tmp/mcp-synthetic-terminal.json','utf8'));"
        )
    execution = _execute(
        tmp_path,
        runtime_image,
        workflow,
        allow_file_io=True,
        environment={
            "FINARY_MCP_WRITER_ID": "synthetic-writer",
            "FINARY_MCP_WRITER_GENERATION": "1",
            "FINARY_MCP_GOOGLE_SHEET_ID": "synthetic-book",
            "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
        },
    )
    result = execution["data"]["resultData"]
    assert not result.get("error")
    data = result["runData"]
    assert "Record MCP Failure" not in data
    if all_responses_lost:
        assert _output(data, "Finalize MCP Failure") == []
    else:
        assert (
            _output(data, "Record MCP Success")[0]["run_id"]
            == _output(data, "Initialize MCP Run")[0]["run_id"]
        )


def test_native_restored_execution_number_gets_new_uuid(runtime_image, tmp_path):
    identifiers = []
    book = empty_book()
    for index in range(2):
        directory = tmp_path / str(index)
        directory.mkdir()
        execution = _execute(
            directory,
            runtime_image,
            substitute(snapshot(), book),
            environment={
                "FINARY_MCP_WRITER_ID": "synthetic-writer",
                "FINARY_MCP_WRITER_GENERATION": "1",
                "FINARY_MCP_GOOGLE_SHEET_ID": "synthetic-book",
                "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
            },
        )
        result = execution["data"]["resultData"]
        assert not result.get("error")
        data = result["runData"]
        identifiers.append(_output(data, "Record MCP Success")[0]["run_id"])
        for node in WORKFLOW["nodes"]:
            name = node["name"]
            if name not in data or not (name.startswith("Write ") or name == "Record MCP Success"):
                continue
            table = node["parameters"]["sheetName"]["value"]
            key = SCHEMA["sheets"][table]["unique_key"]
            for row in _output(data, name):
                book[table] = [r for r in book[table] if r[key] != row[key]] + [row]
    assert identifiers[0].split(":")[1] == identifiers[1].split(":")[1] == "1"
    assert identifiers[0] != identifiers[1]
    assert len(book["positions_history"]) == len(book["portfolio_daily"]) == 2


def test_native_http_nodes_deliver_text_body_to_exported_validator(runtime_image, tmp_path):
    value = snapshot()
    workflow = substitute(value, empty_book())
    native_nodes = {n["name"]: n for n in WORKFLOW["nodes"]}
    for index, node in enumerate(workflow["nodes"]):
        if node["name"] not in {"Fetch MCP Schema", "Fetch MCP Snapshot"}:
            continue
        node = deepcopy(native_nodes[node["name"]])
        path = "/schema" if node["name"] == "Fetch MCP Schema" else "/snapshot"
        node["parameters"]["url"] = "http://127.0.0.1:8766" + path
        workflow["nodes"][index] = node
    execution = _execute(
        tmp_path,
        runtime_image,
        workflow,
        http_payloads={"/schema": SCHEMA, "/snapshot": value},
        environment={
            "FINARY_MCP_WRITER_ID": "synthetic-writer",
            "FINARY_MCP_WRITER_GENERATION": "1",
            "FINARY_MCP_GOOGLE_SHEET_ID": "synthetic-book",
            "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
        },
    )
    data = execution["data"]["resultData"]["runData"]
    for name in ("Fetch MCP Schema", "Fetch MCP Snapshot"):
        response = _output(data, name)[0]
        assert response["statusCode"] == 200
        assert isinstance(response["body"], str)
        assert "data" not in response
    assert _output(data, "Validate MCP Snapshot")[0]["snapshot"] == value
    assert _output(data, "Record MCP Success")[0]["status"] in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}


def engine_run(runtime_image, tmp_path, value, book, *, fail_at=None, mutate=None):
    workflow = substitute(value, book, fail_at)
    if mutate:
        mutate(workflow)
    return _execute(
        tmp_path,
        runtime_image,
        workflow,
        environment={
            "FINARY_MCP_WRITER_ID": "synthetic-writer",
            "FINARY_MCP_WRITER_GENERATION": "1",
            "FINARY_MCP_GOOGLE_SHEET_ID": "synthetic-book",
            "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
        },
    )["data"]["resultData"]


def connector_writes(data):
    return [
        {"node": node, "rows": _output(data, node["name"])}
        for node in WORKFLOW["nodes"]
        if node["name"] in data
        and (
            node["name"].startswith("Write ")
            or node["name"] in {"Record MCP Success", "Record MCP Failure"}
        )
    ]


@pytest.mark.parametrize("empty", [False, True])
def test_initializer_bridge_engine_connector_consumer_round_trip(
    runtime_image, connector, tmp_path, empty
):
    from fastapi.testclient import TestClient

    from app.main import app, get_authenticated_mcp_client
    from app.mcp_workbook import google_create, initialize, native_inventory

    initialized = native_inventory(google_create(initialize("synthetic-writer", 1)))
    initialized["sheets"]["writer_control"]["rows"][0]["state"] = "ACTIVE"
    book = {name: sheet["rows"] for name, sheet in initialized["sheets"].items()}
    wire = SyntheticWire()
    if empty:
        wire.values["holdings"]["data"] = []
    app.dependency_overrides[get_authenticated_mcp_client] = lambda: wire.client()
    try:
        response = TestClient(app).get("/v3/snapshot")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    read_nodes = [n for n in WORKFLOW["nodes"] if n["name"].startswith("Read ")]
    physical = connector(SCHEMA, book, [], read_nodes)["reads"]
    result = engine_run(runtime_image, tmp_path, response.json(), physical)
    assert not result.get("error")
    data = result["runData"]
    applied = connector(SCHEMA, book, connector_writes(data))["workbook"]
    for name, rows in applied.items():
        initialized["sheets"][name]["rows"] = rows
    from datetime import UTC, datetime

    from app.mcp_consumer import select

    accepted = select(initialized, now=datetime.now(UTC))
    assert accepted["current_complete"]
    assert accepted["overview"]["gross_assets"]["amount"] == "1000.00"
    assert accepted["accounts"][0]["native_balance"]["amount"] == "250.00"
    if empty:
        assert accepted["positions"] == []
        assert "Write positions_current" not in data and "Write positions_history" not in data
    else:
        assert accepted["positions"][0]["current_value"]["amount"] == "90.00"
    assert accepted["accounts"][0]["direct_owners_value_eur"] == "375.00"
    assert [name for name, _ in wire.calls] == ["get_portfolio_overview", "accounts", "holdings"]


def test_runtime_populated_empty_repeated_and_partial_preserves_manual(
    runtime_image, connector, tmp_path
):
    book = empty_book()
    book["allocation_targets"] = [
        {
            "target_key": "target",
            "asset_class": "OTHER",
            "target_pct": 0.75,
            "min_pct": 0.5,
            "max_pct": 1,
            "notes": "=1+2",
            "enabled": False,
        }
    ]
    book["cashflows"] = [
        {
            "cashflow_key": "flow",
            "date": "2026-09-11",
            "account_key": "mcp:account:assets:synthetic-a",
            "amount_eur": 0,
            "type": "TRANSFER",
            "notes": "=1+2",
            "source": "manual",
        }
    ]
    book["asset_overrides"] = [
        {
            "override_key": "exact",
            "source_asset_id": snapshot()["positions"][0]["source_asset_id"],
            "custom_asset_class": "CRYPTO",
            "notes": "=1+2",
            "enabled": True,
        }
    ]
    manual = {table: deepcopy(book[table]) for table in SCHEMA["manual_sheets"]}
    original = None
    for index, mode in enumerate(["populated", "partial", "empty", "empty"]):
        wire = SyntheticWire()
        if mode == "empty":
            wire.values["holdings"]["data"] = []
        if mode == "partial":
            wire.values["holdings"]["data"][0]["type"] = "future-holdings"
        directory = tmp_path / str(index)
        directory.mkdir()
        result = engine_run(runtime_image, directory, snapshot(wire), book)
        assert not result.get("error")
        data = result["runData"]
        book = connector(SCHEMA, book, connector_writes(data))["workbook"]
        assert {table: book[table] for table in SCHEMA["manual_sheets"]} == manual
        current = book["positions_current"][0]
        assert current["asset_class"] == "CRYPTO"
        if original is None:
            original = deepcopy(current)
        if mode == "partial":
            assert current == original
            assert "Write positions_current" not in data and "Write positions_history" not in data
        if mode == "empty":
            if index == 3:
                assert "Write positions_current" not in data
                assert _output(data, "Continue positions_current") == [
                    {"completed_table": "positions_current"}
                ]
            assert current == {**original, "is_active": False}
            assert "Write positions_history" not in data
            accepted = observation(
                readback(book), book["sync_runs"][-1], now=NOW + timedelta(days=10)
            )
            assert accepted["current_complete"] and accepted["positions"] == []
        assert _output(data, "Continue positions_history") == [
            {"completed_table": "positions_history"}
        ]
    assert len(book["positions_history"]) == 1
    assert len(book["portfolio_daily"]) == len(book["sync_runs"]) == 4


def test_runtime_exhausted_retry_then_valid_recovery(runtime_image, connector, tmp_path):
    book = empty_book()
    book["cashflows"] = [
        {
            "cashflow_key": "recovery-flow",
            "date": "2026-09-11",
            "account_key": "mcp:account:assets:synthetic-a",
            "amount_eur": 0,
            "type": "TRANSFER",
            "notes": "=1+2",
            "source": "manual",
        }
    ]
    manual = {table: deepcopy(book[table]) for table in SCHEMA["manual_sheets"]}
    for index, fail_at in enumerate(["Write portfolio_members", None]):
        directory = tmp_path / str(index)
        directory.mkdir()
        result = engine_run(runtime_image, directory, snapshot(), book, fail_at=fail_at)
        data = result["runData"]
        emitted = [write for write in connector_writes(data) if write["node"]["name"] != fail_at]
        book = connector(SCHEMA, book, emitted)["workbook"]
        if fail_at:
            assert "Record MCP Success" not in data
            assert book["sync_runs"][-1]["status"] == "FAILED"
            assert (
                book["sync_runs"][-1]["error_message"]
                == "The MCP synchronization failed. Validate the workbook before retrying."
            )
            assert book["accounts_current"] and not book["portfolio_members"]
            assert (
                book["sync_runs"][-1]["observation_id"]
                == book["accounts_current"][0]["observation_id"]
            )
        else:
            assert not result.get("error")
            accepted = observation(
                readback(book), book["sync_runs"][-1], now=NOW + timedelta(days=10)
            )
            assert accepted["current_complete"]
        assert {table: book[table] for table in SCHEMA["manual_sheets"]} == manual
    assert len(book["sync_runs"]) == 2


@pytest.mark.parametrize(
    "mode", ["later_batch", "changed_execution", "changed_generation", "paused", "missing_header"]
)
def test_runtime_invalid_batches_and_control_block_success(runtime_image, tmp_path, mode):
    def mutate(workflow):
        if mode == "later_batch":
            node = next(n for n in workflow["nodes"] if n["name"] == "Prepare MCP Rows")
            marker = "mcpPrepared(snapshot,run,prepared,existing,existing.asset_overrides);"
            assert marker in node["parameters"]["jsCode"]
            node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
                marker,
                "prepared.batches.portfolio_members[0].reported_net_worth_amount='broken';\n"
                + marker,
            )
        elif mode == "changed_execution":
            node = next(n for n in workflow["nodes"] if n["name"] == "Finalize MCP Success")
            node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
                "mcpRun(run,String($execution.id));", "mcpRun(run,'different-execution');"
            )
        elif mode in {"changed_generation", "paused"}:
            node = next(
                n
                for n in workflow["nodes"]
                if n["name"]
                == (
                    "Recheck Writer Control"
                    if mode == "changed_generation"
                    else "Read writer_control"
                )
            )
            node["parameters"]["jsCode"] = (
                node["parameters"]["jsCode"].replace('"generation": 1', '"generation": 2')
                if mode == "changed_generation"
                else node["parameters"]["jsCode"].replace('"state": "ACTIVE"', '"state": "PAUSED"')
            )
        else:
            node = next(n for n in workflow["nodes"] if n["name"] == "Preflight positions_history")
            node["parameters"]["jsCode"] = "return [{json:{wrong:'wrong'}}];"

    result = engine_run(runtime_image, tmp_path, snapshot(), empty_book(), mutate=mutate)
    data = result["runData"]
    assert "Record MCP Success" not in data
    if mode in {"later_batch", "paused", "missing_header"}:
        assert not any(name.startswith("Write ") for name in data)


@pytest.mark.parametrize("mode", ["orphan", "manual_formula", "manual_duplicate"])
def test_runtime_inventory_rejection_precedes_first_portfolio_write(
    runtime_image, connector, tmp_path, mode
):
    from mcp_inputs import manual_rows
    from mcp_workbooks import book_for_consumer

    book = book_for_consumer()
    if mode == "orphan":
        book["sync_runs"] = []
    else:
        book["cashflows"] = [manual_rows()["cashflows"]]
        if mode == "manual_formula":
            book["cashflows"][0]["amount_eur"] = "=1+2"
        else:
            book["cashflows"] *= 2
    original = deepcopy(book)
    reads = [n for n in WORKFLOW["nodes"] if n["name"].startswith("Read ")]
    physical = connector(SCHEMA, book, [], reads)["reads"]
    result = engine_run(runtime_image, tmp_path, snapshot(), physical)
    data = result["runData"]
    assert not any(name.startswith("Write ") for name in data)
    assert "Record MCP Success" not in data
    assert _output(data, "Record MCP Failure")[0]["status"] == "FAILED"
    assert book == original
