"""Generate the current workbook directly from its authoritative MCP definitions."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    contract = json.loads((ROOT / "docs/finary-mcp-contract.json").read_text())
    workbook = contract["current_workbook"]
    schema = {k: v for k, v in workbook.items() if k != "tables"}
    schema.update(
        source_contract_version=contract["contract_version"],
        api_schema=contract["implemented"]["api_schema"],
        writer_provider="finary_official_mcp",
        mcp_tables=workbook["tables"],
        mcp_identity=contract["identity"],
        mcp_numeric_policy=contract["numeric_policy"],
        mcp_valuation_contracts=contract["valuation_contracts"],
        mcp_definitions=contract["$defs"],
        sheets={},
    )
    schema["readme_entries"] = [
        {"key": key, "value": value, "description": description}
        for key, value, description in (
            (
                "workbook_schema",
                workbook["schema_version"],
                "Required physical workbook layout.",
            ),
            (
                "api_schema",
                schema["api_schema"],
                "Normalized bridge snapshot contract.",
            ),
            (
                "source_contract_version",
                contract["contract_version"],
                "Source interpretation contract.",
            ),
            ("timezone", workbook["timezone"], "Business dates and schedules."),
        )
    ] + workbook["readme_entries"]

    def resolve(node):
        while "$ref" in node:
            base = contract["$defs"][node["$ref"].split("/")[-1]]
            properties = {**base.get("properties", {}), **node.get("properties", {})}
            node = {**base, **{k: v for k, v in node.items() if k != "$ref"}}
            if properties:
                node["properties"] = properties
        return node

    def leaf(reference, pointer):
        node = {"$ref": reference}
        for part in pointer.split("/")[1:]:
            node = resolve(node)["properties"][part]
        return node

    def column(name, node, owner):
        normalized = resolve(node)
        nullable = any(x.get("type") == "null" for x in normalized.get("anyOf", []))
        if "anyOf" in normalized:
            normalized = resolve(next(x for x in normalized["anyOf"] if x.get("type") != "null"))
        if "allOf" in normalized and "type" not in normalized:
            normalized = resolve(normalized["allOf"][0])
        kind = {"integer": "NUMBER", "number": "NUMBER", "boolean": "BOOLEAN"}.get(
            normalized.get("type"), "STRING"
        )
        if normalized.get("format") in {"date", "date-time"}:
            kind = "DATE" if normalized["format"] == "date" else "DATETIME"
        return {
            "name": name,
            "type": kind,
            "nullable": nullable,
            "ownership": owner,
            "mcp_schema": node,
        }

    for name, definition in workbook["tables"].items():
        owner = definition["ownership"]
        fields = {
            key: leaf(definition["row_schema"], pointer)
            for key, pointer in definition["column_bindings"].items()
        }
        assert not fields.keys() & definition["workbook_columns"].keys()
        fields.update(definition["workbook_columns"])
        assert definition["key"] in fields
        schema["sheets"][name] = {
            "purpose": definition["grain"],
            "sheet_ownership": owner,
            "unique_key": definition["key"],
            "update_behavior": definition["update_behavior"],
            "deletion_behavior": definition["deletion_behavior"],
            "columns": [column(key, node, owner) for key, node in fields.items()],
        }
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    for path in (
        ROOT / "docs/google-sheets-schema.json",
        ROOT / "finary-bridge/app/workbook-schema.json",
    ):
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Stale workbook artifact: {path.name}")
        else:
            path.write_text(content)


if __name__ == "__main__":
    main()
