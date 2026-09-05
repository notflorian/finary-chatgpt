"""Credential-free checks for the normalized ChatGPT workbook boundary."""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "docs/google-sheets-schema.json"
RUNBOOK_PATH = REPOSITORY_ROOT / "docs/chatgpt.md"
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
    assert "positions_count" in entries["history_rule"]["description"]
    assert "portfolio_daily.run_id" in entries["history_rule"]["description"]
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
    assert {"history_key", "snapshot_date", "run_id"} <= _column_names(
        schema, "positions_history"
    )
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
    normalized_runbook = " ".join(runbook.split())

    for phrase in (
        "Google Sheets OAuth credential and the ChatGPT Google Drive connection are independent",
        "blank currency and numeric cells as unknown, never zero",
        "liabilities and net worth are unknown, not zero",
        "does not revoke the separate Google OAuth credential stored in n8n",
        "does not authorize automated purchases, sales, or transfers",
    ):
        assert phrase in normalized_runbook


def test_project_reference_covers_workbook_semantics() -> None:
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
    assert "does not replace the ChatGPT Project's behavioral Instructions" in reference


def test_chatgpt_surface_uses_project_instead_of_custom_gpt() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
    normalized_runbook = " ".join(runbook.split())

    for phrase in (
        "Use a private ChatGPT **Project**",
        "custom-GPT editor/runtime did not expose the Google Drive connection",
        "scoped product limitation",
        "Google Drive files added to a Project are retrieved on demand",
        "Add the exact private **Finary Portfolio Data** spreadsheet link",
        "Do not export a static workbook copy",
    ):
        assert phrase in normalized_runbook


def test_current_membership_and_fallback_rules_are_published() -> None:
    entries = {entry["key"]: entry for entry in _schema()["readme_entries"]}
    current = entries["current_state_rule"]["description"]
    for phrase in (
        "full accounts_current and positions_current tables before filtering",
        "unique canonical keys", "last_seen_run_id", "accounts_count", "positions_count",
        "never blanks or booleans", "without deduplication", "validated active accounts",
        "position-key sets", "not their last write", "validated history or report unavailable",
    ):
        assert phrase in current
    history = entries["history_rule"]["description"]
    for phrase in (
        "timezone-aware completed_at", "before selecting matching run_id",
        "success cannot restore overwritten rows", "newest valid date first",
        "stale after 48 hours", "Never enrich history from invalid current rows",
        "reconstruct account balances", "aggregate can remain usable without position detail",
    ):
        assert phrase in history
    success = entries["last_success_rule"]["description"]
    for phrase in (
        "opaque equality key", "including failure records", "duplicate terminal records",
        "tied newest instants", "latest success is distinct from the latest state",
    ):
        assert phrase in success


def test_independent_liability_provenance_and_read_limits_are_published() -> None:
    entries = {entry["key"]: entry for entry in _schema()["readme_entries"]}
    liabilities = entries["last_known_liability_rule"]["description"]
    for phrase in (
        "liabilities_count", "Every active last_seen_run_id", "COMPLETE run_id",
        "retained inactive", "failed COMPLETE writes", "no liability history fallback",
        "same-day daily replacement", "zero count", "snapshot date is unavailable",
    ):
        assert phrase in liabilities
    assert "never subtract older last-known liabilities" in entries["liability_rule"]["description"]
    assert "sequential reads are not a transactional snapshot" in entries["failed_snapshot_rule"][
        "description"
    ]
    for filename in (
        "README.md", "docs/architecture.md", "docs/data-model.md", "docs/chatgpt.md",
        "docs/operations.md", "docs/finary-portfolio-data-knowledge.md",
    ):
        text = " ".join((REPOSITORY_ROOT / filename).read_text().split())
        assert "test-only" in text
        assert "transaction" in text.lower()
        assert "latest known valid normalized" not in text
    for filename in ("docs/chatgpt.md", "docs/operations.md", "README.md"):
        text = " ".join((REPOSITORY_ROOT / filename).read_text().split())
        assert "not automatically rewrit" in text
        assert "knowledge" in text
