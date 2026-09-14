"""Complete CLI evidence under stdout backpressure, including failures."""

import subprocess

import pytest
from n8n_runtime import _execute, _output
from n8n_runtime import runtime_image as runtime_image


@pytest.mark.parametrize("failed", [False, True])
def test_runtime_captures_complete_large_cli_evidence(runtime_image, tmp_path, monkeypatch, failed):
    exported = {
        "id": "SyntheticLargeCliEvidence",
        "name": "Synthetic large CLI evidence",
        "active": False,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {
                "id": "manual",
                "name": "Manual",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "large",
                "name": "Large Evidence",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [200, 0],
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "jsCode": "return [{json:{padding:'x'.repeat(16*1024*1024),end:'END'}}];",
                },
            },
            {
                "id": "finish",
                "name": "Finish",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [400, 0],
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "jsCode": "throw new Error('SYNTHETIC_FAILURE');"
                    if failed
                    else "return [{json:{complete:true}}];",
                },
            },
        ],
        "connections": {
            "Manual": {"main": [[{"node": "Large Evidence", "type": "main", "index": 0}]]},
            "Large Evidence": {"main": [[{"node": "Finish", "type": "main", "index": 0}]]},
        },
    }
    run = subprocess.run

    def slow_output(command, *args, **kwargs):
        if command[:2] == ["docker", "run"]:
            command = list(command)
            # Delay the real CLI's stdout reader to reproduce pipe backpressure.
            command[-1] = (
                "(" + command[-1] + ") | node -e '"
                'process.stdin.once("readable",()=>setTimeout('
                "()=>process.stdin.pipe(process.stdout),10000));'"
            )
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", slow_output)
    execution = _execute(tmp_path, runtime_image, exported)
    result = execution["data"]["resultData"]
    assert bool(result.get("error")) is failed
    assert _output(result["runData"], "Large Evidence") == [
        {"padding": "x" * (16 * 1024 * 1024), "end": "END"}
    ]
    if failed:
        assert result["error"]["message"] == "SYNTHETIC_FAILURE [line 1]"
    else:
        assert _output(result["runData"], "Finish") == [{"complete": True}]
