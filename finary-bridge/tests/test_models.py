"""Validation tests for the stable downstream Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import (
    Account,
    AssetClass,
    Liability,
    LiabilityCoverage,
    PortfolioSnapshot,
    PortfolioSnapshotV2,
    Position,
    SnapshotCoverage,
)


def _account() -> Account:
    return Account(
        account_key="finary:account:account-001",
        source_account_id="account-001",
        name="Synthetic Account",
        institution=None,
        account_type="Securities",
        owner=None,
        currency="EUR",
        market_value_eur=100.0,
        metadata={},
    )


def _position() -> Position:
    return Position(
        position_key="finary:account-001:asset:securities:1001",
        source_asset_id="securities:1001",
        account_key="finary:account:account-001",
        name="Synthetic Position",
        ticker=None,
        isin=None,
        asset_class=AssetClass.OTHER,
        quantity=1.0,
        unit_price=100.0,
        currency="EUR",
        fx_to_eur=1.0,
        market_value_native=100.0,
        market_value_eur=100.0,
        metadata={},
    )


def test_stable_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Account(
            account_key="finary:account:account-001",
            source_account_id="account-001",
            name="Synthetic Account",
            account_type="Securities",
            currency="EUR",
            unexpected_private_field="must-not-leak",  # type: ignore[call-arg]
        )


def test_snapshot_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        PortfolioSnapshot(
            generated_at=datetime(2026, 8, 20, 7, 30),
            gross_assets_eur=100.0,
            liabilities_eur=0.0,
            net_worth_eur=100.0,
            accounts=(_account(),),
            positions=(_position(),),
            liabilities=(),
        )


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_models_reject_non_finite_values(invalid_value: float) -> None:
    with pytest.raises(ValidationError):
        Position.model_validate(
            {
                **_position().model_dump(),
                "market_value_native": invalid_value,
            }
        )


def test_snapshot_rejects_invalid_totals_and_references() -> None:
    unrelated_position = _position().model_copy(
        update={"account_key": "finary:account:missing"}
    )
    with pytest.raises(ValidationError, match="existing accounts"):
        PortfolioSnapshot(
            generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
            gross_assets_eur=100.0,
            liabilities_eur=0.0,
            net_worth_eur=100.0,
            accounts=(_account(),),
            positions=(unrelated_position,),
            liabilities=(),
        )


def test_liability_model_exists_and_requires_non_negative_amount() -> None:
    with pytest.raises(ValidationError):
        Liability(
            liability_key="finary:liability:loan-001",
            source_liability_id="loan-001",
            name="Synthetic Loan",
            liability_type="OTHER",
            outstanding_eur=-1.0,
        )


def test_snapshot_rejects_duplicate_liability_keys() -> None:
    liability = Liability(
        liability_key="finary:liability:loan-001",
        source_liability_id="loan-001",
        name="Synthetic Loan",
        liability_type="OTHER",
        outstanding_eur=10.0,
    )
    with pytest.raises(ValidationError, match="liability keys must be unique"):
        PortfolioSnapshot(
            generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
            gross_assets_eur=100.0,
            liabilities_eur=20.0,
            net_worth_eur=80.0,
            accounts=(_account(),),
            positions=(_position(),),
            liabilities=(liability, liability),
        )


def test_v2_unavailable_coverage_requires_null_totals_and_no_liabilities() -> None:
    snapshot = PortfolioSnapshotV2(
        generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
        coverage=SnapshotCoverage(liabilities=LiabilityCoverage.UNAVAILABLE),
        gross_assets_eur=100.0,
        liabilities_eur=None,
        net_worth_eur=None,
        accounts=(_account(),),
        positions=(_position(),),
        liabilities=(),
    )

    assert snapshot.schema_version == "2.0"
    assert snapshot.coverage.liabilities is LiabilityCoverage.UNAVAILABLE


@pytest.mark.parametrize("coverage", [LiabilityCoverage.PARTIAL, LiabilityCoverage.UNAVAILABLE])
def test_v2_incomplete_coverage_rejects_numeric_totals(
    coverage: LiabilityCoverage,
) -> None:
    with pytest.raises(ValidationError, match="requires null totals"):
        PortfolioSnapshotV2(
            generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
            coverage=SnapshotCoverage(liabilities=coverage),
            gross_assets_eur=100.0,
            liabilities_eur=0.0,
            net_worth_eur=100.0,
            accounts=(_account(),),
            positions=(_position(),),
            liabilities=(),
        )


def test_v2_complete_coverage_requires_consistent_numeric_totals() -> None:
    snapshot = PortfolioSnapshotV2(
        generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
        coverage=SnapshotCoverage(liabilities=LiabilityCoverage.COMPLETE),
        gross_assets_eur=100.0,
        liabilities_eur=0.0,
        net_worth_eur=100.0,
        accounts=(_account(),),
        positions=(_position(),),
        liabilities=(),
    )

    assert snapshot.liabilities_eur == 0.0
    assert snapshot.net_worth_eur == 100.0


def test_v2_partial_coverage_may_carry_verified_records_without_a_total() -> None:
    liability = Liability(
        liability_key="finary:liability:synthetic-partial",
        source_liability_id="synthetic-partial",
        name="Synthetic Partial Liability",
        liability_type="OTHER",
        outstanding_eur=10.0,
    )
    snapshot = PortfolioSnapshotV2(
        generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
        coverage=SnapshotCoverage(liabilities=LiabilityCoverage.PARTIAL),
        gross_assets_eur=100.0,
        accounts=(_account(),),
        positions=(_position(),),
        liabilities=(liability,),
    )

    assert snapshot.liabilities_eur is None
    assert snapshot.net_worth_eur is None


def test_v2_unavailable_coverage_rejects_claimed_liabilities() -> None:
    liability = Liability(
        liability_key="finary:liability:synthetic-unavailable",
        source_liability_id="synthetic-unavailable",
        name="Synthetic Unavailable Liability",
        liability_type="OTHER",
        outstanding_eur=10.0,
    )
    with pytest.raises(ValidationError, match="cannot claim liabilities"):
        PortfolioSnapshotV2(
            generated_at=datetime.fromisoformat("2026-08-20T07:30:00+02:00"),
            coverage=SnapshotCoverage(liabilities=LiabilityCoverage.UNAVAILABLE),
            gross_assets_eur=100.0,
            accounts=(_account(),),
            positions=(_position(),),
            liabilities=(liability,),
        )
