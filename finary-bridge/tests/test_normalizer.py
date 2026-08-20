"""Fixture-based tests for deterministic Phase 3 normalization."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.finary_client import (
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
    assert normalize_liabilities(FinaryRawLiabilities(records=())) == ()


def test_non_empty_liability_collection_is_not_fabricated() -> None:
    with pytest.raises(SnapshotNormalizationError, match="no verified normalization rule"):
        normalize_liabilities(FinaryRawLiabilities(records=({"id": "synthetic"},)))
