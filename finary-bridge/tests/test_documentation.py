"""Executable offline operator commands and maintained local documentation links."""

import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from mcp_snapshots import NOW
from mcp_workbooks import book_for_consumer

from app.mcp_workbook import cell, google_create, initialize

ROOT = Path(__file__).parents[2]


def test_local_documentation_links_and_anchors_resolve():
    documents = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *ROOT.glob("docs/*.md"),
        ROOT / ".github/copilot-instructions.md",
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


def native_observation():
    book = book_for_consumer()
    native = google_create(initialize("synthetic-writer", 1))
    for sheet in native["sheets"]:
        name = sheet["properties"]["title"]
        grid = sheet["data"][0]["rowData"]
        headers = [v["userEnteredValue"]["stringValue"] for v in grid[0]["values"]]
        grid[1:] = [{"values": [cell(row.get(h)) for h in headers]} for row in book[name]]
    return native, book["sync_runs"][0]["run_id"]


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
