"""Actual installed Sheets operation with a network-disabled, in-memory transport."""

import json
import select
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sheets_write_cases import boundary_cases, outgoing
from test_n8n_workflow import _run_code_node
from test_n8n_workflow_v2 import _empty_workbook, _known_eur_snapshot, _node
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_n8n_zero_position_runtime import runtime_image as runtime_image
from test_sync_completion import _finalize, _prepare
from workbook_consumer import select_assets, validated_daily

WRITERS = {
    "Select Account Rows": "Upsert Current Accounts",
    "Select Position Rows": "Upsert Current Positions",
    "Select Liability Rows": "Upsert Current Liabilities",
    "Select History Rows": "Upsert Position History",
    "Select Daily Row": "Upsert Portfolio Daily",
}


@pytest.fixture(scope="module")
def connector(runtime_image):
    """Reuse one short-lived Node process, without starting the n8n server."""
    name = f"finary-sheets-test-{uuid4().hex}"
    script = Path(__file__).with_name("sheets_connector_transport.js")
    process = subprocess.Popen(
        [
            "docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--name", name, "-i", "--entrypoint", "node", "--mount",
            f"type=bind,src={script},dst=/tmp/transport.js,readonly",
            runtime_image, "/tmp/transport.js",
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    def apply(schema, workbook, writes):
        process.stdin.write(json.dumps({"schema": schema, "workbook": workbook, "writes": writes})
                            + "\n")
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 45)[0], "Connector response timed out"
        output = process.stdout.readline()
        assert output, "Connector exited without a response"
        result = json.loads(output)
        assert "error" not in result, result.get("error")
        return result

    try:
        yield apply
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=15)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
            process.stdout.close()
            process.stderr.close()


def _writes(workflow, named, *, execution_id, now):
    writes = []
    for selector, writer in WRITERS.items():
        rows = _run_code_node(workflow, selector, named_rows=named, input_rows=[{}])
        if rows:
            writes.append({"node": _node(workflow, writer), "rows": [row["json"] for row in rows]})
    writes.append({
        "node": _node(workflow, "Record Successful Sync"),
        "rows": [_finalize(workflow, named, execution_id=execution_id, now=now)],
    })
    return writes


def _snapshot(now, unknown=False):
    snapshot = _known_eur_snapshot(now)
    snapshot.update(liabilities=[], liabilities_eur=None, net_worth_eur=None)
    snapshot["coverage"] = {"liabilities": "UNAVAILABLE", "position_collections": "COMPLETE"}
    snapshot["positions"][0]["cost_basis_eur"] = 80
    if unknown:
        snapshot["positions"][0].update(
            currency="USD", market_value_native=100, market_value_eur=None,
            fx_to_eur=None, cost_basis_eur=None,
        )
    return snapshot


def test_known_to_unknown_clears_actual_connector_cells(connector, workflow, schema):
    workbook = _empty_workbook()
    for identity, unknown, hour in [("7201", False, "07"), ("7202", True, "08")]:
        now = f"2026-09-07T{hour}:30:00+02:00"
        named = _prepare(
            workflow, schema, execution_id=identity, start=now, prepared_at=now,
            snapshot=_snapshot(now, unknown), workbook=workbook,
        )
        prepared = named["Prepare Validated Rows"][0]
        if unknown:
            assert prepared["position_rows"][0]["market_value_eur"] is None
            assert prepared["position_rows"][0]["weight_portfolio"] is None
        writes = _writes(workflow, named, execution_id=identity, now=now)
        result = connector(schema, workbook, writes)
        workbook = result["workbook"]
    current = workbook["positions_current"][0]
    assert current["market_value_eur"] == ""
    assert current["currency"] == "USD"
    assert current["market_value_native"] == 100
    assert current["weight_portfolio"] == ""
    for sheet in ["positions_current", "positions_history"]:
        for field in ["market_value_eur", "fx_to_eur", "cost_basis_eur"]:
            assert workbook[sheet][0][field] == ""
            assert any(update["sheet"] == sheet and update["column"] == field
                       and update["value"] == "" for update in result["updates"])
    run_id = named["Validate Snapshot"][0]["run"]["run_id"]
    assert current["last_seen_run_id"] == run_id
    assert workbook["positions_history"][0]["run_id"] == run_id
    assert workbook["positions_current"][1]["weight_portfolio"] == 1
    assert workbook["portfolio_daily"][0]["gross_assets_eur"] == 150
    assert workbook["portfolio_daily"][0]["equity_eur"] == ""
    assert workbook["portfolio_daily"][0]["equity_pct"] == 0
    assert workbook["sync_runs"][-1]["status"] == "SUCCESS_WITH_WARNINGS"
    assert len(workbook["positions_history"]) == 2
    assert len(workbook["portfolio_daily"]) == 1
    assert len(workbook["sync_runs"]) == 2
    selected = select_assets(workbook, now=datetime.fromisoformat(now))
    assert selected.source == "current"
    assert selected.positions[0]["market_value_eur"] == ""
    assert selected.run_id == run_id
    assert validated_daily(workbook, workbook["portfolio_daily"][0]) is not None

    # A full new observation restores known values, including an explicit zero.
    now = "2026-09-07T09:30:00+02:00"
    snapshot = _snapshot(now)
    snapshot["positions"][0].update(market_value_native=0, market_value_eur=0, cost_basis_eur=0)
    named = _prepare(workflow, schema, execution_id="7203", start=now, prepared_at=now,
                     snapshot=snapshot, workbook=workbook)
    writes = _writes(workflow, named, execution_id="7203", now=now)
    workbook = connector(schema, workbook, writes)["workbook"]
    assert workbook["positions_current"][0]["market_value_eur"] == 0
    assert workbook["positions_current"][0]["weight_portfolio"] == 0
    assert workbook["positions_history"][0]["cost_basis_eur"] == 0
    assert workbook["positions_current"][0]["fx_to_eur"] == 1
    assert connector(schema, workbook, writes)["workbook"] == workbook

    # Retained observations become false without changing their observation ID;
    # history from the previous same-day run is retained, not relabeled.
    previous = deepcopy(workbook["positions_current"][0])
    now = "2026-09-07T10:30:00+02:00"
    snapshot["generated_at"] = now
    snapshot["positions"].pop(0)
    named = _prepare(workflow, schema, execution_id="7204", start=now, prepared_at=now,
                     snapshot=snapshot, workbook=workbook)
    writes = _writes(workflow, named, execution_id="7204", now=now)
    assert all(write["node"]["name"] != "Upsert Current Liabilities" for write in writes)
    workbook = connector(schema, workbook, writes)["workbook"]
    assert workbook["positions_current"][0] == {**previous, "is_active": False}
    assert len(workbook["positions_history"]) == 2
    assert workbook["positions_history"][0]["run_id"] == previous["last_seen_run_id"]
    assert select_assets(workbook, now=datetime.fromisoformat(now)).source == "current"


def test_actual_connector_null_and_empty_string_countercheck(connector, workflow, schema):
    node = _node(workflow, "Upsert Current Positions")
    workbook = _empty_workbook()
    key = "finary:account-001:asset:securities:1001"
    workbook["positions_current"] = [{"position_key": key, "market_value_eur": 100}]
    for value, expected in [(None, 100), ("", "")]:
        result = connector(schema, deepcopy(workbook), [{"node": node, "rows": [{
            "position_key": key, "market_value_eur": value, "last_seen_run_id": "synthetic-B",
        }]}])
        assert result["workbook"]["positions_current"][0]["market_value_eur"] == expected
        amounts = [update for update in result["updates"] if update["column"] == "market_value_eur"]
        assert len(amounts) == (0 if value is None else 1)


def test_all_eight_writers_clear_cells_and_repeat_idempotently(connector, workflow, schema):
    # Exercise finalized payload retries independently of terminal collision
    # gates. Seed physical stale cells, then replay the actual boundary output.
    cases = boundary_cases(workflow, schema)
    assert len(cases) == 8
    for selector, case in cases.items():
        rows = outgoing(selector, case)
        node = case["node"]
        sheet = node["parameters"]["sheetName"]["value"]
        columns = schema["sheets"][sheet]["columns"]
        key = schema["sheets"][sheet]["unique_key"]
        known = [dict(row) for row in rows]
        for row in known:
            for column in columns:
                if row[column["name"]] == "":
                    value = "synthetic-prior"
                    if column["type"] == "NUMBER":
                        value = 1 if column["name"].endswith("_count") else 12.5
                    elif column["type"] == "DATE":
                        value = "2030-01-01"
                    elif column["type"] == "ENUM":
                        value = schema["enums"][column["name"]][0]
                    elif column["name"] == "schema_version":
                        value = "2.0"
                    row[column["name"]] = value
        blank_write = [{"node": node, "rows": rows}]
        known_write = [{"node": node, "rows": known}]
        # Initial insertion of nullable values uses the actual append conversion.
        book = connector(schema, _empty_workbook(), blank_write)["workbook"]
        assert book[sheet] == rows
        book = connector(schema, book, known_write)["workbook"]
        assert book[sheet] == known
        result = connector(schema, book, blank_write)
        assert result["workbook"][sheet] == rows
        for row in rows:
            for column, value in row.items():
                if value == "":
                    assert any(update["key"] == row[key] and update["column"] == column
                               and update["value"] == "" for update in result["updates"])
        assert connector(schema, result["workbook"], blank_write)["workbook"] == result["workbook"]



@pytest.mark.parametrize("ownership_variants", [False, True],
                         ids=["held-full-ownership", "staked-dismembered"])
def test_verified_scpi_crypto_null_known_null_clears_actual_cells(
    connector, workflow, schema, verified_position_payloads, ownership_position_payloads,
    ownership_variants, valuation_snapshot,
):
    template = ownership_position_payloads if ownership_variants else verified_position_payloads
    values = (("cryptos:1102", 45, 30), ("scpis:1106", 75, 70), ("scpis:1107", 12, 40)) if (
        ownership_variants) else (("cryptos:1002", 60, 50), ("scpis:1006", 105, 100))
    classes = ((("crypto", 45), ("scpi", 87)) if ownership_variants
               else (("crypto", 60), ("scpi", 105)))
    count, denominator = (7, 577) if ownership_variants else (6, 610)
    workbook = _empty_workbook()
    manual = {name: [{"synthetic_manual_note": name}] for name in
              ("allocation_targets", "asset_overrides", "cashflows")}
    workbook.update(deepcopy(manual))
    previous_day = None
    for identity, day, hour, known in [
        ("8301", "07", "07", False), ("8302", "08", "07", False),
        ("8303", "08", "08", True), ("8304", "08", "09", False),
    ]:
        payloads = deepcopy(template)
        if not known:
            for kind in ("cryptos", "scpis"):
                for record in payloads[kind]["result"]:
                    record.pop("valuable")
        now = f"2026-09-{day}T{hour}:30:00+02:00"
        snapshot = valuation_snapshot(payloads, now)
        named = _prepare(workflow, schema, execution_id=identity, start=now,
                         prepared_at=now, snapshot=snapshot, workbook=workbook)
        prepared = named["Prepare Validated Rows"][0]
        assert prepared["position_rows"]
        assert ("PARTIAL_POSITION_EUR_COVERAGE" in prepared["warnings"]) is not known
        assert "LIABILITY_COVERAGE_UNAVAILABLE" in prepared["warnings"]
        writes = _writes(workflow, named, execution_id=identity, now=now)
        assert all(write["node"]["name"] != "Upsert Current Liabilities" for write in writes)
        result = connector(schema, workbook, writes)
        workbook = result["workbook"]
        assert connector(schema, workbook, writes)["workbook"] == workbook
        assert {name: workbook[name] for name in manual} == manual
        daily = next(row for row in workbook["portfolio_daily"]
                     if row["snapshot_date"].endswith(day))
        assert daily["gross_assets_eur"] == 150
        assert daily["net_worth_eur"] == daily["liabilities_eur"] == ""
        assert workbook["sync_runs"][-1]["status"] == "SUCCESS_WITH_WARNINGS"
        for source_id, value, cost in values:
            current = next(row for row in workbook["positions_current"]
                           if row["source_asset_id"] == source_id)
            history = next(row for row in workbook["positions_history"]
                           if row["source_asset_id"] == source_id
                           and row["snapshot_date"].endswith(day))
            assert history["position_key"] == current["position_key"]
            assert history["history_key"] == f"2026-09-{day}:" + current["position_key"]
            for row in (current, history):
                assert row["market_value_eur"] == (value if known else "")
                assert row["fx_to_eur"] == (1 if known else "")
                assert row["currency"] == ("EUR" if known else "")
                assert row["cost_basis_eur"] == cost
            expected_weight = pytest.approx(value / denominator) if known else ""
            assert current["weight_portfolio"] == expected_weight
            assert current["market_value_native"] == value
        for prefix, value in classes:
            assert daily[prefix + "_eur"] == (value if known else "")
            assert daily[prefix + "_pct"] == (pytest.approx(value / denominator) if known else 0)
        if identity == "8301":
            previous_day = deepcopy(workbook["positions_history"])
        else:
            assert len(workbook["positions_history"]) == 2 * count
            assert [row for row in workbook["positions_history"]
                    if row["snapshot_date"] == "2026-09-07"] == previous_day
        if identity == "8304":
            for sheet in ("positions_current", "positions_history"):
                fields = ["market_value_eur", "fx_to_eur", "currency"]
                if sheet == "positions_current":
                    fields.append("weight_portfolio")
                for field in fields:
                    assert sum(update["sheet"] == sheet and update["column"] == field
                               and update["value"] == ""
                               for update in result["updates"]) == len(values)
    assert len(workbook["positions_current"]) == count
    assert len(workbook["portfolio_daily"]) == 2
    before = deepcopy(workbook)
    now = "2026-09-08T10:30:00+02:00"
    payloads["cryptos"]["result"] = []
    payloads["scpis"]["result"] = []
    named = _prepare(workflow, schema, execution_id="8305", start=now, prepared_at=now,
                     snapshot=valuation_snapshot(payloads, now), workbook=workbook)
    workbook = connector(schema, workbook, _writes(
        workflow, named, execution_id="8305", now=now))["workbook"]
    for current, previous in zip(
        workbook["positions_current"], before["positions_current"], strict=True,
    ):
        if current["asset_class"] in {"SCPI", "CRYPTO"}:
            assert current == {**previous, "is_active": False}
    assert len(workbook["positions_history"]) == 2 * count
    for row in before["positions_history"]:
        if row["asset_class"] in {"SCPI", "CRYPTO"} or row["snapshot_date"] == "2026-09-07":
            assert row in workbook["positions_history"]
    selected = select_assets(workbook, now=datetime.fromisoformat(now))
    assert selected.source == "current"
    assert len(selected.positions) == 4
