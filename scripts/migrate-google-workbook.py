"""Apply a reviewed detached migration to a separately created native workbook copy.

Uses only operator-supplied Google access in memory. The candidate must already
be a native copy of the source. No copy, activation or credential export occurs.
"""

import argparse
import getpass
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

import httpx2

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migration", ROOT / "scripts/migrate-workbook.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def entered(cell):
    value = cell.get("userEnteredValue", {})
    if "formulaValue" in value:
        return value["formulaValue"]
    return next(iter(value.values()), "")


def auxiliary_snapshot(sheet):
    """Bind user-owned auxiliary content without volatile calculated cell values."""
    result = deepcopy(sheet)
    migration.check(result["properties"].get("sheetType", "GRID") == "GRID")
    for grid in result.get("data", []):
        for row in grid.get("rowData", []):
            for value in row.get("values", []):
                for computed in ("effectiveValue", "formattedValue", "effectiveFormat", "hyperlink"):
                    value.pop(computed, None)
    return result


def native_inventory(native, schema_version="2.1", reference=None):
    schema = migration.LEGACY if schema_version == "2.1" else migration.CURRENT
    sheets = {}
    auxiliary = []
    ordered = sorted(native["sheets"], key=lambda s: s["properties"]["index"])
    for field in ("title", "sheetId", "index"):
        identifiers = [sheet["properties"][field] for sheet in ordered]
        migration.check(len(set(identifiers)) == len(identifiers))
    for sheet in ordered:
        name = sheet["properties"]["title"]
        if name not in schema["sheets"]:
            # Future canonical names indicate an interrupted or conflicting migration.
            migration.check(name not in migration.CURRENT["sheets"])
            auxiliary.append(auxiliary_snapshot(sheet))
            continue
        grid = sheet.get("data", [])
        migration.check(len(grid) <= 1 and (not grid or not grid[0].get("startRow", 0)))
        rows = grid[0].get("rowData", []) if grid else []
        header = [entered(c) for c in rows[0].get("values", [])] if rows else []
        while header and header[-1] == "":
            header.pop()
        values = []
        gap = False
        for row in rows[1:]:
            cells = [entered(c) for c in row.get("values", [])]
            migration.check(not any(c != "" for c in cells[len(header) :]))
            if any(c != "" for c in cells):
                migration.check(not gap or name in migration.MANUAL)
                values.append(
                    dict(zip(header, (cells + [""] * len(header))[: len(header)], strict=True))
                )
            else:
                gap = True
        sheets[name] = {"headers": header, "rows": values, "metadata": {}}
    inventory = {
        "schema_version": schema_version,
        "workbook_reference": reference or native["spreadsheetId"],
        "sheets": sheets,
    }
    if auxiliary:
        inventory["auxiliary_sheets"] = auxiliary
    migration.inventory(inventory, schema)
    return inventory


def native_preserved(source, candidate):
    """Verify original cells, formulas, notes and formats against the native backup."""
    tables = {s["properties"]["title"]: s for s in candidate["sheets"]}
    for old in source["sheets"]:
        new = tables.get(old["properties"]["title"])
        migration.check(
            new is not None and old["properties"]["index"] == new["properties"]["index"]
        )
        if old["properties"]["title"] not in migration.LEGACY["sheets"]:
            migration.check(auxiliary_snapshot(old) == auxiliary_snapshot(new))
            continue
        for key in (
            "merges",
            "conditionalFormats",
            "filterViews",
            "basicFilter",
            "protectedRanges",
            "charts",
            "bandedRanges",
        ):
            migration.check(old.get(key) == new.get(key))
        old_rows = old.get("data", [{}])[0].get("rowData", [])
        new_rows = new.get("data", [{}])[0].get("rowData", [])
        width = len(migration.headers(migration.LEGACY, old["properties"]["title"]))
        for index, row in enumerate(old_rows):
            cells = new_rows[index].get("values", []) if index < len(new_rows) else []
            for column, before in enumerate(row.get("values", [])):
                after = cells[column] if column < len(cells) else {}
                for key in (
                    "userEnteredValue",
                    "userEnteredFormat",
                    "note",
                    "dataValidation",
                    "textFormatRuns",
                    "pivotTable",
                ):
                    if key != "userEnteredValue" or column < width:
                        migration.check(before.get(key) == after.get(key))


def cell(value):
    if value in (None, ""):
        return {}
    kind = (
        "boolValue"
        if isinstance(value, bool)
        else "numberValue"
        if isinstance(value, (int, float))
        else "stringValue"
    )
    return {"userEnteredValue": {kind: value}}


def requests_for(source_native, candidate_native, source, plan):
    native_preserved(source_native, candidate_native)
    current = native_inventory(candidate_native, "2.1", reference=source["workbook_reference"])
    migration.check(migration.digest(current) == migration.digest(source))
    target = migration.apply(source, None, plan, writers_drained=True)
    tables = {s["properties"]["title"]: s for s in candidate_native["sheets"]}
    next_id = max(s["properties"]["sheetId"] for s in tables.values()) + 1
    requests = []
    for name, sheet in target["sheets"].items():
        if name in migration.MANUAL:
            continue
        if name in tables:
            props = tables[name]["properties"]
            sheet_id = props["sheetId"]
            previous = len(source["sheets"][name]["headers"])
            required = len(sheet["headers"])
            if props["gridProperties"]["columnCount"] < required:
                requests.append(
                    {
                        "appendDimension": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "length": required - props["gridProperties"]["columnCount"],
                        }
                    }
                )
            # Existing values and manual cells are never resubmitted.
            rows = [[*sheet["headers"][previous:]]]
            rows += [[row.get(h, "") for h in sheet["headers"][previous:]] for row in sheet["rows"]]
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": previous},
                        "rows": [{"values": [cell(v) for v in row]} for row in rows],
                        "fields": "userEnteredValue",
                    }
                }
            )
        else:
            sheet_id = next_id
            next_id += 1
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "title": name,
                            "gridProperties": {
                                "rowCount": max(1000, len(sheet["rows"]) + 1),
                                "columnCount": max(26, len(sheet["headers"])),
                            },
                        }
                    }
                }
            )
            rows = [sheet["headers"]] + [
                [r.get(h, "") for h in sheet["headers"]] for r in sheet["rows"]
            ]
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                        "rows": [{"values": [cell(v) for v in row]} for row in rows],
                        "fields": "userEnteredValue",
                    }
                }
            )
    payload = {"requests": requests}
    migration.check(len(json.dumps(payload).encode()) <= 8 * 1024 * 1024)
    return payload


class GoogleCandidate:
    def __init__(self, token, transport=None):
        self.http = httpx2.Client(
            headers={"Authorization": "Bearer " + token},
            timeout=60,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def read(self, identifier):
        response = self.http.get(
            "https://sheets.googleapis.com/v4/spreadsheets/" + quote(identifier, safe=""),
            params={"includeGridData": "true"},
        )
        response.raise_for_status()
        migration.check(len(response.content) <= 64 * 1024 * 1024)
        return response.json()

    def apply(self, source_native, source, plan):
        candidate_id = plan["destination_workbook_reference"]
        migration.check(candidate_id != source["workbook_reference"])
        before = self.read(candidate_id)
        names = {s["properties"]["title"] for s in before["sheets"]}
        if "migration_ledger" in names:
            target = native_inventory(before, "3.0")
            migration.apply(source, target, plan, writers_drained=True)
            return target
        payload = requests_for(source_native, before, source, plan)
        try:
            response = self.http.post(
                "https://sheets.googleapis.com/v4/spreadsheets/"
                + quote(candidate_id, safe="")
                + ":batchUpdate",
                json=payload,
            )
            response.raise_for_status()
        except httpx2.TransportError:
            # A lost response is resolved by reading the ledger, never by blindly
            # resubmitting addSheet requests with possibly committed IDs.
            pass
        after = self.read(candidate_id)
        native_preserved(source_native, after)
        target = native_inventory(after, "3.0")
        migration.apply(source, target, plan, writers_drained=True)
        return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "requests", "apply"))
    parser.add_argument("--workbook")
    parser.add_argument("--native-backup", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--writers-drained", action="store_true")
    args = parser.parse_args()
    try:
        client = GoogleCandidate(getpass.getpass("Independent Google access token (memory only): "))
        if args.command == "inventory":
            native = client.read(args.workbook)
            result = native_inventory(native)
            migration.private_write(args.output.with_suffix(".native.json"), native)
        else:
            source = json.loads(args.source.read_text())
            plan = json.loads(args.plan.read_text())
            backup = json.loads(args.native_backup.read_text())
            migration.check(native_inventory(backup) == source)
            migration.check(args.writers_drained)
            if args.command == "requests":
                result = requests_for(
                    backup, client.read(plan["destination_workbook_reference"]), source, plan
                )
            else:
                result = client.apply(backup, source, plan)
        migration.private_write(args.output, result)
        print('{"status":"VALIDATED"}')
    except Exception:
        print('{"status":"MIGRATION_REVIEW_REQUIRED"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
