"""Executable offline operator commands and maintained local documentation links."""

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from mcp_snapshots import NOW
from mcp_workbooks import book_with_two_observations, native_observation, partial_book

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("section", ["Required local checks", "Opt-in diagnostics"])
def test_isolated_compose_commands_preserve_their_environment_boundary(tmp_path, section):
    document = (ROOT / "docs/development.md").read_text()
    section_text = document.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
    blocks = [
        block
        for block in re.findall(r"```bash\n(.*?)```", section_text, flags=re.S)
        if "docker-compose.mcp-test.yml" in block
    ]
    assert len(blocks) == 1, "Expected one explicit isolated Compose command block"
    state = tmp_path / "synthetic operator state"
    state.mkdir(mode=0o700)
    operator = {
        "FINARY_MCP_CANDIDATE_UID": str(os.getuid()),
        "FINARY_MCP_CANDIDATE_GID": str(os.getgid()),
        "FINARY_MCP_TEST_DIR": str(state),
        "FINARY_MCP_CANDIDATE_API_KEY": "synthetic-operator-key",
        "FINARY_MCP_CANDIDATE_WORKBOOK_ID": "synthetic-operator-book",
        "FINARY_MCP_CANDIDATE_WRITER_ID": "synthetic-operator-writer",
        "FINARY_MCP_CANDIDATE_WRITER_GENERATION": "73",
    }
    # Only the substitute executable is on PATH; no inherited shell hooks or secrets.
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "python").symlink_to(sys.executable)
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"names = {[*operator, 'COMPOSE_ENV_FILES']!r}\n"
        "print(json.dumps({'args': sys.argv[1:], "
        "'env': {name: os.environ.get(name) for name in names}, 'cwd': os.getcwd()}))\n"
    )
    docker.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-eu", "-c", blocks[0]],
        cwd=ROOT,
        env={"PATH": str(binary), "HOME": str(tmp_path), **operator},
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert result.stderr == ""
    calls = [json.loads(line) for line in result.stdout.splitlines()]
    expected = {**operator, "COMPOSE_ENV_FILES": "/dev/null"}
    actions = [["config", "--quiet"]]
    if section == "Required local checks":
        expected.update(
            FINARY_MCP_CANDIDATE_UID="1001",
            FINARY_MCP_CANDIDATE_GID="1001",
            FINARY_MCP_TEST_DIR="/tmp",
            FINARY_MCP_CANDIDATE_API_KEY="synthetic-key",
            FINARY_MCP_CANDIDATE_WORKBOOK_ID="synthetic-book",
        )
    else:
        actions.append(["up", "-d", "--build", "--wait"])
    assert calls == [
        {
            "args": [
                "compose", "--env-file", "/dev/null", "-p", "finary-mcp-candidate",
                "-f", "docker-compose.mcp-test.yml", *action,
            ],
            "env": expected,
            "cwd": str(ROOT),
        }
        for action in actions
    ]


def test_local_documentation_links_and_anchors_resolve():
    documents = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *ROOT.glob("docs/*.md"),
        ROOT / ".github/copilot-instructions.md",
        ROOT / ".specify/memory/constitution.md",
    ]
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(), flags=re.S)
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = urlsplit(link)
            if target.scheme or target.netloc:
                continue
            path = (document.parent / unquote(target.path)).resolve() if target.path else document
            assert path.is_file(), (document, link)
            if target.fragment and path.suffix == ".md":
                headings = re.findall(r"^#+ (.+)$", path.read_text(), flags=re.M)
                anchors = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}
                assert unquote(target.fragment) in anchors, (document, link)


def test_readback_command_checks_exported_rows_without_disclosing_values(
    tmp_path, monkeypatch, capsys
):
    native, run_id = native_observation()
    source = tmp_path / "readback.json"
    source.write_text(json.dumps(native))
    before = source.read_bytes()
    script = ROOT / "scripts/check-workbook.py"
    spec = importlib.util.spec_from_file_location("check_workbook", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(sys, "argv", [str(script), "--input", str(source), "--run-id", run_id])
    module.main()
    assert json.loads(capsys.readouterr().out) == {
        "status": "WORKBOOK_READBACK_VALIDATED",
        "current_complete": True,
        "dated_fallback": False,
        "stale": False,
        "series_break": True,
    }
    # The actual CLI also works outside the checkout with the current wall clock.
    command = [sys.executable, str(script), "--input", str(source), "--run-id", run_id]
    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] in {
        "WORKBOOK_READBACK_VALIDATED",
        "WORKBOOK_READBACK_QUALIFIED",
    }
    assert "synthetic" not in completed.stdout + completed.stderr
    assert source.read_bytes() == before
    command[-1] = "synthetic-sensitive-wrong-run"
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert failed.returncode != 0 and failed.stdout == ""
    assert failed.stderr.strip() == "WORKBOOK_READBACK_REVIEW_REQUIRED"
    assert source.read_bytes() == before


@pytest.mark.parametrize("content", ['{"synthetic-secret":', "[]", '{"sheets": [null]}'])
def test_readback_cli_sanitizes_malformed_input(tmp_path, content):
    source = tmp_path / "readback.json"
    source.write_text(content)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check-workbook.py"),
            "--input",
            str(source),
            "--run-id",
            "synthetic-secret",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip() == "WORKBOOK_READBACK_REVIEW_REQUIRED"
    assert source.read_text() == content


def test_documented_shell_commands_parse_and_select_existing_files():
    for document in (ROOT / "docs/operations.md", ROOT / "docs/development.md"):
        for block in re.findall(r"```bash\n(.*?)```", document.read_text(), flags=re.S):
            subprocess.run(["bash", "-n"], input=block, text=True, check=True, capture_output=True)
            for path in re.findall(
                r"(?:scripts|tests|finary-bridge/tests)/[a-zA-Z0-9_./-]+\.py", block
            ):
                base = ROOT / "finary-bridge" if path.startswith("tests/") else ROOT
                assert (base / path).is_file(), (document, path)


def test_documented_oauth_handoff_command_preserves_explicit_arguments(tmp_path):
    document = (ROOT / "docs/operations.md").read_text()
    section = document.split("## Place state in the bridge volume\n", 1)[1].split(
        "\n## ", 1
    )[0]
    blocks = [
        block
        for block in re.findall(r"```bash\n(.*?)```", section, flags=re.S)
        if "handoff-mcp-oauth-state.py" in block
    ]
    assert len(blocks) == 1
    binary = tmp_path / "bin"
    binary.mkdir()
    python = binary / "python"
    python.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], "
        "'project': os.environ.get('COMPOSE_PROJECT_NAME')}))\n"
    )
    python.chmod(0o700)
    staging = tmp_path / "finary-mcp-bootstrap.with spaces;$x"
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-eu", "-c", blocks[0]],
        cwd=ROOT,
        env={
            "PATH": str(binary),
            "HOME": str(tmp_path),
            "MCP_BOOTSTRAP_DIR": str(staging),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "args": [
            "scripts/handoff-mcp-oauth-state.py",
            "--source",
            str(staging / "oauth.json"),
            "--project-name",
            "finary-chatgpt",
            "--cleanup-source",
        ],
        "project": "finary-chatgpt",
    }


@pytest.mark.parametrize("ambiguous", [False, True])
def test_readback_cli_completion_ambiguity_with_fixed_clock(tmp_path, ambiguous):
    book = book_with_two_observations()
    book["sync_runs"][0]["completed_at"] = "2026-09-11T10:00:00+02:00"
    book["sync_runs"][1]["completed_at"] = (
        "2026-09-11T03:00:00-05:00" if ambiguous else "2026-09-11T03:00:01-05:00"
    )
    run_id = book["sync_runs"][1]["run_id"]
    script = ROOT / "scripts/check-workbook.py"
    launcher = (
        "import datetime, runpy, sys\n"
        "from unittest.mock import patch\n"
        "class Clock(datetime.datetime):\n"
        "    @classmethod\n"
        "    def now(cls, tz=None):\n"
        "        return cls.fromisoformat('2026-09-11T08:01:00+00:00')\n"
        "with patch('datetime.datetime', Clock):\n"
        "    sys.argv = sys.argv[1:]\n"
        "    runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    source = tmp_path / "readback.json"
    for _ in range(2):
        native, _ = native_observation(book)
        source.write_text(json.dumps(native))
        result = subprocess.run(
            [sys.executable, "-c", launcher, str(script), "--input", str(source),
             "--run-id", run_id],
            cwd=tmp_path, capture_output=True, text=True, timeout=30,
        )
        if ambiguous:
            assert result.returncode != 0
            assert result.stdout == ""
            assert result.stderr.strip() == "WORKBOOK_READBACK_REVIEW_REQUIRED"
        else:
            assert result.returncode == 0, result.stderr
            assert result.stderr == ""
            assert json.loads(result.stdout) == {
                "status": "WORKBOOK_READBACK_VALIDATED",
                "current_complete": True, "dated_fallback": False,
                "stale": False, "series_break": False,
            }
        book["sync_runs"].reverse()


def test_documented_identity_exports_use_id_not_shell_uid(tmp_path):
    document = (ROOT / "docs/development.md").read_text()
    block = next(block for block in re.findall(r"```bash\n(.*?)```", document, flags=re.S)
                 if 'export FINARY_MCP_CANDIDATE_UID="$(id -u)"' in block)
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-eu", "-c",
         block + '\nprintf "%s:%s" "$FINARY_MCP_CANDIDATE_UID" "$FINARY_MCP_CANDIDATE_GID"'],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=5, check=True,
    )
    assert result.stdout == f"{os.getuid()}:{os.getgid()}"


@pytest.mark.parametrize("retained", ["failed", "older_success"])
@pytest.mark.parametrize("table", ["source_warnings", "positions_history", "portfolio_daily"])
def test_readback_cli_rejects_unselected_derived_keys(tmp_path, retained, table):
    book = partial_book(tables=(table,)) if retained == "failed" else book_with_two_observations()
    if retained == "older_success":
        book["sync_runs"][-1]["completed_at"] = "2026-09-11T08:00:01+00:00"
    run_id = book["sync_runs"][0 if retained == "failed" else -1]["run_id"]
    source = tmp_path / "synthetic-readback.json"
    command = [sys.executable, str(ROOT / "scripts/check-workbook.py"),
               "--input", str(source), "--run-id", run_id]
    source.write_text(json.dumps(native_observation(book)[0]))
    valid = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["status"] in {
        "WORKBOOK_READBACK_VALIDATED", "WORKBOOK_READBACK_QUALIFIED",
    }
    key = {"source_warnings": "row_key", "positions_history": "history_key",
           "portfolio_daily": "daily_key"}[table]
    book[table][-1 if retained == "failed" else 0][key] = "synthetic-wrong-key"
    source.write_text(json.dumps(native_observation(book)[0]))
    before = source.read_bytes()
    invalid = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert invalid.returncode != 0
    assert invalid.stdout == ""
    assert invalid.stderr.strip() == "WORKBOOK_READBACK_REVIEW_REQUIRED"
    assert source.read_bytes() == before
