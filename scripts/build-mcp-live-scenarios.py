#!/usr/bin/env python3
"""Build inactive, credential-free workflows for an authorized disposable Sheets test."""

import argparse
import asyncio
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "finary-bridge"), str(ROOT / "finary-bridge/tests")]
from app.services.mcp_snapshot_service import McpSnapshotService
from mcp_wire import SyntheticWire


def build(workbook_id, stage):
    if stage not in {"interrupt", "null", "known", "clear"}:
        raise ValueError("Unknown acceptance stage")
    schema = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
    workflow = json.loads((ROOT / "n8n/workflows/finary-mcp-sync.json").read_text())
    wire = SyntheticWire()
    amount = "123.123456789012345678901234" if stage == "known" else None
    wire.values["holdings"]["data"][0]["attributes"]["current_value"] = amount
    value = asyncio.run(
        McpSnapshotService(
            wire.client(), clock=lambda: datetime.now(timezone.utc)
        ).snapshot()
    ).model_dump()
    workflow.update(
        id="mcp-live-" + stage, name="MCP Live Test - " + stage, active=False
    )
    schedule = [
        n["name"]
        for n in workflow["nodes"]
        if n["type"] == "n8n-nodes-base.scheduleTrigger"
    ]
    workflow["nodes"] = [n for n in workflow["nodes"] if n["name"] not in schedule]
    for name in schedule:
        workflow["connections"].pop(name, None)
    for node in workflow["nodes"]:
        node.pop("credentials", None)
        if node["name"] == "Initialize MCP Run":
            code = node["parameters"]["jsCode"]
            code = code.replace(
                "$env.FINARY_MCP_GOOGLE_SHEET_ID", json.dumps(workbook_id)
            )
            code = code.replace("$env.FINARY_MCP_WRITER_ID", "'synthetic-live-writer'")
            node["parameters"]["jsCode"] = code.replace(
                "$env.FINARY_MCP_WRITER_GENERATION", "'1'"
            )
        if node["type"] == "n8n-nodes-base.httpRequest":
            data = schema if node["name"] == "Fetch MCP Schema" else value
            node["type"] = "n8n-nodes-base.code"
            node["typeVersion"] = 2
            node["parameters"] = {
                "jsCode": "return [{json:{statusCode:200,body:"
                + json.dumps(data)
                + "}}];"
            }
    if stage == "interrupt":
        stop = {
            "id": "synthetic-stop",
            "name": "Stop After First Real Write",
            "type": "n8n-nodes-base.stopAndError",
            "typeVersion": 1,
            "position": [0, 500],
            "parameters": {"errorMessage": "EXPECTED_SYNTHETIC_INTERRUPTION"},
        }
        workflow["nodes"].append(stop)
        workflow["connections"]["Write accounts_current"]["main"][0] = [
            {"node": stop["name"], "type": "main", "index": 0}
        ]
    return deepcopy(workflow)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.workbook_id.strip():
        parser.error("A disposable workbook ID is required")
    args.output.write_text(
        json.dumps(
            [
                build(args.workbook_id, stage)
                for stage in ("interrupt", "null", "known", "clear")
            ]
        )
    )
    print('{"status":"INACTIVE_SYNTHETIC_WORKFLOWS_BUILT","count":4}')
