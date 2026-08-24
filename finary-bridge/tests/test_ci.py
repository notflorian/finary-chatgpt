"""Credential-free regression checks for the CI boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

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
    for job in ("tests", "static-analysis", "repository-contracts", "n8n-import"):
        assert f"  {job}:\n" in ci
        assert f"    name: {job}\n" in ci
    assert ci.count("timeout-minutes:") == 4


def test_actions_and_runtime_versions_are_immutable_and_explicit() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    action_lines = [line.strip() for line in ci.splitlines() if "uses: actions/" in line]

    assert action_lines
    assert all(ACTION_REFERENCE.fullmatch(line) for line in action_lines)
    assert 'python-version: "3.12.14"' in ci
    assert 'node-version: "22.23.2"' in ci
    assert ci.count("persist-credentials: false") == 4


def test_ci_explicitly_excludes_live_tests_and_references_no_secrets() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")

    assert 'python -m pytest -m "not live" --ignore=tests/live' in ci
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
    assert "cache:" not in ci


def test_repository_contract_commands_are_quiet_and_dependency_free() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    validator = JSON_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert "python scripts/validate-json.py" in ci
    assert "docker compose config --quiet" in ci
    assert "google-sheets-schema.json" in validator
    assert "finary-daily-sync.json" in validator
    assert "finary-error-handler.json" in validator
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
    assert "finary-daily-sync.json" in validator
    assert "finary-error-handler.json" in validator
    assert "n8n_data" not in validator
    assert "finary_session_data" not in validator
    subprocess.run(["bash", "-n", str(N8N_VALIDATOR_PATH)], cwd=ROOT, check=True)


def test_ci_does_not_activate_the_daily_workflow() -> None:
    daily = json.loads(
        (ROOT / "n8n" / "workflows" / "finary-daily-sync.json").read_text(encoding="utf-8")
    )
    ci = CI_PATH.read_text(encoding="utf-8")
    validator = N8N_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert daily["active"] is False
    assert "--activeState=fromJson" not in validator
    assert "activate:workflow" not in validator
    assert "publish:workflow" not in validator
    assert "docker compose up" not in ci
