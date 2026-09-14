"""Installed Sheets connector with a synthetic cell transport."""

import json
import select
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def connector(runtime_image):
    """Reuse one short-lived Node process, without starting the n8n server."""
    name = f"finary-sheets-test-{uuid4().hex}"
    script = Path(__file__).with_name("sheets_connector_transport.js")
    process = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--name",
            name,
            "-i",
            "--entrypoint",
            "node",
            "--mount",
            f"type=bind,src={script},dst=/tmp/transport.js,readonly",
            runtime_image,
            "/tmp/transport.js",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def apply(schema, workbook, writes, reads=()):
        process.stdin.write(
            json.dumps({"schema": schema, "workbook": workbook, "writes": writes, "reads": reads})
            + "\n"
        )
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
