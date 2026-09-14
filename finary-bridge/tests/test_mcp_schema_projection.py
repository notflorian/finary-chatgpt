"""Downstream dependency discovery, separate from full provider validation."""

import json
import re
import runpy
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
GENERATOR = runpy.run_path(str(ROOT / "scripts/build-mcp-workbook.py"))
CONTRACT = json.loads((ROOT / "docs/finary-mcp-contract.json").read_text())
EXPLICIT_ROOTS = ("snapshot_v1", "writer_control", "id", "decimal", "position")


def minimal_contract():
    return {"$defs": dict.fromkeys(EXPLICIT_ROOTS, {}), "current_workbook": {}}


def test_actual_projection_preserves_content_and_resolves_every_reference():
    before = deepcopy(CONTRACT)
    schema = GENERATOR["build"](CONTRACT)
    projected = schema["mcp_definitions"]
    assert before == CONTRACT
    assert list(projected) == sorted(projected)
    assert set(projected) < set(CONTRACT["$defs"])
    for name, definition in projected.items():
        assert definition == CONTRACT["$defs"][name]
    for reference in re.findall(r'"(?:\$ref|row_schema)": "([^"\n]+)"', json.dumps(schema)):
        assert reference.startswith("#/$defs/")
        assert reference.removeprefix("#/$defs/") in projected
    assert schema == json.loads((ROOT / "docs/google-sheets-schema.json").read_text())


def test_handwritten_named_accesses_are_declared():
    sources = [ROOT / "n8n/mcp-validation.js", ROOT / "n8n/mcp-workbook.js"]
    sources += list((ROOT / "n8n/code-nodes/finary-mcp-sync").glob("*.js"))
    code = "\n".join(path.read_text() for path in sources)
    # Guard the current simple lookup conventions; this is not a JavaScript parser.
    names = set(re.findall(r"mcpSchema\([^,\n]+,\s*['\"](\w+)['\"]\)", code))
    names.update(re.findall(r"mcpContract\.\$defs\.(\w+)", code))
    assert names == set(EXPLICIT_ROOTS) == set(GENERATOR["DOWNSTREAM_ROOTS"])


@pytest.mark.parametrize("root", EXPLICIT_ROOTS)
def test_named_roots_are_independent_of_snapshot_and_workbook_references(root):
    contract = minimal_contract()
    contract["$defs"][root] = {"allOf": [{"$ref": "#/$defs/helper_dependency"}]}
    contract["$defs"]["helper_dependency"] = {"type": "string"}
    assert "helper_dependency" in GENERATOR["project_definitions"](contract)
    del contract["$defs"][root]
    with pytest.raises(ValueError, match=f"Missing downstream definition: {root}"):
        GENERATOR["project_definitions"](contract)


def test_workbook_bindings_nested_dependencies_cycles_and_unused_invalid_refs():
    contract = minimal_contract()
    contract["current_workbook"] = {
        "tables": {
            "synthetic": {
                "row_schema": "#/$defs/row",
                "workbook_columns": {"extra": {"$ref": "#/$defs/column"}},
            }
        }
    }
    contract["$defs"].update(
        {
            "row": {"properties": {"items": {"items": {"$ref": "#/$defs/nested"}}}},
            "column": {"anyOf": [{"$ref": "#/$defs/nested"}]},
            "nested": {
                "if": {"$ref": "#/$defs/condition"},
                "then": {"oneOf": [{"$ref": "#/$defs/row"}]},
                "else": {"allOf": [{"$ref": "#/$defs/column"}]},
            },
            "condition": {"type": "string"},
            "unused": {"$ref": "https://invalid.example/schema"},
        }
    )
    before = deepcopy(contract)
    projected = GENERATOR["project_definitions"](contract)
    assert set(projected) == set(EXPLICIT_ROOTS) | {"row", "column", "nested", "condition"}
    assert contract == before
    del contract["$defs"]["condition"]
    with pytest.raises(ValueError, match="Missing downstream definition: condition"):
        GENERATOR["project_definitions"](contract)


@pytest.mark.parametrize(
    "reference",
    [
        "https://invalid.example/id",
        "other.json#/$defs/id",
        "#/properties/id",
        "#/$defs/position/properties/id",
        "#/$defs/",
        "#/$defs/a~1b",
        None,
    ],
)
@pytest.mark.parametrize("binding", ["definition", "row_schema", "column"])
def test_unsupported_reachable_references_fail(reference, binding):
    contract = minimal_contract()
    if binding == "definition":
        contract["$defs"]["snapshot_v1"] = {"$ref": reference}
    elif binding == "row_schema":
        contract["current_workbook"] = {"row_schema": reference}
    else:
        contract["current_workbook"] = {"workbook_columns": {"extra": {"$ref": reference}}}
    with pytest.raises(ValueError, match="Unsupported downstream reference"):
        GENERATOR["project_definitions"](contract)
