"""Schema 2.0 checks for explicit liability coverage."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
V2_SCHEMA_PATH = ROOT / "docs" / "google-sheets-schema.json"
V2_DOCUMENTATION_PATH = ROOT / "docs" / "google-sheets-schema.md"


def _schema() -> dict[str, object]:
    return json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_v2_schema_preserves_ten_sheets_and_adds_coverage_enum() -> None:
    schema = _schema()
    assert schema["schema_version"] == "2.0"
    assert set(schema["sheets"]) == {
        "README",
        "accounts_current",
        "positions_current",
        "liabilities_current",
        "positions_history",
        "portfolio_daily",
        "allocation_targets",
        "asset_overrides",
        "cashflows",
        "sync_runs",
    }
    assert schema["enums"]["liability_coverage"] == [
        "COMPLETE",
        "PARTIAL",
        "UNAVAILABLE",
    ]


def test_v2_coverage_columns_have_deterministic_order_and_nullability() -> None:
    schema = _schema()
    daily = schema["sheets"]["portfolio_daily"]["columns"]
    telemetry = schema["sheets"]["sync_runs"]["columns"]
    daily_names = [column["name"] for column in daily]
    telemetry_names = [column["name"] for column in telemetry]

    assert daily_names.index("liability_coverage") == daily_names.index(
        "gross_assets_eur"
    ) + 1
    assert telemetry_names.index("liability_coverage") == telemetry_names.index(
        "liabilities_count"
    ) + 1
    assert next(
        column for column in daily if column["name"] == "liability_coverage"
    )["nullable"] is False
    assert next(
        column for column in telemetry if column["name"] == "liability_coverage"
    )["nullable"] is True


def test_v2_data_dictionary_documents_migration_and_unknown_semantics() -> None:
    documentation = V2_DOCUMENTATION_PATH.read_text(encoding="utf-8")
    for phrase in (
        "Only `COMPLETE` may update `liabilities_current`",
        "blank. Blank never means zero",
        "passed live acceptance",
        "FINARY_GOOGLE_SHEET_ID",
        "no parallel v1",
    ):
        assert phrase in documentation
