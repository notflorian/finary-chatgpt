"""Generate typed runtime models and a packaged copy of the reviewed contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/finary-mcp-contract.json"
MODEL_NAMES = (
    "money",
    "provenance",
    "coverage",
    "overview",
    "account",
    "ownership",
    "connection",
    "position",
    "position_rate",
    "allocation_category",
    "allocation_type",
    "member",
    "warning",
    "unsupported_detail",
    "snapshot_v3",
)


def class_name(name):
    return "Mcp" + "".join(word.title() for word in name.split("_"))


def generate(contract):
    definitions = contract["$defs"]

    def annotation(field):
        if "$ref" in field:
            name = field["$ref"].split("/")[-1]
            return class_name(name) if name in MODEL_NAMES else annotation(definitions[name])
        if "const" in field:
            return f"Literal[{field['const']!r}]"
        if "enum" in field:
            return f"Literal[{', '.join(repr(v) for v in field['enum'])}]"
        if "anyOf" in field:
            return " | ".join(annotation(v) for v in field["anyOf"])
        if "allOf" in field and "type" not in field:
            return annotation(field["allOf"][0])
        kind = field.get("type")
        if kind == "array":
            return f"list[{annotation(field['items'])}]" if "items" in field else "list[None]"
        return {"string": "str", "integer": "int", "boolean": "bool", "null": "None"}[kind]

    lines = [
        '"""Generated from the reviewed MCP contract; run scripts/build-mcp-models.py."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import ClassVar, Literal",
        "",
        "from app.mcp_validation import ContractModel",
        "",
    ]
    for name in MODEL_NAMES:
        lines += [
            "",
            f"class {class_name(name)}(ContractModel):",
            f"    contract_name: ClassVar[str] = {name!r}",
        ]
        for field, schema in definitions[name]["properties"].items():
            lines.append(f"    {field}: {annotation(schema)}")
        lines.append("")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--line-length",
            "100",
            "--stdin-filename",
            "mcp_models.py",
        ],
        input="\n".join(lines),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    contract = json.loads(CONTRACT.read_text())
    outputs = {
        ROOT / "finary-bridge/app/mcp-contract.json": CONTRACT.read_text(),
        ROOT / "finary-bridge/app/mcp_models.py": generate(contract),
    }
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Stale generated MCP artifact: {path.name}")
        else:
            path.write_text(content)


if __name__ == "__main__":
    main()
