"""Contract tests for the Google Sheets schema definition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast, get_args

from app.models import Account, AssetClass, Liability, Position

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "docs" / "google-sheets-schema.json"
DOCUMENTATION_PATH = REPOSITORY_ROOT / "docs" / "data-model.md"

REQUIRED_SHEETS = (
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
)
ALLOWED_TYPES = {"STRING", "NUMBER", "BOOLEAN", "DATE", "DATETIME", "ENUM"}
ALLOWED_OWNERS = {"automated", "manual", "derived"}
EXPECTED_HEADERS = {
    "README": ("key", "value", "description"),
    "accounts_current": (
        "account_key", "source", "source_account_id", "name", "institution",
        "account_type", "owner", "currency", "market_value_eur", "last_seen_at",
        "last_seen_run_id", "is_active",
    ),
    "positions_current": (
        "position_key", "source", "source_asset_id", "account_key", "account_name",
        "account_type", "institution", "name", "ticker", "isin", "asset_class",
        "asset_subclass", "region", "quantity", "unit_price", "currency",
        "fx_to_eur", "market_value_native", "market_value_eur", "cost_basis_eur",
        "unrealized_pnl_eur", "unrealized_pnl_pct", "weight_portfolio",
        "last_seen_at", "last_seen_run_id", "is_active",
    ),
    "liabilities_current": (
        "liability_key", "source", "source_liability_id", "name", "liability_type",
        "institution", "outstanding_eur", "interest_rate", "monthly_payment_eur",
        "end_date", "last_seen_at", "last_seen_run_id", "is_active",
    ),
    "positions_history": (
        "history_key", "snapshot_date", "generated_at", "position_key",
        "account_key", "source_asset_id", "name", "ticker", "isin", "asset_class",
        "asset_subclass", "quantity", "unit_price", "currency", "fx_to_eur",
        "market_value_eur", "cost_basis_eur",
    ),
    "portfolio_daily": (
        "snapshot_date", "generated_at", "gross_assets_eur", "liability_coverage",
        "liabilities_eur", "net_worth_eur", "financial_assets_eur", "equity_eur", "bond_eur",
        "cash_eur", "real_estate_eur", "scpi_eur", "private_equity_eur",
        "crypto_eur", "commodity_eur", "life_insurance_fund_eur", "other_eur",
        "equity_pct", "bond_pct", "cash_pct", "real_estate_pct", "scpi_pct",
        "private_equity_pct", "crypto_pct", "commodity_pct",
        "life_insurance_fund_pct", "other_pct", "pea_eur", "cto_eur",
        "life_insurance_eur", "cash_accounts_eur", "run_id",
    ),
    "allocation_targets": (
        "target_key", "asset_class", "asset_subclass", "target_pct", "min_pct",
        "max_pct", "notes", "enabled",
    ),
    "asset_overrides": (
        "override_key", "source_asset_id", "isin", "ticker", "name_match",
        "custom_asset_class", "custom_asset_subclass", "custom_region", "notes",
        "enabled",
    ),
    "cashflows": (
        "cashflow_key", "date", "account_key", "amount_eur", "type", "notes",
        "source",
    ),
    "sync_runs": (
        "run_id", "started_at", "completed_at", "status", "accounts_count",
        "positions_count", "liabilities_count", "liability_coverage", "gross_assets_eur",
        "liabilities_eur", "net_worth_eur", "previous_net_worth_eur",
        "net_worth_change_pct", "duration_ms", "bridge_version", "schema_version",
        "warning_count", "error_code", "error_message",
    ),
}


def _schema() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
    )


def _column_names(sheet: dict[str, Any]) -> list[str]:
    return [column["name"] for column in sheet["columns"]]


def test_required_sheets_and_order_are_canonical() -> None:
    schema = _schema()

    assert schema["workbook_name"] == "Finary Portfolio Data"
    assert tuple(schema["sheets"]) == REQUIRED_SHEETS
    assert schema["timezone"] == "Europe/Paris"
    assert schema["reference_currency"] == "EUR"
    assert schema["null_cell"] == ""
    assert schema["boolean_values"] == ["TRUE", "FALSE"]
    assert schema["key_formats"] == {
        "account_key": "finary:account:{account_id}",
        "source_asset_id": "{position_kind}:{asset_id}",
        "position_key": "finary:{account_id}:asset:{position_kind}:{asset_id}",
        "history_key": "{snapshot_date}:{position_key}",
        "portfolio_daily": "{snapshot_date}",
        "run_id": "YYYYMMDD-HHMMSS",
    }
    assert [entry["key"] for entry in schema["readme_entries"]] == [
        "reference_currency",
        "timezone",
        "current_state_rule",
        "history_rule",
        "override_rule",
        "null_rule",
        "eur_rule",
        "gross_assets_rule",
        "failed_snapshot_rule",
        "liability_rule",
        "partial_liability_rule",
        "unavailable_liability_rule",
        "last_known_liability_rule",
        "allocation_rule",
        "last_success_rule",
        "performance_rule",
    ]
    for sheet_name, expected_headers in EXPECTED_HEADERS.items():
        assert tuple(_column_names(schema["sheets"][sheet_name])) == expected_headers


def test_columns_have_deterministic_valid_definitions() -> None:
    for sheet in _schema()["sheets"].values():
        names = _column_names(sheet)

        assert names
        assert len(names) == len(set(names))
        assert sheet["unique_key"] in names
        assert sheet["sheet_ownership"] in ALLOWED_OWNERS
        for column in sheet["columns"]:
            assert set(column) == {
                "name",
                "type",
                "nullable",
                "ownership",
                "source",
            }
            assert column["type"] in ALLOWED_TYPES
            assert isinstance(column["nullable"], bool)
            assert column["ownership"] in ALLOWED_OWNERS
            assert column["source"]


def test_manual_and_automated_sheet_ownership_is_explicit() -> None:
    sheets = _schema()["sheets"]

    for name in ("allocation_targets", "asset_overrides", "cashflows"):
        assert sheets[name]["sheet_ownership"] == "manual"
        assert {column["ownership"] for column in sheets[name]["columns"]} == {
            "manual"
        }

    for name in (
        "README",
        "accounts_current",
        "positions_current",
        "liabilities_current",
        "positions_history",
    ):
        assert sheets[name]["sheet_ownership"] == "automated"


def test_nullable_eur_and_currency_fields_preserve_unknown_values() -> None:
    schema = _schema()
    sheets = schema["sheets"]
    position_columns = {
        column["name"]: column for column in sheets["positions_current"]["columns"]
    }
    daily_columns = {
        column["name"]: column for column in sheets["portfolio_daily"]["columns"]
    }

    for name in ("currency", "fx_to_eur", "market_value_eur", "cost_basis_eur"):
        assert position_columns[name]["nullable"] is True
    for name in ("liabilities_eur", "net_worth_eur", "financial_assets_eur"):
        assert daily_columns[name]["nullable"] is True
    assert schema["null_cell"] == ""


def test_stable_models_map_without_raw_metadata_columns() -> None:
    sheets = _schema()["sheets"]
    account_columns = set(_column_names(sheets["accounts_current"]))
    position_columns = set(_column_names(sheets["positions_current"]))
    liability_columns = set(_column_names(sheets["liabilities_current"]))

    assert set(Account.model_fields) - {"metadata"} <= account_columns
    assert set(Position.model_fields) - {"metadata"} <= position_columns
    assert set(Liability.model_fields) - {"metadata"} <= liability_columns
    for sheet in sheets.values():
        names = set(_column_names(sheet))
        assert "metadata" not in names
        assert "metadata_json" not in names


def test_entity_nullability_matches_stable_models() -> None:
    schema = _schema()["sheets"]
    mappings = (
        (Account, schema["accounts_current"]),
        (Position, schema["positions_current"]),
        (Liability, schema["liabilities_current"]),
    )

    for model, sheet in mappings:
        columns = {column["name"]: column for column in sheet["columns"]}
        for field_name, field in model.model_fields.items():
            if field_name == "metadata":
                continue
            assert columns[field_name]["nullable"] is (type(None) in get_args(field.annotation))


def test_category_aware_key_contract_is_documented() -> None:
    markdown = DOCUMENTATION_PATH.read_text(encoding="utf-8")
    compact_markdown = " ".join(markdown.split())

    assert "source_asset_id = {position_kind}:{asset_id}" in compact_markdown
    assert (
        "position_key = finary:{account_id}:asset:{position_kind}:{asset_id}"
        in compact_markdown
    )
    assert "{snapshot_date}:{position_key}" in compact_markdown
    assert "equal numeric IDs" in compact_markdown


def test_manual_enums_and_percentage_representation_are_complete() -> None:
    schema = _schema()

    assert schema["percentage_representation"] == "decimal_fraction"
    assert schema["allocation_target_constraint"] == (
        "0 <= min_pct <= target_pct <= max_pct <= 1"
    )
    assert schema["override_matching_precedence"] == [
        "source_asset_id",
        "isin",
        "ticker",
        "name_match",
    ]
    assert schema["enums"]["asset_class"] == [item.value for item in AssetClass]
    assert schema["enums"]["cashflow_type"] == [
        "CONTRIBUTION",
        "WITHDRAWAL",
        "DIVIDEND",
        "INTEREST",
        "FEE",
        "TAX",
        "TRANSFER",
    ]
    assert schema["enums"]["sync_status"] == [
        "SUCCESS",
        "SUCCESS_WITH_WARNINGS",
        "FAILED",
    ]
    assert schema["cashflow_sign_convention"]["positive"] == [
        "CONTRIBUTION",
        "DIVIDEND",
        "INTEREST",
    ]
    assert schema["cashflow_sign_convention"]["negative"] == [
        "WITHDRAWAL",
        "FEE",
        "TAX",
    ]
    markdown = DOCUMENTATION_PATH.read_text(encoding="utf-8")
    assert "0 <= min_pct <= target_pct <= max_pct <= 1" in markdown
    assert "`0.75` means 75%" in markdown


def test_data_model_documents_canonical_schema_without_field_duplication() -> None:
    schema = _schema()
    markdown = DOCUMENTATION_PATH.read_text(encoding="utf-8")
    compact_markdown = " ".join(markdown.split())

    assert "single machine-readable source" in compact_markdown
    for sheet_name in schema["sheets"]:
        assert f"`{sheet_name}`" in markdown


def test_definition_is_data_only_and_has_no_google_credentials() -> None:
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8").lower()

    assert SCHEMA_PATH.suffix == ".json"
    assert "client_secret" not in schema_text
    assert "private_key" not in schema_text
    assert "refresh_token" not in schema_text
    assert "https://" not in schema_text
