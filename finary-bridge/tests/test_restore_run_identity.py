"""Execute exported nodes and simulate workbook writes across database ID reuse.

ID reuse represents restoration here. The runtime module separately exercises
fresh disposable databases; neither module restores a production database.
"""

import json
import subprocess
from copy import deepcopy
from datetime import datetime

import pytest
from test_n8n_workflow import _headers, _nonce, _run_code_node, _run_id
from test_n8n_workflow_v2 import (
    _apply_prepared_writes,
    _empty_workbook,
    _known_eur_snapshot,
    _prepare_for_run,
)
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_operations import ERROR_PATH, _load, _run_error_classifier, _saved_execution, _trigger
from workbook_consumer import select_assets, validated_daily

START = "2026-08-20T07:30:12+02:00"
NEXT = "2026-08-21T07:30:12+02:00"
NOW = datetime.fromisoformat("2026-08-21T05:32:00+00:00")


def restore_snapshot(timestamp=START, value=150):
    snapshot = _known_eur_snapshot(timestamp)
    snapshot["positions"] = snapshot["positions"][:1]
    snapshot["coverage"] = {"liabilities": "UNAVAILABLE", "position_collections": "COMPLETE"}
    snapshot["liabilities"] = []
    snapshot["liabilities_eur"] = snapshot["net_worth_eur"] = None
    snapshot["gross_assets_eur"] = snapshot["accounts"][0]["market_value_eur"] = value
    snapshot["positions"][0]["market_value_eur"] = value
    snapshot["positions"][0]["market_value_native"] = value
    snapshot["positions"][0]["quantity"] = 1
    snapshot["positions"][0]["unit_price"] = value
    return snapshot


def initialize(workflow, execution_id="42", timestamp=START, *, nonce=None):
    return _run_code_node(
        workflow,
        "Initialize Run",
        named_rows={},
        input_rows=[{}],
        execution_id=execution_id,
        now=timestamp,
        nonce=nonce,
    )[0]["json"]


def error_for(run, existing, *, saved=None):
    execution_id = run["run_id"].split(":")[1]
    trigger = _trigger("synthetic failure", "Upsert Position History", execution_id=execution_id)
    trigger["execution"]["executionContext"]["establishedAt"] = run["started_epoch_ms"]
    return _run_error_classifier(trigger, existing, run=run, saved=saved)


@pytest.mark.parametrize("execution_id", ["42", "43"])
@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("legacy", [None, "n8n-execution:42", "20260820-073012"])
def test_restored_or_fresh_execution_preserves_old_evidence(
    workflow,
    schema,
    execution_id,
    complete,
    legacy,
):
    book = _empty_workbook()
    first = initialize(workflow)
    prepared = _prepare_for_run(workflow, schema, restore_snapshot(), book, first["run_id"])
    _apply_prepared_writes(schema, book, prepared)
    if legacy:
        # Retained workbook IDs are opaque. Only this historical fixture is legacy.
        for rows in book.values():
            for row in rows:
                for key in ("run_id", "last_seen_run_id"):
                    if row.get(key) == first["run_id"]:
                        row[key] = legacy
    old_terminal = deepcopy(book["sync_runs"][0])
    second = initialize(workflow, execution_id, NEXT, nonce=_nonce("fresh-entropy"))
    assert first["run_id"] != second["run_id"]
    prepared = _prepare_for_run(
        workflow,
        schema,
        restore_snapshot(NEXT, 160),
        book,
        second["run_id"],
    )
    _apply_prepared_writes(
        schema,
        book,
        prepared,
        stop_after="success" if complete else "positions_current",
        completed_at="2026-08-21T05:31:00Z",
    )
    state = select_assets(book, now=NOW)
    error = error_for(second, book["sync_runs"])
    if complete:
        assert state.source == "current" and state.current_complete
        assert state.positions[0]["market_value_eur"] == 160
        assert not error["should_record"]
        assert len(book["sync_runs"]) == 2
    else:
        assert state.source == "history" and not state.current_complete
        assert state.history[0]["market_value_eur"] == 150
        assert error["should_record"]
        assert error["row"]["run_id"] == second["run_id"]
        assert error["row"]["started_at"] == second["started_at"]
        book["sync_runs"].append(error["row"])
        assert not error_for(second, book["sync_runs"])["should_record"]
    assert book["sync_runs"][0] == old_terminal
    assert validated_daily(book, book["portfolio_daily"][0]) is not None
    assert len(book["sync_runs"]) == 2


@pytest.mark.parametrize("status", ["SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED", "UNKNOWN"])
def test_collision_blocks_prewrite_and_every_terminal_path(workflow, schema, status):
    run = initialize(workflow)
    book = _empty_workbook()
    prepared = _prepare_for_run(workflow, schema, restore_snapshot(), book, run["run_id"])
    old = {**prepared["sync_run_rows"][0], "status": status, "started_at": NEXT}
    book["sync_runs"] = [old]
    before = deepcopy(book)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _prepare_for_run(workflow, schema, restore_snapshot(), book, run["run_id"])
    assert failure.value.stderr == "RUN_IDENTITY_COLLISION"
    assert book == before
    context = {
        "run": run,
        "schema": schema,
        "failure": {
            "code": "SNAPSHOT_VALIDATION_FAILED",
            "message": "Snapshot validation failed",
        },
    }
    named = {
        "Validate Snapshot": [context],
        "Prepare Validated Rows": [prepared],
        "Preflight Failure Sync Header": [_headers(schema, "sync_runs")],
    }
    for node in ("Prepare Failed Run", "Select Success Run"):
        with pytest.raises(subprocess.CalledProcessError) as failure:
            _run_code_node(workflow, node, named_rows=named, input_rows=[old], execution_id="42")
        assert failure.value.stderr == "RUN_IDENTITY_COLLISION"
    with pytest.raises(subprocess.CalledProcessError) as failure:
        error_for(run, [old])
    assert failure.value.stderr == "RUN_IDENTITY_COLLISION"
    assert book == before


@pytest.mark.parametrize("status", ["SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED"])
def test_structured_failure_and_error_replays_preserve_terminal(workflow, schema, status):
    run = initialize(workflow)
    context = _run_code_node(
        workflow,
        "Validate Snapshot",
        execution_id="42",
        input_rows=[{"body": {"invalid": True}}],
        named_rows={"Initialize Run": [run], "Fetch Canonical Schema": [{"body": schema}]},
    )[0]["json"]
    assert not context["can_write"]
    named = {
        "Validate Snapshot": [context],
        "Preflight Failure Sync Header": [_headers(schema, "sync_runs")],
    }
    failed = _run_code_node(
        workflow,
        "Prepare Failed Run",
        execution_id="42",
        named_rows=named,
        input_rows=[{}],
    )[0]["json"]
    assert failed["run_id"] == run["run_id"] and failed["gross_assets_eur"] is None
    old = {**failed, "status": status}
    before = deepcopy(old)
    assert (
        _run_code_node(
            workflow,
            "Prepare Failed Run",
            execution_id="42",
            named_rows=named,
            input_rows=[old],
        )
        == []
    )
    assert not error_for(run, [old])["should_record"]
    assert old == before


@pytest.mark.parametrize(
    "node",
    ["Validate Snapshot", "Prepare Validated Rows", "Prepare Failed Run", "Select Success Run"],
)
def test_saved_execution_context_is_never_relabeled(workflow, schema, node):
    run = initialize(workflow)
    prepared = _prepare_for_run(
        workflow, schema, restore_snapshot(), _empty_workbook(), run["run_id"]
    )
    context = {"run": run, "schema": schema, "can_write": True, "snapshot": restore_snapshot()}
    named = {
        "Initialize Run": [run],
        "Validate Snapshot": [context],
        "Fetch Canonical Schema": [{"body": schema}],
        "Prepare Validated Rows": [prepared],
        "Preflight Failure Sync Header": [_headers(schema, "sync_runs")],
    }
    before = deepcopy(named)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_code_node(workflow, node, execution_id="43", named_rows=named, input_rows=[{}])
    assert failure.value.stderr == "STALE_EXECUTION_IDENTITY"
    assert named == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing-context",
        "missing-mode",
        "invalid-context-source",
        "different-context",
        "different-workflow",
        "different-id",
        "different-mode",
        "missing-data",
        "missing-initialize",
        "duplicate-initialize",
        "legacy-initialize",
        "stale-retry",
    ],
)
def test_source_lookup_fails_closed_on_missing_pruned_or_replaced_execution(workflow, fault):
    run = initialize(workflow)
    trigger = _trigger("SYNTHETIC_PRIVATE_ERROR", execution_id="42")
    saved = _saved_execution(trigger, run)
    if fault == "missing-context":
        trigger["execution"].pop("executionContext")
    elif fault == "missing-mode":
        trigger["execution"].pop("mode")
        saved.pop("mode")
    elif fault == "invalid-context-source":
        trigger["execution"]["executionContext"]["source"] = "unsupported"
    elif fault == "different-context":
        saved["data"]["executionData"]["runtimeData"] = {
            **saved["data"]["executionData"]["runtimeData"],
            "establishedAt": 1787290212000,
        }
    elif fault == "different-workflow":
        saved["workflowId"] = "different"
    elif fault == "different-id":
        saved["id"] = "43"
    elif fault == "different-mode":
        saved["mode"] = "retry"
    elif fault == "missing-data":
        saved.pop("data")
    elif fault == "missing-initialize":
        saved["data"]["resultData"]["runData"] = {}
    elif fault == "duplicate-initialize":
        saved["data"]["resultData"]["runData"]["Initialize Run"] *= 2
    elif fault == "legacy-initialize":
        run["run_id"] = "n8n-execution:42"
    elif fault == "stale-retry":
        run["run_id"] = _run_id("41")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_error_classifier(trigger, [], run=run, saved=saved)
    assert failure.value.stderr in {"SOURCE_RUN_IDENTITY_UNAVAILABLE", "STALE_EXECUTION_IDENTITY"}
    assert failure.value.stdout == ""
    assert "SYNTHETIC_PRIVATE_ERROR" not in failure.value.stderr


@pytest.mark.parametrize("identity", [None, "", 42, True, {}, [], "42/other", " 42", "x" * 129])
def test_both_entry_points_reject_invalid_execution_identity(workflow, identity):
    for exported, node, named in [
        (workflow, "Initialize Run", {}),
        (
            _load(ERROR_PATH),
            "Validate Source Execution ID",
            {
                "Workflow Error Trigger": [_trigger("private", execution_id=identity)],
            },
        ),
    ]:
        with pytest.raises(subprocess.CalledProcessError) as failure:
            _run_code_node(exported, node, named_rows=named, input_rows=[{}], execution_id=identity)
        assert failure.value.stderr == "SOURCE_EXECUTION_ID_UNAVAILABLE"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_lookup_transport_failure_has_explicit_sanitized_diagnostic(status):
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_code_node(
            _load(ERROR_PATH),
            "Resolve Source Execution",
            named_rows={"Workflow Error Trigger": [_trigger("private")]},
            input_rows=[{"statusCode": status, "body": {"message": "private"}}],
        )
    assert failure.value.stderr == "SOURCE_RUN_IDENTITY_UNAVAILABLE"


def test_all_generated_error_copies_match_shared_source():
    import importlib.util

    from test_operations import ROOT

    spec = importlib.util.spec_from_file_location(
        "build_validation", ROOT / "scripts/build-workflow-validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for node in _load(ERROR_PATH)["nodes"]:
        if node["type"] != "n8n-nodes-base.code":
            continue
        path = module.code_node_source_path("finary-error-handler.json", node["name"])
        assert path.is_file()
        assert node["parameters"]["jsCode"] == module.expected_code(
            "finary-error-handler.json", node["name"]
        )
    fetch = next(n for n in _load(ERROR_PATH)["nodes"] if n["name"] == "Fetch Source Execution")
    assert fetch["executeOnce"] and fetch["maxTries"] == 3
    assert fetch["parameters"]["options"]["timeout"] == 10000
    assert fetch["parameters"]["nodeCredentialType"] == "n8nApi"
    assert "127.0.0.1:5678/api/v1/executions/" in fetch["parameters"]["url"]
    assert "credentials" not in fetch
    assert "retryOf" not in json.dumps(fetch)


@pytest.mark.parametrize("nonce", ["", "bad", "0" * 36, "00000000-0000-0000-0000-000000000000"])
def test_invalid_entropy_emits_no_identity(workflow, nonce):
    with pytest.raises(subprocess.CalledProcessError) as failure:
        initialize(workflow, nonce=nonce)
    assert failure.value.stderr == "RUN_IDENTITY_UNAVAILABLE"
    assert failure.value.stdout == ""


@pytest.mark.parametrize("status", ["SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED"])
def test_legacy_database_id_does_not_suppress_new_failures(workflow, schema, status):
    run = initialize(workflow)
    book = _empty_workbook()
    old = _prepare_for_run(workflow, schema, restore_snapshot(), book, run["run_id"])[
        "sync_run_rows"
    ][0]
    old = {**old, "run_id": "n8n-execution:42", "status": status}
    book["sync_runs"] = [old]
    before = deepcopy(book)
    assert _prepare_for_run(workflow, schema, restore_snapshot(), book, run["run_id"])[
        "account_rows"
    ]
    assert error_for(run, book["sync_runs"])["should_record"]
    assert book == before


def test_duplicate_terminal_records_are_not_treated_as_legitimate_replay(workflow, schema):
    run = initialize(workflow)
    book = _empty_workbook()
    row = _prepare_for_run(workflow, schema, restore_snapshot(), book, run["run_id"])[
        "sync_run_rows"
    ][0]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        error_for(run, [row, deepcopy(row)])
    assert failure.value.stderr == "RUN_IDENTITY_COLLISION"
