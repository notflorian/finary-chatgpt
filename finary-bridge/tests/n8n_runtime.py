"""Compose-pinned engine support using disposable network-disabled containers."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def runtime_image():
    image = re.search(r"image: (n8nio/n8n:[^\s]+)", (ROOT / "docker-compose.yml").read_text())[1]
    assert image.startswith("n8nio/n8n:2.35.5@sha256:")
    required = os.environ.get("FINARY_REQUIRE_N8N_RUNTIME") == "1"
    if shutil.which("docker"):
        check = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=15
        )
        if check.returncode == 0:
            return image
    if required:
        pytest.fail("Compose-pinned n8n Docker runtime is required but unavailable")
    pytest.skip("Compose-pinned n8n Docker runtime unavailable; required in isolated CI")


def _execute(
    tmp_path,
    image,
    exported,
    *,
    allow_crypto=True,
    allow_file_io=False,
    environment=None,
    http_payloads=None,
):
    fixture = tmp_path / "workflow.json"
    fixture.write_text(json.dumps(exported))
    server_prefix = ""
    if http_payloads is not None:
        server = tmp_path / "http-server.js"
        server.write_text(
            "const payloads=" + json.dumps(http_payloads) + ";"
            "require('http').createServer((req,res)=>{"
            "res.writeHead(200,{'Content-Type':'application/json'});"
            "res.end(JSON.stringify(payloads[req.url]));"
            "}).listen(8766,'127.0.0.1');"
        )
        server_prefix = "node /tmp/http-server.js & "
    # n8n persists a genuine execution ID in an ephemeral SQLite database.
    container_name = f"finary-mcp-runtime-{uuid4().hex}"
    command = [
        "docker",
        "run",
        "--name",
        container_name,
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "-e",
        "N8N_USER_FOLDER=/tmp/n8n-synthetic",
        "-e",
        "N8N_DIAGNOSTICS_ENABLED=false",
        "-e",
        "N8N_ENCRYPTION_KEY=synthetic-runtime-only-key",
        "-e",
        "N8N_PERSONALIZATION_ENABLED=false",
        "-e",
        "N8N_LOG_LEVEL=info",
        "-e",
        "NODE_FUNCTION_ALLOW_BUILTIN="
        + ",".join((["crypto"] if allow_crypto else []) + (["fs"] if allow_file_io else [])),
        "--mount",
        f"type=bind,src={fixture},dst=/tmp/workflow.json,readonly",
        "--entrypoint",
        "sh",
        image,
        "-c",
        server_prefix + "n8n import:workflow --input=/tmp/workflow.json >/tmp/import.log 2>&1 "
        f"&& n8n execute --id={exported['id']} --rawOutput >/tmp/execution.log 2>&1; "
        "execution_status=$?; "
        "if [ -f /tmp/execution.log ]; then cat /tmp/execution.log; "
        'else cat /tmp/import.log; fi; exit "$execution_status"',
    ]
    if http_payloads is not None:
        command[2:2] = ["--mount", f"type=bind,src={server},dst=/tmp/http-server.js,readonly"]
    for name, value in (environment or {}).items():
        command[2:2] = ["-e", f"{name}={value}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=150)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=15)
    # File-backed CLI output survives n8n's process.exit under pipe backpressure.
    # cat drains it before exiting; logs and failed executions still contain runData.
    for match in re.finditer(r"(?m)^\{", result.stdout):
        try:
            execution, _ = json.JSONDecoder().raw_decode(result.stdout[match.start() :])
        except json.JSONDecodeError:
            continue
        if "resultData" in execution.get("data", {}):
            return execution
    pytest.fail(f"No n8n execution evidence: {result.stdout[-4000:]} {result.stderr[-2000:]}")


def _output(run_data, name):
    calls = run_data[name]
    assert len(calls) == 1, f"Duplicate execution: {name}"
    return [item["json"] for item in calls[0]["data"]["main"][0]]
