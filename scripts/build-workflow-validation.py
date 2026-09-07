"""Embed shared validation and the Pydantic contract in the portable n8n export.

Run with the bridge development environment. --check is credential-free and is
also exercised by pytest; no runtime service or schema endpoint is added.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "finary-bridge"))

from app.models import Account, Liability, PortfolioSnapshotV2, Position

START = "// BEGIN GENERATED CONTRACT VALIDATION\n"
END = "// END GENERATED CONTRACT VALIDATION\n"
NODES = {
    "Initialize Run",
    "Resolve Source Execution",
    "Validate Source Execution ID",
    "Prepare Sanitized Failure",
    "Validate Snapshot",
    "Prepare Validated Rows",
    "Select Success Run",
    "Prepare Failed Run",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    block = generated_block()
    changed = False
    for filename in ("finary-daily-sync.json", "finary-error-handler.json"):
        path = ROOT / "n8n" / "workflows" / filename
        workflow = json.loads(path.read_text())
        for node in workflow["nodes"]:
            if node["name"] not in NODES:
                continue
            code = node["parameters"]["jsCode"]
            body = code.split(END, 1)[1] if code.startswith(START) else code
            expected = block + body
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
