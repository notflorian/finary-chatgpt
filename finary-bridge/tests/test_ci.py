"""Credential-free regression checks for the CI boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
JSON_VALIDATOR_PATH = ROOT / "scripts" / "validate-json.py"
N8N_VALIDATOR_PATH = ROOT / "scripts" / "validate-n8n-imports.sh"

ACTION_REFERENCE = re.compile(r"uses: actions/[a-z-]+@([0-9a-f]{40})(?:\s+#\s+v\d[^\s]*)?")


def test_ci_has_stable_read_only_jobs_and_safe_triggers() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")

    assert "  pull_request:\n" in ci
    assert "  push:\n" in ci
    assert "      - main\n" in ci
    assert "pull_request_target" not in ci
    assert "schedule:" not in ci
    assert "workflow_dispatch:" not in ci
    assert "permissions:\n  contents: read\n" in ci
    assert "contents: write" not in ci
    assert "id-token: write" not in ci
    assert "runs-on: ubuntu-latest" in ci
    for job in (
        "tests-shard",
        "tests",
        "mcp-validation-python314",
        "static-analysis",
        "repository-contracts",
        "n8n-runtime-shard",
        "n8n-shard-validation",
        "n8n-import",
        "oauth-ownership",
        "release-artifacts",
    ):
        assert f"  {job}:\n" in ci
    for stable_name in (
        "tests",
        "mcp-validation-python314",
        "static-analysis",
        "repository-contracts",
        "n8n-import",
        "oauth-ownership",
        "release-artifacts",
    ):
        assert f"    name: {stable_name}\n" in ci
    assert ci.count("timeout-minutes:") == 10


def test_actions_and_runtime_versions_are_immutable_and_explicit() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    action_lines = [line.strip() for line in ci.splitlines() if "uses: actions/" in line]

    assert action_lines
    assert all(ACTION_REFERENCE.fullmatch(line) for line in action_lines)
    assert 'python-version: "3.12.14"' in ci
    assert 'node-version: "22.23.2"' in ci
    assert ci.count("persist-credentials: false") == 8
    assert ci.count("cache: pip") == 6
    assert ci.count("cache-dependency-path: finary-bridge/pyproject.toml") == 6


def test_ci_explicitly_excludes_live_tests_and_references_no_secrets() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")

    assert 'python -m pytest -m "not live" --ignore=tests/live' in ci
    job = ci.split("  tests-shard:", 1)[1].split("  tests:", 1)[0]
    assert 'PYTEST_XDIST_WORKER_COUNT: "4"' in job
    assert "--ignore=tests/test_mcp_oauth_docker.py" in job
    assert "--ci-shard=${{ matrix.shard }}" in job
    assert (
        "-n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15"
    ) in " ".join(job.split())
    assert "FINARY_LIVE_TEST" not in ci
    assert "FINARY_LIVE_SESSION_TEST" not in ci
    assert "FINARY_LIVE_DESCRIBE" not in ci
    assert "secrets." not in ci
    for variable in (
        "FINARY_EMAIL",
        "FINARY_PASSWORD",
        "FINARY_MFA_CODE",
        "FINARY_SESSION_PATH",
        "FINARY_BRIDGE_API_KEY",
        "FINARY_GOOGLE_SHEET_ID",
        "N8N_ENCRYPTION_KEY",
    ):
        assert variable not in ci
    assert "self-hosted" not in ci
    assert "docker compose up" not in ci
    assert "upload-artifact" not in ci


def test_ci_cancels_only_superseded_runs_for_the_same_pull_request() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")

    group = "group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
    assert group in ci
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in ci


def test_repository_contract_commands_are_quiet_and_dependency_free() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    validator = JSON_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert "python scripts/validate-json.py" in ci
    assert "docker compose config --quiet" in ci
    assert "finary-mcp-sync.json" in validator
    subprocess.run([sys.executable, str(JSON_VALIDATOR_PATH)], cwd=ROOT, check=True)


def test_n8n_import_validation_is_compose_pinned_isolated_and_ephemeral() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    validator = N8N_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert "bash scripts/validate-n8n-imports.sh" in ci
    assert "docker compose config --images" in validator
    assert "n8nio/n8n:2.35.5@sha256:" in validator
    assert "--network none" in validator
    assert "--pull never" in validator
    assert "N8N_USER_FOLDER=/tmp/n8n-ci" in validator
    assert "N8N_ENCRYPTION_KEY=ci-only-synthetic-import-key" in validator
    assert "finary-mcp-sync.json" in validator
    assert "n8n_data" not in validator
    assert "finary_session_data" not in validator
    subprocess.run(["bash", "-n", str(N8N_VALIDATOR_PATH)], cwd=ROOT, check=True)


def test_ci_does_not_activate_the_daily_workflow() -> None:
    daily = json.loads(
        (ROOT / "n8n" / "workflows" / "finary-mcp-sync.json").read_text(encoding="utf-8")
    )
    ci = CI_PATH.read_text(encoding="utf-8")
    validator = N8N_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert daily["active"] is False
    assert "--activeState=fromJson" not in validator
    assert "activate:workflow" not in validator
    assert "publish:workflow" not in validator
    assert "docker compose up" not in ci


def test_ci_requires_sharded_pinned_runtime_execution_and_import_reuse():
    ci = CI_PATH.read_text(encoding="utf-8")
    runtime = ci.split("  n8n-runtime-shard:", 1)[1].split("  n8n-shard-validation:", 1)[0]
    collection = ci.split("  n8n-shard-validation:", 1)[1].split("  n8n-import:", 1)[0]
    aggregate = ci.split("  n8n-import:", 1)[1].split("  oauth-ownership:", 1)[0]

    assert runtime.count('shard: ["0/2", "1/2"]') == 1
    assert "bash scripts/validate-n8n-imports.sh" in runtime
    assert "if: matrix.shard == '0/2'" in runtime
    assert 'Pre-pull Compose-pinned n8n image for runtime shard one' in runtime
    assert 'docker pull "$n8n_image" >/dev/null' in runtime
    assert runtime.count("if: matrix.shard == '1/2'") == 1
    assert 'FINARY_REQUIRE_N8N_RUNTIME: "1"' in runtime
    assert 'PYTEST_XDIST_WORKER_COUNT: "3"' in runtime
    assert "--ci-shard=${{ matrix.shard }}" in runtime
    pytest_cmd = (
        "python -m pytest -q -n auto --maxprocesses 4 --dist worksteal "
        "--max-worker-restart 0 --durations=15"
    )
    assert pytest_cmd in " ".join(runtime.split())
    assert "finary-bridge/tests/test_n8n_runtime_support.py" in runtime
    assert "finary-bridge/tests/test_mcp_runtime.py" in runtime
    assert "python scripts/validate-pytest-shards.py runtime" in collection
    assert "docker" not in collection
    assert "if: ${{ always() }}" in aggregate
    assert "needs: [n8n-runtime-shard, n8n-shard-validation]" in aggregate
    assert 'test "$RUNTIME_RESULT" = success && test "$COLLECTION_RESULT" = success' in aggregate
    assert "continue-on-error" not in aggregate


def test_ci_shards_are_complete_and_aggregate_fail_closed() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    test_shards = ci.split("  tests-shard:", 1)[1].split("  tests:", 1)[0]
    test_aggregate = ci.split("  tests:", 1)[1].split("  mcp-validation-python314:", 1)[0]

    assert test_shards.count('shard: ["0/2", "1/2"]') == 1
    assert "if: ${{ always() }}" in test_aggregate
    assert "needs: tests-shard" in test_aggregate
    assert 'test "$SHARD_RESULT" = success' in test_aggregate
    assert "continue-on-error" not in test_aggregate


@pytest.mark.parametrize(
    "environment,accepted",
    [
        ({"SHARD_RESULT": "success"}, True),
        ({"SHARD_RESULT": "failure"}, False),
        ({"SHARD_RESULT": "cancelled"}, False),
        ({"SHARD_RESULT": "skipped"}, False),
    ],
)
def test_ci_aggregate_shell_guards_accept_only_success(environment, accepted) -> None:
    completed = subprocess.run(
        ["bash", "-c", 'test "$SHARD_RESULT" = success'], env=environment
    )
    assert (completed.returncode == 0) is accepted


@pytest.mark.parametrize(
    "environment,accepted",
    [
        ({"RUNTIME_RESULT": "success", "COLLECTION_RESULT": "success"}, True),
        ({"RUNTIME_RESULT": "failure", "COLLECTION_RESULT": "success"}, False),
        ({"RUNTIME_RESULT": "cancelled", "COLLECTION_RESULT": "success"}, False),
        ({"RUNTIME_RESULT": "skipped", "COLLECTION_RESULT": "success"}, False),
        ({"RUNTIME_RESULT": "success", "COLLECTION_RESULT": "failure"}, False),
        ({"RUNTIME_RESULT": "success", "COLLECTION_RESULT": "cancelled"}, False),
        ({"RUNTIME_RESULT": "success", "COLLECTION_RESULT": "skipped"}, False),
    ],
)
def test_n8n_aggregate_shell_guard_requires_runtime_and_collection_success(
    environment, accepted
) -> None:
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'test "$RUNTIME_RESULT" = success && test "$COLLECTION_RESULT" = success',
        ],
        env=environment,
    )
    assert (completed.returncode == 0) is accepted


def test_python314_compatibility_job_runs_mcp_validation() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    job = ci.split("  mcp-validation-python314:", 1)[1].split("  static-analysis:", 1)[0]
    assert 'python-version: "3.14.6"' in job
    assert (
        "-n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15"
    ) in " ".join(job.split())
    assert "timeout-minutes: 10" in job
    assert 'python -m pip install -e ".[dev]"' in job
    selected = re.findall(r"tests/test_[a-z_]+\.py", job)
    assert set(selected) == {
        "tests/test_mcp_contract.py", "tests/test_mcp_auth.py", "tests/test_mcp_integration.py",
        "tests/test_mcp_optional.py", "tests/test_mcp_precision.py", "tests/test_mcp_timestamps.py",
        "tests/test_http_boundary.py", "tests/test_health.py", "tests/test_product_baseline.py",
    }
    assert all((ROOT / "finary-bridge" / path).is_file() for path in selected)
    assert "docker" not in job
    assert "n8n" not in job


def test_ci_requires_actual_oauth_ownership_runtime():
    ci = CI_PATH.read_text(encoding="utf-8")
    job = ci.split("  oauth-ownership:", 1)[1]
    assert 'FINARY_REQUIRE_OAUTH_DOCKER: "1"' in job
    assert "python -m pytest -q finary-bridge/tests/test_mcp_oauth_docker.py" in job
    assert "continue-on-error" not in job
    assert "timeout-minutes: 10" in job
