"""Synthetic inputs for every exported Sheets serialization boundary."""

import json

from test_n8n_workflow import _headers, _run_code_node
from test_n8n_workflow_v2 import V2_ERROR_PATH, _node
from test_operations import _run_error_classifier, _trigger
from test_sync_completion import _prepare

NOW = "2026-09-07T06:30:00Z"
EXECUTION_ID = "7200"
WRITERS = {
    "Select Account Rows": ("Upsert Current Accounts", "account_rows"),
    "Select Position Rows": ("Upsert Current Positions", "position_rows"),
    "Select Liability Rows": ("Upsert Current Liabilities", "liability_rows"),
    "Select History Rows": ("Upsert Position History", "history_rows"),
    "Select Daily Row": ("Upsert Portfolio Daily", "daily_rows"),
    "Select Success Run": ("Record Successful Sync", "sync_run_rows"),
    "Prepare Failed Run": ("Record Failed Sync", None),
    "Select Failure Row": ("Record Operational Failure", None),
}


def boundary_cases(workflow, schema):
    named = _prepare(
        workflow, schema, execution_id=EXECUTION_ID, start=NOW, prepared_at=NOW,
    )
    prepared = named["Prepare Validated Rows"][0]
    cases = {}
    for selector, (writer, batch) in WRITERS.items():
        if batch:
            cases[selector] = {
                "workflow": workflow, "named": named, "raw": prepared[batch],
                "path": f"namedRows['Prepare Validated Rows'][0].{batch}[0]",
                "node": _node(workflow, writer),
            }
    context = _run_code_node(
        workflow, "Validate Snapshot", execution_id=EXECUTION_ID, now=NOW,
        named_rows={
            "Initialize Run": [named["Validate Snapshot"][0]["run"]],
            "Fetch Canonical Schema": [{"body": schema}],
        }, input_rows=[{"body": {"invalid": True}}],
    )[0]["json"]
    assert context["can_write"] is False
    cases["Prepare Failed Run"] = {
        "workflow": workflow,
        "named": {"Validate Snapshot": [context],
                  "Preflight Failure Sync Header": [_headers(schema, "sync_runs")]},
        "node": _node(workflow, "Record Failed Sync"),
        "path": "namedRows['Validate Snapshot'][0].run",
    }
    error = json.loads(V2_ERROR_PATH.read_text())
    failure = _run_error_classifier(_trigger("synthetic failure", execution_id=EXECUTION_ID), [])
    cases["Select Failure Row"] = {
        "workflow": error, "named": {"Prepare Sanitized Failure": [failure]},
        "raw": [failure["row"]], "path": "namedRows['Prepare Sanitized Failure'][0].row",
        "node": _node(error, "Record Operational Failure"),
    }
    return cases


def outgoing(selector, case, *, setup_js=""):
    return [item["json"] for item in _run_code_node(
        case["workflow"], selector, named_rows=case["named"], input_rows=[{}],
        execution_id=EXECUTION_ID, now=NOW, setup_js=setup_js,
    )]
