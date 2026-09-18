"""Offline preparation of a personalized, still-inactive n8n workflow."""

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/prepare-n8n-workflow.py"


def command(output, credential_id="synthetic opaque/id", credential_name="Synthetic Sheets"):
    return [
        sys.executable,
        str(SCRIPT),
        "--credential-id",
        credential_id,
        "--credential-name",
        credential_name,
        "--output",
        str(output),
    ]


def test_cli_binds_every_google_sheets_node_without_changing_canonical_export(tmp_path):
    source = ROOT / "n8n/workflows/finary-mcp-sync.json"
    before = source.read_bytes()
    output = tmp_path / "finary-mcp-sync-local.json"

    result = subprocess.run(
        command(output),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    original = json.loads(before)
    prepared = json.loads(output.read_text())
    target_indexes = [
        index
        for index, node in enumerate(original["nodes"])
        if node["type"] == "n8n-nodes-base.googleSheets"
    ]
    assert target_indexes
    assert prepared["active"] is False
    expected = deepcopy(original)
    for index, node in enumerate(prepared["nodes"]):
        if index in target_indexes:
            assert node["credentials"] == {
                "googleSheetsOAuth2Api": {
                    "id": "synthetic opaque/id",
                    "name": "Synthetic Sheets",
                }
            }
            expected["nodes"][index]["credentials"] = node["credentials"]
        else:
            assert node == original["nodes"][index]
    assert prepared == expected
    assert "synthetic opaque/id" not in result.stdout + result.stderr


@pytest.mark.parametrize("arguments", [["--credential-id", ""], ["--credential-name", ""], []])
def test_cli_rejects_missing_or_blank_credential_values(tmp_path, arguments):
    output = tmp_path / "workflow.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments, "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert "synthetic-sensitive" not in result.stdout + result.stderr


def test_cli_refuses_existing_checkout_and_symlinked_checkout_destinations(tmp_path):
    existing = tmp_path / "existing.json"
    existing.write_text("operator artifact")
    for output in (existing, ROOT / "personalized-workflow.json"):
        result = subprocess.run(command(output), capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
    assert existing.read_text() == "operator artifact"
    assert not (ROOT / "personalized-workflow.json").exists()
    redirected = tmp_path / "redirected"
    redirected.symlink_to(ROOT, target_is_directory=True)
    output = redirected / "personalized-workflow.json"
    result = subprocess.run(command(output), capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert not output.exists()


def test_internal_source_validation_never_returns_partial_workflow():
    spec = importlib.util.spec_from_file_location("prepare_n8n_workflow", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for source in ({}, {"active": False, "nodes": []}, {"active": False, "nodes": [None]}):
        with pytest.raises(ValueError):
            module.prepared_workflow(source, "synthetic-id", "Synthetic name")
