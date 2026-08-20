"""Validation tests for the stable downstream Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import Account, AssetClass, Liability, PortfolioSnapshot, Position


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
