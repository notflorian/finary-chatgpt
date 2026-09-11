"""Materialize the reviewed append-only delta into the canonical workbook contract."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    legacy = json.loads((ROOT / "docs/google-sheets-schema-v2.json").read_text())
    contract = json.loads((ROOT / "docs/finary-mcp-contract.json").read_text())
    schema = deepcopy(legacy)
    schema.update(
        schema_version="3.0",
        reference_currency="PER_OBSERVATION",
        writer_provider="finary_official_mcp",
    )
    schema["legacy_schema"] = "google-sheets-schema-v2.json"
    schema["source_contract_version"] = contract["contract_version"]
    schema["mcp_tables"] = contract["workbook_migration"]["tables"]
    schema["mcp_identity"] = contract["identity"]
    schema["mcp_numeric_policy"] = contract["numeric_policy"]
    schema["mcp_valuation_contracts"] = contract["valuation_contracts"]
    schema["mcp_definitions"] = contract["$defs"]
    schema["legacy_constraints"] = legacy["sheets"]

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

    def column(name, node, owner, source, nullable=None):
        normalized = resolve(node)
        nullable_schema = any(x.get("type") == "null" for x in normalized.get("anyOf", []))
        if "anyOf" in normalized:
            normalized = resolve(next(x for x in normalized["anyOf"] if x.get("type") != "null"))
        if "allOf" in normalized:
            normalized = resolve(normalized["allOf"][0])
        kind = {"integer": "NUMBER", "number": "NUMBER", "boolean": "BOOLEAN"}.get(
            normalized.get("type"), "STRING"
        )
        if normalized.get("format") in {"date", "date-time"}:
            kind = "DATE" if normalized["format"] == "date" else "DATETIME"
        return {
            "name": name,
            "type": kind,
            "nullable": nullable_schema if nullable is None else nullable,
            "ownership": owner,
            "source": source,
            "mcp_schema": node,
        }

    def append(table, name, node, nullable=False):
        columns = schema["sheets"][table]["columns"]
        if name not in {c["name"] for c in columns}:
            columns.append(column(name, node, "derived", "MCP observation membership", nullable))

    for table, definition in schema["mcp_tables"].items():
        if "row_schema" not in definition:
            continue
        owner = "manual" if definition["ownership"] == "operator" else "automated"
        if table not in schema["sheets"]:
            unique = (
                definition["key"]
                if definition["key"] in definition["column_bindings"]
                else "row_key"
            )
            schema["sheets"][table] = {
                "purpose": definition.get("grain", table),
                "sheet_ownership": owner,
                "unique_key": unique,
                "update_behavior": "Observation-keyed deterministic upsert; terminal membership required.",
                "deletion_behavior": "Never delete automatically.",
                "columns": [],
            }
            if unique == "row_key":
                append(table, "row_key", {"$ref": "#/$defs/key"})
        target = schema["sheets"][table]
        existing = {c["name"]: c for c in target["columns"]}
        for name, pointer in definition["column_bindings"].items():
            node = leaf(definition["row_schema"], pointer)
            if name in existing:
                existing[name]["mcp_schema"] = node
            else:
                target["columns"].append(
                    column(
                        name,
                        node,
                        owner,
                        definition["row_schema"] + pointer,
                        True if table in legacy["sheets"] else None,
                    )
                )
        for name in definition.get("membership_columns", []):
            append(
                table,
                name,
                {"$ref": "#/$defs/uuid"}
                if name == "observation_id"
                else {"type": "string", "minLength": 1},
                table in legacy["sheets"],
            )
    for table in ("accounts_current", "positions_current", "positions_history", "portfolio_daily"):
        append(table, "provider", {"const": "finary_official_mcp"}, True)
    append("portfolio_daily", "daily_key", {"$ref": "#/$defs/key"})
    schema["sheets"]["portfolio_daily"]["unique_key"] = "daily_key"
    for name, node in {
        "observation_id": {"$ref": "#/$defs/uuid"},
        "provider": {"const": "finary_official_mcp"},
        "source_contract_version": {"const": contract["contract_version"]},
        "writer_generation": {"type": "integer", "minimum": 1},
        "writer_id": {"type": "string", "minLength": 1},
        "workbook_schema": {"const": "3.0"},
        "series_break": {"type": "boolean"},
    }.items():
        append("sync_runs", name, node, True)
    for name in schema["mcp_tables"]["sync_runs"]["count_columns"].values():
        append(
            "sync_runs",
            name,
            {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
            True,
        )
    shared = {
        "account_key",
        "source",
        "source_account_id",
        "position_key",
        "source_asset_id",
        "history_key",
        "snapshot_date",
        "generated_at",
        "run_id",
        "last_seen_run_id",
        "last_seen_at",
        "is_active",
        "asset_class",
    }
    for table in ("accounts_current", "positions_current", "positions_history", "portfolio_daily"):
        for col in schema["sheets"][table]["columns"]:
            if col["name"] in {c["name"] for c in legacy["sheets"][table]["columns"]}:
                col["legacy_nullable"] = col["nullable"]
                if col["name"] not in shared:
                    col["nullable"] = True
    schema["key_formats"]["portfolio_daily"] = contract["identity"]["daily_key"]
    schema["readme_entries"] += [
        {
            "key": "mcp_authority",
            "value": "Official overview; household/direct; native currency",
            "description": "Select a validated successful observation; detail sums do not replace totals.",
        }
    ]
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "docs/google-sheets-schema.json"
    content = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if path.read_text() != content:
            raise SystemExit("Canonical MCP workbook schema is stale")
    else:
        path.write_text(content)


if __name__ == "__main__":
    main()
