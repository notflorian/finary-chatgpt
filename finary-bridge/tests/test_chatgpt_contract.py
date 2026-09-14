"""Current consumer documentation and secret-free workbook fields."""

from pathlib import Path

from app.mcp_workbook import SCHEMA

ROOT = Path(__file__).parents[2]


def test_reference_covers_every_current_table():
    reference = (ROOT / "docs/finary-portfolio-data-knowledge.md").read_text()
    for table in SCHEMA["sheets"]:
        assert f"`{table}`" in reference
    for phrase in [
        "later account",
        "not zero",
        "48 hours",
        "not atomic",
        "Official allocation",
        "Debt detail is unavailable",
    ]:
        assert phrase.lower() in " ".join(reference.split()).lower()


def test_workbook_fields_do_not_carry_credentials():
    prohibited = ["password", "token", "cookie", "mfa", "totp", "credential", "oauth"]
    for sheet in SCHEMA["sheets"].values():
        for column in sheet["columns"]:
            assert not any(fragment in column["name"].lower() for fragment in prohibited)


def test_readme_has_current_authority_and_no_empty_compatibility_columns():
    entries = {row["key"]: row["value"] for row in SCHEMA["readme_entries"]}
    assert entries["workbook_schema"] == "1.0"
    assert entries["source_contract_version"] == "1.0.0"
    assert "Official overview" in entries["authority"]
    assert "Multiple immutable observations" in entries["history"]
    assert "Debt detail is unavailable" in entries["debt"]
    assert "Exact decimal text" in entries["money"]
