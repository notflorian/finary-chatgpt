"""Role-specific exported helpers and their independent schema boundaries."""

import runpy
import subprocess
from copy import deepcopy

import pytest
from mcp_artifacts import ROOT, SCHEMA, WORKFLOW
from mcp_workbooks import empty_book, failure, prepare
from n8n_code import _run_code_node

GENERATOR = runpy.run_path(str(ROOT / "scripts/build-mcp-workflow.py"))


def test_small_roles_omit_unrelated_helpers():
    for node in WORKFLOW["nodes"]:
        if node["type"] != "n8n-nodes-base.code":
            continue
        name, code = node["name"], node["parameters"]["jsCode"]
        if name.startswith(("Initialize ", "Check ", "Select ", "Continue ")) or name == (
            "Finalize MCP Failure"
        ):
            for helper in ("mcpSnapshot", "mcpBuild", "mcpRetained", "mcpSeriesBreak"):
                assert f"const {helper} =" not in code, (name, helper)
        if name.startswith(("Initialize ", "Check ", "Continue ")):
            assert "const mcpSchemaValid =" not in code
            assert "const mcpItems =" not in code
        if name.startswith("Continue "):
            assert "const mcpRun =" not in code
            assert "const mcpTimestampPattern =" not in code
        if name == "Validate MCP Snapshot":
            assert "const mcpBuild =" not in code
            assert "const mcpSeriesBreak =" not in code


def test_groups_emit_dependencies_once_and_before_dependents():
    groups = GENERATOR["read_groups"]()
    for role in GENERATOR["PROFILES"]:
        code = GENERATOR["shared_helpers"](role, groups)
        assert code == GENERATOR["shared_helpers"](role, groups)
        for group, dependencies in GENERATOR["GROUP_DEPENDENCIES"].items():
            marker = f"// Shared helpers: {group}\n"
            if marker not in code:
                continue
            assert code.count(marker) == 1
            assert groups[group] in code
            for dependency in dependencies:
                assert code.index(f"// Shared helpers: {dependency}\n") < code.index(marker)
    with pytest.raises(KeyError):
        GENERATOR["shared_helpers"]("Unknown role", groups)


@pytest.mark.parametrize("mutation", ["outside", "unclosed", "duplicate", "unknown", "missing"])
def test_invalid_group_boundaries_fail_generation(tmp_path, monkeypatch, mutation):
    namespace = GENERATOR["read_groups"].__globals__
    monkeypatch.setitem(namespace, "ROOT", tmp_path)
    (tmp_path / "n8n").mkdir()
    for filename in ("mcp-validation.js", "mcp-workbook.js"):
        (tmp_path / "n8n" / filename).write_text((ROOT / "n8n" / filename).read_text())
    path = tmp_path / "n8n/mcp-validation.js"
    source = path.read_text()
    if mutation == "outside":
        source += "const undeclared = true;\n"
    elif mutation == "unclosed":
        source = source.removesuffix("// @mcp-end\n")
    elif mutation == "duplicate":
        source += "// @mcp-group core\nconst duplicate = true;\n// @mcp-end\n"
    elif mutation == "unknown":
        source = source.replace("// @mcp-group core", "// @mcp-group unknown")
    else:
        source = source[source.index("// @mcp-end\n") + len("// @mcp-end\n") :]
    path.write_text(source)
    with pytest.raises(ValueError):
        GENERATOR["read_groups"]()


@pytest.mark.parametrize(
    "name",
    [
        "Validate MCP Snapshot",
        "Prepare MCP Rows",
        "Check positions_current",
        "Select positions_current",
        "Continue positions_current",
        "Finalize MCP Success",
        "Finalize MCP Failure",
    ],
)
def test_every_schema_bound_role_rejects_tampering(name):
    workflow = deepcopy(WORKFLOW)
    node = next(node for node in workflow["nodes"] if node["name"] == name)
    check = "mcpAssert(require('crypto').createHash('sha256')"
    assert node["parameters"]["jsCode"].count(check) == 1
    node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
        check, "mcpWorkbook.schema_version='tampered';\n" + check
    )
    with pytest.raises(subprocess.CalledProcessError) as rejected:
        _run_code_node(
            workflow,
            name,
            named_rows={"Validate MCP Snapshot": [{"schema": deepcopy(SCHEMA)}]},
            input_rows=[{}],
        )
    assert rejected.value.stderr == "MCP_VALIDATION_FAILED"


def test_continue_needs_only_its_intact_schema():
    named = {"Validate MCP Snapshot": [{"schema": deepcopy(SCHEMA)}]}
    assert _run_code_node(
        WORKFLOW, "Continue positions_current", named_rows=named, input_rows=[]
    ) == [{"json": {"completed_table": "positions_current"}}]
    named["Validate MCP Snapshot"][0]["schema"]["schema_version"] = "tampered"
    with pytest.raises(subprocess.CalledProcessError) as rejected:
        _run_code_node(WORKFLOW, "Continue positions_current", named_rows=named, input_rows=[])
    assert rejected.value.stderr == "MCP_VALIDATION_FAILED"


def test_check_and_select_preserve_empty_and_nonempty_batches():
    named = prepare()
    for empty in (False, True):
        if empty:
            named["Prepare MCP Rows"][0]["batches"]["positions_current"] = []
        checked = _run_code_node(
            WORKFLOW,
            "Check positions_current",
            named_rows=named,
            input_rows=[{}],
            execution_id="mcp-test",
        )
        assert checked == [{"json": {"has_rows": not empty}}]
        selected = _run_code_node(
            WORKFLOW,
            "Select positions_current",
            named_rows=named,
            input_rows=[{}],
            execution_id="mcp-test",
        )
        assert len(selected) == (0 if empty else 1)
        if selected:
            assert (
                selected[0]["json"]["position_key"]
                == (named["Prepare MCP Rows"][0]["batches"]["positions_current"][0]["position_key"])
            )


@pytest.mark.parametrize("unusable", [[], [{}], [{"schema": {"schema_version": "invalid"}}]])
def test_failure_has_its_own_schema_without_validation_or_preparation(unusable):
    book = empty_book()
    # Retain only a real Initialize result; neither normal-path output is usable.
    named = {"Initialize MCP Run": prepare()["Initialize MCP Run"]}
    named["Validate MCP Snapshot"] = deepcopy(unusable)
    named["Prepare MCP Rows"] = deepcopy(unusable)
    rows = failure(named, book)
    assert len(rows) == 1
    assert rows[0]["status"] == "FAILED"
    assert rows[0]["observation_id"] == ""
    assert rows[0]["error_code"] == "MCP_SYNC_FAILED"
    assert rows[0]["error_message"] == (
        "The MCP synchronization failed. Validate the workbook before retrying."
    )
