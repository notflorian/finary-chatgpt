"""Inventory, plan and apply an append-only migration to an exported workbook.

The inventory preserves complete cell/format metadata supplied by the operator.
No Finary state or Google credential is read. Native request generation is
separate from applying a reviewed plan to its detached inventory copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LEGACY = json.loads((ROOT / "docs/google-sheets-schema-v2.json").read_text())
CURRENT = json.loads((ROOT / "docs/google-sheets-schema.json").read_text())
MANUAL = ("allocation_targets", "asset_overrides", "cashflows")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def check(condition):
    if not condition:
        raise ValueError("Migration precondition failed; inspect the detached inventory")


def headers(schema, table):
    return [column["name"] for column in schema["sheets"][table]["columns"]]


def inventory(workbook, schema=LEGACY):
    check(workbook["schema_version"] == schema["schema_version"])
    check(list(workbook["sheets"]) == list(schema["sheets"]))
    for table, sheet in workbook["sheets"].items():
        check(sheet["headers"] == headers(schema, table))
        key = schema["sheets"][table]["unique_key"]
        keys = [row.get(key) for row in sheet["rows"]]
        check(all(isinstance(k, str) and k.strip() for k in keys) and len(set(keys)) == len(keys))
    return {
        "workbook_reference": workbook["workbook_reference"],
        "schema_version": schema["schema_version"],
        "row_counts": {name: len(sheet["rows"]) for name, sheet in workbook["sheets"].items()},
        "legacy_digest": digest(workbook["sheets"]),
        "manual_digest": digest({n: workbook["sheets"][n] for n in MANUAL}),
    }


def plan(source, backup, destination_reference, migration_id, writer_id, changed_at):
    checked = inventory(source)
    check(digest(source) == digest(backup))
    check(source["workbook_reference"] != destination_reference)
    check(datetime.fromisoformat(changed_at).utcoffset() is not None)
    for value in (destination_reference, migration_id, writer_id):
        check(isinstance(value, str) and value.strip() and len(value) <= 256)
    result = {
        "migration_id": migration_id,
        "source_workbook_reference": source["workbook_reference"],
        "destination_workbook_reference": destination_reference,
        "from_schema": "2.1",
        "to_schema": "3.0",
        "legacy_digest": checked["legacy_digest"],
        "manual_digest": checked["manual_digest"],
        "source_digest": digest(source),
        "schema_digest": digest(CURRENT),
        "writer_id": writer_id,
        "changed_at": changed_at,
        "row_counts": checked["row_counts"],
    }
    result["plan_digest"] = digest(result)
    return result


def apply(source, target, migration, *, writers_drained):
    check(writers_drained is True)
    check(digest(source) == migration["source_digest"])
    check(digest(CURRENT) == migration["schema_digest"])
    check(
        migration["plan_digest"]
        == digest({k: v for k, v in migration.items() if k != "plan_digest"})
    )
    inventory(source)
    if target is not None:
        check(target["workbook_reference"] == migration["destination_workbook_reference"])
        ledger = target["sheets"].get("migration_ledger", {}).get("rows", [])
        check(len(ledger) == 1 and ledger[0]["plan_digest"] == migration["plan_digest"])
        check(ledger[0]["status"] == "VALIDATED")
        verify(source, target, migration)
        return deepcopy(target)
    result = deepcopy(source)
    result["workbook_reference"] = migration["destination_workbook_reference"]
    result["schema_version"] = "3.0"
    for table in CURRENT["sheets"]:
        if table not in result["sheets"]:
            result["sheets"][table] = {
                "headers": headers(CURRENT, table),
                "rows": [],
                "metadata": {},
            }
        elif table not in MANUAL:
            result["sheets"][table]["headers"] = headers(CURRENT, table)
            for row in result["sheets"][table]["rows"]:
                for name in headers(CURRENT, table):
                    row.setdefault(name, "")
                if table == "portfolio_daily":
                    row["daily_key"] = row["snapshot_date"]
    legacy_rows = []
    for table in ("positions_history", "portfolio_daily"):
        for row in source["sheets"][table]["rows"]:
            old_key = row[LEGACY["sheets"][table]["unique_key"]]
            legacy_rows.append(
                {
                    "row_key": f"{quote(table, safe='-._~')}:{quote(old_key, safe='-._~')}",
                    "table_name": table,
                    "legacy_key": old_key,
                    "provider": "finary_private_api",
                    "source_contract_version": "",
                    "scope": "",
                    "ownership_basis": "",
                    "currency": "",
                    "run_id": row.get("run_id", ""),
                    "evidence_reference": "preserved-legacy-schema-2.1",
                }
            )
    result["sheets"]["legacy_observations"]["rows"] = legacy_rows
    result["sheets"]["writer_control"]["rows"] = [
        {
            "row_key": "singleton",
            "workbook_schema": "3.0",
            "provider": "finary_official_mcp",
            "generation": 1,
            "writer_id": migration["writer_id"],
            "migration_id": migration["migration_id"],
            "state": "PAUSED",
        }
    ]
    ledger = {
        key: migration[key]
        for key in (
            "migration_id",
            "source_workbook_reference",
            "destination_workbook_reference",
            "from_schema",
            "to_schema",
            "plan_digest",
            "legacy_digest",
            "manual_digest",
            "changed_at",
        )
    }
    result["sheets"]["migration_ledger"]["rows"] = [{**ledger, "status": "VALIDATED"}]
    verify(source, result, migration)
    return result


def verify(source, target, migration):
    inventory(target, CURRENT)
    check(target["workbook_reference"] == migration["destination_workbook_reference"])
    check(target.get("auxiliary_sheets", []) == source.get("auxiliary_sheets", []))
    for table, old in source["sheets"].items():
        if table in MANUAL:
            continue
        new = target["sheets"][table]
        check(len(new["rows"]) >= len(old["rows"]))
        for before, after in zip(old["rows"], new["rows"], strict=False):
            check(all(after.get(k) == v for k, v in before.items()))
        check(new.get("metadata", {}) == old.get("metadata", {}))
    # Reruns after activation must preserve manual edits instead of overwriting
    # them; initial verification binds the copied manual digest before activation.
    controls = target["sheets"]["writer_control"]["rows"]
    check(len(controls) == 1 and controls[0]["provider"] == "finary_official_mcp")


def verified_override(override, crosswalk, mcp_source_asset_id):
    check(override.get("enabled") is True)
    check(crosswalk.get("state") == "VERIFIED")
    check(
        crosswalk.get("legacy_key") == override.get("source_asset_id")
        and crosswalk.get("mcp_key") == mcp_source_asset_id
    )
    check(bool((crosswalk.get("evidence_reference") or "").strip()))
    check(datetime.fromisoformat(crosswalk["reviewed_at"]).utcoffset() is not None)
    result = deepcopy(override)
    result["source_asset_id"] = mcp_source_asset_id
    result["override_key"] = "mcp-verified:" + quote(mcp_source_asset_id, safe="-._~")
    return result


def rollback_check(legacy, preserved_mcp, reconciled_manual_digest):
    inventory(legacy, LEGACY)
    inventory(preserved_mcp, CURRENT)
    check(legacy["workbook_reference"] != preserved_mcp["workbook_reference"])
    check(all(r["state"] == "PAUSED" for r in preserved_mcp["sheets"]["writer_control"]["rows"]))
    check(reconciled_manual_digest == digest({n: legacy["sheets"][n] for n in MANUAL}))
    return {
        "legacy_workbook": legacy["workbook_reference"],
        "legacy_schema": "2.1",
        "preserved_mcp_workbook": preserved_mcp["workbook_reference"],
        "manual_reconciliation_digest": reconciled_manual_digest,
    }


def private_write(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("inventory", "plan", "apply", "verify", "rollback-check")
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--destination-reference")
    parser.add_argument("--migration-id")
    parser.add_argument("--writer-id")
    parser.add_argument("--changed-at")
    parser.add_argument("--writers-drained", action="store_true")
    parser.add_argument("--reconciled-manual-digest")
    args = parser.parse_args()
    source = json.loads(args.source.read_text())
    target = json.loads(args.target.read_text()) if args.target else None
    migration = json.loads(args.plan.read_text()) if args.plan else None
    if args.command == "inventory":
        result = inventory(source)
    elif args.command == "plan":
        result = plan(
            source,
            json.loads(args.backup.read_text()),
            args.destination_reference,
            args.migration_id,
            args.writer_id,
            args.changed_at,
        )
    elif args.command == "apply":
        result = apply(source, target, migration, writers_drained=args.writers_drained)
    elif args.command == "verify":
        verify(source, target, migration)
        result = {"status": "VALIDATED"}
    else:
        result = rollback_check(source, target, args.reconciled_manual_digest)
    private_write(args.output, result)
    print(json.dumps({"status": "OK", "command": args.command}))


if __name__ == "__main__":
    main()
