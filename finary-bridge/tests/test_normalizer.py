"""Fixture-based tests for deterministic portfolio normalization."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.finary_client import (
    FinaryFeatureUnavailableError,
    FinaryLiabilityCoverage,
    FinaryPositionKind,
    FinaryRawAccounts,
    FinaryRawLiabilities,
    FinaryRawPositionGroup,
    FinaryRawPositions,
)
from app.models import AssetClass, Position
from app.normalizer import (
    SnapshotNormalizationError,
    calculate_gross_assets_eur,
    canonicalize_id,
    make_account_key,
    make_position_key,
    make_source_asset_id,
    normalize_accounts,
    normalize_liabilities,
    normalize_positions,
)


def _account_keys(raw_accounts: FinaryRawAccounts) -> set[str]:
    return {account.account_key for account in normalize_accounts(raw_accounts)}


def _position_by_kind(
    raw_positions: FinaryRawPositions,
    raw_accounts: FinaryRawAccounts,
) -> dict[str, Position]:
    positions = normalize_positions(
        raw_positions,
        account_keys=_account_keys(raw_accounts),
    )
    return {position.source_asset_id.split(":", maxsplit=1)[0]: position for position in positions}


def test_id_canonicalization_and_category_aware_keys() -> None:
    assert canonicalize_id(1001, field_name="position id") == "1001"
    assert canonicalize_id(" account-001 ", field_name="account id") == "account-001"
    assert make_account_key("account-001") == "finary:account:account-001"
    assert make_source_asset_id(FinaryPositionKind.SECURITIES, 1001) == "securities:1001"
    assert (
        make_position_key("account-001", FinaryPositionKind.SECURITIES, 1001)
        == "finary:account-001:asset:securities:1001"
    )
    assert make_position_key(
        "account-001", FinaryPositionKind.SECURITIES, 1001
    ) != make_position_key("account-001", FinaryPositionKind.CRYPTOS, 1001)


def test_invalid_identifier_is_rejected() -> None:
    with pytest.raises(SnapshotNormalizationError, match="string or integer"):
        canonicalize_id(True, field_name="position id")


def test_accounts_use_verified_fields_and_ignore_nested_assets(
    raw_accounts: FinaryRawAccounts,
) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    records[0]["securities"] = [{"id": 999999, "private": "must-not-leak"}]
    normalized = normalize_accounts(FinaryRawAccounts(records=tuple(records)))

    assert len(normalized) == 2
    assert normalized[0].source_account_id == "account-synthetic-001"
    assert normalized[0].name == "Sample Investment Account"
    assert normalized[0].institution == "Sample Institution"
    assert normalized[0].account_type == "Securities"
    assert normalized[0].currency == "EUR"
    assert normalized[0].market_value_eur == 100.0
    assert normalized[0].metadata == {}


def test_non_eur_account_is_not_relabelled_and_blocks_required_total(
    raw_accounts: FinaryRawAccounts,
) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    currency = records[0]["currency"]
    assert isinstance(currency, dict)
    currency["code"] = "USD"
    normalized = normalize_accounts(FinaryRawAccounts(records=tuple(records)))

    assert normalized[0].market_value_eur is None
    with pytest.raises(SnapshotNormalizationError, match="EUR provenance"):
        calculate_gross_assets_eur(
            FinaryRawAccounts(records=tuple(records)), normalized
        )


def test_display_balance_alone_is_not_eur_provenance(
    raw_accounts: FinaryRawAccounts,
) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    records[0]["currency"] = {"code": "USD"}
    records[0]["display_currency"] = {"code": "EUR"}
    records[0]["display_balance"] = 999999.0

    account = normalize_accounts(FinaryRawAccounts(records=tuple(records)))[0]

    assert account.currency == "USD"
    assert account.market_value_eur is None


def test_duplicate_account_ids_are_rejected(raw_accounts: FinaryRawAccounts) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    records[1]["id"] = records[0]["id"]
    with pytest.raises(SnapshotNormalizationError, match="duplicate account"):
        normalize_accounts(FinaryRawAccounts(records=tuple(records)))


def test_fixture_position_mappings_are_category_specific(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    positions = _position_by_kind(raw_positions, raw_accounts)

    security = positions["securities"]
    assert security.name == "Sample Index Fund"
    assert security.ticker == "SAMPLE"
    assert security.isin == "XX0000000001"
    assert security.account_key == "finary:account:account-synthetic-001"
    assert security.currency == "EUR"
    assert security.market_value_native == 120.0
    assert security.market_value_eur == 120.0
    assert security.asset_class is AssetClass.OTHER

    crypto = positions["cryptos"]
    assert crypto.name == "Sample Token"
    assert crypto.ticker == "SYN"
    assert crypto.quantity == 2.0
    assert crypto.currency is None
    assert crypto.market_value_eur is None
    assert crypto.cost_basis_eur == 50.0
    assert crypto.asset_class is AssetClass.CRYPTO

    euro_fund = positions["fonds_euro"]
    assert euro_fund.name == "Sample Euro Fund"
    assert euro_fund.unit_price == 105.0
    assert euro_fund.cost_basis_eur == 100.0
    assert euro_fund.asset_class is AssetClass.LIFE_INSURANCE_FUND

    generic = positions["generic_assets"]
    assert generic.name == "Sample Collectible"
    assert generic.asset_class is AssetClass.OTHER
    assert generic.market_value_eur == 110.0

    real_estate = positions["real_estates"]
    assert real_estate.name == "Sample Property"
    assert real_estate.asset_class is AssetClass.REAL_ESTATE
    assert real_estate.market_value_eur == 110.0
    assert real_estate.metadata == {}

    scpi = positions["scpis"]
    assert scpi.name == "Sample Property Fund"
    assert scpi.quantity == 2.0
    assert scpi.asset_class is AssetClass.SCPI
    assert scpi.currency is None
    assert scpi.market_value_eur is None


def test_real_estate_value_is_not_adjusted_again_for_ownership(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    positions = _position_by_kind(raw_positions, raw_accounts)
    assert positions["real_estates"].market_value_native == 110.0


def test_non_eur_security_and_display_value_do_not_create_eur_market_value(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    security_index = next(
        index
        for index, group in enumerate(groups)
        if group.kind is FinaryPositionKind.SECURITIES
    )
    records = [deepcopy(dict(record)) for record in groups[security_index].records]
    security = records[0]["security"]
    assert isinstance(security, dict)
    security["currency"] = {"code": "USD"}
    records[0]["display_current_value"] = 120.0
    groups[security_index] = FinaryRawPositionGroup(
        kind=FinaryPositionKind.SECURITIES,
        records=tuple(records),
    )

    positions = normalize_positions(
        FinaryRawPositions(groups=tuple(groups)),
        account_keys=_account_keys(raw_accounts),
    )
    normalized = next(
        position for position in positions if position.source_asset_id == "securities:1001"
    )

    assert normalized.currency == "USD"
    assert normalized.market_value_native == 120.0
    assert normalized.market_value_eur is None
    assert normalized.fx_to_eur is None


def test_equal_numeric_ids_in_different_categories_do_not_collide(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    crypto_index = next(
        index
        for index, group in enumerate(groups)
        if group.kind is FinaryPositionKind.CRYPTOS
    )
    crypto_records = [
        deepcopy(dict(record)) for record in groups[crypto_index].records
    ]
    crypto_records[0]["id"] = 1001
    groups[crypto_index] = FinaryRawPositionGroup(
        kind=FinaryPositionKind.CRYPTOS,
        records=tuple(crypto_records),
    )

    positions = normalize_positions(
        FinaryRawPositions(groups=tuple(groups)),
        account_keys=_account_keys(raw_accounts),
    )
    keys = {position.position_key for position in positions}
    assert "finary:account-synthetic-001:asset:securities:1001" in keys
    assert "finary:account-synthetic-002:asset:cryptos:1001" in keys


def test_duplicate_id_within_position_kind_is_rejected(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    security_index = next(
        index
        for index, group in enumerate(groups)
        if group.kind is FinaryPositionKind.SECURITIES
    )
    record = deepcopy(dict(groups[security_index].records[0]))
    groups[security_index] = FinaryRawPositionGroup(
        kind=FinaryPositionKind.SECURITIES,
        records=(record, deepcopy(record)),
    )
    with pytest.raises(SnapshotNormalizationError, match="duplicate position id"):
        normalize_positions(
            FinaryRawPositions(groups=tuple(groups)),
            account_keys=_account_keys(raw_accounts),
        )


def test_holdings_account_id_is_authoritative(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    security_group = next(
        group for group in groups if group.kind is FinaryPositionKind.SECURITIES
    )
    record = deepcopy(dict(security_group.records[0]))
    record["holdings_account_id"] = "unknown-account"
    record["account"] = {"id": "account-synthetic-001"}
    record["bank_account"] = {"id": "account-synthetic-001"}
    replacement = FinaryRawPositionGroup(
        kind=FinaryPositionKind.SECURITIES,
        records=(record,),
    )
    groups[groups.index(security_group)] = replacement

    with pytest.raises(SnapshotNormalizationError, match="unknown account"):
        normalize_positions(
            FinaryRawPositions(groups=tuple(groups)),
            account_keys=_account_keys(raw_accounts),
        )


def test_non_empty_unverified_collection_is_rejected(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    generic = next(
        group for group in groups if group.kind is FinaryPositionKind.GENERIC_ASSETS
    )
    crowdlending_index = next(
        index
        for index, group in enumerate(groups)
        if group.kind is FinaryPositionKind.CROWDLENDINGS
    )
    groups[crowdlending_index] = FinaryRawPositionGroup(
        kind=FinaryPositionKind.CROWDLENDINGS,
        records=(deepcopy(dict(generic.records[0])),),
    )
    with pytest.raises(SnapshotNormalizationError, match="no verified normalization rule"):
        normalize_positions(
            FinaryRawPositions(groups=tuple(groups)),
            account_keys=_account_keys(raw_accounts),
        )


def test_invalid_position_number_is_rejected(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    groups = deepcopy(list(raw_positions.groups))
    security_index = next(
        index
        for index, group in enumerate(groups)
        if group.kind is FinaryPositionKind.SECURITIES
    )
    records = [deepcopy(dict(record)) for record in groups[security_index].records]
    records[0]["current_value"] = float("nan")
    groups[security_index] = FinaryRawPositionGroup(
        kind=FinaryPositionKind.SECURITIES,
        records=tuple(records),
    )
    with pytest.raises(SnapshotNormalizationError, match="must be finite"):
        normalize_positions(
            FinaryRawPositions(groups=tuple(groups)),
            account_keys=_account_keys(raw_accounts),
        )


def test_gross_assets_use_only_non_collection_account_balances(
    raw_accounts: FinaryRawAccounts,
) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    records[0]["is_collection"] = True
    records[1]["is_collection"] = False
    modified = FinaryRawAccounts(records=tuple(records))

    gross = calculate_gross_assets_eur(modified, normalize_accounts(modified))

    assert gross == 50.0


def test_gross_assets_do_not_add_position_values(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    accounts = normalize_accounts(raw_accounts)
    positions = normalize_positions(raw_positions, account_keys=_account_keys(raw_accounts))

    assert sum(account.market_value_eur or 0.0 for account in accounts) == 150.0
    assert sum(position.market_value_eur or 0.0 for position in positions) > 150.0
    assert calculate_gross_assets_eur(raw_accounts, accounts) == 150.0


def test_empty_verified_liability_collection_is_supported_but_not_inferred_from_loans() -> None:
    assert (
        normalize_liabilities(
            FinaryRawLiabilities(
                records=(), coverage=FinaryLiabilityCoverage.COMPLETE
            )
        )
        == ()
    )


@pytest.mark.parametrize(
    "coverage",
    [FinaryLiabilityCoverage.PARTIAL, FinaryLiabilityCoverage.UNAVAILABLE],
)
def test_incomplete_empty_liability_collection_is_never_zero(
    coverage: FinaryLiabilityCoverage,
) -> None:
    with pytest.raises(FinaryFeatureUnavailableError, match="not verified complete"):
        normalize_liabilities(FinaryRawLiabilities(records=(), coverage=coverage))


def test_non_empty_liability_collection_is_not_fabricated() -> None:
    with pytest.raises(SnapshotNormalizationError, match="no verified normalization rule"):
        normalize_liabilities(
            FinaryRawLiabilities(
                records=({"id": "synthetic"},),
                coverage=FinaryLiabilityCoverage.COMPLETE,
            )
        )


def test_oversized_integer_is_a_sanitized_normalization_error(
    numeric_raw_inputs, numeric_field, oversized_integer,
):
    accounts, positions = numeric_raw_inputs(numeric_field, oversized_integer)
    with pytest.raises(SnapshotNormalizationError, match="must be finite") as caught:
        keys = _account_keys(accounts)
        normalize_positions(positions, account_keys=keys)
    assert str(caught.value) == {
        "balance": "account balance must be finite",
        "current_value": "position current value must be finite",
        "quantity": "position quantity must be finite",
    }[numeric_field]
    assert caught.value.__suppress_context__ is True
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("value", [True, False, "123", float("nan"), float("inf"), -float("inf")])
def test_numeric_normalization_preserves_invalid_input_rejection(
    numeric_raw_inputs, numeric_field, value,
):
    accounts, positions = numeric_raw_inputs(numeric_field, value)
    with pytest.raises(SnapshotNormalizationError):
        keys = _account_keys(accounts)
        normalize_positions(positions, account_keys=keys)


@pytest.mark.parametrize("value", [10**300, -(10**300), 1e300, -1e300, 0, 0.0, -2.5])
def test_numeric_normalization_preserves_finite_values(numeric_raw_inputs, numeric_field, value):
    accounts, positions = numeric_raw_inputs(numeric_field, value)
    normalized_accounts = normalize_accounts(accounts)
    normalized_positions = normalize_positions(
        positions, account_keys={account.account_key for account in normalized_accounts},
    )
    security = next(p for p in normalized_positions if p.source_asset_id == "securities:1001")
    actual = {
        "balance": normalized_accounts[0].market_value_eur,
        "current_value": security.market_value_native,
        "quantity": security.quantity,
    }[numeric_field]
    assert actual == float(value)


def test_numeric_normalization_preserves_nullability(numeric_raw_inputs, numeric_field):
    accounts, positions = numeric_raw_inputs(numeric_field, None)
    if numeric_field == "quantity":
        normalized = normalize_positions(positions, account_keys=_account_keys(accounts))
        security = next(p for p in normalized if p.source_asset_id == "securities:1001")
        assert security.quantity is None
    else:
        with pytest.raises(SnapshotNormalizationError, match="is required"):
            keys = _account_keys(accounts)
            normalize_positions(positions, account_keys=keys)


@pytest.mark.parametrize("kind, value, cost, unit_price", [
    ("cryptos", 60, 50, 30), ("scpis", 105, 100, None),
])
def test_verified_current_valuation_uses_total_once(
    raw_accounts, verified_raw_positions, kind, value, cost, unit_price,
):
    position = _position_by_kind(verified_raw_positions, raw_accounts)[kind]
    assert position.currency == "EUR"
    assert position.market_value_native == position.market_value_eur == value
    assert position.fx_to_eur == 1
    assert position.cost_basis_eur == cost
    assert position.unit_price == unit_price
    assert position.quantity == 2


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
@pytest.mark.parametrize("missing", ["currency", "valuable", "type", "ownership"])
def test_missing_current_evidence_cannot_borrow_currency(
    kind, missing, verified_position_payloads, valuation_snapshot,
):
    record = verified_position_payloads[kind]["result"][0]
    if missing == "currency":
        if kind == "cryptos":
            record.pop("buying_price_currency")
            record["crypto"]["code"] = "EUR"
        else:
            record["scpi"].pop("currency")
    elif missing == "ownership":
        record.pop("owning_type" if kind == "cryptos" else "property_type")
    else:
        record.pop(missing)
    # Adversarial fallback candidates never establish a positive native mapping.
    record.update(currency={"code": "EUR"}, display_currency={"code": "EUR"},
                  display_current_value=999, account={"currency": {"code": "EUR"}})
    snapshot = valuation_snapshot()
    position = next(row for row in snapshot["positions"]
                    if row["source_asset_id"].startswith(kind + ":"))
    assert snapshot["reference_currency"] == "EUR"
    assert position["market_value_eur"] is None
    assert position["fx_to_eur"] is None
    assert position["market_value_native"] == (60 if kind == "cryptos" else 105)
    if kind == "cryptos" and missing != "currency":
        assert position["cost_basis_eur"] == 50
    if kind == "scpis" and missing == "valuable":
        assert position["cost_basis_eur"] == 100


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
def test_native_non_eur_is_not_converted_from_display_or_guessed_rates(
    kind, verified_position_payloads, valuation_snapshot,
):
    record = verified_position_payloads[kind]["result"][0]
    if kind == "cryptos":
        record["buying_price_currency"] = {"code": "USD"}
        record["crypto"]["code"] = "EUR"
    else:
        for product in ("scpi", "valuable"):
            record[product]["currency"] = {"code": "USD"}
    record.update(display_currency={"code": "EUR"}, display_current_value=123)
    # An uncontracted rate is adversarial input, not an upstream fixture schema.
    for rate in (None, 0.9, 1 / 0.9, True, "0.9", float("inf"), 1e308):
        record["fx_to_eur"] = rate
        position = next(row for row in valuation_snapshot()["positions"]
                        if row["source_asset_id"].startswith(kind + ":"))
        assert position["currency"] == "USD"
        assert position["market_value_eur"] is None
        assert position["fx_to_eur"] is None
        assert position["cost_basis_eur"] is None


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
@pytest.mark.parametrize("cost", [None, 0])
def test_known_zero_market_value_is_independent_of_cost(
    kind, cost, verified_position_payloads, valuation_snapshot,
):
    record = verified_position_payloads[kind]["result"][0]
    record.update(current_value=0, buying_value=cost)
    position = next(row for row in valuation_snapshot()["positions"]
                    if row["source_asset_id"].startswith(kind + ":"))
    assert position["market_value_eur"] == position["market_value_native"] == 0
    assert position["fx_to_eur"] == 1
    assert position["cost_basis_eur"] == cost


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
@pytest.mark.parametrize("field", ["current_value", "current_price", "quantity", "buying_value"])
@pytest.mark.parametrize("invalid", [True, "60", float("nan"), float("inf"), 10**400])
def test_verified_currency_does_not_relax_monetary_validation(
    kind, field, invalid, verified_position_payloads, valuation_snapshot,
):
    verified_position_payloads[kind]["result"][0][field] = invalid
    with pytest.raises(SnapshotNormalizationError):
        valuation_snapshot()


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
def test_missing_total_still_fails_instead_of_using_units_or_display(
    kind, verified_position_payloads, valuation_snapshot,
):
    verified_position_payloads[kind]["result"][0].pop("current_value")
    with pytest.raises(SnapshotNormalizationError, match="current value is required"):
        valuation_snapshot()


def test_scpi_shares_fallback_does_not_multiply_the_total(
    verified_position_payloads, valuation_snapshot,
):
    record = verified_position_payloads["scpis"]["result"][0]
    record.pop("quantity")
    snapshot = valuation_snapshot()
    position = next(row for row in snapshot["positions"] if row["asset_class"] == "SCPI")
    assert position["quantity"] == 2
    assert position["unit_price"] is None
    assert position["market_value_eur"] == 105
    record["shares"] = "2"
    with pytest.raises(SnapshotNormalizationError):
        valuation_snapshot()


@pytest.mark.parametrize("kind, field, value", [
    ("scpis", "property_type", "bare_ownership"),
    ("scpis", "property_type", "usufruct"),
    ("cryptos", "owning_type", "staked"),
])
def test_unverified_ownership_variants_remain_unknown(
    kind, field, value, verified_position_payloads, valuation_snapshot,
):
    verified_position_payloads[kind]["result"][0][field] = value
    position = next(row for row in valuation_snapshot()["positions"]
                    if row["source_asset_id"].startswith(kind + ":"))
    assert position["currency"] is None
    assert position["market_value_eur"] is None


@pytest.mark.parametrize("kind", ["cryptos", "scpis"])
def test_missing_cost_does_not_block_positive_market_coverage(
    kind, verified_position_payloads, valuation_snapshot,
):
    record = verified_position_payloads[kind]["result"][0]
    record.pop("buying_value")
    record.pop("buying_price")
    position = next(row for row in valuation_snapshot()["positions"]
                    if row["source_asset_id"].startswith(kind + ":"))
    assert position["market_value_eur"] == (60 if kind == "cryptos" else 105)
    assert position["fx_to_eur"] == 1
    assert position["cost_basis_eur"] is None
