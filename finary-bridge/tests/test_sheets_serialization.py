"""Offline checks of the eight real exported Code-node write boundaries."""

import json
import subprocess
from copy import deepcopy

import pytest
from sheets_write_cases import WRITERS, boundary_cases, outgoing
from test_n8n_workflow_v2 import schema as schema
from test_n8n_workflow_v2 import workflow as workflow


@pytest.fixture(scope="module")
def cases(workflow, schema):
    return boundary_cases(workflow, schema)


@pytest.mark.parametrize("selector", WRITERS)
def test_every_write_boundary_serializes_without_mutating_internal_rows(cases, schema, selector):
    case = cases[selector]
    before = deepcopy(case)
    rows = outgoing(selector, case, setup_js="""
const beforeSerialization = JSON.stringify(namedRows);
process.on('beforeExit', () => {
  require('node:assert/strict').equal(JSON.stringify(namedRows), beforeSerialization);
});
""")
    sheet = case["node"]["parameters"]["sheetName"]["value"]
    columns = schema["sheets"][sheet]["columns"]
    assert rows
    assert any(row[column["name"]] == "" for row in rows for column in columns)
    for index, row in enumerate(rows):
        assert list(row) == [column["name"] for column in columns]
        assert all(value is not None for value in row.values())
        if "raw" in case:
            raw = case["raw"][index]
            assert row == {key: "" if value is None else value for key, value in raw.items()}
    if "raw" in case:
        assert any(value is None for row in case["raw"] for value in row.values())
    assert case == before


@pytest.mark.parametrize("selector", WRITERS)
@pytest.mark.parametrize("mutation", ["missing", "null", "undefined", "empty"])
def test_required_values_cannot_be_hidden_by_serialization(cases, selector, mutation):
    case = cases[selector]
    # The structured failure path owns its row locally; its required run ID is
    # checked before row construction. Other paths receive prepared rows.
    field = ("run_id" if selector == "Prepare Failed Run"
             else case["node"]["parameters"]["columns"]["matchingColumns"][0])
    access = f"{case['path']}[{json.dumps(field)}]"
    setup = f"delete {access};" if mutation == "missing" else (
        f"{access} = {dict(null='null', undefined='undefined', empty=chr(39)*2)[mutation]};"
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        outgoing(selector, case, setup_js=setup)
    assert error.value.stdout == ""


@pytest.mark.parametrize("selector", [name for name in WRITERS if name != "Prepare Failed Run"])
def test_nullable_undefined_and_extra_fields_are_rejected(cases, schema, selector):
    case = cases[selector]
    sheet = case["node"]["parameters"]["sheetName"]["value"]
    field = next(c["name"] for c in schema["sheets"][sheet]["columns"] if c["nullable"])
    for setup in [
        f"{case['path']}.{field} = undefined;", f"delete {case['path']}.{field};",
        f"{case['path']}.extra = null;",
    ]:
        with pytest.raises(subprocess.CalledProcessError) as error:
            outgoing(selector, case, setup_js=setup)
        assert error.value.stdout == ""


def test_all_exported_upserts_have_a_serializing_predecessor(cases):
    expected = {case["node"]["name"] for case in cases.values()}
    actual = set()
    for selector, case in cases.items():
        workflow = case["workflow"]
        writer = case["node"]["name"]
        assert workflow["connections"][selector]["main"][0] == [
            {"node": writer, "type": "main", "index": 0}
        ]
        for node in workflow["nodes"]:
            if (node["type"] == "n8n-nodes-base.googleSheets"
                    and node["parameters"].get("operation") == "appendOrUpdate"):
                actual.add(node["name"])
    assert actual == expected and len(actual) == 8
