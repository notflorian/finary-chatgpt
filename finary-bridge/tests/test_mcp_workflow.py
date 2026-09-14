"""Exported v3 validation, deterministic batches and fresh workbook initialization."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from n8n_code import _run_code_node
from test_mcp_integration import NOW, snapshot

from app.mcp_workbook import initialize

ROOT = Path(__file__).parents[2]
SCHEMA = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
WORKFLOW = json.loads((ROOT / "n8n/workflows/finary-mcp-sync.json").read_text())


def empty_book():
    inventory = initialize("synthetic-writer", 1)
    inventory["sheets"]["writer_control"]["rows"][0]["state"] = "ACTIVE"
    return {name: sheet["rows"] for name, sheet in inventory["sheets"].items()}


def test_exported_series_comparison_requires_known_compatible_dimensions():
    from app.mcp_consumer import compatible

    workflow = deepcopy(WORKFLOW)
    node = next(n for n in workflow["nodes"] if n["name"] == "Validate MCP Snapshot")
    body = (ROOT / "n8n/code-nodes/finary-mcp-sync/validate-mcp-snapshot.js").read_text()
    assert node["parameters"]["jsCode"].endswith(body)
    node["parameters"]["jsCode"] = (
        node["parameters"]["jsCode"].removesuffix(body)
        + """
const {left,right}=$input.first().json;
const previous={run_id:'prior',observation_id:'observation',status:'SUCCESS',
  completed_at:'2026-09-11T08:00:00+02:00',provider:'finary_official_mcp',
  workbook_schema:mcpWorkbook.schema_version,source_contract_version:mcpContract.contract_version};
const row={run_id:previous.run_id,observation_id:previous.observation_id};
for(const [column,path]of Object.entries(mcpWorkbook.mcp_tables.observations.column_bindings)){
  if(path.startsWith('/provenance/'))row[column]=left[path.split('/').pop()];
}
return [{json:{series_break:mcpSeriesBreak({sync_runs:[previous],observations:[row]},right)}}];
"""
    )
    original = snapshot()["provenance"]
    pairs = [(original, original, False)]
    for field in [
        "provider",
        "source_contract_version",
        "scope",
        "ownership_basis",
        "metric",
        "currency",
    ]:
        pairs.extend(
            [
                (original, {**original, field: "changed"}, True),
                (original, {**original, field: None}, True),
                ({**original, field: None}, {**original, field: None}, True),
            ]
        )
    for left, right, expected in pairs:
        result = _run_code_node(
            workflow,
            "Validate MCP Snapshot",
            named_rows={},
            input_rows=[{"left": left, "right": right}],
        )[0]["json"]["series_break"]
        assert result is expected and compatible(left, right) is not expected


def readback(book):
    inventory = initialize("synthetic-writer", 1)
    for name, rows in book.items():
        inventory["sheets"][name]["rows"] = deepcopy(rows)
    return inventory


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
    assert prepared["batches"]["portfolio_daily"][0]["gross_assets_amount"] == "1000.00"
    assert "gross_assets_eur" not in prepared["batches"]["portfolio_daily"][0]
    terminal = writes(named)[-1]["rows"][0]
    assert terminal["positions_current_expected_count"] == 1
    assert "liabilities_current_expected_count" not in terminal
    assert terminal["portfolio_members_expected_count"] == 1
    assert terminal["series_break"] is True
    assert "market_value_native" not in prepared["batches"]["positions_current"][0]
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


def test_retained_current_source_cannot_disagree_with_observation_provider():
    book = empty_book()
    for write in writes(prepare(book=book)):
        table = write["node"]["parameters"]["sheetName"]["value"]
        book[table] += write["rows"]
    book["observations"][0]["provenance_provider"] = "unsupported"
    with pytest.raises(subprocess.CalledProcessError):
        prepare(book=book, execution="next-execution")


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


@pytest.mark.parametrize(
    "mode", ["missing", "version", "metadata", "header_missing", "header_reordered", "header_extra"]
)
def test_incompatible_layout_never_prepares_batches(mode):
    named = prepare()
    if mode == "missing":
        named["Read writer_control"] = [{}]
    elif mode == "version":
        named["Read writer_control"][0]["workbook_schema"] = "3.0"
    elif mode == "metadata":
        named["Read README"][0]["value"] = "3.0"
    else:
        header = named["Preflight positions_history"][0]
        if mode == "header_missing":
            header.pop("observation_id")
        if mode == "header_reordered":
            named["Preflight positions_history"] = [dict(reversed(list(header.items())))]
        if mode == "header_extra":
            header["obsolete_column"] = "obsolete_column"
    with pytest.raises(subprocess.CalledProcessError):
        _run_code_node(
            WORKFLOW, "Prepare MCP Rows", named_rows=named, input_rows=[{}], execution_id="mcp-test"
        )


@pytest.mark.parametrize("mode", ["missing", "malformed", "duplicate", "disabled", "exact"])
def test_override_requires_exact_supported_identity(mode):
    book = empty_book()
    row = {
        "override_key": "custom",
        "source_asset_id": snapshot()["positions"][0]["source_asset_id"],
        "custom_asset_class": "CRYPTO",
        "notes": "",
        "enabled": True,
    }
    if mode == "missing":
        row.pop("source_asset_id")
    if mode == "malformed":
        row["source_asset_id"] = "security:synthetic-h"
    if mode == "disabled":
        row["enabled"] = False
    book["asset_overrides"] = [row]
    if mode == "duplicate":
        book["asset_overrides"].append({**row, "override_key": "another"})
    if mode in {"missing", "malformed", "duplicate"}:
        with pytest.raises(subprocess.CalledProcessError):
            prepare(book=book)
    else:
        assert prepare(book=book)["Prepare MCP Rows"][0]["batches"]["positions_current"][0][
            "asset_class"
        ] == ("OTHER" if mode == "disabled" else "CRYPTO")


@pytest.mark.parametrize(
    "mode", ["missing", "duplicate", "paused", "writer", "generation", "version"]
)
def test_failure_control_is_independently_required(mode):
    book = empty_book()
    named = prepare(book=book)
    if mode == "missing":
        book["writer_control"] = []
    if mode == "duplicate":
        book["writer_control"] *= 2
    if mode == "paused":
        book["writer_control"][0]["state"] = "PAUSED"
    if mode == "writer":
        book["writer_control"][0]["writer_id"] = "different"
    if mode == "generation":
        book["writer_control"][0]["generation"] = 2
    if mode == "version":
        book["writer_control"][0]["workbook_schema"] = "3.0"
    with pytest.raises(subprocess.CalledProcessError):
        failure(named, book)


@pytest.mark.parametrize("field", ["observation_id", "run_id", "account_key", "is_active"])
def test_missing_required_retained_values_are_never_defaulted(field):
    book = empty_book()
    for write in writes(prepare(book=book)):
        book[write["node"]["parameters"]["sheetName"]["value"]] += write["rows"]
    book["positions_current"][0].pop(field)
    with pytest.raises(subprocess.CalledProcessError):
        prepare(book=book, execution="next")
