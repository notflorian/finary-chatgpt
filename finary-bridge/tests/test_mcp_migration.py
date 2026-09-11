"""Reviewed native migration requests exercised against synthetic Google HTTP."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "native_migration", ROOT / "scripts/migrate-google-workbook.py"
)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
migration = native.migration


def source_grid():
    sheets = []
    for index, (name, table) in enumerate(migration.LEGACY["sheets"].items()):
        values = [{"userEnteredValue": {"stringValue": c["name"]}} for c in table["columns"]]
        rows = [{"values": values}]
        if name == "portfolio_daily":
            rows.append({"values": [{"userEnteredValue": {"stringValue": "2026-09-11"}}]})
        if name == "asset_overrides":
            rows.append(
                {
                    "values": [
                        {
                            "userEnteredValue": {"stringValue": "manual"},
                            "note": "Synthetic note",
                            "userEnteredFormat": {"textFormat": {"bold": True}},
                        }
                    ]
                }
            )
        sheets.append(
            {
                "properties": {
                    "sheetId": index + 1,
                    "title": name,
                    "index": index,
                    "gridProperties": {"columnCount": max(26, len(values)), "rowCount": 1000},
                },
                "data": [{"rowData": rows}],
            }
        )
    return {"spreadsheetId": "synthetic-source", "sheets": sheets}


class FakeGoogle:
    def __init__(self, original, lost_response=False):
        self.value = deepcopy(original)
        self.value["spreadsheetId"] = "synthetic-candidate"
        self.posts = []
        self.lost_response = lost_response

    def respond(self, request):
        assert str(request.url).startswith(
            "https://sheets.googleapis.com/v4/spreadsheets/synthetic-candidate"
        )
        if request.method == "POST":
            payload = json.loads(request.content)
            self.posts.append(payload)
            for item in payload["requests"]:
                if "addSheet" in item:
                    props = deepcopy(item["addSheet"]["properties"])
                    props["index"] = len(self.value["sheets"])
                    self.value["sheets"].append({"properties": props, "data": [{"rowData": []}]})
                elif "appendDimension" in item:
                    dimension = item["appendDimension"]
                    sheet = next(
                        s
                        for s in self.value["sheets"]
                        if s["properties"]["sheetId"] == dimension["sheetId"]
                    )
                    sheet["properties"]["gridProperties"]["columnCount"] += dimension["length"]
                else:
                    update = item["updateCells"]
                    start = update["start"]
                    sheet = next(
                        s
                        for s in self.value["sheets"]
                        if s["properties"]["sheetId"] == start["sheetId"]
                    )
                    rows = sheet["data"][0]["rowData"]
                    for offset, row in enumerate(update["rows"]):
                        index = start["rowIndex"] + offset
                        while len(rows) <= index:
                            rows.append({"values": []})
                        cells = rows[index]["values"]
                        for column, value in enumerate(row["values"], start["columnIndex"]):
                            while len(cells) <= column:
                                cells.append({})
                            cells[column].update(value)
            if self.lost_response:
                raise httpx2.ReadError("Synthetic response loss")
            return httpx2.Response(200, json={"replies": []})
        return httpx2.Response(200, json=self.value)


@pytest.mark.parametrize("response_lost", [False, True])
def test_native_copy_migration_replay_and_response_loss(response_lost):
    original = source_grid()
    source = native.native_inventory(original)
    plan = migration.plan(
        source,
        deepcopy(source),
        "synthetic-candidate",
        "migration-synthetic",
        "synthetic-writer",
        "2026-09-11T10:00:00+02:00",
    )
    peer = FakeGoogle(original, response_lost)
    client = native.GoogleCandidate("synthetic-google", httpx2.MockTransport(peer.respond))
    target = client.apply(original, source, plan)
    assert client.apply(original, source, plan) == target
    assert len(peer.posts) == 1
    assert target["sheets"]["writer_control"]["rows"][0]["state"] == "PAUSED"
    assert target["sheets"]["portfolio_daily"]["rows"][0]["daily_key"] == "2026-09-11"
    assert target["sheets"]["asset_overrides"] == source["sheets"]["asset_overrides"]
    assert not any(
        item.get("updateCells", {}).get("start", {}).get("sheetId") == 9
        for item in peer.posts[0]["requests"]
    )


def test_native_copy_changed_manual_value_is_not_overwritten():
    original = source_grid()
    source = native.native_inventory(original)
    plan = migration.plan(
        source,
        deepcopy(source),
        "synthetic-candidate",
        "migration-synthetic",
        "synthetic-writer",
        "2026-09-11T10:00:00+02:00",
    )
    peer = FakeGoogle(original)
    peer.value["sheets"][8]["data"][0]["rowData"][0]["values"][0]["userEnteredValue"] = {
        "stringValue": "conflict"
    }
    with pytest.raises(ValueError):
        native.GoogleCandidate("synthetic", httpx2.MockTransport(peer.respond)).apply(
            original, source, plan
        )
    assert not peer.posts


def test_override_exact_pair_and_rollback_preserve_manual_edits():
    original = source_grid()
    source = native.native_inventory(original)
    plan = migration.plan(
        source,
        deepcopy(source),
        "synthetic-candidate",
        "migration-synthetic",
        "synthetic-writer",
        "2026-09-11T10:00:00+02:00",
    )
    target = migration.apply(source, None, plan, writers_drained=True)
    target["sheets"]["asset_overrides"]["rows"][0]["notes"] = "New manual change"
    assert migration.apply(source, target, plan, writers_drained=True) == target
    digest = migration.digest({name: source["sheets"][name] for name in migration.MANUAL})
    assert migration.rollback_check(source, target, digest)["legacy_schema"] == "2.1"
    override = {"enabled": True, "source_asset_id": "security:1"}
    pair = {
        "state": "VERIFIED",
        "legacy_key": "security:1",
        "mcp_key": "mcp:holding:securities:h1",
        "evidence_reference": "Synthetic reviewed holding",
        "reviewed_at": "2026-09-11T10:00:00+02:00",
    }
    assert (
        migration.verified_override(override, pair, pair["mcp_key"])["source_asset_id"]
        == pair["mcp_key"]
    )
    for changes in (
        {"state": "UNRESOLVED"},
        {"legacy_key": "security:2"},
        {"evidence_reference": ""},
    ):
        with pytest.raises(ValueError):
            migration.verified_override(override, {**pair, **changes}, pair["mcp_key"])
