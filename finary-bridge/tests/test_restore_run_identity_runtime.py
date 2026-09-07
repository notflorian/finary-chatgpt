"""Pinned n8n engine and dispatcher proofs with synthetic external transports.

Fresh disposable SQLite databases intentionally reuse numeric execution IDs.
The actual pinned error dispatcher creates the source trigger payload; only its
service delivery and external HTTP/Sheets I/O are replaced. No backup restore,
production API call, workflow publication or project volume is performed.
"""

import json
import re
import subprocess
from copy import deepcopy
from datetime import datetime

import pytest
from test_n8n_workflow_v2 import _empty_workbook, _known_eur_snapshot, _upsert
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow
from test_n8n_zero_position_runtime import WRITES, _execute, _output, _substitute_io
from test_n8n_zero_position_runtime import runtime_image as runtime_image
from test_net_worth_baseline import WARNING, _retained_identity_baseline
from test_operations import ERROR_PATH, _load
from test_restore_run_identity import NEXT, NOW, restore_snapshot
from workbook_consumer import select_assets, validated_daily

# Invoke the installed dispatcher unchanged; intercept its final delivery only.
DISPATCH = r"""
const fs = require('fs');
const base = '/usr/local/lib/node_modules/n8n';
const {Container} = require(require.resolve('@n8n/di', {paths:[base]}));
const original = Container.get.bind(Container);
let delivered;
const done = new Promise(resolve => { delivered = resolve; });
Container.get = function(type) {
  if (type.name === 'WorkflowExecutionService') return {
    executeErrorWorkflow: async (id, payload) => delivered(payload),
  };
  if (type.name === 'OwnershipService') return {getWorkflowProjectCached: async () => ({})};
  if (type.name === 'UrlService') return {getInstanceBaseUrl: () => 'http://localhost:5678'};
  return original(type);
};
const dispatcher = base + '/dist/execution-lifecycle/execute-error-workflow.js';
const {executeErrorWorkflow} = require(dispatcher);
const input = JSON.parse(fs.readFileSync('/tmp/source.json', 'utf8'));
executeErrorWorkflow(input.workflow, input.execution, input.execution.mode, input.id);
const timeout = setTimeout(() => {
  process.stderr.write('NO_ERROR_DELIVERY'); process.exit(2);
}, 15000);
done.then(payload => {
  clearTimeout(timeout);
  process.stdout.write('\nSYNTHETIC_TRIGGER=' + JSON.stringify(payload) + '\n');
}).catch(() => process.exit(2));
"""


def _dispatch(tmp_path, image, exported, execution):
    origin = _output(execution["data"]["resultData"]["runData"], "Initialize Run")[0]
    source_id = origin["run_id"].split(":")[1]
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "workflow": {
                    **exported,
                    "settings": {**exported["settings"], "errorWorkflow": "synthetic-error"},
                },
                "execution": execution,
                "id": source_id,
            }
        )
    )
    script = tmp_path / "dispatch.js"
    script.write_text(DISPATCH)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "-e",
            "N8N_USER_FOLDER=/tmp/n8n-dispatch",
            "-e",
            "N8N_ENCRYPTION_KEY=synthetic-dispatch-only-key",
            "-e",
            "N8N_DIAGNOSTICS_ENABLED=false",
            "--mount",
            f"type=bind,src={source},dst=/tmp/source.json,readonly",
            "--mount",
            f"type=bind,src={script},dst=/tmp/dispatch.js,readonly",
            "--entrypoint",
            "node",
            image,
            "/tmp/dispatch.js",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    payload = re.search(r"(?m)^SYNTHETIC_TRIGGER=(.*)$", result.stdout)
    assert result.returncode == 0 and payload, result.stdout[-2000:] + result.stderr[-2000:]
    trigger = json.loads(payload[1])
    assert trigger["execution"]["id"] == source_id
    assert (
        trigger["execution"]["executionContext"]
        == execution["data"]["executionData"]["runtimeData"]
    )
    assert "startedAt" not in trigger["execution"]
    saved = {**execution, "id": source_id, "workflowId": exported["id"]}
    return trigger, saved, origin


def _error_io(trigger, saved, schema, terminal_rows):
    exported = _load(ERROR_PATH)
    exported["id"] = "SyntheticErrorIdentity"
    exported["name"] = "Synthetic error identity runtime"
    for node in exported["nodes"]:
        kind = node["type"]
        name = node["name"]
        if kind == "n8n-nodes-base.errorTrigger":
            code = f"return [{{json:{json.dumps(trigger)}}}];"
        elif kind == "n8n-nodes-base.httpRequest":
            body = saved if name == "Fetch Source Execution" else schema
            code = f"return [{{json:{{statusCode:200,body:{json.dumps(body)}}}}}];"
        elif kind == "n8n-nodes-base.googleSheets":
            code = (
                f"return {json.dumps(terminal_rows)}.map(json => ({{json}}));"
                if name == "Read Sync Runs"
                else "return $input.all();"
            )
        else:
            continue
        node["type"] = "n8n-nodes-base.code"
        node["typeVersion"] = 2
        node["parameters"] = {"mode": "runOnceForAllItems", "jsCode": code}
    exported["nodes"].append(
        {
            "id": "synthetic-error-input",
            "name": "Synthetic Error Input",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [-220, 0],
            "parameters": {},
        }
    )
    exported["connections"]["Synthetic Error Input"] = {
        "main": [[{"node": "Workflow Error Trigger", "type": "main", "index": 0}]],
    }
    return exported


def _apply_execution(book, schema, execution):
    data = execution["data"]["resultData"]["runData"]
    for name in sorted(
        (name for name in WRITES if name in data),
        key=lambda name: data[name][0]["executionIndex"],
    ):
        if "error" in data[name][0] or "data" not in data[name][0]:
            continue
        sheet = WRITES[name]
        book[sheet] = _upsert(
            book[sheet], _output(data, name), schema["sheets"][sheet]["unique_key"]
        )
    return data


@pytest.mark.parametrize("complete", [False, True])
def test_fresh_database_id_reuse_and_actual_error_graph(
    runtime_image, tmp_path, workflow, schema, complete
):
    book = _empty_workbook()
    first_export = _substitute_io(workflow, schema, restore_snapshot(), book)
    first = _execute(tmp_path, runtime_image, first_export)
    assert not first["data"]["resultData"].get("error")
    first_data = _apply_execution(book, schema, first)
    old = deepcopy(book["sync_runs"][0])
    second_export = _substitute_io(
        workflow,
        schema,
        restore_snapshot(NEXT, 160),
        book,
        fail_at=None if complete else "Upsert Position History",
    )
    second = _execute(tmp_path, runtime_image, second_export)
    second_data = _apply_execution(book, schema, second)
    a = _output(first_data, "Initialize Run")[0]
    b = _output(second_data, "Initialize Run")[0]
    assert a["run_id"].split(":")[1] == b["run_id"].split(":")[1] == "1"
    assert a["run_id"] != b["run_id"]  # Real crypto, fresh databases, same numeric ID.
    assert book["sync_runs"][0] == old
    assert validated_daily(book, book["portfolio_daily"][0]) is not None
    state = select_assets(book, now=NOW)
    if complete:
        assert len(book["sync_runs"]) == 2 and state.current_complete
        assert state.positions[0]["market_value_eur"] == 160
        return
    assert not state.current_complete and state.source == "history"
    assert state.history[0]["market_value_eur"] == 150
    trigger, saved, origin = _dispatch(tmp_path, runtime_image, second_export, second)
    handler = _execute(
        tmp_path, runtime_image, _error_io(trigger, saved, schema, book["sync_runs"])
    )
    data = handler["data"]["resultData"]
    assert not data.get("error"), data.get("error")
    row = _output(data["runData"], "Record Operational Failure")[0]
    assert row["run_id"] == origin["run_id"] and row["started_at"] == origin["started_at"]
    assert row["gross_assets_eur"] == "" and row["status"] == "FAILED"
    assert _output(data["runData"], "Prepare Sanitized Failure")[0]["should_record"]
    book["sync_runs"].append(row)
    # Replay the same actual trigger through Code/If nodes: no second terminal write.
    replay = _execute(tmp_path, runtime_image, _error_io(trigger, saved, schema, book["sync_runs"]))
    replay_data = replay["data"]["resultData"]
    assert not replay_data.get("error")
    assert not _output(replay_data["runData"], "Prepare Sanitized Failure")[0]["should_record"]
    assert "Record Operational Failure" not in replay_data["runData"]


@pytest.mark.parametrize("path", ["prewrite", "success", "invalid-snapshot"])
def test_runtime_collision_stops_portfolio_or_terminal_writes(
    runtime_image, tmp_path, workflow, schema, path
):
    snapshot = restore_snapshot() if path != "invalid-snapshot" else {"invalid": True}
    exported = _substitute_io(workflow, schema, snapshot, _empty_workbook())
    target = {
        "prewrite": "Read Sync Runs",
        "success": "Read Terminal Before Success",
        "invalid-snapshot": "Read Terminal Before Failure",
    }[path]
    for node in exported["nodes"]:
        if node["name"] == target:
            node["parameters"]["jsCode"] = (
                "return [{json:{run_id:$('Initialize Run').first().json.run_id,"
                "started_at:'2026-01-01T00:00:00Z',status:'SUCCESS'}}];"
            )
    execution = _execute(tmp_path, runtime_image, exported)
    result = execution["data"]["resultData"]
    assert result["error"]["message"].startswith("RUN_IDENTITY_COLLISION")
    assert "Record Successful Sync" not in result["runData"]
    assert "Record Failed Sync" not in result["runData"]
    if path != "success":
        assert not set(WRITES) & result["runData"].keys()
    else:
        assert "Upsert Portfolio Daily" in result["runData"]


def test_runtime_terminal_response_loss_retains_payload(runtime_image, tmp_path, workflow, schema):
    exported = _substitute_io(workflow, schema, restore_snapshot(), _empty_workbook())
    for node in exported["nodes"]:
        if node["name"] == "Record Successful Sync":
            node["parameters"]["jsCode"] = """
const fs = require('fs');
const path = '/tmp/synthetic-terminal.json';
const payload = JSON.stringify($input.all());
if (!fs.existsSync(path)) {
  fs.writeFileSync(path, payload, {mode: 0o600});
  throw new Error('SYNTHETIC_RESPONSE_LOST_AFTER_PERSISTENCE');
}
if (fs.readFileSync(path, 'utf8') !== payload) throw new Error('TERMINAL_PAYLOAD_CHANGED');
return $input.all();
"""
    execution = _execute(tmp_path, runtime_image, exported, allow_file_io=True)
    result = execution["data"]["resultData"]
    assert not result.get("error"), result.get("error")
    data = result["runData"]
    assert len(data["Initialize Run"]) == len(data["Select Success Run"]) == 1
    assert _output(data, "Record Successful Sync") == _output(data, "Select Success Run")
    # n8n reports the successful attempt's node duration, excluding retry waits.
    elapsed = datetime.fromisoformat(execution["stoppedAt"].replace("Z", "+00:00")) - (
        datetime.fromisoformat(execution["startedAt"].replace("Z", "+00:00"))
    )
    assert elapsed.total_seconds() >= 5


@pytest.mark.parametrize("case", ["before-writes", "lost-success", "replaced-source"])
def test_runtime_error_identity_boundaries(runtime_image, tmp_path, workflow, schema, case):
    book = _empty_workbook()
    exported = _substitute_io(
        workflow,
        schema,
        restore_snapshot(),
        book,
        fail_at="Record Successful Sync" if case == "lost-success" else None,
    )
    if case != "lost-success":
        next(n for n in exported["nodes"] if n["name"] == "Read Current Accounts")["parameters"][
            "jsCode"
        ] = "throw new Error('SYNTHETIC_READ_FAILURE');"
    execution = _execute(tmp_path, runtime_image, exported)
    result = execution["data"]["resultData"]
    assert result.get("error")
    if case == "lost-success":
        # The external write persisted but every response was lost.
        book["sync_runs"] = _output(result["runData"], "Select Success Run")
    else:
        assert not set(WRITES) & result["runData"].keys()
    trigger, saved, origin = _dispatch(tmp_path, runtime_image, exported, execution)
    if case == "replaced-source":
        saved = deepcopy(saved)
        saved["data"]["executionData"]["runtimeData"]["establishedAt"] += 1
    handler = _execute(
        tmp_path, runtime_image, _error_io(trigger, saved, schema, book["sync_runs"])
    )
    handled = handler["data"]["resultData"]
    if case == "replaced-source":
        assert handled["error"]["message"].startswith("SOURCE_RUN_IDENTITY_UNAVAILABLE")
        assert "Record Operational Failure" not in handled["runData"]
        return
    assert not handled.get("error"), handled.get("error")
    classification = _output(handled["runData"], "Prepare Sanitized Failure")[0]
    assert classification["row"]["run_id"] == origin["run_id"]
    assert classification["should_record"] is (case == "before-writes")
    assert ("Record Operational Failure" in handled["runData"]) is (case == "before-writes")
    if case == "lost-success":
        assert book["sync_runs"] == _output(result["runData"], "Select Success Run")


def test_runtime_missing_crypto_fails_without_any_write(runtime_image, tmp_path, workflow, schema):
    exported = _substitute_io(workflow, schema, restore_snapshot(), _empty_workbook())
    execution = _execute(tmp_path, runtime_image, exported, allow_crypto=False)
    result = execution["data"]["resultData"]
    assert result["error"]["message"].startswith("RUN_IDENTITY_UNAVAILABLE")
    assert not set(WRITES) & result["runData"].keys()


def test_runtime_reused_number_retains_legacy_net_worth_baseline(
    runtime_image, tmp_path, workflow, schema
):
    book = _retained_identity_baseline(workflow, schema, "n8n-execution:1", older=True)
    retained = deepcopy(book)
    snapshot = _known_eur_snapshot("2026-09-05T12:00:00Z", first_value=170)
    assert snapshot["coverage"]["liabilities"] == "COMPLETE"
    assert snapshot["net_worth_eur"] == 210
    exported = _substitute_io(workflow, schema, snapshot, book)
    execution = _execute(tmp_path, runtime_image, exported)
    assert not execution["data"]["resultData"].get("error")
    data = _apply_execution(book, schema, execution)
    run = _output(data, "Initialize Run")[0]
    assert run["run_id"].startswith("n8n-run:1:")
    prepared = _output(data, "Prepare Validated Rows")[0]
    assert WARNING in prepared["warnings"]
    terminal = _output(data, "Record Successful Sync")[0]
    assert terminal["run_id"] == run["run_id"]
    assert terminal["previous_net_worth_eur"] == 140
    assert terminal["net_worth_change_pct"] == 0.5
    assert terminal["status"] == "SUCCESS_WITH_WARNINGS"
    assert WARNING in terminal["error_message"]
    for sheet in ("portfolio_daily", "positions_history", "sync_runs"):
        assert book[sheet][: len(retained[sheet])] == retained[sheet]
    assert len(book["sync_runs"]) == 3
    assert validated_daily(book, retained["portfolio_daily"][-1]) is not None
