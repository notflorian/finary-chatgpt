"""Operational safety of the supported inactive writer export."""

from mcp_artifacts import SCHEMA, WORKFLOW


def test_read_and_write_boundaries():
    writers = []
    for node in WORKFLOW["nodes"]:
        assert "credentials" not in node
        if node["type"] != "n8n-nodes-base.googleSheets":
            continue
        assert node["retryOnFail"] and node["maxTries"] == 3
        assert node["waitBetweenTries"] == 5000
        table = node["parameters"]["sheetName"]["value"]
        if node["parameters"].get("operation") == "appendOrUpdate":
            writers.append(table)
            assert not node.get("executeOnce", False)
            assert table not in SCHEMA["manual_sheets"] + ["README", "writer_control"]
            assert node["parameters"]["options"] == {
                "cellFormat": "RAW",
                "handlingExtraData": "error",
                "allowEmptyValues": True,
            }
            assert node["parameters"]["columns"]["matchingColumns"] == [
                SCHEMA["sheets"][table]["unique_key"]
            ]
        else:
            assert node["executeOnce"] and node["alwaysOutputData"]
    assert set(writers) == set(SCHEMA["mcp_tables"]["sync_runs"]["count_columns"]) | {"sync_runs"}
    assert writers.count("sync_runs") == 2
    assert not WORKFLOW["active"]
    assert WORKFLOW["settings"]["executionTimeout"] == 300
    assert "errorWorkflow" not in WORKFLOW["settings"]
