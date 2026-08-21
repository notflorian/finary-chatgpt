"""Stable downstream models owned by the Finary bridge."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isclose
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
MetadataValue = str | bool | int | float | None


class StableModel(BaseModel):
    """Base configuration for immutable, finite, strict API models."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class AssetClass(StrEnum):
    """Stable top-level asset classifications."""

    EQUITY = "EQUITY"
    BOND = "BOND"
    CASH = "CASH"
    REAL_ESTATE = "REAL_ESTATE"
    SCPI = "SCPI"
    PRIVATE_EQUITY = "PRIVATE_EQUITY"
    CRYPTO = "CRYPTO"
    COMMODITY = "COMMODITY"
    LIFE_INSURANCE_FUND = "LIFE_INSURANCE_FUND"
    OTHER = "OTHER"


class LiabilityCoverage(StrEnum):
    """Completeness of the liabilities represented by a v2 snapshot."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class Account(StableModel):
    """One normalized Finary account without private upstream nesting."""

    account_key: str = Field(min_length=1)
    source: Literal["finary"] = "finary"
    source_account_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    institution: str | None = None
    account_type: str = Field(min_length=1)
    owner: str | None = None
    currency: CurrencyCode
    market_value_eur: float | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class Position(StableModel):
    """One category-aware normalized position associated with an account."""

    position_key: str = Field(min_length=1)
    source: Literal["finary"] = "finary"
    source_asset_id: str = Field(min_length=1)
    account_key: str = Field(min_length=1)
    name: str | None = None
    ticker: str | None = None
    isin: str | None = None
    asset_class: AssetClass
    asset_subclass: str | None = None
    region: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    currency: CurrencyCode | None = None
    fx_to_eur: float | None = None
    market_value_native: float
    market_value_eur: float | None = None
    cost_basis_eur: float | None = None
    unrealized_pnl_eur: float | None = None
    unrealized_pnl_pct: float | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class Liability(StableModel):
    """Stable liability model reserved for a future verified upstream shape."""

    liability_key: str = Field(min_length=1)
    source: Literal["finary"] = "finary"
    source_liability_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    liability_type: str = Field(min_length=1)
    institution: str | None = None
    outstanding_eur: float = Field(ge=0)
    interest_rate: float | None = None
    monthly_payment_eur: float | None = Field(default=None, ge=0)
    end_date: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class PortfolioSnapshot(StableModel):
    """Versioned normalized snapshot returned by ``GET /v1/snapshot``."""

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    reference_currency: Literal["EUR"] = "EUR"
    gross_assets_eur: float = Field(ge=0)
    liabilities_eur: float = Field(ge=0)
    net_worth_eur: float
    accounts: tuple[Account, ...]
    positions: tuple[Position, ...]
    liabilities: tuple[Liability, ...]

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject timestamps whose UTC offset is unknown."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_consistency(self) -> PortfolioSnapshot:
        """Validate stable-key uniqueness, references, and liability totals."""

        account_keys = [account.account_key for account in self.accounts]
        if len(account_keys) != len(set(account_keys)):
            raise ValueError("account keys must be unique")

        position_keys = [position.position_key for position in self.positions]
        if len(position_keys) != len(set(position_keys)):
            raise ValueError("position keys must be unique")
        account_key_set = set(account_keys)
        if any(position.account_key not in account_key_set for position in self.positions):
            raise ValueError("positions must reference existing accounts")

        liability_keys = [liability.liability_key for liability in self.liabilities]
        if len(liability_keys) != len(set(liability_keys)):
            raise ValueError("liability keys must be unique")

        expected_liabilities = sum(
            liability.outstanding_eur for liability in self.liabilities
        )
        if not isclose(
            self.liabilities_eur,
            expected_liabilities,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("liabilities total must equal normalized liabilities")
        expected_net_worth = self.gross_assets_eur - self.liabilities_eur
        if not isclose(
            self.net_worth_eur,
            expected_net_worth,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("net worth must equal gross assets minus liabilities")
        return self


class SnapshotCoverage(StableModel):
    """Coverage decisions that qualify nullable v2 portfolio totals."""

    liabilities: LiabilityCoverage


class PortfolioSnapshotV2(StableModel):
    """Coverage-aware snapshot returned by ``GET /v2/snapshot``."""

    schema_version: Literal["2.0"] = "2.0"
    generated_at: datetime
    reference_currency: Literal["EUR"] = "EUR"
    coverage: SnapshotCoverage
    gross_assets_eur: float = Field(ge=0)
    liabilities_eur: float | None = Field(default=None, ge=0)
    net_worth_eur: float | None = None
    accounts: tuple[Account, ...]
    positions: tuple[Position, ...]
    liabilities: tuple[Liability, ...]

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject timestamps whose UTC offset is unknown."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_consistency(self) -> PortfolioSnapshotV2:
        """Validate keys, references, and coverage-dependent totals."""

        account_keys = [account.account_key for account in self.accounts]
        if len(account_keys) != len(set(account_keys)):
            raise ValueError("account keys must be unique")

        position_keys = [position.position_key for position in self.positions]
        if len(position_keys) != len(set(position_keys)):
            raise ValueError("position keys must be unique")
        account_key_set = set(account_keys)
        if any(position.account_key not in account_key_set for position in self.positions):
            raise ValueError("positions must reference existing accounts")

        liability_keys = [liability.liability_key for liability in self.liabilities]
        if len(liability_keys) != len(set(liability_keys)):
            raise ValueError("liability keys must be unique")

        if self.coverage.liabilities is LiabilityCoverage.COMPLETE:
            if self.liabilities_eur is None or self.net_worth_eur is None:
                raise ValueError("complete liability coverage requires numeric totals")
            expected_liabilities = sum(
                liability.outstanding_eur for liability in self.liabilities
            )
            if not isclose(
                self.liabilities_eur,
                expected_liabilities,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("liabilities total must equal normalized liabilities")
            if not isclose(
                self.net_worth_eur,
                self.gross_assets_eur - self.liabilities_eur,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("net worth must equal gross assets minus liabilities")
        else:
            if self.liabilities_eur is not None or self.net_worth_eur is not None:
                raise ValueError("incomplete liability coverage requires null totals")
            if self.coverage.liabilities is LiabilityCoverage.UNAVAILABLE and self.liabilities:
                raise ValueError("unavailable liability coverage cannot claim liabilities")
        return self


class ErrorDetail(StableModel):
    """Stable machine-readable API error detail."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class ErrorResponse(StableModel):
    """Project-wide API error envelope."""

    error: ErrorDetail
