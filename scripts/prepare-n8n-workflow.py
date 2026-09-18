"""Prepare one inactive n8n workflow with an existing Sheets credential reference."""

import argparse
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "n8n/workflows/finary-mcp-sync.json"
SHEETS_TYPE = "n8n-nodes-base.googleSheets"
CREDENTIAL_TYPE = "googleSheetsOAuth2Api"


def fail(message):
    raise ValueError(message)


def checkouts():
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "list", "--porcelain", "-z"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        fail("WORKFLOW_OUTPUT_PATH_REJECTED")
    return [
        Path(entry.removeprefix("worktree ")).resolve()
        for entry in completed.stdout.split("\0")
        if entry.startswith("worktree ")
    ]


def external_output(path):
    output = path.resolve()
    if path.exists() or path.is_symlink():
        fail("WORKFLOW_OUTPUT_EXISTS")
    if not output.parent.is_dir():
        fail("WORKFLOW_OUTPUT_PATH_REJECTED")
    if any(output.is_relative_to(checkout) for checkout in checkouts()):
        fail("WORKFLOW_OUTPUT_PATH_REJECTED")
    return output


def prepared_workflow(source, credential_id, credential_name):
    if not isinstance(source, dict) or source.get("active") is not False:
        fail("WORKFLOW_SOURCE_INVALID")
    nodes = source.get("nodes")
    if not isinstance(nodes, list) or not isinstance(source.get("connections"), dict) or any(
        not isinstance(node, dict) or not isinstance(node.get("type"), str) for node in nodes
    ):
        fail("WORKFLOW_SOURCE_INVALID")
    prepared = deepcopy(source)
    targets = [node for node in prepared["nodes"] if node["type"] == SHEETS_TYPE]
    if not targets:
        fail("WORKFLOW_SOURCE_NO_GOOGLE_SHEETS_NODES")
    reference = {"id": credential_id, "name": credential_name}
    for node in targets:
        credentials = node.get("credentials", {})
        if not isinstance(credentials, dict):
            fail("WORKFLOW_SOURCE_INVALID")
        node["credentials"] = {**credentials, CREDENTIAL_TYPE: reference}
    return prepared, len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-id", required=True)
    parser.add_argument("--credential-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.credential_id.strip() or not args.credential_name.strip():
        parser.error("credential ID and credential name must not be blank")
    try:
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        prepared, count = prepared_workflow(source, args.credential_id, args.credential_name)
        serialized = json.dumps(prepared, indent=2, ensure_ascii=False) + "\n"
        output = external_output(args.output)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
    print(f"Prepared {count} Google Sheets nodes at {output}")


if __name__ == "__main__":
    main()
