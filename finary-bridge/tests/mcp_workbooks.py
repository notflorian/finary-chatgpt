"""Fresh inventories and actual exported Code-node execution for workbook tests.

These helpers produce Code-node evidence; engine/connector evidence belongs to
n8n_runtime and sheets_connector. Every returned workbook and batch is independent.
"""

from copy import deepcopy
from datetime import timedelta

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


def writes(named, execution="mcp-test", *, now=NOW):
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
        now=now.isoformat(),
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


def book_for_consumer(value=None, *, now=NOW):
    book = empty_book()
    for write in writes(prepare(value, book=book), now=now):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    return book


def book_with_rowless_failures():
    """Retain valid distinct FAILED terminals without any associated portfolio rows."""
    book = book_for_consumer()
    execution = "failed-first"
    first = failure(prepare(book=book, execution=execution), book, execution=execution)[0]
    second = {
        **deepcopy(first),
        "run_id": "n8n-run:failed-second:00000000-0000-4000-8000-000000000099",
        "observation_id": "00000000-0000-4000-8000-000000000098",
    }
    book["sync_runs"] += [first, second]
    return book


def book_with_two_observations(value=None, next_value=None):
    book = book_for_consumer(value)
    for write in writes(prepare(next_value, book=book, execution="next"), execution="next"):
        table = write["node"]["parameters"]["sheetName"]["value"]
        key = SCHEMA["sheets"][table]["unique_key"]
        for row in write["rows"]:
            book[table] = [r for r in book[table] if r[key] != row[key]] + [row]
    return book


def book_with_retained_observations(count):
    """Build bounded retained history without repeatedly invoking the JS writer."""
    assert count >= 1
    source = book_for_consumer()
    original_terminal = source["sync_runs"][0]
    original_run = original_terminal["run_id"]
    original_observation = original_terminal["observation_id"]
    book = empty_book()

    def identity(index):
        suffix = f"{index + 1:012x}"
        observation_id = f"00000000-0000-4000-8000-{suffix}"
        run_id = f"n8n-run:retained-{index}:00000000-0000-4000-8000-{suffix}"
        return run_id, observation_id

    def replace_identity(value, run_id, observation_id):
        if isinstance(value, str):
            return value.replace(original_run, run_id).replace(
                original_observation, observation_id
            )
        if isinstance(value, dict):
            return {
                key: replace_identity(item, run_id, observation_id)
                for key, item in value.items()
            }
        return value

    retained_tables = [
        table
        for table in source
        if table
        not in {
            "README",
            "writer_control",
            "allocation_targets",
            "asset_overrides",
            "cashflows",
        }
    ]
    for index in range(count):
        run_id, observation_id = identity(index)
        for table in retained_tables:
            if table.endswith("_current") and index != count - 1:
                continue
            for original in source[table]:
                row = replace_identity(deepcopy(original), run_id, observation_id)
                if table == "sync_runs":
                    completed = NOW + timedelta(microseconds=index)
                    row["completed_at"] = completed.isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    )
                book[table].append(row)
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
