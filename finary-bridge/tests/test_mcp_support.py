"""Shared support stays acyclic, test-only and independent of collection order."""

import ast
from copy import deepcopy
from pathlib import Path

from mcp_artifacts import base, cases, materialize
from mcp_inputs import manual_rows
from mcp_snapshots import snapshot
from mcp_wire import SyntheticWire
from mcp_workbooks import empty_book, prepare, readback


def test_tests_never_import_other_test_modules():
    directory = Path(__file__).parent
    imports = []
    for path in directory.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module or ""] if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else []
            )
            if isinstance(node, ast.Call) and node.args:
                function = node.func
                called = (
                    function.id if isinstance(function, ast.Name)
                    else function.attr if isinstance(function, ast.Attribute)
                    else None
                )
                argument = node.args[0]
                if (
                    called in {"__import__", "import_module"}
                    and isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                ):
                    names.append(argument.value)
            imports.extend(
                f"{path.name}:{node.lineno}: {name}"
                for name in names if any(part.startswith("test_") for part in name.split("."))
            )
    assert imports == []


def test_materialized_cases_and_native_peers_do_not_share_mutable_state():
    case = cases("snapshot_v1")[0]
    original_changes = deepcopy(case["changes"])
    value = materialize(case)
    value["accounts"].clear()
    assert materialize(case)["accounts"]
    case["changes"].append({"op": "remove", "path": "/accounts"})
    assert cases("snapshot_v1")[0]["changes"] == original_changes
    wire = SyntheticWire()
    wire.values["accounts"]["data"].clear()
    wire.calls.append(("accounts", {}))
    assert SyntheticWire().values["accounts"]["data"] == base("accounts")["data"]
    assert SyntheticWire().calls == []
    first, second = snapshot(), snapshot()
    assert first["observation_id"] != second["observation_id"]
    first["positions"].clear()
    assert second["positions"]


def test_workbook_preparation_and_readback_do_not_alias_caller_rows():
    book = empty_book()
    prepared = prepare(book=book)
    prepared["Read writer_control"][0]["generation"] = 99
    prepared["Fetch MCP Schema"][0]["body"]["sheets"].clear()
    assert book["writer_control"][0]["generation"] == 1
    assert prepare()["Read writer_control"][0]["generation"] == 1
    restored = readback(book)
    restored["sheets"]["writer_control"]["rows"].clear()
    assert book["writer_control"] and empty_book()["writer_control"]
    inputs = manual_rows()
    inputs["allocation_targets"]["target_pct"] = 0
    assert manual_rows()["allocation_targets"]["target_pct"] == 0.75
