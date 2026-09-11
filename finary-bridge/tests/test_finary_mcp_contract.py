"""Offline schema and cross-record checks for the planned MCP contract.

This is a fixture oracle, not a transport client, normalizer or migration engine.
Declared connector payloads and project acceptance have separate validation.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs" / "finary-mcp-contract.json"
FIXTURES = Path(__file__).parent / "fixtures" / "finary-mcp"
CONTRACT = json.loads(CONTRACT_PATH.read_text())
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
BASES = json.loads((FIXTURES / MANIFEST["base_file"]).read_text())
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(TypeError, ValueError))
def timezone_timestamp(value):
    """Require a real timezone-aware datetime without optional format packages."""
    return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None


def validator(reference):
    return Draft202012Validator(
        {"$ref": reference, "$defs": CONTRACT["$defs"]}, format_checker=FORMATS
    )


def materialize(case):
    value = deepcopy(BASES[case["base"]])
    for change in case["changes"]:
        parts = [
            part.replace("~1", "/").replace("~0", "~") for part in change["path"].split("/")[1:]
        ]
        target = value
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        if change["op"] == "remove":
            del target[key]
        else:
            assert change["op"] == "set"
            target[key] = deepcopy(change["value"])
    return value


def identity(template, **values):
    return CONTRACT["identity"][template].format(
        **{f"E({key})": quote(value, safe="-._~") for key, value in values.items()}, **values
    )


def pagination_error(value):
    """Check recorded page evidence without fetching or normalizing anything."""
    pages = value["pages"]
    limits = CONTRACT["transport_policy"]["limits"]
    if not pages or len(pages) > limits["max_pages_per_account"]:
        return "MCP_INCOMPLETE_COLLECTION"
    offset, total, limit = 0, pages[0]["meta"]["total"], pages[0]["meta"]["limit"]
    seen = set()
    offsets = set()
    included = {}
    for page in pages:
        meta, rows = page["meta"], page["data"]
        if meta["offset"] in offsets:
            return "MCP_INCOMPLETE_COLLECTION"
        offsets.add(meta["offset"])
        if (meta["offset"], meta["total"], meta["limit"]) != (offset, total, limit):
            return "MCP_INCOMPLETE_COLLECTION"
        if len(rows) > limit or (not rows and (total != 0 or offset != 0)):
            return "MCP_INCOMPLETE_COLLECTION"
        offset += len(rows)
        if offset > total or offset > limits["max_holdings_per_run"]:
            return "MCP_INCOMPLETE_COLLECTION"
        if meta["has_more"] != (offset < total):
            return "MCP_INCOMPLETE_COLLECTION"
        for resource in page["included"]:
            key = resource["type"], resource["id"]
            if key in included and included[key] != resource:
                return "MCP_INCOMPLETE_COLLECTION"
            included[key] = resource
        for row in rows:
            key = row["type"], row["id"]
            if key in seen or row["relationships"]["asset"]["data"] != {
                "type": "assets",
                "id": value["account_id"],
            }:
                return "MCP_INCOMPLETE_COLLECTION"
            if row["type"] not in CONTRACT["pagination"]["observed_types"]:
                return "MCP_UNSUPPORTED_DETAIL"
            seen.add(key)
    if offset != total or pages[-1]["meta"]["has_more"]:
        return "MCP_INCOMPLETE_COLLECTION"
    return None


def money_error(money, overview_currency=None):
    amount, eur, currency = money["amount"], money["amount_eur"], money["currency"]
    if overview_currency is not None and currency != overview_currency:
        return "CURRENCY_EVIDENCE"
    if amount is None:
        return None if eur is None and money["eur_basis"] == "UNAVAILABLE" else "CURRENCY_EVIDENCE"
    if currency is None:
        return "CURRENCY_EVIDENCE"
    if money["eur_basis"] == "SOURCE_EUR" and currency != "EUR":
        return "CURRENCY_EVIDENCE"
    if currency == "EUR":
        if eur is None or Decimal(amount) != Decimal(eur) or money["eur_basis"] != "SOURCE_EUR":
            return "CURRENCY_EVIDENCE"
    elif overview_currency is not None and (eur is not None or money["eur_basis"] != "UNAVAILABLE"):
        return "CURRENCY_EVIDENCE"
    return None


def valuation_error(value):
    """Check native valuation coverage independently of EUR or ownership quality."""
    for dimension, rule in CONTRACT["valuation_contracts"].items():
        rows = value[rule["rows"]]
        known = sum(
            row[rule["money_field"]]["amount"] is not None
            and row[rule["money_field"]]["currency"] is not None
            for row in rows
        )
        if value["coverage"][rule["collection"]] != "COMPLETE":
            expected = "UNAVAILABLE"
        elif known == len(rows):
            expected = "COMPLETE"
        elif known:
            expected = "PARTIAL"
        else:
            expected = "UNAVAILABLE"
        if value["coverage"][dimension] != expected:
            return "VALUATION_COVERAGE"
    return None


def snapshot_error(value):
    provenance = value["provenance"]
    start = datetime.fromisoformat(provenance["collection_started_at"])
    end = datetime.fromisoformat(provenance["collection_ended_at"])
    generated = datetime.fromisoformat(value["generated_at"])
    if not start <= end <= generated:
        return "COLLECTION_WINDOW"
    if generated.astimezone(ZoneInfo("Europe/Paris")).date().isoformat() != value["snapshot_date"]:
        return "COLLECTION_WINDOW"
    if error := valuation_error(value):
        return error
    groups = [
        value["overview"][name]
        for name in (
            "gross_assets",
            "financial_assets",
            "reported_liabilities",
            "reported_net_worth",
        )
    ]
    groups += [row["value"] for row in value["allocation_categories"] + value["allocation_types"]]
    groups += [
        row[name]
        for row in value["members"]
        for name in ("gross_assets", "reported_liabilities", "reported_net_worth")
    ]
    for group in groups:
        if error := money_error(group, provenance["currency"]):
            return error
    accounts = {row["account_key"] for row in value["accounts"]}
    if len(accounts) != len(value["accounts"]):
        return "IDENTITY"
    warnings = {(row["code"], row["entity_key"]) for row in value["warnings"]}
    if len(warnings) != len(value["warnings"]):
        return "IDENTITY"
    diagnostics = set()
    for row in value["unsupported_details"]:
        key = row["account_key"], row["holding_type"], row["reason"]
        if key in diagnostics or row["account_key"] not in accounts:
            return "IDENTITY"
        diagnostics.add(key)
    for row in value["accounts"]:
        if row["account_key"] != identity("account_key", account_id=row["source_account_id"]):
            return "IDENTITY"
        if error := money_error(row["native_balance"]):
            return error
        if (
            row["native_balance"]["eur_basis"] == "SOURCE_CONVERSION"
            and (
                row["native_balance"]["amount_eur"] is None
                or row["full_value_eur"] is None
                or Decimal(row["native_balance"]["amount_eur"]) != Decimal(row["full_value_eur"])
            )
        ):
            return "CURRENCY_EVIDENCE"
    connections = {row["connection_key"] for row in value["connections"]}
    if len(connections) != len(value["connections"]):
        return "IDENTITY"
    for row in value["accounts"]:
        if row["connection_state"] == "NO_CONNECTION" and row["connection_key"] is not None:
            return "IDENTITY"
        if row["connection_state"] == "RESOLVED" and row["connection_key"] not in connections:
            return "IDENTITY"
        if row["connection_state"] == "UNRESOLVED" and row["connection_key"] is None:
            return "IDENTITY"
    owners = set()
    for row in value["ownership"]:
        key = row["account_key"], row["owner_key"]
        if key in owners or row["account_key"] not in accounts:
            return "IDENTITY"
        owners.add(key)
        if row["owner_key"] != identity(
            "owner_key", owner_type=row["owner_type"], owner_id=row["owner_source_id"]
        ):
            return "IDENTITY"
        parent = next(a for a in value["accounts"] if a["account_key"] == row["account_key"])
        if parent["ownership_evidence"] != "EXPLICIT_ENTRIES":
            return "IDENTITY"
    holdings = set()
    for row in value["positions"]:
        key = row["holding_type"], row["holding_id"]
        if key in holdings or row["account_key"] not in accounts:
            return "IDENTITY"
        holdings.add(key)
        source_id = next(
            a["source_account_id"]
            for a in value["accounts"]
            if a["account_key"] == row["account_key"]
        )
        args = {"holding_type": row["holding_type"], "holding_id": row["holding_id"]}
        if row["source_asset_id"] != identity("source_asset_id", **args):
            return "IDENTITY"
        if row["position_key"] != identity("position_key", account_id=source_id, **args):
            return "IDENTITY"
        for name in ("current_value", "buying_price"):
            if row[name]["eur_basis"] == "SOURCE_CONVERSION":
                return "CURRENCY_EVIDENCE"
            if error := money_error(row[name]):
                return error
    positions = {row["position_key"] for row in value["positions"]}
    rates = set()
    for row in value["position_rates"]:
        key = row["position_key"], row["source_field"]
        if row["position_key"] not in positions or key in rates:
            return "IDENTITY"
        rates.add(key)
    categories = {row["category"] for row in value["allocation_categories"]}
    if len(categories) != len(value["allocation_categories"]):
        return "IDENTITY"
    types = set()
    for row in value["allocation_types"]:
        key = row["category"], row["holding_type"]
        if row["category"] not in categories or key in types:
            return "IDENTITY"
        types.add(key)
    ordinals = {row["member_ordinal"] for row in value["members"]}
    if len(ordinals) != len(value["members"]):
        return "IDENTITY"
    for row in [value["overview"], *value["members"]]:
        amount = row["reported_liabilities"]["amount"]
        if amount is not None and Decimal(amount) < 0:
            return "NEGATIVE_DEBT"
    return None


def migration_error(value):
    expected_daily = identity(
        "daily_key", snapshot_date=value["snapshot_date"], observation_id=value["observation_id"]
    )
    if value["mcp_account_key"] != identity("account_key", account_id=value["mcp_account_id"]):
        return "MIGRATION_BOUNDARY"
    if value["legacy_account_key"] == value["mcp_account_key"]:
        return "MIGRATION_BOUNDARY"
    if (
        value["legacy_daily_key"] == value["mcp_daily_key"]
        or value["mcp_daily_key"] != expected_daily
    ):
        return "MIGRATION_BOUNDARY"
    expected_history = identity(
        "history_key",
        snapshot_date=value["snapshot_date"],
        observation_id=value["observation_id"],
        position_key=value["mcp_position_key"],
    )
    if value["mcp_history_key"] != expected_history:
        return "MIGRATION_BOUNDARY"
    if value["legacy_history_key"] == value["mcp_history_key"]:
        return "MIGRATION_BOUNDARY"
    crosswalk = value["crosswalk"]
    documented = (
        crosswalk["mcp_key"] is not None
        and bool((crosswalk["evidence_reference"] or "").strip())
        and crosswalk["reviewed_at"] is not None
    )
    if crosswalk["state"] == "VERIFIED" and not documented:
        return "MIGRATION_BOUNDARY"
    if value["apply_legacy_override"] and (
        crosswalk["state"] != "VERIFIED"
        or not documented
        or crosswalk["legacy_key"] != value["legacy_override"]["source_asset_id"]
        or crosswalk["mcp_key"] != value["mcp_source_asset_id"]
        or not value["legacy_override"]["enabled"]
    ):
        return "MIGRATION_BOUNDARY"
    if (
        value["series_comparable"]
        or value["rollback_schema"] != CONTRACT["workbook_migration"]["from"]
    ):
        return "MIGRATION_BOUNDARY"
    if not value["preserve_manual_edits"] or not value["preserve_new_observations"]:
        return "MIGRATION_BOUNDARY"
    return None


def period_error(value):
    if "start_date" not in value:
        return None
    start, end = date.fromisoformat(value["start_date"]), date.fromisoformat(value["end_date"])
    today = date.fromisoformat(MANIFEST["inspection_date"])
    return None if start <= end <= today else "MCP_INVALID_ARGUMENT"


def wrapper_error(value):
    if value.get("isError"):
        return "MCP_TOOL_ERROR"
    if "structuredContent" not in value:
        return "MCP_MALFORMED_RESPONSE"
    return None


CHECKS = {
    "pagination": pagination_error,
    "snapshot": snapshot_error,
    "migration": migration_error,
    "period": period_error,
    "wrapper": wrapper_error,
    "decimal": lambda value: None if Decimal(value).is_finite() else "DECIMAL",
}


def fixture_quality(case, value, contract_error):
    """Evaluate the declared quality dimension without consulting expected values."""
    rule = CONTRACT["fixture_quality_rules"][case["schema"]]
    if rule["kind"] == "pagination":
        return "PARTIAL" if contract_error else "COMPLETE"
    if contract_error:
        return "NOT_APPLICABLE"
    if rule["kind"] == "constant":
        return rule["value"]
    if rule["kind"] == "field":
        for key in rule["path"].split("/")[1:]:
            value = value[key]
        return value
    if rule["kind"] == "capability":
        capability = CONTRACT["capabilities"][case["action"]]
        assert capability["output_schema"] == case["schema"]
        if (
            capability["support_status"] == "DECLARED_ONLY"
            or case["evidence_class"] == "synthetic_declared_shape"
        ):
            return capability["support_status"]
        return rule["defensive_quality"]
    raise AssertionError(f"Unsupported quality rule: {rule['kind']}")


def fixture_outcome(case):
    value = materialize(case)
    errors = list(validator(case["schema"]).iter_errors(value))
    if errors:
        assert not case["checks"]
        return {"schema_valid": False, "quality": "NOT_APPLICABLE", "contract_error": None}
    required_check = CONTRACT["fixture_quality_rules"][case["schema"]].get("required_check")
    if required_check:
        assert required_check in case["checks"]
    actual = next((error for name in case["checks"] if (error := CHECKS[name](value))), None)
    return {
        "schema_valid": True,
        "quality": fixture_quality(case, value, actual),
        "contract_error": actual,
    }


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["id"])
def test_synthetic_contract_case(case):
    assert fixture_outcome(case) == case["expected"]


def test_every_manifest_quality_expectation_is_exercised():
    for case in MANIFEST["cases"]:
        wrong_known_quality = "PARTIAL" if case["expected"]["quality"] == "COMPLETE" else "COMPLETE"
        for quality in ("MADE_UP_QUALITY", wrong_known_quality):
            corrupted = deepcopy(case)
            corrupted["expected"]["quality"] = quality
            with pytest.raises(AssertionError):
                test_synthetic_contract_case(corrupted)


@pytest.mark.parametrize(
    "case_id",
    [
        "empty-holdings",
        "official-totals-differ-from-details",
        "cross-provider-collision-same-day-cutover",
    ],
)
def test_quality_evidence_cannot_skip_required_cross_record_check(case_id):
    case = deepcopy(next(case for case in MANIFEST["cases"] if case["id"] == case_id))
    case["checks"] = []
    with pytest.raises(AssertionError):
        fixture_outcome(case)


@pytest.mark.parametrize("entity_key", [None, "mcp:account:assets:synthetic-a"])
def test_duplicate_warning_keys_fail_schema_and_semantic_validation(entity_key):
    value = deepcopy(BASES["snapshot"])
    warning = {"code": "MISSING_ENRICHMENT", "entity_key": entity_key}
    value["warnings"] = [warning, deepcopy(warning)]
    assert not validator("#/$defs/snapshot_v3").is_valid(value)
    assert snapshot_error(value) == "IDENTITY"


@pytest.mark.parametrize("count_delta", [0, 1])
def test_duplicate_diagnostic_keys_ignore_count_in_identity(count_delta):
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "unknown-detail-retained-with-qualified-overview"
    )
    value = materialize(case)
    duplicate = deepcopy(value["unsupported_details"][0])
    duplicate["count"] += count_delta
    value["unsupported_details"].append(duplicate)
    assert validator("#/$defs/snapshot_v3").is_valid(value) == bool(count_delta)
    assert snapshot_error(value) == "IDENTITY"


@pytest.mark.parametrize(
    "row_path,field",
    [
        (("overview",), "gross_assets"),
        (("overview",), "financial_assets"),
        (("overview",), "reported_liabilities"),
        (("overview",), "reported_net_worth"),
        (("allocation_categories", 0), "value"),
        (("allocation_types", 0), "value"),
        (("members", 0), "gross_assets"),
        (("members", 0), "reported_liabilities"),
        (("members", 0), "reported_net_worth"),
    ],
)
@pytest.mark.parametrize("currency", [None, "USD"])
def test_every_overview_money_group_requires_provenance_currency(row_path, field, currency):
    value = deepcopy(BASES["snapshot"])
    row = value
    for key in row_path:
        row = row[key]
    row[field].update(currency=currency, amount_eur=None, eur_basis="UNAVAILABLE")
    assert validator("#/$defs/snapshot_v3").is_valid(value) == (currency is not None)
    assert snapshot_error(value) == "CURRENCY_EVIDENCE"


@pytest.mark.parametrize(
    "amount,currency,view_currency,expected",
    [
        (None, None, None, None),
        (None, "EUR", "EUR", None),
        (None, None, "EUR", "CURRENCY_EVIDENCE"),
        (None, "USD", "EUR", "CURRENCY_EVIDENCE"),
        ("0", None, None, "CURRENCY_EVIDENCE"),
        ("1.00", None, None, "CURRENCY_EVIDENCE"),
    ],
)
def test_null_amount_does_not_bypass_view_currency(amount, currency, view_currency, expected):
    money = {"amount": amount, "currency": currency, "amount_eur": None, "eur_basis": "UNAVAILABLE"}
    assert money_error(money, view_currency) == expected


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
@pytest.mark.parametrize("missing", [("amount",), ("currency",), ("amount", "currency")])
def test_unknown_native_valuation_fails_schema_and_semantic_checks(dimension, missing):
    value = deepcopy(BASES["snapshot"])
    rule = CONTRACT["valuation_contracts"][dimension]
    money = value[rule["rows"]][0][rule["money_field"]]
    money.update(amount_eur=None, eur_basis="UNAVAILABLE")
    for field in missing:
        money[field] = None
    for state in ("COMPLETE", "PARTIAL"):
        value["coverage"][dimension] = state
        assert not validator("#/$defs/snapshot_v3").is_valid(value)
        assert snapshot_error(value) == "VALUATION_COVERAGE"
    value["coverage"][dimension] = "UNAVAILABLE"
    if missing == ("currency",):
        assert not validator("#/$defs/snapshot_v3").is_valid(value)
        assert snapshot_error(value) == "CURRENCY_EVIDENCE"
        return
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) is None


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
@pytest.mark.parametrize("amount,currency,eur", [("0.00", "EUR", "0"), ("90.00", "USD", None)])
def test_complete_native_valuation_accepts_zero_and_nullable_eur(dimension, amount, currency, eur):
    value = deepcopy(BASES["snapshot"])
    rule = CONTRACT["valuation_contracts"][dimension]
    value[rule["rows"]][0][rule["money_field"]] = {
        "amount": amount,
        "currency": currency,
        "amount_eur": eur,
        "eur_basis": "SOURCE_EUR" if currency == "EUR" else "UNAVAILABLE",
    }
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) is None


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
def test_partial_empty_and_unretrieved_valuation_have_distinct_states(dimension):
    value = deepcopy(BASES["snapshot"])
    rule = CONTRACT["valuation_contracts"][dimension]
    second = deepcopy(value[rule["rows"]][0])
    if dimension == "account_valuation":
        second["source_account_id"] = "synthetic-b"
        second["account_key"] = identity("account_key", account_id="synthetic-b")
    else:
        second["holding_id"] = "synthetic-h2"
        args = {"holding_id": second["holding_id"], "holding_type": second["holding_type"]}
        second["source_asset_id"] = identity("source_asset_id", **args)
        second["position_key"] = identity("position_key", account_id="synthetic-a", **args)
    second[rule["money_field"]] = {
        "amount": None, "currency": None, "amount_eur": None, "eur_basis": "UNAVAILABLE"
    }
    value[rule["rows"]].append(second)
    for state in ("COMPLETE", "UNAVAILABLE", "PARTIAL"):
        value["coverage"][dimension] = state
        assert validator("#/$defs/snapshot_v3").is_valid(value) == (state == "PARTIAL")
        assert snapshot_error(value) == (None if state == "PARTIAL" else "VALUATION_COVERAGE")

    value[rule["rows"]] = []
    value["positions"] = []
    value["position_rates"] = []
    if dimension == "account_valuation":
        value["ownership"] = []
    value["coverage"][dimension] = "COMPLETE"
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) is None
    value["coverage"][rule["collection"]] = "PARTIAL"
    if dimension == "account_valuation":
        value["coverage"].update(holdings="UNAVAILABLE", holding_valuation="UNAVAILABLE")
    assert not validator("#/$defs/snapshot_v3").is_valid(value)
    assert snapshot_error(value) == "VALUATION_COVERAGE"
    value["coverage"][dimension] = "UNAVAILABLE"
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) is None


@pytest.mark.parametrize(
    "field,replacement,schema_valid",
    [
        ("state", "UNRESOLVED", False),
        ("state", "REJECTED", False),
        ("mcp_key", None, False),
        ("evidence_reference", None, False),
        ("evidence_reference", " \t ", False),
        ("reviewed_at", None, False),
        ("legacy_key", "security:8", True),
        ("mcp_key", "mcp:holding:security-holdings:8", True),
    ],
)
def test_override_application_requires_documented_exact_pair(field, replacement, schema_valid):
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "verified-exact-crosswalk-allows-enabled-override"
    )
    value = materialize(case)
    value["crosswalk"][field] = replacement
    assert validator("#/$defs/migration_case").is_valid(value) == schema_valid
    assert migration_error(value) == "MIGRATION_BOUNDARY"


def test_disabled_override_cannot_apply_even_with_verified_crosswalk():
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "verified-exact-crosswalk-allows-enabled-override"
    )
    value = materialize(case)
    value["legacy_override"]["enabled"] = False
    assert not validator("#/$defs/migration_case").is_valid(value)
    assert migration_error(value) == "MIGRATION_BOUNDARY"


@pytest.mark.parametrize("zero", ["0", "0.0", "0.00", "-0.00", "0.000000000000000000"])
def test_independent_empty_debt_accepts_numeric_zero_at_any_allowed_scale(zero):
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "independent-empty-debt-enumeration-design-only"
    )
    value = materialize(case)
    value["overview"]["reported_liabilities"]["amount"] = zero
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) is None


@pytest.mark.parametrize("amount", ["0.01", "-0.01", "0.0000000000000000000", "00", "0e0"])
def test_independent_empty_debt_rejects_nonzero_or_invalid_decimal(amount):
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "independent-empty-debt-enumeration-design-only"
    )
    value = materialize(case)
    value["overview"]["reported_liabilities"]["amount"] = amount
    assert not validator("#/$defs/snapshot_v3").is_valid(value)


@pytest.mark.parametrize(
    "eur,full,expected",
    [
        ("250.00", "250.0", None),
        ("250", "250.000", None),
        ("0.00", "-0.0", None),
        ("9007199254740993.00", "9007199254740993.0", None),
        ("250.00", "250.000000000000000001", "CURRENCY_EVIDENCE"),
        ("9007199254740993.00", "9007199254740992.00", "CURRENCY_EVIDENCE"),
        ("250.00", None, "CURRENCY_EVIDENCE"),
    ],
)
def test_eur_conversion_compares_exact_decimal_values(eur, full, expected):
    case = next(
        case for case in MANIFEST["cases"]
        if case["id"] == "verified-account-native-to-eur-conversion"
    )
    value = materialize(case)
    value["accounts"][0]["native_balance"]["amount_eur"] = eur
    value["accounts"][0]["full_value_eur"] = full
    validator("#/$defs/snapshot_v3").validate(value)
    assert snapshot_error(value) == expected


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_contract_definitions_registry_and_evidence_are_resolvable():
    Draft202012Validator.check_schema(CONTRACT)
    for definition in CONTRACT["$defs"].values():
        Draft202012Validator.check_schema(definition)
    expected = {
        "get_me",
        "profiles",
        "accounts",
        "holdings",
        "get_portfolio_overview",
        "get_budget_overview",
        "goals",
        "search_spending",
        "simulate_compound_interest",
    }
    assert set(CONTRACT["capabilities"]) == expected
    for action, capability in CONTRACT["capabilities"].items():
        assert capability["runtime_status"] == "NOT_IMPLEMENTED"
        assert set(capability["evidence"]) <= CONTRACT["evidence"].keys()
        assert any(case["action"] == action for case in MANIFEST["cases"])
    for node in walk(CONTRACT):
        if isinstance(node, dict) and "$ref" in node:
            assert node["$ref"].startswith("#/$defs/")
            assert node["$ref"].split("/")[-1] in CONTRACT["$defs"]
    for case in MANIFEST["cases"]:
        assert case["base"] in BASES
        assert (
            case["contract_version"] == MANIFEST["contract_version"] == CONTRACT["contract_version"]
        )
        assert case["evidence_class"].startswith("synthetic_")
        assert set(case["evidence_references"]) <= CONTRACT["evidence"].keys()
    assert len({case["id"] for case in MANIFEST["cases"]}) == len(MANIFEST["cases"])
    assert {case["base"] for case in MANIFEST["cases"]} == BASES.keys()
    assert set(CONTRACT["fixture_quality_rules"]) == {case["schema"] for case in MANIFEST["cases"]}
    for rule in CONTRACT["fixture_quality_rules"].values():
        assert rule["kind"] in {"constant", "field", "capability", "pagination"}
    for ambiguity in CONTRACT["ambiguities"].values():
        assert set(ambiguity["evidence"]) <= CONTRACT["evidence"].keys()
        assert all(
            ambiguity[key]
            for key in (
                "affected_fields",
                "conservative_behavior",
                "downstream_impact",
                "resolution",
            )
        )


def test_normalized_financial_fields_have_authority_grain_and_units():
    for name in (
        "account",
        "ownership",
        "position",
        "position_rate",
        "overview",
        "money",
        "allocation_category",
        "allocation_type",
        "member",
        "connection",
        "provenance",
    ):
        for schema in CONTRACT["$defs"][name]["properties"].values():
            assert all(
                schema["x-field"][key]
                for key in ("authority", "grain", "unit", "currency", "absence", "evidence")
            )
    assert not CONTRACT["$defs"]["account_observed"]["properties"]["attributes"]["required"]
    assert CONTRACT["$defs"]["snapshot_v3"]["properties"]["debt_details"]["maxItems"] == 0


def test_identity_encoding_is_injective_and_preserves_opaque_ids():
    ids = ["42", "042", "a:b", "a%3Ab", "a/b", "a?b", "é", "e\u0301", "A", "a"]
    keys = [identity("account_key", account_id=value) for value in ids]
    assert len(set(keys)) == len(ids)
    assert keys[2:4] == ["mcp:account:assets:a%3Ab", "mcp:account:assets:a%253Ab"]
    assert all(not key.startswith("finary:") for key in keys)
    assert not validator("#/$defs/id").is_valid(" a ")
    assert not validator("#/$defs/id").is_valid(42)
    for control in ("\x00", "\x1f", "\x7f", "\u0080", "\u009f"):
        assert not validator("#/$defs/id").is_valid("synthetic" + control)
    assert identity(
        "source_asset_id", holding_type="security-holdings", holding_id="7"
    ) != identity("source_asset_id", holding_type="crypto-holdings", holding_id="7")


def test_overview_authority_is_not_a_detail_sum_constraint():
    snapshot = BASES["snapshot"]
    validator("#/$defs/snapshot_v3").validate(snapshot)
    gross = Decimal(snapshot["overview"]["gross_assets"]["amount"])
    assert gross != sum(Decimal(a["full_value_eur"]) for a in snapshot["accounts"])
    assert gross != sum(Decimal(p["current_value"]["amount"]) for p in snapshot["positions"])
    assert snapshot["coverage"]["debt_detail"] == "UNAVAILABLE"
    assert snapshot["overview"]["reported_liabilities"]["amount"] == "200.00"
    assert snapshot["debt_details"] == []
    assert snapshot["coverage"]["detail_semantics"] in CONTRACT["write_gates"][
        "allowed_position_semantics"
    ]


def test_workbook_delta_and_legacy_versions_remain_separate():
    active = json.loads((ROOT / "docs" / "google-sheets-schema.json").read_text())
    delta = CONTRACT["workbook_migration"]
    assert active["schema_version"] == delta["from"] == CONTRACT["implemented"]["workbook_schema"]
    assert CONTRACT["planned"] == {
        "api_schema": "3.0",
        "route": "/v3/snapshot",
        "workbook_schema": "3.0",
    }
    assert delta["to"] == "3.0" and delta["status"] == "PLANNED_DELTA_ONLY"
    assert delta["manual_sheets"] == ["allocation_targets", "asset_overrides", "cashflows"]
    assert delta["currency_storage"] == "DECIMAL_TEXT_NATIVE_WITH_NULLABLE_EUR"
    assert delta["preserve_sheet_order"]
    for table, definition in delta["tables"].items():
        if "row_schema" in definition:
            assert definition["row_schema"].split("/")[-1] in CONTRACT["$defs"]
        assert (table in active["sheets"]) == (definition["mode"] != "append_table")
    for name in (
        "accounts",
        "holdings",
        "debt_detail",
        "account_valuation",
        "holding_valuation",
        "debt_valuation",
        "overview_quality",
        "detail_semantics",
        "source_freshness",
    ):
        assert name in CONTRACT["$defs"]["coverage"]["required"]
    ordering = delta["ordering"]
    assert (
        ordering.index("drain_disable_old_writer_and_error_handlers")
        < ordering.index("apply_append_only_schema_delta_once")
        < ordering.index("operator_activate_new_schedule")
    )


def schema_leaves(schema, path=""):
    if "$ref" in schema:
        schema = CONTRACT["$defs"][schema["$ref"].split("/")[-1]]
    if schema.get("type") == "object":
        for key, value in schema["properties"].items():
            yield from schema_leaves(value, path + "/" + key)
    else:
        yield path


def test_workbook_column_bindings_cover_each_normalized_leaf_without_collisions():
    active = json.loads((ROOT / "docs" / "google-sheets-schema.json").read_text())
    for table, definition in CONTRACT["workbook_migration"]["tables"].items():
        if "row_schema" not in definition:
            continue
        schema = CONTRACT["$defs"][definition["row_schema"].split("/")[-1]]
        bindings = definition["column_bindings"]
        assert set(bindings.values()) == set(schema_leaves(schema))
        assert len(bindings) == len(set(bindings.values()))
        if table in active["sheets"]:
            existing = {column["name"] for column in active["sheets"][table]["columns"]}
            for column in bindings:
                assert column not in existing or column in {
                    "account_key",
                    "source_account_id",
                    "position_key",
                    "source_asset_id",
                    "asset_class",
                }
    assert (
        "mcp_quantity"
        in CONTRACT["workbook_migration"]["tables"]["positions_current"]["column_bindings"]
    )


def test_declared_unknowns_do_not_acquire_false_upstream_requirements():
    for name in ("get_me_output", "profiles_output", "accounts_output", "holdings_output"):
        output = CONTRACT["$defs"][name]["properties"]
        data = output["data"]
        assert data.get("items", {}).get("required", []) == []
    assert CONTRACT["$defs"]["budget_output"]["properties"]["view"] == {}
    assert CONTRACT["$defs"]["simulation_output"]["properties"]["series"]["items"] == {}
    for action in ("search_spending", "simulate_compound_interest"):
        assert CONTRACT["capabilities"][action]["support_status"] == "DECLARED_ONLY"
    goal = CONTRACT["$defs"]["goals_output"]["properties"]["goals"]["items"]
    assert "id" not in goal["properties"]
    assert "progress" not in goal["properties"]
    assert CONTRACT["input_policy"]["scheduled_prompt"] == "OMIT"
    attributes = CONTRACT["$defs"]["holding_observed"]["properties"]["attributes"]
    assert "annual_yield_percent" not in attributes["properties"]
