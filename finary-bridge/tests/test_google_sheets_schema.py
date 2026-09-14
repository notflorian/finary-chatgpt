"""Self-contained current layout and executable fresh initialization."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.mcp_workbook import SCHEMA, google_create, headers, initialize, native_inventory, records

ROOT = Path(__file__).parents[2]
EXPECTED_SHEETS = [
    "README",
    "writer_control",
    "sync_runs",
    "accounts_current",
    "positions_current",
    "positions_history",
    "portfolio_daily",
    "account_ownership",
    "source_connections",
    "position_rates",
    "official_allocation_categories",
    "official_allocation_types",
    "portfolio_members",
    "observations",
    "source_warnings",
    "unsupported_details",
    "allocation_targets",
    "asset_overrides",
    "cashflows",
]


def test_fresh_initialization_is_complete_deterministic_and_paused():
    book = initialize("synthetic-writer", 7)
    assert book == initialize("synthetic-writer", 7)
    assert list(book["sheets"]) == EXPECTED_SHEETS
    assert book["schema_version"] == "4.0"
    values = records(book)
    assert values["writer_control"] == [
        {
            "row_key": "singleton",
            "workbook_schema": "4.0",
            "provider": "finary_official_mcp",
            "generation": 7,
            "writer_id": "synthetic-writer",
            "state": "PAUSED",
        }
    ]
    assert all(
        not rows for name, rows in values.items() if name not in ["README", "writer_control"]
    )
    request = google_create(book)
    assert native_inventory(request) == book
    assert request["sheets"][0]["data"][0]["rowData"][1]["values"][1] == {
        "userEnteredValue": {"stringValue": "4.0"}
    }
    assert headers()["asset_overrides"] == [
        "override_key",
        "source_asset_id",
        "custom_asset_class",
        "notes",
        "enabled",
    ]
    assert headers()["cashflows"] == [
        "cashflow_key",
        "date",
        "account_key",
        "amount_eur",
        "type",
        "notes",
        "source",
    ]
    assert SCHEMA["percentage_representation"] == "decimal_fraction"
    assert headers()["allocation_targets"] == [
        "target_key",
        "asset_class",
        "target_pct",
        "min_pct",
        "max_pct",
        "notes",
        "enabled",
    ]
    assert SCHEMA["allocation_target_constraint"] == "0 <= min_pct <= target_pct <= max_pct <= 1"


@pytest.mark.parametrize(
    "writer,generation",
    [
        ("", 1),
        ("   ", 1),
        ("writer", 0),
        ("writer", -1),
        ("writer", True),
        ("writer", 1.5),
        ("writer", 9007199254740992),
    ],
)
def test_initialization_rejects_invalid_control(writer, generation):
    with pytest.raises(ValueError):
        initialize(writer, generation)


@pytest.mark.parametrize(
    "mode",
    ["version", "missing", "reordered", "extra", "metadata", "control", "duplicate", "table_order"],
)
def test_physical_layout_rejects_incompatible_readback(mode):
    book = initialize("synthetic-writer", 1)
    if mode == "version":
        book["schema_version"] = "3.0"
    if mode == "missing":
        book["sheets"]["positions_current"]["headers"].pop()
    if mode == "reordered":
        book["sheets"]["positions_current"]["headers"].reverse()
    if mode == "extra":
        book["sheets"]["positions_current"]["headers"].append("obsolete_value")
    if mode == "metadata":
        book["sheets"]["README"]["rows"][0]["value"] = "3.0"
    if mode == "control":
        book["sheets"]["writer_control"]["rows"][0]["workbook_schema"] = "3.0"
    if mode == "duplicate":
        book["sheets"]["writer_control"]["rows"] *= 2
    if mode == "table_order":
        book["sheets"] = dict(reversed(list(book["sheets"].items())))
    with pytest.raises(ValueError):
        records(book)


def test_cli_creates_fresh_workbook_without_overwriting_existing_output(tmp_path):
    output = tmp_path / "fresh.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/initialize-workbook.py"),
        "--writer-id",
        "synthetic-writer",
        "--generation",
        "1",
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True)
    assert json.loads(output.read_text()) == google_create(initialize("synthetic-writer", 1))
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build-workflow-validation.py"), "--check"], check=True
    )


def test_native_decoder_rejects_automated_formulas_and_extra_data():
    native = google_create(initialize("synthetic-writer", 1))
    for value in [{"formulaValue": "=1+2"}, {"numberValue": 4}]:
        broken = deepcopy(native)
        broken["sheets"][0]["data"][0]["rowData"][1]["values"][1]["userEnteredValue"] = value
        with pytest.raises(ValueError):
            native_inventory(broken)


def test_clean_generation_reproduces_all_supported_artifacts(tmp_path):
    import shutil

    artifacts = [
        "docs/google-sheets-schema.json",
        "finary-bridge/app/workbook-schema.json",
        "finary-bridge/app/mcp-contract.json",
        "finary-bridge/app/mcp_models.py",
        "n8n/workflows/finary-mcp-sync.json",
    ]
    inputs = [
        "docs/finary-mcp-contract.json",
        "scripts/build-workflow-validation.py",
        "scripts/build-mcp-models.py",
        "scripts/build-mcp-workbook.py",
        "scripts/build-mcp-workflow.py",
        "scripts/initialize-workbook.py",
        "n8n/mcp-workbook.js",
        "n8n/mcp-validation.js",
        *[
            "n8n/code-nodes/finary-mcp-sync/" + name + ".js"
            for name in [
                "initialize-mcp-run",
                "validate-mcp-snapshot",
                "prepare-mcp-rows",
                "finalize-mcp-success",
                "finalize-mcp-failure",
            ]
        ],
    ]
    for name in inputs:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for name in ["__init__.py", "mcp_validation.py", "mcp_workbook.py"]:
        target = tmp_path / "finary-bridge/app" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "finary-bridge/app" / name, target)
    (tmp_path / "n8n/workflows").mkdir()
    subprocess.run(
        [sys.executable, str(tmp_path / "scripts/build-workflow-validation.py")], check=True
    )
    for name in artifacts:
        assert (tmp_path / name).read_bytes() == (ROOT / name).read_bytes()
    subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts/initialize-workbook.py"),
            "--writer-id",
            "synthetic-writer",
            "--generation",
            "1",
            "--format",
            "inventory",
            "--output",
            str(tmp_path / "new.json"),
        ],
        check=True,
    )
    assert json.loads((tmp_path / "new.json").read_text()) == initialize("synthetic-writer", 1)


@pytest.mark.parametrize("table", ["accounts_current", "cashflows", "writer_control"])
def test_create_request_rejects_populated_or_activated_inventories_without_changes(table):
    book = initialize("synthetic-writer", 1)
    if table == "writer_control":
        book["sheets"][table]["rows"][0]["state"] = "ACTIVE"
    else:
        book["sheets"][table]["rows"] = [{"operator": "=1+2"}]
    before = deepcopy(book)
    with pytest.raises(ValueError):
        google_create(book)
    assert book == before
