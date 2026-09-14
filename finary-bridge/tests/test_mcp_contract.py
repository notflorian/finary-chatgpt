"""Independent fixture expectations at schema and production semantic boundaries.

Declared upstream shapes remain evidence metadata, not proof of runtime support.
Transport cases run through the native SDK in test_mcp_integration.
"""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator
from mcp_artifacts import BASE_NAMES, CONTRACT, MANIFEST, base, cases, materialize, validator

from app.mcp_models import McpSnapshotV1
from app.mcp_validation import key as identity
from app.mcp_validation import validate, validate_money, validate_snapshot


def test_unsupported_warning_is_rejected_by_contract_and_model():
    from pydantic import ValidationError

    from app.mcp_models import McpWarning

    warning = {"code": "STALE_SOURCE", "entity_key": None}
    assert validator("#/$defs/warning").is_valid(warning)
    assert McpWarning.model_validate(warning).code == "STALE_SOURCE"
    warning["code"] = "UNRESOLVED_CROSSWALK"
    assert not validator("#/$defs/warning").is_valid(warning)
    with pytest.raises(ValidationError):
        McpWarning.model_validate(warning)


def declared_quality(case, value):
    """Check evidence metadata only; semantic rejection is tested at its owning boundary."""
    rule = CONTRACT["fixture_quality_rules"][case["schema"]]
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


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["id"])
def test_synthetic_schema_and_declared_evidence(case):
    value = materialize(case)
    expected = case["expected"]
    assert validator(case["schema"]).is_valid(value) is expected["schema_valid"]
    with nullcontext() if expected["schema_valid"] else pytest.raises(ValueError):
        validate(case["schema"].split("/")[-1], value)
    if not expected["schema_valid"] or expected["contract_error"]:
        assert expected["quality"] == (
            "PARTIAL" if case["schema"] == "#/$defs/holdings_session" else "NOT_APPLICABLE"
        )
    elif case["schema"] != "#/$defs/holdings_session":
        assert declared_quality(case, value) == expected["quality"]


def assert_snapshot_semantics(value, error=None):
    # Error names describe independent fixture expectations; production errors are sanitized.
    with nullcontext() if error is None else pytest.raises(ValueError, match="semantic validation"):
        validate_snapshot(value)


@pytest.mark.parametrize("entity_key", [None, "mcp:account:assets:synthetic-a"])
def test_duplicate_warning_keys_fail_schema_and_semantic_validation(entity_key):
    value = base("snapshot")
    warning = {"code": "MISSING_ENRICHMENT", "entity_key": entity_key}
    value["warnings"] = [warning, deepcopy(warning)]
    assert not validator("#/$defs/snapshot_v1").is_valid(value)
    assert_snapshot_semantics(value, "IDENTITY")


@pytest.mark.parametrize("count_delta", [0, 1])
def test_duplicate_diagnostic_keys_ignore_count_in_identity(count_delta):
    case = next(
        case
        for case in MANIFEST["cases"]
        if case["id"] == "unknown-detail-retained-with-qualified-overview"
    )
    value = materialize(case)
    duplicate = deepcopy(value["unsupported_details"][0])
    duplicate["count"] += count_delta
    value["unsupported_details"].append(duplicate)
    assert validator("#/$defs/snapshot_v1").is_valid(value) == bool(count_delta)
    assert_snapshot_semantics(value, "IDENTITY")


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
    value = base("snapshot")
    row = value
    for key in row_path:
        row = row[key]
    row[field].update(currency=currency, amount_eur=None, eur_basis="UNAVAILABLE")
    assert validator("#/$defs/snapshot_v1").is_valid(value) == (currency is not None)
    assert_snapshot_semantics(value, "CURRENCY_EVIDENCE")


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
    with nullcontext() if expected is None else pytest.raises(ValueError):
        validate_money(money, view_currency)


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
@pytest.mark.parametrize("missing", [("amount",), ("currency",), ("amount", "currency")])
def test_unknown_native_valuation_fails_schema_and_semantic_checks(dimension, missing):
    value = base("snapshot")
    rule = CONTRACT["valuation_contracts"][dimension]
    money = value[rule["rows"]][0][rule["money_field"]]
    money.update(amount_eur=None, eur_basis="UNAVAILABLE")
    for field in missing:
        money[field] = None
    for state in ("COMPLETE", "PARTIAL"):
        value["coverage"][dimension] = state
        assert not validator("#/$defs/snapshot_v1").is_valid(value)
        assert_snapshot_semantics(value, "VALUATION_COVERAGE")
    value["coverage"][dimension] = "UNAVAILABLE"
    if missing == ("currency",):
        assert not validator("#/$defs/snapshot_v1").is_valid(value)
        assert_snapshot_semantics(value, "CURRENCY_EVIDENCE")
        return
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value)


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
@pytest.mark.parametrize("amount,currency,eur", [("0.00", "EUR", "0"), ("90.00", "USD", None)])
def test_complete_native_valuation_accepts_zero_and_nullable_eur(dimension, amount, currency, eur):
    value = base("snapshot")
    rule = CONTRACT["valuation_contracts"][dimension]
    value[rule["rows"]][0][rule["money_field"]] = {
        "amount": amount,
        "currency": currency,
        "amount_eur": eur,
        "eur_basis": "SOURCE_EUR" if currency == "EUR" else "UNAVAILABLE",
    }
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value)


@pytest.mark.parametrize("dimension", ["account_valuation", "holding_valuation"])
def test_partial_empty_and_unretrieved_valuation_have_distinct_states(dimension):
    value = base("snapshot")
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
        "amount": None,
        "currency": None,
        "amount_eur": None,
        "eur_basis": "UNAVAILABLE",
    }
    value[rule["rows"]].append(second)
    for state in ("COMPLETE", "UNAVAILABLE", "PARTIAL"):
        value["coverage"][dimension] = state
        assert validator("#/$defs/snapshot_v1").is_valid(value) == (state == "PARTIAL")
        assert_snapshot_semantics(value, (None if state == "PARTIAL" else "VALUATION_COVERAGE"))

    value[rule["rows"]] = []
    value["positions"] = []
    value["position_rates"] = []
    if dimension == "account_valuation":
        value["ownership"] = []
    value["coverage"][dimension] = "COMPLETE"
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value)
    value["coverage"][rule["collection"]] = "PARTIAL"
    if dimension == "account_valuation":
        value["coverage"].update(holdings="UNAVAILABLE", holding_valuation="UNAVAILABLE")
    assert not validator("#/$defs/snapshot_v1").is_valid(value)
    assert_snapshot_semantics(value, "VALUATION_COVERAGE")
    value["coverage"][dimension] = "UNAVAILABLE"
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value)


@pytest.mark.parametrize("zero", ["0", "0.0", "0.00", "-0.00", "0.000000000000000000"])
def test_independent_empty_debt_accepts_numeric_zero_at_any_allowed_scale(zero):
    case = next(
        case
        for case in MANIFEST["cases"]
        if case["id"] == "independent-empty-debt-enumeration-design-only"
    )
    value = materialize(case)
    value["overview"]["reported_liabilities"]["amount"] = zero
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value)


@pytest.mark.parametrize(
    "amount",
    [
        "0.01",
        "-0.01",
        "0." + "0" * (CONTRACT["numeric_policy"]["limits"]["fractional_digits"] + 1),
        "00",
        "0e0",
    ],
)
def test_independent_empty_debt_rejects_nonzero_or_invalid_decimal(amount):
    case = next(
        case
        for case in MANIFEST["cases"]
        if case["id"] == "independent-empty-debt-enumeration-design-only"
    )
    value = materialize(case)
    value["overview"]["reported_liabilities"]["amount"] = amount
    assert not validator("#/$defs/snapshot_v1").is_valid(value)


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
        case
        for case in MANIFEST["cases"]
        if case["id"] == "verified-account-native-to-eur-conversion"
    )
    value = materialize(case)
    value["accounts"][0]["native_balance"]["amount_eur"] = eur
    value["accounts"][0]["full_value_eur"] = full
    validator("#/$defs/snapshot_v1").validate(value)
    assert_snapshot_semantics(value, expected)


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
        assert set(capability["evidence"]) <= CONTRACT["evidence"].keys()
        assert any(case["action"] == action for case in MANIFEST["cases"])
    for node in walk(CONTRACT):
        if isinstance(node, dict) and "$ref" in node:
            assert node["$ref"].startswith("#/$defs/")
            assert node["$ref"].split("/")[-1] in CONTRACT["$defs"]
    for case in MANIFEST["cases"]:
        assert base(case["base"]) is not None
        assert (
            case["contract_version"] == MANIFEST["contract_version"] == CONTRACT["contract_version"]
        )
        assert case["evidence_class"].startswith("synthetic_")
        assert set(case["evidence_references"]) <= CONTRACT["evidence"].keys()
    assert len({case["id"] for case in MANIFEST["cases"]}) == len(MANIFEST["cases"])
    assert {case["base"] for case in MANIFEST["cases"]} == set(BASE_NAMES)
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
    assert CONTRACT["$defs"]["snapshot_v1"]["properties"]["debt_details"]["maxItems"] == 0


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
    snapshot = base("snapshot")
    validator("#/$defs/snapshot_v1").validate(snapshot)
    gross = Decimal(snapshot["overview"]["gross_assets"]["amount"])
    assert gross != sum(Decimal(a["full_value_eur"]) for a in snapshot["accounts"])
    assert gross != sum(Decimal(p["current_value"]["amount"]) for p in snapshot["positions"])
    assert snapshot["coverage"]["debt_detail"] == "UNAVAILABLE"
    assert snapshot["overview"]["reported_liabilities"]["amount"] == "200.00"
    assert snapshot["debt_details"] == []
    assert (
        snapshot["coverage"]["detail_semantics"]
        in CONTRACT["write_gates"]["allowed_position_semantics"]
    )


def schema_leaves(schema, path=""):
    if "$ref" in schema:
        schema = CONTRACT["$defs"][schema["$ref"].split("/")[-1]]
    if schema.get("type") == "object":
        for key, value in schema["properties"].items():
            yield from schema_leaves(value, path + "/" + key)
    else:
        yield path


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


def test_workbook_column_bindings_cover_each_normalized_leaf_without_collisions():
    for definition in CONTRACT["current_workbook"]["tables"].values():
        schema = CONTRACT["$defs"][definition["row_schema"].split("/")[-1]]
        bindings = definition["column_bindings"]
        assert set(bindings.values()) == set(schema_leaves(schema))
        assert len(bindings) == len(set(bindings.values()))
        assert not bindings.keys() & definition["workbook_columns"].keys()


@pytest.mark.parametrize(
    "case",
    cases("snapshot_v1"),
    ids=lambda c: c["id"],
)
def test_runtime_model_preserves_declared_snapshot_outcome(case):
    value = materialize(case)
    accepted = case["expected"]["schema_valid"] and case["expected"]["contract_error"] is None
    if accepted:
        assert McpSnapshotV1.model_validate(value).model_dump() == value
    else:
        with pytest.raises(ValueError):
            McpSnapshotV1.model_validate(value)
