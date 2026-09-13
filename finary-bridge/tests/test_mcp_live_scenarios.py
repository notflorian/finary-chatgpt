"""Live-test exports retain production validation and real Sheets writers."""

import importlib.util
from pathlib import Path

import pytest
from test_mcp_workflow import SCHEMA, WORKFLOW, empty_book, prepare

spec = importlib.util.spec_from_file_location(
    "live_scenarios", Path(__file__).parents[2] / "scripts/build-mcp-live-scenarios.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize("stage", ["interrupt", "null", "known", "clear"])
def test_synthetic_live_workflows_preserve_production_writers(stage):
    result = builder.build("synthetic-disposable-book", stage)
    assert not result["active"]
    assert not any(
        n["type"] in {"n8n-nodes-base.httpRequest", "n8n-nodes-base.scheduleTrigger"}
        for n in result["nodes"]
    )
    for node in result["nodes"]:
        assert "credentials" not in node
        if node["type"] == "n8n-nodes-base.googleSheets":
            assert node == next(n for n in WORKFLOW["nodes"] if n["name"] == node["name"])
    if stage == "interrupt":
        assert (
            result["connections"]["Write accounts_current"]["main"][0][0]["node"]
            == "Stop After First Real Write"
        )
    book = empty_book()
    book["writer_control"][0]["writer_id"] = "synthetic-live-writer"
    fetch = next(n for n in result["nodes"] if n["name"] == "Fetch MCP Snapshot")
    import json

    payload = json.loads(fetch["parameters"]["jsCode"].split("body:", 1)[1].removesuffix("}}];"))
    prepared = prepare(payload, book, workflow=result)["Prepare MCP Rows"][0]
    assert prepared["batches"]["positions_current"][0]["mcp_current_value_amount"] == (
        "123.123456789012345678901234" if stage == "known" else None
    )
    assert set(prepared["batches"]) <= set(SCHEMA["sheets"])
