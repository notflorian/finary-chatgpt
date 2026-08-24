"""Checks for safe workflow scheduling and operational controls."""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_workflow_stays_safe_to_import() -> None:
    workflow = json.loads(
        (REPOSITORY_ROOT / "n8n/workflows/finary-daily-sync.json").read_text()
    )

    assert workflow["active"] is False
    assert workflow["settings"]["timezone"] == "Europe/Paris"
    assert any(
        node["type"] == "n8n-nodes-base.manualTrigger"
        for node in workflow["nodes"]
    )

    schedule_nodes = [
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.scheduleTrigger"
    ]
    assert len(schedule_nodes) == 1
    assert (
        schedule_nodes[0]["parameters"]["rule"]["interval"][0]["expression"]
        == "30 7 * * *"
    )


def test_operations_document_preserves_schedule_controls() -> None:
    operations = (REPOSITORY_ROOT / "docs/operations.md").read_text()

    assert "repository workflow exports are inactive for safe import" in operations
    assert "07:30 `Europe/Paris`" in operations
    assert "unpublish:workflow" in operations
    assert "older than 48 hours" in operations
    assert "docker compose down -v" in operations
