"""Credential-free checks for the normalized ChatGPT workbook boundary."""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "docs/google-sheets-schema.json"
RUNBOOK_PATH = REPOSITORY_ROOT / "docs/chatgpt-connection.md"
KNOWLEDGE_PATH = REPOSITORY_ROOT / "docs/finary-portfolio-data-knowledge.md"


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _column_names(schema: dict[str, object], sheet: str) -> set[str]:
    sheets = schema["sheets"]
    return {column["name"] for column in sheets[sheet]["columns"]}


def test_chatgpt_readme_semantics_are_machine_readable() -> None:
    schema = _schema()
    entries = {entry["key"]: entry for entry in schema["readme_entries"]}
    required = {
        "null_rule",
        "gross_assets_rule",
        "liability_rule",
        "partial_liability_rule",
        "unavailable_liability_rule",
        "last_known_liability_rule",
        "allocation_rule",
        "last_success_rule",
        "performance_rule",
    }

    assert required <= entries.keys()
    assert "SUCCESS or SUCCESS_WITH_WARNINGS" in entries["last_success_rule"][
        "value"
    ]
    assert "later FAILED row does not replace" in entries["last_success_rule"][
        "description"
    ]
    assert "not investment performance" in entries["performance_rule"]["value"]
    assert "blank never means zero" in entries["null_rule"]["value"]


def test_chatgpt_current_daily_and_telemetry_fields_are_stable() -> None:
    schema = _schema()

    assert {"is_active"} <= _column_names(schema, "accounts_current")
    assert {
        "is_active",
        "market_value_eur",
        "weight_portfolio",
    } <= _column_names(schema, "positions_current")
    assert {
        "snapshot_date",
        "generated_at",
        "gross_assets_eur",
        "liability_coverage",
        "liabilities_eur",
        "net_worth_eur",
        "run_id",
    } <= _column_names(schema, "portfolio_daily")
    assert {
        "run_id",
        "completed_at",
        "status",
        "liability_coverage",
        "warning_count",
        "error_code",
    } <= _column_names(schema, "sync_runs")


def test_liability_current_requires_complete_coverage() -> None:
    schema = _schema()
    liability_sheet = schema["sheets"]["liabilities_current"]

    assert "only when liability_coverage is COMPLETE" in liability_sheet[
        "update_behavior"
    ]
    assert "PARTIAL or UNAVAILABLE never writes" in liability_sheet[
        "update_behavior"
    ]


def test_workbook_schema_has_no_secret_bearing_fields() -> None:
    schema = _schema()
    prohibited_fragments = {
        "password",
        "token",
        "cookie",
        "mfa",
        "totp",
        "clerk_session",
        "n8n_credential",
        "oauth_refresh",
    }
    column_names = {
        column["name"].lower()
        for sheet in schema["sheets"].values()
        for column in sheet["columns"]
    }

    for name in column_names:
        assert not any(fragment in name for fragment in prohibited_fragments)


def test_chatgpt_runbook_preserves_consumer_and_revocation_boundaries() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    for phrase in (
        "independent of the Google Sheets OAuth",
        "blank cell is unknown/unavailable, never zero",
        "must not be added to account",
        "last-known complete liability state",
        "later failures do not advance it",
        "not investment performance",
        "ACTUAL_DISCONNECT_RECONNECT_TEST=PASS",
        "No custom MCP, plugin, proxy, webhook, public URL",
    ):
        assert phrase in runbook


def test_custom_gpt_knowledge_reference_covers_workbook_semantics() -> None:
    reference = KNOWLEDGE_PATH.read_text(encoding="utf-8")
    normalized_reference = " ".join(reference.split()).lower()

    for sheet in _schema()["sheets"]:
        assert f"`{sheet}`" in reference

    for phrase in (
        "newest valid `completed_at`",
        "`SUCCESS_WITH_WARNINGS`",
        "`is_active = TRUE`",
        "it never means zero",
        "no speculative foreign-exchange conversion",
        "Never calculate gross assets by adding account balances and position",
        "`PARTIAL_POSITION_EUR_COVERAGE`",
        "They are not, by themselves, investment returns",
        "external cashflows are complete",
        "finary:{account_id}:asset:{position_kind}:{asset_id}",
        "ISO 8601 with an explicit timezone offset",
    ):
        assert phrase.lower() in normalized_reference

    assert "Personal Investment Policy" in reference
    assert "does not replace the custom GPT's behavioral Instructions" in reference
