"""Embed shared validation and the Pydantic contract in the portable n8n export.

Run with the bridge development environment. --check is credential-free and is
also exercised by pytest; no runtime service or schema endpoint is added.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "finary-bridge"))

from app.models import Account, Liability, PortfolioSnapshotV2, Position  # noqa: E402

START = "// BEGIN GENERATED CONTRACT VALIDATION\n"
END = "// END GENERATED CONTRACT VALIDATION\n"
WORKFLOWS = ("finary-daily-sync.json", "finary-error-handler.json")
VALIDATED_NODES = {
    "Initialize Run",
    "Resolve Source Execution",
    "Validate Source Execution ID",
    "Prepare Sanitized Failure",
    "Validate Snapshot",
    "Prepare Validated Rows",
    "Select Success Run",
    "Prepare Failed Run",
}
SERIALIZED_NODES = {
    "Select Account Rows",
    "Select Position Rows",
    "Select Liability Rows",
    "Select History Rows",
    "Select Daily Row",
    "Select Success Run",
    "Prepare Failed Run",
    "Select Failure Row",
}


def api_contract():
    schema = PortfolioSnapshotV2.model_json_schema()
    # JSON Schema does not encode default factories. Only the verified empty
    # metadata factory is supported; fail visibly if the models change it.
    for model in (Account, Position, Liability):
        field = model.model_fields["metadata"]
        assert field.default_factory is dict
        schema["$defs"][model.__name__]["properties"]["metadata"]["default"] = {}

    def compact(node):
        supported = {
            "$defs",
            "$ref",
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "anyOf",
            "default",
            "const",
            "enum",
            "minLength",
            "pattern",
            "minimum",
            "format",
            "title",
            "description",
        }
        assert not node.keys() - supported, "Unsupported API schema constraint"
        assert node.get("format", "date-time") == "date-time", "Unsupported API format"
        assert node.get("type", "object") in {
            "object",
            "array",
            "string",
            "boolean",
            "integer",
            "number",
            "null",
        }, "Unsupported API type"
        result = {}
        for key, value in node.items():
            if key in {"title", "description"}:
                continue
            if key in {"$defs", "properties"}:
                value = {name: compact(child) for name, child in value.items()}
            elif key in {"items", "additionalProperties"} and isinstance(value, dict):
                value = compact(value)
            elif key == "anyOf":
                value = [compact(child) for child in value]
            result[key] = value
        return result

    return compact(schema)


def generated_block():
    contract = json.dumps(api_contract(), ensure_ascii=True, separators=(",", ":"))
    library = (ROOT / "n8n" / "validation.js").read_text()
    return START + f"const apiContract = {contract};\n" + library + END


def code_node_source_path(workflow_name, node_name):
    directory = ROOT / "n8n" / "code-nodes" / Path(workflow_name).stem
    slug = re.sub(r"[^a-z0-9]+", "-", node_name.lower()).strip("-")
    return directory / f"{slug}.js"


def expected_code(workflow_name, node_name):
    body = code_node_source_path(workflow_name, node_name).read_text()
    prelude = generated_block() if node_name in VALIDATED_NODES else ""
    if node_name in SERIALIZED_NODES:
        prelude += (ROOT / "n8n" / "sheets-serialization.js").read_text()
    return prelude + body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = False
    for filename in WORKFLOWS:
        path = ROOT / "n8n" / "workflows" / filename
        workflow = json.loads(path.read_text())
        for node in workflow["nodes"]:
            if node["type"] != "n8n-nodes-base.code":
                continue
            code = node["parameters"]["jsCode"]
            expected = expected_code(filename, node["name"])
            changed |= code != expected
            node["parameters"]["jsCode"] = expected
        if not args.check:
            path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
    if args.check:
        if changed:
            raise SystemExit(
                "Workflow validation is stale; run scripts/build-workflow-validation.py"
            )
        print("Workflow validation matches Pydantic models and shared source")


if __name__ == "__main__":
    main()
