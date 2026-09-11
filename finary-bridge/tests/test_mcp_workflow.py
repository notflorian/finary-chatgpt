"""Exported v3 validation, deterministic batches and migration compatibility."""

import importlib.util
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from test_mcp_integration import NOW, snapshot
from test_n8n_workflow import _run_code_node

ROOT = Path(__file__).parents[2]
SCHEMA = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
WORKFLOW = json.loads((ROOT / "n8n/workflows/finary-mcp-sync.json").read_text())


def empty_book():
    book = {name: [] for name in SCHEMA["sheets"]}
    book["writer_control"] = [
        {
            "row_key": "singleton",
            "workbook_schema": "3.0",
            "provider": "finary_official_mcp",
            "generation": 1,
            "writer_id": "synthetic-writer",
            "migration_id": "synthetic-migration",
            "state": "ACTIVE",
        }
    ]
    return book


def prepare(value=None, book=None, execution="mcp-test", workflow=None):
    workflow = workflow or WORKFLOW
    book = book or empty_book()
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
    named["Fetch MCP Schema"] = [{"statusCode": 200, "body": SCHEMA}]
    named["Fetch MCP Snapshot"] = [{"statusCode": 200, "body": value or snapshot()}]
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
                result.append({"node": node, "rows": [r["json"] for r in rows]})
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
            "node": next(n for n in WORKFLOW["nodes"] if n["name"] == "Record MCP Success"),
            "rows": [r["json"] for r in terminal],
        }
    )
    return result


def test_exported_writer_preserves_totals_and_all_batches():
    named = prepare()
    prepared = named["Prepare MCP Rows"][0]
    assert prepared["batches"]["portfolio_daily"][0]["mcp_gross_assets_amount"] == "1000.00"
    assert prepared["batches"]["portfolio_daily"][0]["gross_assets_eur"] is None
    terminal = writes(named)[-1]["rows"][0]
    assert terminal["positions_current_expected_count"] == 1
    assert terminal["liabilities_current_expected_count"] == ""
    assert terminal["portfolio_members_expected_count"] == 1
    assert terminal["series_break"] is True
    assert prepared["batches"]["positions_current"][0]["market_value_native"] is None
    assert not WORKFLOW["active"]


@pytest.mark.parametrize("mutation", ["provider", "generation", "writer", "duplicate", "paused"])
def test_writer_exclusion(mutation):
    book = empty_book()
    row = book["writer_control"][0]
    if mutation == "provider":
        row["provider"] = "finary_private_api"
    if mutation == "generation":
        row["generation"] = 2
    if mutation == "writer":
        row["writer_id"] = "other-writer"
    if mutation == "duplicate":
        book["writer_control"].append(deepcopy(row))
    if mutation == "paused":
        row["state"] = "PAUSED"
    with pytest.raises(subprocess.CalledProcessError):
        prepare(book=book)


@pytest.mark.parametrize(
    "path", ["warnings", "members", "unsupported_details", "currency", "valuation"]
)
def test_exported_diagnostic_and_currency_regressions(path):
    value = snapshot()
    if path == "warnings":
        value["warnings"].append(deepcopy(value["warnings"][0]))
    if path == "members":
        value["members"].append(deepcopy(value["members"][0]))
    if path == "unsupported_details":
        value["unsupported_details"] = [
            {
                "account_key": "mcp:account:assets:orphan",
                "holding_type": "future",
                "count": 1,
                "reason": "UNSUPPORTED_TYPE",
            }
        ]
    if path == "currency":
        value["members"][0]["reported_net_worth"]["currency"] = "USD"
    if path == "valuation":
        value["coverage"]["holding_valuation"] = "UNAVAILABLE"
    with pytest.raises(subprocess.CalledProcessError):
        prepare(value)


def test_migration_repeated_preserves_history_and_manual_cells(tmp_path):
    spec = importlib.util.spec_from_file_location("migration", ROOT / "scripts/migrate-workbook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {
        "schema_version": "2.1",
        "workbook_reference": "synthetic-legacy",
        "sheets": {
            name: {"headers": [c["name"] for c in s["columns"]], "rows": [], "metadata": {}}
            for name, s in module.LEGACY["sheets"].items()
        },
    }
    source["sheets"]["portfolio_daily"]["rows"] = [
        {"snapshot_date": "2026-09-11", "gross_assets_eur": 50, "run_id": "legacy-run"}
    ]
    source["sheets"]["asset_overrides"]["rows"] = [
        {
            "override_key": "manual",
            "source_asset_id": "security:1",
            "notes": "Synthetic manual note",
            "enabled": True,
        }
    ]
    source["sheets"]["asset_overrides"]["metadata"] = {
        "format": {"color": "synthetic"},
        "formula": "=1+2",
    }
    plan = module.plan(
        source,
        deepcopy(source),
        "synthetic-candidate",
        "migration-synthetic",
        "synthetic-writer",
        NOW.isoformat(),
    )
    migrated = module.apply(source, None, plan, writers_drained=True)
    assert module.apply(source, migrated, plan, writers_drained=True) == migrated
    assert migrated["sheets"]["asset_overrides"] == source["sheets"]["asset_overrides"]
    assert migrated["sheets"]["portfolio_daily"]["rows"][0]["daily_key"] == "2026-09-11"
    assert migrated["sheets"]["legacy_observations"]["rows"][0]["scope"] == ""
    assert migrated["sheets"]["writer_control"]["rows"][0]["state"] == "PAUSED"
    with pytest.raises(ValueError):
        module.apply(source, None, plan, writers_drained=False)
    broken = deepcopy(migrated)
    broken["sheets"]["migration_ledger"]["rows"][0]["status"] = "PREPARED"
    with pytest.raises(ValueError):
        module.apply(source, broken, plan, writers_drained=True)


def test_legacy_schema_is_frozen_and_new_columns_append():
    legacy = json.loads((ROOT / "docs/google-sheets-schema-v2.json").read_text())
    assert list(SCHEMA["sheets"])[: len(legacy["sheets"])] == list(legacy["sheets"])
    for name, sheet in legacy["sheets"].items():
        assert [c["name"] for c in SCHEMA["sheets"][name]["columns"]][: len(sheet["columns"])] == [
            c["name"] for c in sheet["columns"]
        ]
    for name in ("allocation_targets", "asset_overrides", "cashflows"):
        assert SCHEMA["sheets"][name] == legacy["sheets"][name]


def test_restored_context_and_terminal_collision_are_rejected():
    named = prepare()
    for mode in ("restored", "terminal", "mutated-batch"):
        altered = deepcopy(named)
        if mode == "terminal":
            altered["Read MCP Terminal Before Success"] = altered["Prepare MCP Rows"][0]["batches"][
                "sync_runs"
            ]
        if mode == "mutated-batch":
            altered["Prepare MCP Rows"][0]["batches"]["portfolio_members"][0][
                "reported_net_worth_amount"
            ] = "0"
        with pytest.raises(subprocess.CalledProcessError):
            writes(altered, execution="different-execution" if mode == "restored" else "mcp-test")


def test_legacy_override_is_not_applied_without_deliberate_crosswalk():
    book = empty_book()
    book["asset_overrides"] = [
        {
            "override_key": "legacy",
            "source_asset_id": "security:synthetic-h",
            "enabled": True,
            "custom_asset_class": "CRYPTO",
        }
    ]
    result = prepare(book=book)["Prepare MCP Rows"][0]
    assert result["batches"]["positions_current"][0]["asset_class"] == "OTHER"


def test_retained_history_mixed_run_blocks_new_writes():
    book = empty_book()
    for write in writes(prepare(book=book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    book["positions_history"][0]["run_id"] = "foreign"
    with pytest.raises(subprocess.CalledProcessError):
        prepare(book=book, execution="next-execution")


def test_exported_validator_preserves_every_declared_snapshot_outcome():
    from test_finary_mcp_contract import MANIFEST, materialize, snapshot_error, validator

    named = prepare()
    for case in MANIFEST["cases"]:
        if case["schema"] != "#/$defs/snapshot_v3":
            continue
        value = materialize(case)
        accepted = validator(case["schema"]).is_valid(value) and snapshot_error(value) is None
        named["Fetch MCP Snapshot"] = [{"statusCode": 200, "body": value}]
        if accepted:
            result = _run_code_node(
                WORKFLOW,
                "Validate MCP Snapshot",
                named_rows=named,
                input_rows=[{}],
                execution_id="mcp-test",
            )
            assert result[0]["json"]["snapshot"] == value, case["id"]
        else:
            with pytest.raises(subprocess.CalledProcessError):
                _run_code_node(
                    WORKFLOW,
                    "Validate MCP Snapshot",
                    named_rows=named,
                    input_rows=[{}],
                    execution_id="mcp-test",
                )
