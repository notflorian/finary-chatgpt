#!/usr/bin/env python3
"""Prove CI pytest shard unions match their unsharded collections exactly."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
BRIDGE = ROOT / "finary-bridge"
SUITES = {
    "main": [
        "-m",
        "not live",
        "--ignore=tests/live",
        "--ignore=tests/test_mcp_oauth_docker.py",
    ],
    "runtime": [
        "tests/test_n8n_runtime_support.py",
        "tests/test_mcp_runtime.py",
    ],
}


def collect(arguments: list[str], shard: str | None = None) -> set[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", *arguments]
    if shard is not None:
        command.append(f"--ci-shard={shard}")
    completed = subprocess.run(
        command,
        cwd=BRIDGE,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        line
        for line in completed.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }


def validate(name: str, arguments: list[str]) -> None:
    unsharded = collect(arguments)
    shards = [collect(arguments, f"{index}/2") for index in range(2)]
    if not unsharded or any(not shard for shard in shards):
        raise SystemExit(f"{name}: unsharded collection or a shard is unexpectedly empty")
    if shards[0] & shards[1]:
        raise SystemExit(f"{name}: shard intersection is not empty")
    if shards[0] | shards[1] != unsharded:
        raise SystemExit(f"{name}: shard union differs from unsharded collection")
    print(f"{name}: {len(unsharded)} tests split as {len(shards[0])} + {len(shards[1])}")


def main() -> None:
    requested = sys.argv[1:] or list(SUITES)
    unknown = set(requested) - set(SUITES)
    if unknown:
        raise SystemExit(f"unknown suite: {', '.join(sorted(unknown))}")
    for name in requested:
        validate(name, SUITES[name])


if __name__ == "__main__":
    main()
