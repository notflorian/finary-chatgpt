"""Fresh inventories and actual exported Code-node execution for workbook tests.

These helpers produce Code-node evidence; engine/connector evidence belongs to
n8n_runtime and sheets_connector. Every returned workbook and batch is independent.
"""

from copy import deepcopy

from mcp_artifacts import SCHEMA, WORKFLOW
from mcp_snapshots import NOW, snapshot
from n8n_code import _run_code_node

from app.mcp_workbook import cell, google_create, initialize


def empty_book():
    inventory = initialize("synthetic-writer", 1)
    inventory["sheets"]["writer_control"]["rows"][0]["state"] = "ACTIVE"
    return {name: sheet["rows"] for name, sheet in inventory["sheets"].items()}


def readback(book):
    inventory = initialize("synthetic-writer", 1)
    for name, rows in book.items():
        inventory["sheets"][name]["rows"] = deepcopy(rows)
    return inventory


def prepare(value=None, book=None, execution="mcp-test", workflow=None):
    workflow = WORKFLOW if workflow is None else workflow
    book = empty_book() if book is None else deepcopy(book)
    named = {}
    run = _run_code_node(
        workflow,
        "Initialize MCP Run",
        named_rows={},
        input_rows=[{}],
        execution_id=execution,
        now=NOW.isoformat(),
        setup_js=(
            "const $env={FINARY_MCP_WRITER_ID:'synthetic-writer',"
            "FINARY_MCP_WRITER_GENERATION:'1',"
            "FINARY_MCP_GOOGLE_SHEET_ID:'synthetic-book'};"
        ),
    )[0]["json"]
    named["Initialize MCP Run"] = [run]
    named["Fetch MCP Schema"] = [{"statusCode": 200, "body": deepcopy(SCHEMA)}]
    named["Fetch MCP Snapshot"] = [
        {"statusCode": 200, "body": snapshot() if value is None else deepcopy(value)}
    ]
    named["Validate MCP Snapshot"] = [
        r["json"]
        for r in _run_code_node(
            workflow,
            "Validate MCP Snapshot",
            named_rows=named,
            input_rows=[{}],
            execution_id=execution,
        )
    ]
    for name in SCHEMA["sheets"]:
        named["Read " + name] = book[name] or [{}]
        named["Preflight " + name] = [
            {c["name"]: c["name"] for c in SCHEMA["sheets"][name]["columns"]}
        ]
    named["Prepare MCP Rows"] = [
        r["json"]
        for r in _run_code_node(
            workflow, "Prepare MCP Rows", named_rows=named, input_rows=[{}], execution_id=execution
        )
    ]
    named["Recheck Writer Control"] = book["writer_control"]
    named["Read MCP Terminal Before Success"] = book["sync_runs"] or [{}]
    return named


def writes(named, execution="mcp-test"):
    result = []
    for node in WORKFLOW["nodes"]:
        if node["name"].startswith("Write "):
            table = node["parameters"]["sheetName"]["value"]
            rows = _run_code_node(
                WORKFLOW,
                "Select " + table,
                named_rows=named,
                input_rows=[{}],
                execution_id=execution,
            )
            if rows:
                result.append({"node": deepcopy(node), "rows": [r["json"] for r in rows]})
    terminal = _run_code_node(
        WORKFLOW,
        "Finalize MCP Success",
        named_rows=named,
        input_rows=[{}],
        execution_id=execution,
        now=NOW.isoformat(),
    )
    result.append(
        {
            "node": deepcopy(
                next(n for n in WORKFLOW["nodes"] if n["name"] == "Record MCP Success")
            ),
            "rows": [r["json"] for r in terminal],
        }
    )
    return result


def failure(named, book, execution="mcp-test"):
    named = deepcopy(named)
    named["Failure Writer Control"] = book["writer_control"]
    named["Failure Terminal Header"] = [
        {c["name"]: c["name"] for c in SCHEMA["sheets"]["sync_runs"]["columns"]}
    ]
    named["Failure Terminal Read"] = book["sync_runs"] or [{}]
    return [
        item["json"]
        for item in _run_code_node(
            WORKFLOW,
            "Finalize MCP Failure",
            named_rows=named,
            input_rows=[{}],
            execution_id=execution,
            now=NOW.isoformat(),
        )
    ]


def book_for_consumer(value=None):
    book = empty_book()
    for write in writes(prepare(value, book=book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    return book


def book_with_two_observations(value=None, next_value=None):
    book = book_for_consumer(value)
    for write in writes(prepare(next_value, book=book, execution="next"), execution="next"):
        table = write["node"]["parameters"]["sheetName"]["value"]
        key = SCHEMA["sheets"][table]["unique_key"]
        for row in write["rows"]:
            book[table] = [r for r in book[table] if r[key] != row[key]] + [row]
    return book


def partial_book(value=None, tables=("source_warnings",)):
    book = book_for_consumer()
    named = prepare(value, book=book, execution="partial")
    for write in writes(named, execution="partial"):
        table = write["node"]["parameters"]["sheetName"]["value"]
        if table in tables:
            book[table] += write["rows"]
    book["sync_runs"] += failure(named, book, execution="partial")
    return book


def native_observation(book=None):
    book = book_for_consumer() if book is None else book
    native = google_create(initialize("synthetic-writer", 1))
    for sheet in native["sheets"]:
        name = sheet["properties"]["title"]
        grid = sheet["data"][0]["rowData"]
        headers = [v["userEnteredValue"]["stringValue"] for v in grid[0]["values"]]
        grid[1:] = [{"values": [cell(row.get(h)) for h in headers]} for row in book[name]]
    return native, book["sync_runs"][0]["run_id"]
