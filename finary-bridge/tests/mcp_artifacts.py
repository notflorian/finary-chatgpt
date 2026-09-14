"""Canonical artifacts and independent, freshly materialized synthetic contract cases."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "docs/finary-mcp-contract.json").read_text())
SCHEMA = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
WORKFLOW = json.loads((ROOT / "n8n/workflows/finary-mcp-sync.json").read_text())
FIXTURES = Path(__file__).parent / "fixtures/finary-mcp"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
_BASES = json.loads((FIXTURES / MANIFEST["base_file"]).read_text())
BASE_NAMES = tuple(_BASES)
FORMATS = FormatChecker()


def base(name):
    return deepcopy(_BASES[name])


def cases(schema):
    return [deepcopy(case) for case in MANIFEST["cases"] if case["schema"] == f"#/$defs/{schema}"]


@FORMATS.checks("date-time", raises=(TypeError, ValueError))
def timezone_timestamp(value):
    """Require a real timezone-aware datetime without optional format packages."""
    return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None


def validator(reference):
    return Draft202012Validator(
        {"$ref": reference, "$defs": CONTRACT["$defs"]}, format_checker=FORMATS
    )


def materialize(case):
    value = base(case["base"])
    for change in case["changes"]:
        parts = [
            part.replace("~1", "/").replace("~0", "~") for part in change["path"].split("/")[1:]
        ]
        target = value
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        if change["op"] == "remove":
            del target[key]
        else:
            assert change["op"] == "set"
            target[key] = deepcopy(change["value"])
    return value
