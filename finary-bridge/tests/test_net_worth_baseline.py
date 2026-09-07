"""Writer-side comparison regressions using exported JavaScript and synthetic writes."""

import json
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from test_n8n_workflow import _run_code_node, _run_id
from test_n8n_workflow_v2 import (
    _apply_prepared_writes,
    _empty_workbook,
    _known_eur_snapshot,
    _node,
    _upsert,
)
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_operations import _run_error_classifier, _trigger
from test_sync_completion import _finalize, _prepare

WARNING = "NET_WORTH_CHANGE_OVER_20_PERCENT"


def _failure(
    schema,
    records,
    *,
    execution_id="B",
    step="Upsert Portfolio Daily",
    message="execution timed out",
):
    return _run_error_classifier(
        _trigger(message, step, execution_id=execution_id), records,
    )


def _legacy_selection(workflow):
    """Countercheck only: replace the selector in memory with the reviewed defect."""
    legacy = deepcopy(workflow)
    node = _node(legacy, "Prepare Validated Rows")
    code = node["parameters"]["jsCode"]
    start = code.index("// Validate retained daily aggregates")
    end = code.index("const change =", start)
    old = """previousDaily.sort((a, b) => String(b.snapshot_date).localeCompare(String(a.snapshot_date)));
const previous = previousDaily.find((row) => row.net_worth_eur !== '' && row.net_worth_eur !== null && Number.isFinite(Number(row.net_worth_eur)));
const previousNetWorth = previous ? Number(previous.net_worth_eur) : null;
"""  # noqa: E501
    node["parameters"]["jsCode"] = code[:start] + old + code[end:]
    return legacy


def _attempt(workflow, schema, book, execution_id="C", worth=210, day="05", **kwargs):
    hour = "13" if execution_id == "C" else "12"
    timestamp = f"2026-09-{day}T{hour}:00:00Z"
    snapshot = _known_eur_snapshot(timestamp, first_value=max(0, worth - 40))
    snapshot["liabilities_eur"] = snapshot["gross_assets_eur"] - worth
    snapshot["liabilities"][0]["outstanding_eur"] = snapshot["liabilities_eur"]
    snapshot["net_worth_eur"] = worth
    return _prepare(
        workflow,
        schema,
        workbook=book,
        execution_id=execution_id,
        start=timestamp,
        prepared_at=f"2026-09-{day}T{hour}:00:10Z",
        snapshot=snapshot,
        **kwargs,
    )


def _commit(workflow, schema, book, named, *, completed_at=None):
    prepared = named["Prepare Validated Rows"][0]
    run = named["Validate Snapshot"][0]["run"]
    execution_id = run["run_id"].split(":")[1]
    completed_at = (
        completed_at
        or (datetime.fromisoformat(run["started_at"]) + timedelta(minutes=1)).isoformat()
    )
    _apply_prepared_writes(schema, book, prepared, stop_after="portfolio_daily")
    terminal = _finalize(workflow, named, execution_id=execution_id, now=completed_at)
    book["sync_runs"] = _upsert(book["sync_runs"], [terminal], "run_id")
    return terminal


def _assert_comparison(named, previous, change, warning, *, status=None, current=210):
    prepared = named["Prepare Validated Rows"][0]
    terminal = prepared["sync_run_rows"][0]
    assert terminal["previous_net_worth_eur"] == previous
    if change is None:
        assert terminal["net_worth_change_pct"] is None
    else:
        assert terminal["net_worth_change_pct"] == pytest.approx(change)
    assert (WARNING in prepared["warnings"]) is warning
    assert (WARNING in (terminal["error_message"] or "")) is warning
    assert terminal["status"] == (status or ("SUCCESS_WITH_WARNINGS" if warning else "SUCCESS"))
    assert terminal["net_worth_eur"] == prepared["daily_rows"][0]["net_worth_eur"] == current


@pytest.fixture
def book(workflow, schema):
    workbook = _empty_workbook()
    a = _attempt(workflow, schema, workbook, "A", 140, "04")
    terminal = _commit(workflow, schema, workbook, a)
    assert terminal["status"] == "SUCCESS"
    return workbook


@pytest.mark.parametrize("failed", [False, True], ids=["uncommitted-B", "FAILED-B"])
def test_interrupted_daily_write_cannot_become_baseline(workflow, schema, book, failed):
    b = _attempt(workflow, schema, book, "B", 200)
    _apply_prepared_writes(
        schema, book, b["Prepare Validated Rows"][0], stop_after="portfolio_daily"
    )
    if failed:
        failure = _failure(schema, book["sync_runs"])
        assert failure["should_record"] is True
        book["sync_runs"].append(failure["row"])
    assert [row["status"] for row in book["sync_runs"]] == (
        ["SUCCESS", "FAILED"] if failed else ["SUCCESS"]
    )
    c = _attempt(workflow, schema, book)
    _assert_comparison(c, 140, 0.50, True)
    old_c = _attempt(_legacy_selection(workflow), schema, book)
    _assert_comparison(old_c, 200, 0.05, False)
    terminal = _commit(workflow, schema, book, c)
    assert terminal["status"] == "SUCCESS_WITH_WARNINGS"
    assert terminal["completed_at"] == "2026-09-05T13:01:00.000Z"


@pytest.mark.parametrize("warnings", [False, True], ids=["SUCCESS", "SUCCESS_WITH_WARNINGS"])
def test_both_success_statuses_supply_an_ordinary_baseline(workflow, schema, warnings):
    workbook = _empty_workbook()
    snapshot = _known_eur_snapshot("2026-09-04T12:00:00Z")
    if warnings:
        snapshot["positions"][0]["market_value_eur"] = None
    a = _prepare(
        workflow,
        schema,
        execution_id="A",
        start=snapshot["generated_at"],
        snapshot=snapshot,
        workbook=workbook,
    )
    terminal = _commit(workflow, schema, workbook, a)
    assert terminal["status"] == ("SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS")
    c = _attempt(workflow, schema, workbook, worth=154)
    _assert_comparison(c, 140, 0.10, False, current=154)


@pytest.mark.parametrize("missing", ["all", "daily", "terminal", "unmatched"])
def test_missing_evidence_is_unavailable(workflow, schema, book, missing):
    if missing in {"all", "daily"}:
        book["portfolio_daily"] = []
    if missing in {"all", "terminal"}:
        book["sync_runs"] = []
    if missing == "unmatched":
        book["sync_runs"][0]["run_id"] = "foreign"
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("b_failed", [False, True])
def test_same_day_success_cannot_validate_replacement_or_reconstruct_missing_daily(
    workflow, schema, book, fallback, b_failed
):
    if not fallback:
        book = _empty_workbook()
    old = _attempt(workflow, schema, book, "old-same-day", 180)
    _commit(workflow, schema, book, old)
    replacement = _attempt(workflow, schema, book, "B", 200)
    _apply_prepared_writes(
        schema, book, replacement["Prepare Validated Rows"][0], stop_after="portfolio_daily"
    )
    if b_failed:
        book["sync_runs"].append(_failure(schema, book["sync_runs"])["row"])
    assert not any(row["run_id"] == _run_id("old-same-day") for row in book["portfolio_daily"])
    _assert_comparison(
        _attempt(workflow, schema, book),
        140 if fallback else None,
        0.50 if fallback else None,
        fallback,
    )


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize(
    "anomaly",
    [
        "daily-identical",
        "daily-foreign",
        "terminal-identical",
        "terminal-success-warning",
        "terminal-success-failure",
    ],
)
def test_duplicate_physical_evidence_is_rejected(workflow, schema, book, fallback, anomaly):
    if not fallback:
        book = _empty_workbook()
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "B", 200))
    sheet = "portfolio_daily" if anomaly.startswith("daily") else "sync_runs"
    duplicate = deepcopy(book[sheet][-1])
    if anomaly == "daily-foreign":
        duplicate["run_id"] = "foreign"
    elif anomaly == "terminal-success-warning":
        duplicate["status"] = "SUCCESS_WITH_WARNINGS"
    elif anomaly == "terminal-success-failure":
        duplicate["status"] = "FAILED"
    book[sheet].insert(0, duplicate)
    _assert_comparison(
        _attempt(workflow, schema, book),
        140 if fallback else None,
        0.50 if fallback else None,
        fallback,
    )


@pytest.mark.parametrize(
    "sheet,field,value",
    [
        ("portfolio_daily", "run_id", None),
        ("portfolio_daily", "run_id", ""),
        ("portfolio_daily", "run_id", "  "),
        ("portfolio_daily", "run_id", True),
        ("portfolio_daily", "run_id", 123),
        ("portfolio_daily", "run_id", "n8n-execution:A "),
        ("sync_runs", "run_id", "n8n-execution:A "),
        ("sync_runs", "status", "FAILED"),
        ("sync_runs", "status", "RUNNING"),
        ("portfolio_daily", "liability_coverage", "PARTIAL"),
        ("portfolio_daily", "liability_coverage", "UNKNOWN"),
        ("sync_runs", "liability_coverage", "UNAVAILABLE"),
        ("sync_runs", "gross_assets_eur", 151),
        ("sync_runs", "liabilities_eur", 11),
        ("sync_runs", "net_worth_eur", 141),
        ("portfolio_daily", "net_worth_eur", 141),
        ("portfolio_daily", "financial_assets_eur", "invalid"),
        ("portfolio_daily", "snapshot_date", "2026-09-03"),
        ("portfolio_daily", "snapshot_date", "2026-9-4"),
        ("portfolio_daily", "snapshot_date", "2026-02-30"),
        ("portfolio_daily", "generated_at", "2026-09-04T12:00:00"),
        ("portfolio_daily", "generated_at", "2026-09-04"),
        ("portfolio_daily", "generated_at", "2026-09-04T23:00:00Z"),
        ("portfolio_daily", "generated_at", "2026-09-04T24:00:00Z"),
        ("portfolio_daily", "generated_at", "2026-02-30T12:00:00Z"),
        ("sync_runs", "completed_at", None),
        ("sync_runs", "completed_at", ""),
        ("sync_runs", "completed_at", "not-a-time"),
        ("sync_runs", "completed_at", "2026-09-04T12:01:00"),
        ("sync_runs", "completed_at", "2026-09-04T12:01:00+25:00"),
        ("sync_runs", "completed_at", "2026-02-30T12:01:00Z"),
    ],
)
def test_invalid_daily_or_terminal_metadata_cannot_supply_baseline(
    workflow, schema, book, sheet, field, value
):
    book[sheet][0][field] = value
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


@pytest.mark.parametrize("field", ["gross_assets_eur", "liabilities_eur", "net_worth_eur"])
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "",
        " \t ",
        True,
        False,
        "malformed",
        "NaN",
        "Infinity",
        "-Infinity",
        float("nan"),
        float("inf"),
        -float("inf"),
        "1,000",
        "0x8c",
        "140 EUR",
        "missing",
    ],
)
def test_numbers_are_never_coerced_to_a_usable_baseline(workflow, schema, book, field, invalid):
    for sheet in ("portfolio_daily", "sync_runs"):
        if invalid == "missing":
            book[sheet][0].pop(field)
        else:
            book[sheet][0][field] = invalid
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


@pytest.mark.parametrize("represent", [str, lambda n: f" +{n}.0 ", lambda n: f"{n}e0"])
def test_supported_numeric_strings_and_opaque_legacy_ids(workflow, schema, book, represent):
    for sheet in ("portfolio_daily", "sync_runs"):
        row = book[sheet][0]
        row["run_id"] = " 20260904-legacy:opaque "
        for key in ("gross_assets_eur", "liabilities_eur", "net_worth_eur"):
            row[key] = represent(row[key])
    _assert_comparison(_attempt(workflow, schema, book), 140, 0.50, True)


@pytest.mark.parametrize("delta,valid", [(1e-9, True), (1e-7, False), (1, False)])
def test_arithmetic_uses_existing_tolerance_but_copied_totals_match_exactly(
    workflow, schema, book, delta, valid
):
    for sheet in ("portfolio_daily", "sync_runs"):
        book[sheet][0]["gross_assets_eur"] += delta
    _assert_comparison(
        _attempt(workflow, schema, book), 140 if valid else None, 0.50 if valid else None, valid
    )
    book["sync_runs"][0]["net_worth_eur"] += 1e-9
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


@pytest.mark.parametrize("field", ["gross_assets_eur", "liabilities_eur"])
def test_negative_gross_or_liabilities_are_not_valid_evidence(workflow, schema, book, field):
    for sheet in ("portfolio_daily", "sync_runs"):
        row = book[sheet][0]
        row[field] = -10
        row["net_worth_eur"] = row["gross_assets_eur"] - row["liabilities_eur"]
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "first_completion,second_completion,previous,change,warning",
    [
        ("2026-09-06T00:02:00+02:00", "2026-09-05T21:59:00Z", 140, 0.50, True),
        ("2026-09-05T23:00:00+02:00", "2026-09-05T21:01:00Z", 200, 0.05, False),
        ("2026-09-05T23:00:00+02:00", "2026-09-05T21:00:00Z", None, None, False),
        ("2026-09-05T21:00:00.0001Z", "2026-09-05T23:00:00.0002+02:00", 200, 0.05, False),
        ("2026-09-05T21:00:00.100Z", "2026-09-05T23:00:00.1+02:00", None, None, False),
    ],
)
def test_completion_instants_not_physical_dates_or_ids_determine_order(
    workflow, schema, book, reverse, first_completion, second_completion, previous, change, warning
):
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "B", 200))
    book["sync_runs"][0]["completed_at"] = first_completion
    book["sync_runs"][1]["completed_at"] = second_completion
    if reverse:
        book["sync_runs"].reverse()
        book["portfolio_daily"].reverse()
    _assert_comparison(_attempt(workflow, schema, book, day="06"), previous, change, warning)


@pytest.mark.parametrize("generated", ["2026-09-03T22:00:00Z", "2026-09-04T14:00:00+02:00"])
def test_generated_business_date_uses_paris(workflow, schema, book, generated):
    book["portfolio_daily"][0]["generated_at"] = generated
    _assert_comparison(_attempt(workflow, schema, book), 140, 0.50, True)


@pytest.mark.parametrize(
    "previous,current,change,warning",
    [
        (0, 210, None, False),
        (-100, -50, 0.50, True),
        (-100, -120, -0.20, False),
        (100, 120, 0.20, False),
        (100, 80, -0.20, False),
        (100, 120.01, 0.2001, True),
        (100, 79.99, -0.2001, True),
        (100, 0, -1, True),
    ],
)
def test_zero_negative_values_and_strict_threshold(
    workflow, schema, previous, current, change, warning
):
    book = _empty_workbook()
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "A", previous, "04"))
    _assert_comparison(
        _attempt(workflow, schema, book, worth=current), previous, change, warning, current=current
    )


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_current_coverage_retains_only_previous_known_value(
    workflow, schema, book, coverage
):
    snapshot = _known_eur_snapshot("2026-09-05T13:00:00Z")
    snapshot.update(liabilities=[], liabilities_eur=None, net_worth_eur=None)
    snapshot["coverage"]["liabilities"] = coverage
    named = _prepare(workflow, schema, workbook=book, snapshot=snapshot)
    _assert_comparison(named, 140, None, False, status="SUCCESS_WITH_WARNINGS", current=None)
    assert named["Prepare Validated Rows"][0]["liability_rows"] == []
    terminal = _finalize(workflow, named)
    assert terminal["net_worth_eur"] is None and terminal["status"] == "SUCCESS_WITH_WARNINGS"


@pytest.mark.parametrize("coverage", ["PARTIAL", "UNAVAILABLE"])
def test_incomplete_newer_daily_is_not_a_numeric_baseline(workflow, schema, book, coverage):
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "B", 200))
    for sheet in ("portfolio_daily", "sync_runs"):
        book[sheet][-1].update(
            liability_coverage=coverage, liabilities_eur=None, net_worth_eur=None
        )
    _assert_comparison(_attempt(workflow, schema, book), 140, 0.50, True)


def test_daily_baseline_does_not_depend_on_current_membership_or_history(workflow, schema, book):
    book["positions_history"] = []
    for sheet in ("accounts_current", "positions_current", "liabilities_current"):
        for row in book[sheet]:
            row["last_seen_run_id"] = "foreign-uncommitted-run"
            row["is_active"] = "invalid"
    _assert_comparison(_attempt(workflow, schema, book), 140, 0.50, True)
    # Valid detail must also never repair an invalid aggregate.
    book["portfolio_daily"][0]["gross_assets_eur"] = None
    _assert_comparison(_attempt(workflow, schema, book), None, None, False)


def test_current_execution_is_excluded_and_reruns_and_terminal_retries_preserve_identity(
    workflow, schema, book
):
    with pytest.raises(subprocess.CalledProcessError) as collision:
        _attempt(workflow, schema, book, execution_id="A")
    assert collision.value.stderr == "RUN_IDENTITY_COLLISION"
    c = _attempt(workflow, schema, book)
    _assert_comparison(c, 140, 0.50, True)
    terminal = _commit(workflow, schema, book, c)
    before = deepcopy(book)
    for _ in range(3):
        book["sync_runs"] = _upsert(book["sync_runs"], [terminal], "run_id")
    assert book == before
    assert terminal["run_id"] == _run_id("C")
    assert terminal["completed_at"] == "2026-09-05T13:01:00.000Z"
    assert terminal["duration_ms"] == 60000
    with pytest.raises(subprocess.CalledProcessError) as collision:
        _attempt(workflow, schema, book)
    assert collision.value.stderr == "RUN_IDENTITY_COLLISION"
    rerun = _attempt(workflow, schema, book, execution_id="D", worth=210)
    _assert_comparison(rerun, 210, 0, False)
    _commit(workflow, schema, book, rerun, completed_at="2026-09-05T14:01:00Z")
    assert len(book["portfolio_daily"]) == 2
    assert len({row["history_key"] for row in book["positions_history"]}) == 4
    assert [row["run_id"] for row in book["sync_runs"]] == [
        _run_id("A"),
        _run_id("C"),
        _run_id("D"),
    ]


def _walk_reads(workflow, named, *, fail_at=None):
    """Follow exported connections with complete synthetic Sheets results or failed retries."""
    evidence = {name: named.pop(name) for name in list(named) if name.startswith("Read ")}
    named.pop("Prepare Validated Rows")
    name = "Read Asset Overrides"
    visited = []
    while name != "Select Account Rows":
        assert name not in visited
        visited.append(name)
        node = _node(workflow, name)
        if node["type"] == "n8n-nodes-base.googleSheets":
            assert node.get("continueOnFail", False) is False
            assert node.get("onError", "stopWorkflow") == "stopWorkflow"
            assert node["executeOnce"] is True
            assert node["retryOnFail"] is True and node["maxTries"] == 3
            assert node["waitBetweenTries"] == 5000
            if name == fail_at:
                return visited, None  # Retry exhaustion emits no normal output.
            # The engine's Always Output Data applies only after successful empty reads.
            input_rows = deepcopy(evidence[name])
            if not input_rows:
                assert node["alwaysOutputData"] is True
                input_rows = [{}]
            named[name] = input_rows
        else:
            assert name == "Prepare Validated Rows"
            named[name] = [
                item["json"]
                for item in _run_code_node(
                    workflow,
                    name,
                    named_rows=named,
                    input_rows=input_rows,
                    execution_id="C",
                    now="2026-09-05T13:00:10Z",
                )
            ]
        connections = workflow["connections"][name]["main"]
        assert len(connections) == 1 and len(connections[0]) == 1
        name = connections[0][0]["node"]
    return visited, named


@pytest.mark.parametrize("empty", [False, True])
def test_full_evidence_reads_are_connected_before_preparation_and_writes(
    workflow, schema, book, empty
):
    if empty:
        book = _empty_workbook()
    named = _attempt(workflow, schema, book)
    visited, prepared = _walk_reads(workflow, named)
    assert visited[-3:] == ["Read Portfolio Daily", "Read Sync Runs", "Prepare Validated Rows"]
    for name, sheet in [
        ("Read Portfolio Daily", "portfolio_daily"),
        ("Read Sync Runs", "sync_runs"),
    ]:
        node = _node(workflow, name)
        assert node["typeVersion"] == 4.7
        params = node["parameters"]
        assert params.get("operation", "read") == "read"
        assert params["sheetName"] == {"__rl": True, "mode": "name", "value": sheet}
        # Pinned 4.7 reads the full sheet without filters/range/first-empty-row limits.
        assert set(params) == {"documentId", "sheetName", "options"}
        assert params["options"] == ({"returnFirstMatch": False} if sheet == "sync_runs" else {})
    _assert_comparison(prepared, None if empty else 140, None if empty else 0.50, not empty)
    # Every normal path from snapshot validation to a portfolio write must pass both reads.
    pending = [("Snapshot Is Valid", [])]
    while pending:
        name, path = pending.pop()
        assert name not in path
        path = [*path, name]
        node = _node(workflow, name)
        if node["parameters"].get("operation") == "appendOrUpdate":
            if node["parameters"]["sheetName"]["value"] != "sync_runs":
                assert path.index("Read Portfolio Daily") < path.index("Read Sync Runs")
                assert path.index("Read Sync Runs") < path.index("Prepare Validated Rows")
            continue
        for branch in workflow["connections"].get(name, {}).get("main", []):
            pending.extend((edge["node"], path) for edge in branch)


@pytest.mark.parametrize("step", ["Read Portfolio Daily", "Read Sync Runs"])
@pytest.mark.parametrize(
    "message,code",
    [
        ("401 credential rejected SYNTHETIC_PRIVATE_DETAIL", "GOOGLE_AUTH_FAILED"),
        ("429 quota SYNTHETIC_PRIVATE_DETAIL", "GOOGLE_RATE_LIMITED"),
        ("503 unavailable SYNTHETIC_PRIVATE_DETAIL", "GOOGLE_TEMPORARY_FAILURE"),
    ],
)
def test_failed_evidence_read_stops_writes_and_uses_sanitized_error_path(
    workflow, schema, book, step, message, code
):
    original = deepcopy(book)
    visited, prepared = _walk_reads(workflow, _attempt(workflow, schema, book), fail_at=step)
    assert visited[-1] == step and prepared is None
    assert "Prepare Validated Rows" not in visited
    assert not any(name.startswith("Upsert ") for name in visited)
    failure = _failure(schema, book["sync_runs"], execution_id="C", step=step, message=message)
    assert failure["should_record"] is True
    row = failure["row"]
    assert row["status"] == "FAILED" and row["error_code"] == code
    assert row["run_id"] == _run_id("C")
    assert row["previous_net_worth_eur"] is None and row["net_worth_change_pct"] is None
    assert WARNING not in row["error_message"]
    assert "SYNTHETIC_PRIVATE_DETAIL" not in json.dumps(failure)
    assert book == original


def test_tied_latest_usable_states_do_not_fall_through_to_an_arbitrary_older_state(
    workflow, schema, book
):
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "B", 200))
    _commit(workflow, schema, book, _attempt(workflow, schema, book, "D", 220, "06"))
    book["sync_runs"][1]["completed_at"] = book["sync_runs"][2]["completed_at"]
    _assert_comparison(_attempt(workflow, schema, book, day="07"), None, None, False)
