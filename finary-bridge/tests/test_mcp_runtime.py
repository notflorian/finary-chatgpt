"""Real pinned engine and installed Sheets connector with synthetic I/O only."""

from copy import deepcopy
from datetime import timedelta

import pytest
from mcp_wire import SyntheticWire
from test_mcp_integration import NOW, snapshot
from test_mcp_workflow import SCHEMA, WORKFLOW, empty_book, prepare, writes
from test_n8n_zero_position_runtime import _execute, _output
from test_n8n_zero_position_runtime import runtime_image as runtime_image
from test_sheets_connector_runtime import connector as connector

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
    assert terminal["liabilities_current_expected_count"] == ""
    if mode == "normal":
        assert (
            _output(data, "Write positions_current")[0]["mcp_current_value_amount"]
            == precise_amount
        )


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
        assert current["mcp_current_value_amount"] == ("" if amount is None else amount)
        assert current["mcp_current_value_amount_eur"] == ("" if amount is None else amount)
        assert current["is_active"] is True
        assert book["portfolio_members"][-1]["reported_net_worth_amount"] == "-20"
        accepted = observation(book, book["sync_runs"][-1], now=NOW + timedelta(minutes=1))
        assert accepted["current_complete"]
    assert len(book["portfolio_daily"]) == 3 and len(book["positions_history"]) == 3
    assert any(
        u["column"] == "mcp_current_value_amount" and u["value"] == "" for u in result["updates"]
    )
    assert connector(SCHEMA, book, emitted)["workbook"] == book


def test_native_full_precision_through_installed_connector_and_consumer(connector):
    from test_mcp_precision import precise_wire

    amount = "123456789012345678901234." + "1" * 64
    value = snapshot(precise_wire(amount))
    result = connector(SCHEMA, empty_book(), writes(prepare(value)))
    book = result["workbook"]
    assert book["positions_current"][0]["mcp_current_value_amount"] == amount
    assert book["accounts_current"][0]["mcp_native_balance_amount"] == amount
    accepted = observation(book, book["sync_runs"][-1], now=NOW + timedelta(minutes=1))
    assert accepted["current_complete"]


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
