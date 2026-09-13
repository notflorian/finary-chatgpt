"""Physical Sheets reads cannot silently round text during numeric coercion."""

from copy import deepcopy
from subprocess import CalledProcessError

import pytest
from test_mcp_workflow import SCHEMA, WORKFLOW, empty_book, prepare
from test_n8n_workflow import _run_code_node


def decode(table, row):
    workflow = deepcopy(WORKFLOW)
    node = next(n for n in workflow["nodes"] if n["name"] == "Prepare MCP Rows")
    prefix = node["parameters"]["jsCode"].rsplit("const {run,snapshot,schema}=", 1)[0]
    node["parameters"]["jsCode"] = (
        prefix + f"return $input.all().map(i=>({{json:mcpDecode('{table}',i.json)}}));"
    )
    return _run_code_node(
        workflow,
        "Prepare MCP Rows",
        named_rows={"Validate MCP Snapshot": [{"schema": SCHEMA}]},
        input_rows=[row],
    )[0]["json"]


@pytest.mark.parametrize(
    "value",
    [
        "9007199254740993",
        "-9007199254740993",
        "9007199254740992",
        "1.0000000000000001",
        "0.123456789012345678901234",
        "1." + "1" * 64,
        "123456789012345678901234",
    ],
)
def test_number_columns_preserve_strings_that_cannot_be_safely_coerced(value):
    assert decode("positions_current", {"quantity": value})["quantity"] == value


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", 0),
        ("-0", 0),
        ("1.000", 1),
        ("001", 1),
        ("9007199254740991", 9007199254740991),
        ("-9007199254740991", -9007199254740991),
    ],
)
def test_exact_safe_integers_remain_compatible_with_sheets_text(value, expected):
    assert decode("writer_control", {"generation": value})["generation"] == expected


def test_native_amount_columns_remain_text_at_full_contract_precision():
    value = "123456789012345678901234." + "1" * 64
    columns = {c["name"]: c for c in SCHEMA["sheets"]["positions_current"]["columns"]}
    for name in ("mcp_current_value_amount", "mcp_current_value_amount_eur"):
        assert columns[name]["type"] == "STRING"
        assert decode("positions_current", {name: value})[name] == value


def test_writer_generation_cannot_round_into_an_authorized_integer():
    book = empty_book()
    book["writer_control"][0]["generation"] = "1.0000000000000001"
    with pytest.raises(CalledProcessError):
        prepare(book=book)
