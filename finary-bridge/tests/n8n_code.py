"""Execute individual exported Code nodes with controlled synthetic context."""

import json
import shutil
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest


def _node(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def _nonce(execution_id: str) -> str:
    # Controlled entropy for exported-node tests; engine tests use real crypto.
    return str(UUID(bytes=uuid5(NAMESPACE_URL, str(execution_id)).bytes, version=4))


def _run_code_node(
    workflow: dict[str, Any],
    node_name: str,
    *,
    named_rows: dict[str, list[dict[str, Any]]],
    input_rows: list[dict[str, Any]],
    execution_id: str = "test-execution",
    now: str | None = None,
    clock_step_ms: int = 0,
    setup_js: str = "",
    nonce: str | None = None,
) -> list[dict[str, Any]]:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to execute n8n Code node tests")
    code = _node(workflow, node_name)["parameters"]["jsCode"]
    controlled_nonce = nonce if nonce is not None else _nonce(execution_id)
    harness = f"""
require('crypto').randomUUID = () => {json.dumps(controlled_nonce)};
const namedRows = {json.dumps(named_rows)};
const inputRows = {json.dumps(input_rows)};
const $execution = {{ id: {json.dumps(execution_id)}, mode: 'test' }};
const fixedNow = {json.dumps(now)};
const NativeDate = Date;
let clockReads = 0;
const readClock = () => new NativeDate(fixedNow).getTime() + clockReads++ * {clock_step_ms};
if (fixedNow !== null) {{
  globalThis.Date = class extends NativeDate {{
    constructor(...args) {{ super(...(args.length ? args : [readClock()])); }}
    static now() {{ return readClock(); }}
  }};
}}
const $ = (name) => ({{
  first: () => ({{ json: (namedRows[name] || [{{}}])[0] }}),
  all: () => (namedRows[name] || []).map((json) => ({{ json }})),
}});
const $input = {{
  first: () => ({{ json: inputRows[0] || {{}} }}),
  all: () => inputRows.map((json) => ({{ json }})),
}};
{setup_js}
(async () => {{
{code}
}})().then((result) => process.stdout.write(JSON.stringify(result))).catch((error) => {{
  process.stderr.write(String(error && error.message ? error.message : error));
  process.exit(2);
}});
"""
    completed = subprocess.run(  # noqa: S603
        ["node"],
        input=harness,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_mcp_validation_probe(body, input_rows, *, node_name="Validate MCP Snapshot"):
    """Probe the actual exported library; full-node and engine tests keep their boundaries."""
    from copy import deepcopy

    from mcp_artifacts import ROOT, SCHEMA, WORKFLOW

    workflow = deepcopy(WORKFLOW)
    node = _node(workflow, node_name)
    filename = "-".join(node_name.lower().split()) + ".js"
    entry = (ROOT / "n8n/code-nodes/finary-mcp-sync" / filename).read_text()
    assert node["parameters"]["jsCode"].endswith(entry)
    node["parameters"]["jsCode"] = node["parameters"]["jsCode"].removesuffix(entry) + body
    return _run_code_node(
        workflow,
        node_name,
        named_rows={"Validate MCP Snapshot": [{"schema": deepcopy(SCHEMA)}]},
        input_rows=input_rows,
    )
