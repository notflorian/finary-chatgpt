"""Fresh workbook structure, physical-cell decoding and current layout validation."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Any, cast
from urllib.parse import quote

from jsonschema import Draft202012Validator

from app.mcp_validation import CONTRACT, FORMATS, validate

SCHEMA: dict[str, Any] = json.loads(files("app").joinpath("workbook-schema.json").read_text())
VERSION: str = SCHEMA["schema_version"]
CHILD_KEYS = {
    "account_ownership": ("account_key", "owner_key"),
    "source_connections": ("connection_key",),
    "position_rates": ("position_key", "source_field"),
    "official_allocation_categories": ("category",),
    "official_allocation_types": ("category", "holding_type"),
    "portfolio_members": ("member_ordinal",),
    "source_warnings": ("code", "entity_key"),
    "unsupported_details": ("account_key", "holding_type", "reason"),
}


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("Incompatible or malformed workbook")


def headers() -> dict[str, list[str]]:
    return {name: [c["name"] for c in sheet["columns"]] for name, sheet in SCHEMA["sheets"].items()}


def decode_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Decode connector blanks/booleans/counts without coercing decimal text."""
    require(isinstance(row, dict) and set(row) <= set(headers()[table]) | {"row_number"})
    result = {}
    for column in SCHEMA["sheets"][table]["columns"]:
        value = row.get(column["name"])
        if value == "":
            value = None
        if column["type"] == "BOOLEAN" and isinstance(value, str) and value in {"TRUE", "FALSE"}:
            value = value == "TRUE"
        if (
            column["type"] == "NUMBER"
            and isinstance(value, str)
            and re.fullmatch(r"-?[0-9]+(?:\.0+)?", value)
        ):
            try:
                number = Decimal(value)
                if (
                    number.is_finite()
                    and abs(number) <= 9007199254740991
                    and number == number.to_integral_value()
                ):
                    value = int(number)
            except InvalidOperation:
                pass
        result[column["name"]] = value
    return result


def validate_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    result = decode_row(table, row)
    definition = SCHEMA["mcp_tables"][table]
    for col in SCHEMA["sheets"][table]["columns"]:
        value = result[col["name"]]
        if value is None:
            require(col["nullable"])
        else:
            require(not isinstance(value, float) or math.isfinite(value))
            require(
                Draft202012Validator(
                    {**col["mcp_schema"], "$defs": CONTRACT["$defs"]}, format_checker=FORMATS
                ).is_valid(value)
            )
    if table in SCHEMA["manual_sheets"]:
        require(
            all(
                name == "notes" or not isinstance(value, str) or not value.startswith("=")
                for name, value in result.items()
            )
        )
    if table == "allocation_targets":
        require(result["min_pct"] <= result["target_pct"] <= result["max_pct"])
    normalized: dict[str, Any] = {}
    for col, pointer in definition["column_bindings"].items():
        parts = pointer.split("/")[1:]
        target = normalized
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = result[col]
    validate(definition["row_schema"].split("/")[-1], normalized)
    return result


def validate_derived_key(table: str, row: dict[str, Any]) -> None:
    """Check a decoded, schema-valid row using only its own retained identity."""
    if table in CHILD_KEYS:
        parts = []
        for field in CHILD_KEYS[table]:
            value = row[field]
            if field == "entity_key":
                part = "~null" if value is None else "~value" + quote(value, safe="-._~")
            elif field == "member_ordinal":
                # Schema-valid integral numbers, including Sheets 1.0, encode as 1.
                part = str(int(value))
            else:
                part = quote(value, safe="-._~")
            parts.append(part)
        expected = row["observation_id"] + ":" + table + ":" + ":".join(parts)
        require(row["row_key"] == expected)
    elif table == "positions_history":
        require(
            row["history_key"]
            == f"mcp:history:{row['snapshot_date']}:{row['observation_id']}:{row['position_key']}"
        )
    elif table == "portfolio_daily":
        require(row["daily_key"] == f"mcp:daily:{row['snapshot_date']}:{row['observation_id']}")


def initialize(writer_id: str, generation: int) -> dict[str, Any]:
    """Build a deterministic empty inventory; no credential or network access."""
    control = {
        "row_key": "singleton",
        "workbook_schema": VERSION,
        "provider": SCHEMA["writer_provider"],
        "generation": generation,
        "writer_id": writer_id,
        "state": SCHEMA["initial_control_state"],
    }
    validate_row("writer_control", control)
    book: dict[str, Any] = {
        "schema_version": VERSION,
        "sheets": {name: {"headers": cols, "rows": []} for name, cols in headers().items()},
    }
    book["sheets"]["README"]["rows"] = deepcopy(SCHEMA["readme_entries"])
    book["sheets"]["writer_control"]["rows"] = [control]
    return book


def records(inventory: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Validate actual ordered headers and immutable metadata before interpretation."""
    require(inventory.get("schema_version") == VERSION)
    sheets = inventory.get("sheets")
    require(isinstance(sheets, dict) and list(sheets) == list(SCHEMA["sheets"]))
    sheets = cast(dict[str, Any], sheets)
    result = {}
    for name, expected in headers().items():
        sheet = sheets[name]
        require(sheet.get("headers") == expected and isinstance(sheet.get("rows"), list))
        result[name] = sheet["rows"]
    require(result["README"] == SCHEMA["readme_entries"])
    require(len(result["writer_control"]) == 1)
    validate_row("writer_control", result["writer_control"][0])
    for table in [
        "sync_runs",
        *SCHEMA["manual_sheets"],
        *SCHEMA["mcp_tables"]["sync_runs"]["count_columns"],
    ]:
        result[table] = [validate_row(table, row) for row in result[table]]
        key = SCHEMA["sheets"][table]["unique_key"]
        keys = [row[key] for row in result[table]]
        require(len(keys) == len(set(keys)))
    for table in SCHEMA["mcp_tables"]["sync_runs"]["count_columns"]:
        for row in result[table]:
            validate_derived_key(table, row)
            terminals = [
                r for r in result["sync_runs"] if r["observation_id"] == row["observation_id"]
            ]
            require(len(terminals) == 1)
            require(terminals[0]["run_id"] == row["run_id"])
            require(terminals[0]["provider"] == SCHEMA["writer_provider"])
    return result


def cell(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    kind = (
        "boolValue"
        if type(value) is bool
        else "numberValue"
        if type(value) in {int, float}
        else "stringValue"
    )
    return {"userEnteredValue": {kind: value}}


def google_create(inventory: dict[str, Any]) -> dict[str, Any]:
    """A spreadsheets.create body: creates only a new workbook, never edits a target."""
    control = records(inventory)["writer_control"][0]
    require(inventory == initialize(control["writer_id"], control["generation"]))
    return {
        "properties": {"title": SCHEMA["workbook_name"], "timeZone": SCHEMA["timezone"]},
        "sheets": [
            {
                "properties": {
                    "sheetId": index,
                    "title": name,
                    "index": index,
                    "gridProperties": {
                        "rowCount": max(1000, len(sheet["rows"]) + 1),
                        "columnCount": len(sheet["headers"]),
                        "frozenRowCount": 1,
                    },
                },
                "data": [
                    {
                        "rowData": [
                            {"values": [cell(value) for value in sheet["headers"]]},
                            *[
                                {"values": [cell(row.get(col)) for col in sheet["headers"]]}
                                for row in sheet["rows"]
                            ],
                        ]
                    }
                ],
            }
            for index, (name, sheet) in enumerate(inventory["sheets"].items())
        ],
    }


def native_inventory(native: dict[str, Any]) -> dict[str, Any]:
    """Decode a complete spreadsheets.get(includeGridData=true) current read."""

    def entered(value: dict[str, Any], *, manual: bool) -> Any:
        user = value.get("userEnteredValue", {})
        if "formulaValue" in user:
            require(manual)
            return user["formulaValue"]
        require(len(user) <= 1 and set(user) <= {"stringValue", "numberValue", "boolValue"})
        return next(iter(user.values()), "")

    ordered = sorted(native["sheets"], key=lambda s: s["properties"]["index"])
    for field in ("title", "sheetId", "index"):
        ids = [s["properties"][field] for s in ordered]
        require(len(set(ids)) == len(ids))
    require([s["properties"]["title"] for s in ordered] == list(SCHEMA["sheets"]))
    result: dict[str, Any] = {"schema_version": VERSION, "sheets": {}}
    for sheet in ordered:
        name = sheet["properties"]["title"]
        require(sheet["properties"].get("sheetType", "GRID") == "GRID")
        grid = sheet.get("data", [])
        require(len(grid) == 1 and grid[0].get("startRow", 0) == grid[0].get("startColumn", 0) == 0)
        rows = grid[0].get("rowData", [])
        require(bool(rows))
        header = [entered(v, manual=False) for v in rows[0].get("values", [])]
        while header and header[-1] == "":
            header.pop()
        values = []
        for row in rows[1:]:
            cells = [
                entered(
                    v,
                    manual=name in SCHEMA["manual_sheets"]
                    and index < len(header)
                    and header[index] == "notes",
                )
                for index, v in enumerate(row.get("values", []))
            ]
            require(not any(v != "" for v in cells[len(header) :]))
            if any(v != "" for v in cells):
                values.append(
                    dict(zip(header, (cells + [""] * len(header))[: len(header)], strict=True))
                )
        result["sheets"][name] = {"headers": header, "rows": values}
    records(result)
    return result
